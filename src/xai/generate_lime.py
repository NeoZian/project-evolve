import os
import sys
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from lime.lime_tabular import LimeTabularExplainer
from sqlalchemy import create_engine, text

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

df_all = pd.read_sql("""
    SELECT
        student_feedback_rating,
        peer_score,
        avg_grade,
        nlp_sentiment_score,
        course_quality_score,
        final_evaluation_score
    FROM evaluation_results
""", engine)

feature_cols = [
    "student_feedback_rating",
    "peer_score",
    "avg_grade",
    "nlp_sentiment_score",
    "course_quality_score"
]

if df_all.empty:
    print("No evaluation_results records found. Run the data and AI layers first.")
    sys.exit(1)

X = df_all[feature_cols].values
y = df_all["final_evaluation_score"].values


def weighted_score_prediction(x):
    """
    LIME perturbs samples. Therefore, do not map perturbed rows back to
    original gender/department by row index. Protected attributes are audited
    in the fairness module, not used inside this local explanation function.
    """
    scores = []
    for row in x:
        student_fb = row[0]
        peer = row[1]
        avg_grade = row[2]
        nlp_sent = row[3]
        course_qual = row[4]

        perf_score = (avg_grade / 4.0) * 5.0
        perf_score = np.clip(perf_score, 1, 5)

        score = (
            student_fb * 0.35 +
            peer * 0.25 +
            perf_score * 0.20 +
            nlp_sent * 0.10 +
            course_qual * 0.10
        )
        scores.append(np.clip(score, 1, 5))
    return np.array(scores)


feature_names = [
    "Student Feedback",
    "Peer Review",
    "Avg Grade",
    "NLP Sentiment",
    "Course Quality"
]

explainer = LimeTabularExplainer(
    X,
    feature_names=feature_names,
    mode="regression",
    training_labels=y
)

df_single = pd.read_sql(
    text("""
        SELECT
            student_feedback_rating,
            peer_score,
            avg_grade,
            nlp_sentiment_score,
            course_quality_score
        FROM evaluation_results
        WHERE faculty_id = :faculty_id
    """),
    engine,
    params={"faculty_id": faculty_id}
)

if df_single.empty:
    print(f"Faculty ID {faculty_id} not found")
    sys.exit(1)

instance = df_single.values[0]
os.makedirs("explanations", exist_ok=True)

exp = explainer.explain_instance(
    instance,
    weighted_score_prediction,
    num_features=5
)
exp.save_to_file(f"explanations/lime_{faculty_id}.html")
print("OK")
