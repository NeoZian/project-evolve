"""Regenerate canonical seven-factor audit hashes.

Run this after the scoring formula is synchronized and after SHAP/LIME has been
updated. It creates one tamper-evident hash per evaluation row so the dashboard
can still report the same evaluation-log scale as the original prototype, while
ensuring every hash includes the canonical seven-factor payload and formula
version.

Usage:
    python src/audit/regenerate_audit_hashes.py
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.scoring.seven_factor import FORMULA_VERSION, canonical_audit_payload  # noqa: E402

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://evolve_user:strongpassword@localhost/evolve_db")
engine = create_engine(DATABASE_URL)

evaluation_sql = """
    SELECT
        ROW_NUMBER() OVER (ORDER BY faculty_id, faculty_name, department, feedback_text) AS evaluation_id,
        faculty_id,
        faculty_name,
        department,
        final_evaluation_score,
        student_feedback_rating,
        peer_score,
        avg_grade,
        nlp_sentiment_score,
        course_material_score,
        service_score,
        pd_score
    FROM evaluation_results
    ORDER BY faculty_id, evaluation_id
"""

df = pd.read_sql(evaluation_sql, engine)
if df.empty:
    raise RuntimeError("No evaluation_results rows found. Run the data/AI pipeline first.")

generated_at = datetime.now(timezone.utc).isoformat()
records = []
for _, row in df.iterrows():
    payload = canonical_audit_payload(
        row.to_dict(),
        evaluation_id=int(row["evaluation_id"]),
        timestamp=generated_at,
        scope="row_level_evaluation",
    )
    payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    result_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    records.append({
        "evaluation_id": int(row["evaluation_id"]),
        "faculty_id": int(row["faculty_id"]),
        "final_score": float(row["final_evaluation_score"]),
        "result_hash": result_hash,
        "blockchain_tx_hash": None,
        "formula_version": FORMULA_VERSION,
        "payload_json": payload_json,
        "timestamp": generated_at,
        "status": "canonical_seven_factor_hash_generated_database_only",
    })

with engine.begin() as conn:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS blockchain_audit_logs (
            id SERIAL PRIMARY KEY,
            evaluation_id INTEGER,
            faculty_id INTEGER NOT NULL,
            final_score FLOAT,
            result_hash TEXT NOT NULL,
            blockchain_tx_hash TEXT,
            formula_version TEXT DEFAULT 'evolve_seven_factor_v2.0_2026_06',
            payload_json TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'logged'
        )
    """))
    conn.execute(text("ALTER TABLE blockchain_audit_logs ADD COLUMN IF NOT EXISTS final_score FLOAT"))
    conn.execute(text("ALTER TABLE blockchain_audit_logs ADD COLUMN IF NOT EXISTS formula_version TEXT DEFAULT 'evolve_seven_factor_v2.0_2026_06'"))
    conn.execute(text("ALTER TABLE blockchain_audit_logs ADD COLUMN IF NOT EXISTS payload_json TEXT"))
    conn.execute(text("DELETE FROM blockchain_audit_logs"))
    for rec in records:
        conn.execute(text("""
            INSERT INTO blockchain_audit_logs
                (evaluation_id, faculty_id, final_score, result_hash, blockchain_tx_hash,
                 formula_version, payload_json, timestamp, status)
            VALUES
                (:evaluation_id, :faculty_id, :final_score, :result_hash, :blockchain_tx_hash,
                 :formula_version, :payload_json, :timestamp, :status)
        """), rec)

print(f"Regenerated {len(records)} canonical seven-factor audit hashes")
print(f"Formula version: {FORMULA_VERSION}")
print("Note: blockchain_tx_hash is null because this script creates database hashes. Use a permissioned chain/Ganache write job if on-chain transactions are required.")
