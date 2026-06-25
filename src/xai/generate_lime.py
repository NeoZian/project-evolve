"""Generate seven-factor LIME explanations for a selected faculty member."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from lime.lime_tabular import LimeTabularExplainer
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.scoring.seven_factor import (  # noqa: E402
    FORMULA_VERSION,
    FACTOR_WEIGHTS,
    FACTOR_LABELS,
    calculate_seven_factor_score,
)

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://evolve_user:strongpassword@localhost/evolve_db"
)

engine = create_engine(DATABASE_URL)

if len(sys.argv) < 2:
    print("Usage: python src/xai/generate_lime.py <faculty_id>")
    sys.exit(1)

faculty_id = int(sys.argv[1])

aggregate_sql = """
    SELECT
        faculty_id,
        ROUND(AVG(student_feedback_rating)::numeric, 4) AS student_feedback_rating,
        ROUND(AVG(peer_score)::numeric, 4) AS peer_score,
        ROUND(AVG(LEAST(GREATEST((avg_grade / 4.0) * 5.0, 1), 5))::numeric, 4) AS performance_score,
        ROUND(AVG(nlp_sentiment_score)::numeric, 4) AS nlp_sentiment_score,
        ROUND(AVG(course_material_score)::numeric, 4) AS course_material_score,
        ROUND(AVG(service_score)::numeric, 4) AS service_score,
        ROUND(AVG(pd_score)::numeric, 4) AS pd_score,
        ROUND(AVG(final_evaluation_score)::numeric, 4) AS final_evaluation_score
    FROM evaluation_results
    GROUP BY faculty_id
    ORDER BY faculty_id
"""

df_all = pd.read_sql(aggregate_sql, engine)
if df_all.empty:
    print("No evaluation_results records found. Run the data and AI layers first.")
    sys.exit(1)

feature_cols = list(FACTOR_WEIGHTS.keys())
X = df_all[feature_cols].astype(float).values
y = df_all["final_evaluation_score"].astype(float).values


def weighted_score_prediction(x):
    """Predict with the canonical seven-factor formula for LIME perturbations."""
    scores = []
    for row in x:
        values = {feature_cols[i]: float(np.clip(row[i], 1.0, 5.0)) for i in range(len(feature_cols))}
        scores.append(calculate_seven_factor_score(values, rounded=False))
    return np.array(scores)


feature_names = [FACTOR_LABELS[col] for col in feature_cols]

explainer = LimeTabularExplainer(
    X,
    feature_names=feature_names,
    mode="regression",
    training_labels=y,
    discretize_continuous=True,
    verbose=False,
)

df_single = df_all[df_all["faculty_id"].astype(int) == faculty_id]
if df_single.empty:
    print(f"Faculty ID {faculty_id} not found")
    sys.exit(1)

instance = df_single.iloc[0][feature_cols].astype(float).values
os.makedirs("explanations", exist_ok=True)
safe_formula_version = FORMULA_VERSION.replace(".", "_").replace("-", "_")

exp = explainer.explain_instance(
    instance,
    weighted_score_prediction,
    num_features=7,
)
html = exp.as_html()
html = html.replace("LIME", f"LIME - Project Evolve {FORMULA_VERSION}", 1)
versioned_path = f"explanations/lime_{faculty_id}_{safe_formula_version}.html"
legacy_path = f"explanations/lime_{faculty_id}.html"
with open(versioned_path, "w", encoding="utf-8") as f:
    f.write(html)
# Also write the legacy path for direct local viewing, but the API serves the
# versioned file to avoid stale formula output.
with open(legacy_path, "w", encoding="utf-8") as f:
    f.write(html)
print("OK")
