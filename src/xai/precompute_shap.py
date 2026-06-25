"""Precompute seven-factor SHAP-style explanations for Project Evolve.

The canonical score is a transparent additive formula. For an additive linear
model, Shapley contributions relative to a baseline are exactly weight times
(feature_value - baseline_feature_value) before final clipping. This script uses
that exact attribution rather than a slow KernelExplainer pass over thousands of
rows. It stores one explanation per faculty_id after faculty-level aggregation,
which prevents repeated feedback rows from overwriting each other randomly.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# Allow running as "python src/xai/precompute_shap.py" from project root.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.scoring.seven_factor import FORMULA_VERSION, FACTOR_WEIGHTS, calculate_seven_factor_score  # noqa: E402

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://evolve_user:strongpassword@localhost/evolve_db"
)

engine = create_engine(DATABASE_URL)

query = """
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

df = pd.read_sql(query, engine)
print(f"Loaded {len(df)} faculty-level records for seven-factor explanation precomputation")

if df.empty:
    raise RuntimeError("No evaluation_results records found. Run the data and AI layers first.")

feature_cols = list(FACTOR_WEIGHTS.keys())
missing = [col for col in feature_cols if col not in df.columns]
if missing:
    raise RuntimeError(f"Missing seven-factor columns required for XAI: {missing}")

# Baseline feature values and base prediction for the additive model.
baseline = df[feature_cols].mean().to_dict()
base_value = calculate_seven_factor_score(baseline, rounded=False)

shap_records = []
for _, row in df.iterrows():
    contributions = {}
    for col, weight in FACTOR_WEIGHTS.items():
        contributions[col] = float(weight * (float(row[col]) - float(baseline[col])))
    shap_records.append({
        "faculty_id": int(row["faculty_id"]),
        "shap_values_json": json.dumps(contributions, sort_keys=True),
        "base_value": float(base_value),
        "formula_version": FORMULA_VERSION,
    })

with engine.begin() as conn:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS shap_explanations (
            faculty_id INTEGER PRIMARY KEY,
            shap_values_json TEXT,
            base_value FLOAT,
            formula_version TEXT DEFAULT 'seven_factor_v1.0_2026_06',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))
    conn.execute(text("ALTER TABLE shap_explanations ADD COLUMN IF NOT EXISTS formula_version TEXT DEFAULT 'seven_factor_v1.0_2026_06'"))

    for rec in shap_records:
        conn.execute(text("""
            INSERT INTO shap_explanations
                (faculty_id, shap_values_json, base_value, formula_version)
            VALUES
                (:faculty_id, :shap_values_json, :base_value, :formula_version)
            ON CONFLICT (faculty_id) DO UPDATE SET
                shap_values_json = EXCLUDED.shap_values_json,
                base_value = EXCLUDED.base_value,
                formula_version = EXCLUDED.formula_version,
                updated_at = CURRENT_TIMESTAMP
        """), rec)

print(f"Precomputed seven-factor explanations for {len(shap_records)} faculty")
print(f"Formula version: {FORMULA_VERSION}")
