import os
import json
import numpy as np
import pandas as pd
import shap
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://evolve_user:strongpassword@localhost/evolve_db"
)

engine = create_engine(DATABASE_URL)

df = pd.read_sql("""
    SELECT
        faculty_id,
        student_feedback_rating,
        peer_score,
        avg_grade,
        nlp_sentiment_score,
        course_quality_score,
        final_evaluation_score
    FROM evaluation_results
""", engine)

print(f"Loaded {len(df)} records for SHAP precomputation")

feature_cols = [
    "student_feedback_rating",
    "peer_score",
    "avg_grade",
    "nlp_sentiment_score",
    "course_quality_score"
]

X = df[feature_cols].values


def weighted_score(student_fb, peer, avg_grade, nlp_sent, course_qual):
    """
    Explain only evaluation-related factors. Protected attributes such as gender
    and department are intentionally excluded from this SHAP prediction function;
    they are audited separately in the fairness module.
    """
    perf_score = (avg_grade / 4.0) * 5.0
    perf_score = np.clip(perf_score, 1, 5)

    score = (
        student_fb * 0.35 +
        peer * 0.25 +
        perf_score * 0.20 +
        nlp_sent * 0.10 +
        course_qual * 0.10
    )

    return np.clip(score, 1, 5)


def model_for_shap(X_array):
    scores = []
    for row in X_array:
        score = weighted_score(row[0], row[1], row[2], row[3], row[4])
        scores.append(score)
    return np.array(scores)


if len(X) == 0:
    raise RuntimeError("No evaluation_results records found. Run the data and AI layers first.")

background_size = min(100, len(X))
background = X[:background_size]

explainer = shap.KernelExplainer(model_for_shap, background)
shap_values = explainer.shap_values(X)

shap_records = []
for idx, row in df.iterrows():
    contributions = {}
    for i, col in enumerate(feature_cols):
        contributions[col] = float(shap_values[idx][i])
    shap_records.append({
        "faculty_id": int(row["faculty_id"]),
        "shap_values_json": json.dumps(contributions),
        "base_value": float(explainer.expected_value)
    })

with engine.begin() as conn:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS shap_explanations (
            faculty_id INTEGER PRIMARY KEY,
            shap_values_json TEXT,
            base_value FLOAT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))

    for rec in shap_records:
        conn.execute(text("""
            INSERT INTO shap_explanations
                (faculty_id, shap_values_json, base_value)
            VALUES
                (:faculty_id, :shap_values_json, :base_value)
            ON CONFLICT (faculty_id) DO UPDATE SET
                shap_values_json = EXCLUDED.shap_values_json,
                base_value = EXCLUDED.base_value,
                updated_at = CURRENT_TIMESTAMP
        """), rec)

print(f"Precomputed SHAP values for {len(shap_records)} faculty")
