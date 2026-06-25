from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import Response, JSONResponse
import pandas as pd
from datetime import datetime, timedelta, date
import sqlalchemy as sa
import numpy as np
import json
import hashlib
from web3 import Web3
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.pdfgen import canvas
import io
import glob
import subprocess
import os
from pydantic import BaseModel
from typing import Optional
from scipy.stats import ttest_ind
from dotenv import load_dotenv
from src.fairness.mitigation import mitigate_bias
from src.scoring.seven_factor import (
    FORMULA_VERSION,
    FACTOR_WEIGHTS,
    FACTOR_LABELS,
    FACTOR_DESCRIPTIONS,
    FACTOR_SOURCES,
    clamp_score,
    normalize_performance_score,
    calculate_seven_factor_score,
    build_factor_breakdown,
    canonical_audit_payload,
)
import math


load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://evolve_user:strongpassword@localhost/evolve_db"
)

engine = sa.create_engine(DATABASE_URL)


def ensure_runtime_tables():
    """Create runtime tables used by the API if they are missing."""
    try:
        with engine.begin() as conn:
            conn.execute(sa.text("""
                CREATE TABLE IF NOT EXISTS faculty_feedback (
                    id SERIAL PRIMARY KEY,
                    faculty_id INTEGER,
                    understandability_score INTEGER CHECK (understandability_score BETWEEN 1 AND 5),
                    trust_score INTEGER CHECK (trust_score BETWEEN 1 AND 5),
                    comment TEXT,
                    xai_viewed BOOLEAN DEFAULT FALSE,
                    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))

            conn.execute(sa.text("""
                CREATE TABLE IF NOT EXISTS shap_explanations (
                    faculty_id INTEGER PRIMARY KEY,
                    shap_values_json TEXT,
                    base_value FLOAT,
                    formula_version TEXT DEFAULT 'evolve_seven_factor_v2.0_2026_06',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(sa.text("ALTER TABLE shap_explanations ADD COLUMN IF NOT EXISTS formula_version TEXT DEFAULT 'evolve_seven_factor_v2.0_2026_06'"))

            conn.execute(sa.text("""
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
            conn.execute(sa.text("ALTER TABLE blockchain_audit_logs ADD COLUMN IF NOT EXISTS final_score FLOAT"))
            conn.execute(sa.text("ALTER TABLE blockchain_audit_logs ADD COLUMN IF NOT EXISTS formula_version TEXT DEFAULT 'evolve_seven_factor_v2.0_2026_06'"))
            conn.execute(sa.text("ALTER TABLE blockchain_audit_logs ADD COLUMN IF NOT EXISTS payload_json TEXT"))
    except Exception as e:
        print(f"Runtime table initialization skipped: {e}")


ensure_runtime_tables()

app = FastAPI(title="Project Evolve API")

os.makedirs("reports", exist_ok=True)
os.makedirs("explanations", exist_ok=True)
app.mount("/reports", StaticFiles(directory="reports"), name="reports")

allowed_origins = os.getenv(
    "CORS_ALLOW_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in allowed_origins if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

lime_cache = {}


class FeedbackCreate(BaseModel):
    faculty_id: int
    understandability_score: int
    trust_score: int
    comment: Optional[str] = None
    xai_viewed: bool = False


class LoginRequest(BaseModel):
    password: str


APP_PASSWORD = os.getenv("APP_PASSWORD") or os.getenv("SITE_PASSWORD") or "ProjectEvolve@2026"
APP_ACCESS_TOKEN = os.getenv("APP_ACCESS_TOKEN") or hashlib.sha256(
    f"project-evolve:{APP_PASSWORD}".encode()
).hexdigest()


@app.middleware("http")
async def simple_password_gate(request: Request, call_next):
    public_paths = {"/", "/health", "/api/auth/login"}
    if request.method == "OPTIONS" or request.url.path in public_paths or request.url.path.startswith("/reports"):
        return await call_next(request)
    token = request.headers.get("x-access-token")
    if token != APP_ACCESS_TOKEN:
        return JSONResponse(status_code=401, content={"detail": "Login required"})
    return await call_next(request)


@app.post("/api/auth/login")
async def login(payload: LoginRequest):
    if payload.password != APP_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid password")
    return {"access_token": APP_ACCESS_TOKEN}


def make_serializable(data):
    if isinstance(data, list):
        return [make_serializable(item) for item in data]
    if isinstance(data, dict):
        return {key: make_serializable(value) for key, value in data.items()}
    if isinstance(data, (np.integer, np.int64)):
        return int(data)
    if isinstance(data, (np.floating, np.float64)):
        if math.isnan(data) or math.isinf(data):
            return None
        return float(data)
    if isinstance(data, float):
        if math.isnan(data) or math.isinf(data):
            return None
        return data
    if isinstance(data, (datetime, date)):
        return data.isoformat()
    if isinstance(data, np.ndarray):
        return make_serializable(data.tolist())
    if isinstance(data, pd.Series):
        return make_serializable(data.tolist())
    if isinstance(data, pd.DataFrame):
        return make_serializable(data.to_dict(orient="records"))
    return data


SEVEN_FACTOR_AGGREGATE_SQL = """
    SELECT
        faculty_id,
        ROUND(AVG(final_evaluation_score)::numeric, 4) AS final_evaluation_score,
        ROUND(AVG(student_feedback_rating)::numeric, 4) AS student_feedback_rating,
        ROUND(AVG(peer_score)::numeric, 4) AS peer_score,
        ROUND(AVG(LEAST(GREATEST((avg_grade / 4.0) * 5.0, 1), 5))::numeric, 4) AS performance_score,
        ROUND(AVG(nlp_sentiment_score)::numeric, 4) AS nlp_sentiment_score,
        ROUND(AVG(course_material_score)::numeric, 4) AS course_material_score,
        ROUND(AVG(service_score)::numeric, 4) AS service_score,
        ROUND(AVG(pd_score)::numeric, 4) AS pd_score
    FROM evaluation_results
    GROUP BY faculty_id
    ORDER BY faculty_id
"""


def _load_faculty_level_factors() -> pd.DataFrame:
    """Load one aggregated seven-factor row per faculty member."""
    return pd.read_sql(sa.text(SEVEN_FACTOR_AGGREGATE_SQL), engine)


def _canonical_explanation_payload(faculty_id: int) -> dict:
    """Build exact seven-factor additive attributions from current data.

    This endpoint intentionally computes from evaluation_results at request time
    instead of trusting cached shap_explanations rows. This keeps the
    explanation aligned with the currently displayed score.
    Contributions are baseline-relative: weight * (faculty_factor - population_mean_factor).
    """
    df = _load_faculty_level_factors()
    if df.empty:
        return {
            "final_score": 0,
            "base_value": 0,
            "formula_version": FORMULA_VERSION,
            "explanation_method": "canonical_additive_baseline_attribution",
            "top_positive_factors": [],
            "top_negative_factors": [],
            "neutral_factors": [],
            "all_factor_contributions": [],
            "full_explanation": "Explanation not available because no evaluation records were found.",
        }

    df["faculty_id"] = df["faculty_id"].astype(int)
    selected = df[df["faculty_id"] == int(faculty_id)]
    if selected.empty:
        raise HTTPException(404, "Faculty not found")

    feature_cols = list(FACTOR_WEIGHTS.keys())
    selected_row = selected.iloc[0]
    baseline = df[feature_cols].astype(float).mean().to_dict()
    base_value = calculate_seven_factor_score(baseline, rounded=False)
    final_score = float(selected_row.get("final_evaluation_score", 0))

    positive, negative, neutral, all_items = [], [], [], []
    for key, weight in FACTOR_WEIGHTS.items():
        value = float(selected_row[key])
        baseline_value = float(baseline[key])
        contribution = float(weight * (value - baseline_value))
        item = {
            "feature": FACTOR_LABELS.get(key, key.replace("_", " ").title()),
            "feature_key": key,
            "value": round(value, 4),
            "baseline_value": round(baseline_value, 4),
            "weight": weight,
            "weight_percent": round(weight * 100, 1),
            "weighted_contribution_to_score": round(weight * value, 4),
            "contribution": round(contribution, 3),
            "description": FACTOR_DESCRIPTIONS.get(key),
            "source": FACTOR_SOURCES.get(key),
        }
        all_items.append(item)
        if contribution > 0.0005:
            positive.append(item)
        elif contribution < -0.0005:
            negative.append(item)
        else:
            neutral.append(item)

    positive.sort(key=lambda x: x["contribution"], reverse=True)
    negative.sort(key=lambda x: x["contribution"])
    all_items.sort(key=lambda x: abs(x["contribution"]), reverse=True)

    formula_score_from_aggregated_factors = calculate_seven_factor_score(selected_row.to_dict(), rounded=False)
    approximation_gap = final_score - float(formula_score_from_aggregated_factors)

    explanation_text = (
        f"All seven canonical factors are included using formula version {FORMULA_VERSION}. "
        f"The baseline prediction is {base_value:.2f}. Contributions are measured relative to the faculty-level population baseline; "
        "positive values lift the faculty score above that baseline and negative values pull it below. "
    )
    if positive:
        explanation_text += "Positive contributors: " + ", ".join(
            [f"{p['feature']} ({p['contribution']:+.3f})" for p in positive]
        ) + ". "
    if negative:
        explanation_text += "Negative contributors: " + ", ".join(
            [f"{n['feature']} ({n['contribution']:+.3f})" for n in negative]
        ) + ". "
    if neutral:
        explanation_text += "Near-baseline contributors: " + ", ".join([n["feature"] for n in neutral]) + ". "
    if abs(approximation_gap) > 0.02:
        explanation_text += (
            f"The displayed final score is averaged from row-level evaluation records; the aggregate-factor formula differs by {approximation_gap:+.3f}."
        )

    return {
        "final_score": round(final_score, 4),
        "base_value": round(float(base_value), 4),
        "formula_version": FORMULA_VERSION,
        "explanation_method": "canonical_additive_baseline_attribution",
        "top_positive_factors": positive[:7],
        "top_negative_factors": negative[:7],
        "neutral_factors": neutral,
        "all_factor_contributions": all_items,
        "formula_score_from_aggregated_factors": round(float(formula_score_from_aggregated_factors), 4),
        "aggregation_gap": round(float(approximation_gap), 4),
        "full_explanation": explanation_text.strip(),
    }


WEB3_PROVIDER_URL = os.getenv("WEB3_PROVIDER_URL", "http://127.0.0.1:8545")
CONTRACT_ADDRESS = os.getenv(
    "CONTRACT_ADDRESS",
    "0xe78A0F7E598Cc8b0Bb87894B0F60dD2a88d6a8Ab"
)
w3 = Web3(Web3.HTTPProvider(WEB3_PROVIDER_URL))
blockchain_available = w3.is_connected()

ABI = [
	{
		"inputs": [
			{
				"internalType": "uint256",
				"name": "facultyId",
				"type": "uint256"
			}
		],
		"name": "addApproval",
		"outputs": [],
		"stateMutability": "nonpayable",
		"type": "function"
	},
	{
		"anonymous": False,
		"inputs": [
			{
				"indexed": True,
				"internalType": "uint256",
				"name": "facultyId",
				"type": "uint256"
			},
			{
				"indexed": False,
				"internalType": "address",
				"name": "approver",
				"type": "address"
			}
		],
		"name": "ApprovalAdded",
		"type": "event"
	},
	{
		"anonymous": False,
		"inputs": [
			{
				"indexed": True,
				"internalType": "uint256",
				"name": "facultyId",
				"type": "uint256"
			},
			{
				"indexed": False,
				"internalType": "string",
				"name": "resultHash",
				"type": "string"
			},
			{
				"indexed": False,
				"internalType": "uint256",
				"name": "timestamp",
				"type": "uint256"
			}
		],
		"name": "EvaluationStored",
		"type": "event"
	},
	{
		"inputs": [
			{
				"internalType": "uint256",
				"name": "facultyId",
				"type": "uint256"
			},
			{
				"internalType": "string",
				"name": "resultHash",
				"type": "string"
			}
		],
		"name": "storeEvaluation",
		"outputs": [],
		"stateMutability": "nonpayable",
		"type": "function"
	},
	{
		"inputs": [
			{
				"internalType": "uint256",
				"name": "",
				"type": "uint256"
			}
		],
		"name": "approvalCount",
		"outputs": [
			{
				"internalType": "uint256",
				"name": "",
				"type": "uint256"
			}
		],
		"stateMutability": "view",
		"type": "function"
	},
	{
		"inputs": [
			{
				"internalType": "uint256",
				"name": "",
				"type": "uint256"
			},
			{
				"internalType": "uint256",
				"name": "",
				"type": "uint256"
			}
		],
		"name": "approvals",
		"outputs": [
			{
				"internalType": "address",
				"name": "",
				"type": "address"
			}
		],
		"stateMutability": "view",
		"type": "function"
	},
	{
		"inputs": [
			{
				"internalType": "uint256",
				"name": "facultyId",
				"type": "uint256"
			}
		],
		"name": "getApprovalCount",
		"outputs": [
			{
				"internalType": "uint256",
				"name": "",
				"type": "uint256"
			}
		],
		"stateMutability": "view",
		"type": "function"
	},
	{
		"inputs": [
			{
				"internalType": "uint256",
				"name": "facultyId",
				"type": "uint256"
			}
		],
		"name": "getEvaluation",
		"outputs": [
			{
				"components": [
					{
						"internalType": "uint256",
						"name": "facultyId",
						"type": "uint256"
					},
					{
						"internalType": "uint256",
						"name": "timestamp",
						"type": "uint256"
					},
					{
						"internalType": "string",
						"name": "resultHash",
						"type": "string"
					},
					{
						"internalType": "address",
						"name": "evaluator",
						"type": "address"
					}
				],
				"internalType": "struct FacultyEvaluation.EvaluationRecord",
				"name": "",
				"type": "tuple"
			}
		],
		"stateMutability": "view",
		"type": "function"
	},
	{
		"inputs": [
			{
				"internalType": "uint256",
				"name": "",
				"type": "uint256"
			}
		],
		"name": "records",
		"outputs": [
			{
				"internalType": "uint256",
				"name": "facultyId",
				"type": "uint256"
			},
			{
				"internalType": "uint256",
				"name": "timestamp",
				"type": "uint256"
			},
			{
				"internalType": "string",
				"name": "resultHash",
				"type": "string"
			},
			{
				"internalType": "address",
				"name": "evaluator",
				"type": "address"
			}
		],
		"stateMutability": "view",
		"type": "function"
	}
]

contract = None
if blockchain_available and CONTRACT_ADDRESS:
    try:
        contract = w3.eth.contract(address=CONTRACT_ADDRESS, abi=ABI)
    except Exception as e:
        print(f"Blockchain contract initialization failed: {e}")
        contract = None


@app.get("/")
async def root():
    return {"message": "Project Evolve API is running."}


@app.get("/api/feedback")
async def get_feedback_entries(limit: int = Query(100, ge=1, le=500)):
    """Return submitted faculty feedback for display on the feedback page.

    Supports both database schemas used by this project:
    - local/newer: id + submitted_at
    - Supabase dump/older: feedback_id + created_at
    """
    try:
        inspector = sa.inspect(engine)
        if not inspector.has_table("faculty_feedback"):
            return {
                "feedback": [],
                "summary": {
                    "total": 0,
                    "avg_understandability": None,
                    "avg_trust": None,
                    "xai_viewed_count": 0,
                },
                "total": 0,
            }

        with engine.begin() as conn:
            columns = {
                row[0]
                for row in conn.execute(
                    sa.text("""
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_schema = 'public'
                          AND table_name = 'faculty_feedback'
                    """)
                )
            }

        id_column = "id" if "id" in columns else "feedback_id"
        timestamp_column = "submitted_at" if "submitted_at" in columns else "created_at"

        faculty_lookup_sql = ""
        faculty_join_sql = ""
        faculty_name_sql = "'Unknown Faculty' AS faculty_name"
        department_sql = "'N/A' AS department"
        if inspector.has_table("evaluation_results"):
            faculty_lookup_sql = """
                WITH faculty_lookup AS (
                    SELECT
                        faculty_id,
                        MAX(faculty_name) AS faculty_name,
                        MAX(department) AS department
                    FROM evaluation_results
                    GROUP BY faculty_id
                )
            """
            faculty_join_sql = "LEFT JOIN faculty_lookup fl ON fl.faculty_id = ff.faculty_id"
            faculty_name_sql = "COALESCE(fl.faculty_name, 'Unknown Faculty') AS faculty_name"
            department_sql = "COALESCE(fl.department, 'N/A') AS department"

        df = pd.read_sql(
            sa.text(f"""
                {faculty_lookup_sql}
                SELECT
                    ff.{id_column} AS id,
                    ff.faculty_id,
                    {faculty_name_sql},
                    {department_sql},
                    ff.understandability_score,
                    ff.trust_score,
                    ff.comment,
                    ff.xai_viewed,
                    ff.{timestamp_column} AS submitted_at
                FROM faculty_feedback ff
                {faculty_join_sql}
                ORDER BY ff.{timestamp_column} DESC, ff.{id_column} DESC
                LIMIT :limit
            """),
            engine,
            params={"limit": limit}
        )

        summary = pd.read_sql(
            sa.text("""
                SELECT
                    COUNT(*) AS total,
                    AVG(understandability_score) AS avg_understandability,
                    AVG(trust_score) AS avg_trust,
                    SUM(CASE WHEN xai_viewed THEN 1 ELSE 0 END) AS xai_viewed_count
                FROM faculty_feedback
            """),
            engine
        ).iloc[0].to_dict()

        return {
            "feedback": make_serializable(df.to_dict(orient="records")),
            "summary": make_serializable(summary),
            "total": int(summary.get("total") or 0),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Feedback list unavailable: {e}")


@app.post("/api/feedback")
async def submit_feedback(feedback: FeedbackCreate):
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text("""
                    INSERT INTO faculty_feedback
                    (faculty_id, understandability_score, trust_score, comment, xai_viewed)
                    VALUES (:fid, :und, :trust, :comment, :xai)
                """),
                {
                    "fid": feedback.faculty_id,
                    "und": feedback.understandability_score,
                    "trust": feedback.trust_score,
                    "comment": feedback.comment,
                    "xai": feedback.xai_viewed,
                }
            )
        return {"message": "Feedback submitted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/feedback/analysis")
async def get_feedback_analysis():
    try:
        df = pd.read_sql("SELECT trust_score, xai_viewed FROM faculty_feedback", engine)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Feedback analysis unavailable: {e}")

    if df.empty:
        return {"message": "No feedback data yet"}

    group_viewed = df[df["xai_viewed"] == True]["trust_score"].dropna()
    group_not_viewed = df[df["xai_viewed"] == False]["trust_score"].dropna()

    result = {
        "total_responses": int(len(df)),
        "average_trust_overall": float(df["trust_score"].mean()),
        "average_trust_xai_viewed": float(group_viewed.mean()) if len(group_viewed) else None,
        "average_trust_xai_not_viewed": float(group_not_viewed.mean()) if len(group_not_viewed) else None,
    }

    if len(group_viewed) < 2 or len(group_not_viewed) < 2:
        result["message"] = "Not enough responses in both groups for statistical testing."
        return result

    t_stat, p_value = ttest_ind(group_viewed, group_not_viewed, equal_var=False)
    result.update({
        "t_statistic": float(t_stat),
        "p_value": float(p_value),
        "interpretation": (
            f"Faculty who viewed XAI reports have average trust score "
            f"{group_viewed.mean():.2f}, compared with {group_not_viewed.mean():.2f} "
            f"for those who did not. p-value = {p_value:.4f}. "
            f"The difference is {'significant' if p_value < 0.05 else 'not significant'}."
        )
    })
    return result


@app.get("/faculties")
async def get_all_faculties(
    page: int = Query(1, ge=1),
    limit: int = Query(15, ge=1, le=100),
    search: Optional[str] = None,
    min_score: Optional[float] = None,
    max_score: Optional[float] = None,
    faculty_id: Optional[int] = None
):
    offset = (page - 1) * limit

    query = sa.text("""
        WITH ranked_faculties AS (
            SELECT
                faculty_id,
                faculty_name,
                department,
                ROUND(AVG(final_evaluation_score)::numeric, 2) AS final_evaluation_score,
                ROUND(AVG(student_feedback_rating)::numeric, 2) AS student_feedback_rating,
                ROUND(AVG(peer_score)::numeric, 2) AS peer_score,
                ROUND(AVG(avg_grade)::numeric, 2) AS avg_grade,
                ROUND(AVG(LEAST(GREATEST((avg_grade / 4.0) * 5.0, 1), 5))::numeric, 2) AS performance_score,
                ROUND(AVG(nlp_sentiment_score)::numeric, 2) AS nlp_sentiment_score,
                ROUND(AVG(course_quality_score)::numeric, 2) AS course_quality_score,
                ROUND(AVG(course_material_score)::numeric, 2) AS course_material_score,
                ROUND(AVG(service_score)::numeric, 2) AS service_score,
                ROUND(AVG(pd_score)::numeric, 2) AS pd_score,
                ROUND(AVG(total_service_hours)::numeric, 2) AS total_service_hours,
                ROUND(AVG(total_pd_hours)::numeric, 2) AS total_pd_hours
            FROM evaluation_results
            GROUP BY faculty_id, faculty_name, department
        )
        SELECT *
        FROM ranked_faculties
        WHERE (:search IS NULL OR faculty_name ILIKE :search_pattern OR department ILIKE :search_pattern)
          AND (:min_score IS NULL OR final_evaluation_score >= :min_score)
          AND (:max_score IS NULL OR final_evaluation_score <= :max_score)
          AND (:faculty_id IS NULL OR faculty_id = :faculty_id)
        ORDER BY final_evaluation_score DESC
        LIMIT :limit OFFSET :offset
    """)

    count_query = sa.text("""
        WITH ranked_faculties AS (
            SELECT
                faculty_id,
                faculty_name,
                department,
                ROUND(AVG(final_evaluation_score)::numeric, 2) AS final_evaluation_score
            FROM evaluation_results
            GROUP BY faculty_id, faculty_name, department
        )
        SELECT COUNT(*)
        FROM ranked_faculties
        WHERE (:search IS NULL OR faculty_name ILIKE :search_pattern OR department ILIKE :search_pattern)
          AND (:min_score IS NULL OR final_evaluation_score >= :min_score)
          AND (:max_score IS NULL OR final_evaluation_score <= :max_score)
          AND (:faculty_id IS NULL OR faculty_id = :faculty_id)
    """)

    params = {
        "search": search,
        "search_pattern": f"%{search}%" if search else None,
        "min_score": min_score,
        "max_score": max_score,
        "faculty_id": faculty_id,
        "limit": limit,
        "offset": offset,
    }

    df = pd.read_sql(query, engine, params=params)
    total = pd.read_sql(count_query, engine, params=params).iloc[0, 0]

    return {
        "faculties": make_serializable(df.to_dict(orient="records")),
        "pagination": {
            "page": page,
            "limit": limit,
            "total": int(total),
            "total_pages": (int(total) + limit - 1) // limit
        }
    }


@app.get("/evaluate/{faculty_id}")
async def evaluate_faculty(faculty_id: int):
    """Return the canonical seven-factor faculty evaluation report.

    This endpoint returns all seven formula factors plus the formula metadata
    needed by the frontend, PDF, XAI, and audit layers.
    """
    df = pd.read_sql(
        sa.text("""
            SELECT
                faculty_id,
                faculty_name,
                department,
                ROUND(AVG(final_evaluation_score)::numeric, 2) AS final_evaluation_score,
                ROUND(AVG(student_feedback_rating)::numeric, 2) AS student_feedback_rating,
                ROUND(AVG(peer_score)::numeric, 2) AS peer_score,
                ROUND(AVG(avg_grade)::numeric, 2) AS avg_grade,
                ROUND(AVG(LEAST(GREATEST((avg_grade / 4.0) * 5.0, 1), 5))::numeric, 2) AS performance_score,
                ROUND(AVG(nlp_sentiment_score)::numeric, 2) AS nlp_sentiment_score,
                ROUND(AVG(course_quality_score)::numeric, 2) AS course_quality_score,
                ROUND(AVG(course_material_score)::numeric, 2) AS course_material_score,
                ROUND(AVG(service_score)::numeric, 2) AS service_score,
                ROUND(AVG(pd_score)::numeric, 2) AS pd_score,
                ROUND(AVG(total_service_hours)::numeric, 2) AS total_service_hours,
                ROUND(AVG(total_pd_hours)::numeric, 2) AS total_pd_hours
            FROM evaluation_results
            WHERE faculty_id = :faculty_id
            GROUP BY faculty_id, faculty_name, department
        """),
        engine,
        params={"faculty_id": faculty_id}
    )

    if df.empty:
        raise HTTPException(status_code=404, detail="Faculty not found")

    row = df.iloc[0]
    factor_values = {
        "student_feedback_rating": row.get("student_feedback_rating"),
        "peer_score": row.get("peer_score"),
        "performance_score": row.get("performance_score"),
        "nlp_sentiment_score": row.get("nlp_sentiment_score"),
        "course_material_score": row.get("course_material_score"),
        "service_score": row.get("service_score"),
        "pd_score": row.get("pd_score"),
    }
    factor_breakdown = build_factor_breakdown(factor_values)
    formula_score = calculate_seven_factor_score(factor_values)

    # key_factors is retained for frontend/backward compatibility and contains
    # all seven canonical factors.
    key_factors = {
        "student_feedback": float(row.get("student_feedback_rating", 0)),
        "peer_review": float(row.get("peer_score", 0)),
        "performance": float(row.get("performance_score", 0)),
        "nlp_sentiment": float(row.get("nlp_sentiment_score", 0)),
        "course_material": float(row.get("course_material_score", 0)),
        "service_contribution": float(row.get("service_score", 0)),
        "professional_development": float(row.get("pd_score", 0)),
    }

    return {
        "faculty_id": int(row["faculty_id"]),
        "faculty_name": row["faculty_name"],
        "department": row["department"],
        "final_evaluation_score": float(row["final_evaluation_score"]),
        "computed_formula_score_from_aggregated_factors": float(formula_score),
        "formula_version": FORMULA_VERSION,
        "formula": "0.25*student_feedback + 0.20*peer_review + 0.15*performance + 0.10*nlp_sentiment + 0.05*course_material + 0.15*service_contribution + 0.10*professional_development",
        "weights": dict(FACTOR_WEIGHTS),
        "factor_breakdown": factor_breakdown,
        "key_factors": key_factors,
        "supporting_values": {
            "avg_grade_raw": float(row.get("avg_grade", 0)),
            "course_quality_proxy_not_in_final_formula": float(row.get("course_quality_score", 0)),
            "total_service_hours": float(row.get("total_service_hours", 0)),
            "total_pd_hours": float(row.get("total_pd_hours", 0)),
        },
        # Kept for old frontend components. The canonical course factor is now
        # course_material_score, but course_quality_score remains useful as a
        # supporting proxy display value.
        "course_quality_score": float(row.get("course_quality_score", 0)),
        "course_material_score": float(row.get("course_material_score", 0)),
        "service_score": float(row.get("service_score", 0)),
        "pd_score": float(row.get("pd_score", 0)),
    }


@app.get("/explanation/{faculty_id}")
async def get_explanation(faculty_id: int):
    """Return synchronized seven-factor explainability output.

    The explanation is computed directly from the current seven-factor
    evaluation_results table so the XAI view always matches the score shown
    in the report.
    """
    return make_serializable(_canonical_explanation_payload(faculty_id))


@app.get("/explanation/lime/{faculty_id}")
async def get_lime_explanation(faculty_id: int):
    if faculty_id in lime_cache:
        cached_time, html = lime_cache[faculty_id]
        if datetime.now() - cached_time < timedelta(hours=24):
            return Response(content=html, media_type="text/html")
    try:
        result = subprocess.run(
            ["python", "src/xai/generate_lime.py", str(faculty_id)],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        )
        if result.returncode != 0:
            raise HTTPException(500, f"LIME generation failed: {result.stderr}")
        safe_version = FORMULA_VERSION.replace(".", "_").replace("-", "_")
        html_path = f"explanations/lime_{faculty_id}_{safe_version}.html"
        if not os.path.exists(html_path):
            # Backward-compatible fallback only for local development. The
            # generator also writes the versioned path to keep LIME outputs
            # aligned with the formula version.
            legacy_path = f"explanations/lime_{faculty_id}.html"
            html_path = legacy_path if os.path.exists(legacy_path) else html_path
        if not os.path.exists(html_path):
            raise HTTPException(404, "LIME HTML file was not generated")
        with open(html_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        lime_cache[faculty_id] = (datetime.now(), html_content)
        return Response(content=html_content, media_type="text/html")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Error generating LIME: {str(e)}")


@app.post("/api/xai/precompute_shap")
async def precompute_shap():
    try:
        result = subprocess.run(
            ["python", "src/xai/precompute_shap.py"],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        )
        if result.returncode != 0:
            raise HTTPException(500, f"Precomputation failed: {result.stderr}")
        return {"message": "SHAP values precomputed successfully"}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/audit/{faculty_id}")
async def get_audit_trail(faculty_id: int):
    """Return the most recent canonical seven-factor audit hash for one faculty.

    Prefer blockchain_audit_logs because it can be regenerated from the current
    seven-factor payload. Fall back to the legacy evaluation_results_with_blockchain
    table only when no canonical log exists.
    """
    try:
        inspector = sa.inspect(engine)

        if inspector.has_table("blockchain_audit_logs"):
            df = pd.read_sql(
                sa.text("""
                    SELECT faculty_id, final_score, blockchain_tx_hash, result_hash,
                           timestamp, status, formula_version
                    FROM blockchain_audit_logs
                    WHERE faculty_id = :faculty_id
                    ORDER BY timestamp DESC, id DESC
                    LIMIT 1
                """),
                engine,
                params={"faculty_id": faculty_id}
            )
            if not df.empty:
                row = df.iloc[0]
                return {
                    "faculty_id": int(row["faculty_id"]),
                    "final_score": float(row.get("final_score") or 0),
                    "blockchain_tx_hash": row.get("blockchain_tx_hash") or "Database-only canonical hash",
                    "result_hash": row.get("result_hash") or "N/A",
                    "timestamp": str(row.get("timestamp", datetime.utcnow())),
                    "status": row.get("status") or "Canonical seven-factor audit hash available.",
                    "formula_version": row.get("formula_version") or FORMULA_VERSION,
                    "audit_source": "blockchain_audit_logs"
                }

        if inspector.has_table("evaluation_results_with_blockchain"):
            df = pd.read_sql(
                sa.text("""
                    SELECT *
                    FROM evaluation_results_with_blockchain
                    WHERE faculty_id = :faculty_id
                    LIMIT 1
                """),
                engine,
                params={"faculty_id": faculty_id}
            )
            if not df.empty:
                row = df.iloc[0]
                timestamp_value = row.get("timestamp", row.get("logged_at", datetime.utcnow()))
                return {
                    "faculty_id": int(row["faculty_id"]),
                    "final_score": float(row.get("final_evaluation_score", 0)),
                    "blockchain_tx_hash": row.get("blockchain_tx_hash") or "Legacy record without transaction hash",
                    "result_hash": row.get("result_hash", "N/A"),
                    "timestamp": str(timestamp_value),
                    "status": "Legacy audit record from an earlier scoring version. Regenerate canonical seven-factor audit hashes before final deployment.",
                    "formula_version": "legacy_pre_seven_factor",
                    "audit_source": "evaluation_results_with_blockchain"
                }

        return {
            "faculty_id": faculty_id,
            "final_score": 0,
            "blockchain_tx_hash": "Not available",
            "result_hash": "N/A",
            "timestamp": str(datetime.utcnow()),
            "status": "No audit record found. Run src/audit/regenerate_audit_hashes.py to create canonical seven-factor hashes.",
            "formula_version": FORMULA_VERSION,
            "audit_source": "none"
        }
    except Exception as e:
        print(f"Audit endpoint error: {e}")
        return {
            "faculty_id": faculty_id,
            "final_score": 0,
            "blockchain_tx_hash": "Not available",
            "result_hash": "N/A",
            "timestamp": str(datetime.utcnow()),
            "status": "Blockchain/audit service currently unavailable.",
            "formula_version": FORMULA_VERSION,
            "audit_source": "error"
        }


@app.get("/verify/{faculty_id}")
async def verify_blockchain(faculty_id: int):
    if contract is None:
        raise HTTPException(status_code=503, detail="Blockchain service unavailable. Start Ganache and set CONTRACT_ADDRESS.")
    inspector = sa.inspect(engine)
    source_table = "evaluation_results_with_blockchain" if inspector.has_table("evaluation_results_with_blockchain") else "evaluation_results"
    df_db = pd.read_sql(
        sa.text(f"""
            SELECT *
            FROM {source_table}
            WHERE faculty_id = :faculty_id
            LIMIT 1
        """),
        engine,
        params={"faculty_id": faculty_id}
    )
    if df_db.empty:
        raise HTTPException(status_code=404, detail="Faculty not found")
    row = df_db.iloc[0]
    timestamp_value = row.get("timestamp", row.get("logged_at", None))
    if timestamp_value is None:
        raise HTTPException(status_code=400, detail="Cannot verify because the original blockchain timestamp is missing.")
    record_payload = {
        "faculty_id": int(row["faculty_id"]),
        "final_score": float(row["final_evaluation_score"]),
        "nlp_sentiment": float(row["nlp_sentiment_score"]) if "nlp_sentiment_score" in row else None,
        "timestamp": str(timestamp_value)
    }
    recomputed = hashlib.sha256(json.dumps(record_payload, sort_keys=True).encode()).hexdigest()
    try:
        onchain = contract.functions.getEvaluation(faculty_id).call()
        onchain_hash = onchain[2]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Blockchain verification failed: {str(e)}")
    return {
        "verified": recomputed == onchain_hash,
        "recomputed_hash": recomputed,
        "onchain_hash": onchain_hash,
        "payload_used": record_payload
    }


@app.get("/export_pdf/{faculty_id}")
async def export_audit_pdf(faculty_id: int):
    """Generate a complete seven-factor faculty audit PDF.

    The PDF now matches the canonical seven-factor score used by
    evaluation_results and the updated SHAP/LIME scripts.
    """

    def fmt(value, default="Not available"):
        if value is None:
            return default
        try:
            if pd.isna(value):
                return default
        except Exception:
            pass
        if isinstance(value, (float, np.floating)):
            return f"{float(value):.2f}"
        return str(value)

    def score(value, default=0.0):
        try:
            if value is None or pd.isna(value):
                return default
            return float(value)
        except Exception:
            return default

    df_db = pd.read_sql(
        sa.text("""
            SELECT
                faculty_id,
                faculty_name,
                department,
                ROUND(AVG(final_evaluation_score)::numeric, 2) AS final_evaluation_score,
                ROUND(AVG(student_feedback_rating)::numeric, 2) AS student_feedback_rating,
                ROUND(AVG(peer_score)::numeric, 2) AS peer_score,
                ROUND(AVG(avg_grade)::numeric, 2) AS avg_grade,
                ROUND(AVG(LEAST(GREATEST((avg_grade / 4.0) * 5.0, 1), 5))::numeric, 2) AS performance_score,
                ROUND(AVG(nlp_sentiment_score)::numeric, 2) AS nlp_sentiment_score,
                ROUND(AVG(course_quality_score)::numeric, 2) AS course_quality_score,
                ROUND(AVG(course_material_score)::numeric, 2) AS course_material_score,
                ROUND(AVG(service_score)::numeric, 2) AS service_score,
                ROUND(AVG(pd_score)::numeric, 2) AS pd_score,
                ROUND(AVG(total_service_hours)::numeric, 2) AS total_service_hours,
                ROUND(AVG(total_pd_hours)::numeric, 2) AS total_pd_hours
            FROM evaluation_results
            WHERE faculty_id = :faculty_id
            GROUP BY faculty_id, faculty_name, department
        """),
        engine,
        params={"faculty_id": faculty_id}
    )
    if df_db.empty:
        raise HTTPException(status_code=404, detail="Faculty not found")

    row = df_db.iloc[0]
    final_score = score(row.get("final_evaluation_score"))
    factor_values = {
        "student_feedback_rating": row.get("student_feedback_rating"),
        "peer_score": row.get("peer_score"),
        "performance_score": row.get("performance_score"),
        "nlp_sentiment_score": row.get("nlp_sentiment_score"),
        "course_material_score": row.get("course_material_score"),
        "service_score": row.get("service_score"),
        "pd_score": row.get("pd_score"),
    }
    factor_breakdown = build_factor_breakdown(factor_values)

    result_hash = "Not available"
    transaction_hash = "Not available"
    audit_timestamp = "Not available"
    audit_status = "No canonical audit record was found for this faculty member."

    inspector = sa.inspect(engine)
    try:
        if inspector.has_table("blockchain_audit_logs"):
            log_df = pd.read_sql(
                sa.text("""
                    SELECT result_hash, blockchain_tx_hash, timestamp, status, formula_version
                    FROM blockchain_audit_logs
                    WHERE faculty_id = :faculty_id
                    ORDER BY timestamp DESC, id DESC
                    LIMIT 1
                """),
                engine,
                params={"faculty_id": faculty_id}
            )
            if not log_df.empty:
                log_row = log_df.iloc[0]
                result_hash = fmt(log_row.get("result_hash"), result_hash)
                transaction_hash = fmt(log_row.get("blockchain_tx_hash"), transaction_hash)
                audit_timestamp = fmt(log_row.get("timestamp"), audit_timestamp)
                audit_status = fmt(log_row.get("status"), audit_status)

        if result_hash == "Not available" and inspector.has_table("evaluation_results_with_blockchain"):
            audit_df = pd.read_sql(
                sa.text("""
                    SELECT *
                    FROM evaluation_results_with_blockchain
                    WHERE faculty_id = :faculty_id
                    LIMIT 1
                """),
                engine,
                params={"faculty_id": faculty_id}
            )
            if not audit_df.empty:
                audit_row = audit_df.iloc[0]
                result_hash = fmt(audit_row.get("result_hash"), result_hash)
                transaction_hash = fmt(audit_row.get("blockchain_tx_hash"), transaction_hash)
                audit_timestamp = fmt(audit_row.get("timestamp", audit_row.get("logged_at")), audit_timestamp)
                audit_status = "Legacy blockchain audit record found; regenerate canonical seven-factor audit hashes for final deployment."
    except Exception as e:
        print(f"PDF audit lookup failed: {e}")

    recommendations = []
    factor_map = {item["key"]: item["value"] for item in factor_breakdown}
    if factor_map.get("nlp_sentiment_score", 0) < 3:
        recommendations.append(["Improve Clarity in Explanations", "Student comments and NLP sentiment indicate possible confusion. Add concrete examples, visual aids, and recap checkpoints."])
    if factor_map.get("student_feedback_rating", 0) < 3.5:
        recommendations.append(["Boost Student Engagement", "Student feedback is below the preferred range. Increase interaction, office-hour visibility, and participation opportunities."])
    if factor_map.get("peer_score", 0) < 3.5:
        recommendations.append(["Schedule Peer Observation", "Peer score is below target. A structured teaching observation can provide practical improvement evidence."])
    if factor_map.get("performance_score", 0) < 3.5:
        recommendations.append(["Support Student Success", "Student outcome indicators are below target. Consider formative assessment, early intervention, and learning support."])
    if factor_map.get("course_material_score", 0) < 3.5:
        recommendations.append(["Strengthen Course Materials", "Course material/readability score suggests room for improvement. Review syllabus clarity, rubrics, assignments, and learning resources."])
    if factor_map.get("service_score", 0) < 3:
        recommendations.append(["Increase Documented Academic Service", "Service contribution evidence is low in the prototype record. Record committee work, mentoring, outreach, or curriculum service."])
    if factor_map.get("pd_score", 0) < 3:
        recommendations.append(["Expand Professional Development", "Professional-development score is low in the prototype record. Add workshops, teaching certifications, conferences, or pedagogy training."])
    if final_score > 4.2:
        recommendations.append(["Exceptional Overall Performance", "The canonical seven-factor score is high. Continue current best practices and consider mentoring junior faculty or leading initiatives."])
    if not recommendations:
        recommendations.append(["Maintain Continuous Improvement", "Overall indicators are stable. Continue monitoring all seven evidence dimensions each term."])

    try:
        explanation_payload = _canonical_explanation_payload(faculty_id)
        ordered = explanation_payload.get("all_factor_contributions", [])
        shap_summary = "; ".join([
            f"{item['feature']}: {float(item['contribution']):+.3f} "
            f"(value {float(item['value']):.2f}, baseline {float(item['baseline_value']):.2f}, weight {float(item['weight']) * 100:.0f}%)"
            for item in ordered
        ])
    except Exception as e:
        print(f"PDF canonical explanation generation failed: {e}")
        shap_summary = "Canonical seven-factor explanation unavailable for this faculty record."

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.65 * inch,
        leftMargin=0.65 * inch,
        topMargin=0.55 * inch,
        bottomMargin=0.55 * inch,
        title=f"Project Evolve Seven-Factor Audit Report - Faculty {faculty_id}"
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("ProjectEvolveTitle", parent=styles["Title"], fontSize=18, leading=22, spaceAfter=12, textColor=colors.HexColor("#1f2937"))
    section_style = ParagraphStyle("ProjectEvolveSection", parent=styles["Heading2"], fontSize=13, leading=16, spaceBefore=10, spaceAfter=8, textColor=colors.HexColor("#1d4ed8"))
    normal = ParagraphStyle("ProjectEvolveNormal", parent=styles["BodyText"], fontSize=9.5, leading=13, spaceAfter=6)
    small = ParagraphStyle("ProjectEvolveSmall", parent=styles["BodyText"], fontSize=8, leading=10)

    def p(text, style=normal):
        return Paragraph(str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"), style)

    def table(rows, widths=None):
        t = Table(rows, colWidths=widths, hAlign="LEFT")
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5edff")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#111827")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8.2),
            ("LEADING", (0, 0), (-1, -1), 10.2),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#cbd5e1")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        return t

    story = []
    story.append(Paragraph("Project Evolve - Seven-Factor Faculty Audit Report", title_style))
    story.append(p(f"Generated on: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC", small))
    story.append(p(f"Canonical formula version: {FORMULA_VERSION}", small))
    story.append(Spacer(1, 8))

    story.append(Paragraph("Faculty Overview", section_style))
    story.append(table([
        [p("Field", small), p("Value", small)],
        [p("Faculty ID", small), p(faculty_id, small)],
        [p("Name", small), p(fmt(row.get("faculty_name")), small)],
        [p("Department", small), p(fmt(row.get("department")), small)],
        [p("Final Evaluation Score", small), p(fmt(final_score), small)],
    ], [2.0 * inch, 4.3 * inch]))

    story.append(Paragraph("Canonical Seven-Factor Formula", section_style))
    story.append(p("Final Score = 0.25*Student Feedback + 0.20*Peer Review + 0.15*Performance + 0.10*NLP Sentiment + 0.05*Course Material + 0.15*Service Contribution + 0.10*Professional Development", normal))

    story.append(Paragraph("Evaluation Factors", section_style))
    factor_rows = [[p("Factor", small), p("Value", small), p("Weight", small), p("Weighted contribution", small), p("Meaning/source", small)]]
    for item in factor_breakdown:
        factor_rows.append([
            p(item["label"], small),
            p(fmt(item["value"]), small),
            p(f"{item['weight_percent']:.1f}%", small),
            p(fmt(item["weighted_contribution"]), small),
            p(item["description"], small),
        ])
    story.append(table(factor_rows, [1.35 * inch, 0.55 * inch, 0.55 * inch, 0.9 * inch, 3.0 * inch]))

    story.append(Paragraph("Supporting Non-Formula Values", section_style))
    story.append(table([
        [p("Value", small), p("Display", small), p("Note", small)],
        [p("Raw avg_grade", small), p(fmt(row.get("avg_grade")), small), p("Stored student outcome value before normalization.", small)],
        [p("Course quality proxy", small), p(fmt(row.get("course_quality_score")), small), p("Legacy/display proxy; canonical formula uses course_material_score.", small)],
        [p("Total service hours", small), p(fmt(row.get("total_service_hours")), small), p("Used to generate service_score.", small)],
        [p("Total PD hours", small), p(fmt(row.get("total_pd_hours")), small), p("Used to generate pd_score.", small)],
    ], [1.8 * inch, 1.0 * inch, 3.5 * inch]))

    story.append(Paragraph("Explainable AI Summary", section_style))
    story.append(p(shap_summary, normal))

    story.append(Paragraph("Audit Details", section_style))
    story.append(table([
        [p("Audit Field", small), p("Value", small)],
        [p("Transaction Hash", small), p(transaction_hash, small)],
        [p("Result Hash", small), p(result_hash, small)],
        [p("Audit Timestamp", small), p(audit_timestamp, small)],
        [p("Audit Status", small), p(audit_status, small)],
    ], [2.0 * inch, 4.3 * inch]))

    story.append(Paragraph("Actionable Recommendations", section_style))
    recommendation_rows = [[p("Recommendation", small), p("Details", small)]]
    recommendation_rows.extend([[p(title, small), p(detail, small)] for title, detail in recommendations])
    story.append(table(recommendation_rows, [2.0 * inch, 4.3 * inch]))

    story.append(Spacer(1, 10))
    story.append(p("This report is generated for transparent, human-reviewed faculty development. It is not an automatic high-stakes personnel decision.", small))

    doc.build(story)
    buffer.seek(0)
    return Response(
        content=buffer.getvalue(),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=project_evolve_seven_factor_audit_{faculty_id}.pdf",
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "X-Project-Evolve-PDF-Version": "seven-factor-v2"
        }
    )


def _normalise_department_list(values):
    """Clean and sort department names for the fairness selector."""
    cleaned = []
    seen = set()
    for value in values or []:
        if value is None:
            continue
        department = str(value).strip()
        if not department or department.lower() in {"nan", "none", "null", "\\n"} or department == "\\N":
            continue
        key = department.lower()
        if key not in seen:
            seen.add(key)
            cleaned.append(department)
    return sorted(cleaned, key=lambda item: item.lower())


FAIRNESS_OVERALL_LABEL = "Overall / All Departments"


def _load_departments_from_reports():
    files = glob.glob(os.path.join("reports", "fairness_report_*.json"))
    for path in sorted(files, key=os.path.getctime, reverse=True):
        try:
            with open(path, "r") as f:
                data = json.load(f)
            departments = _normalise_department_list(data.get("available_departments", []))
            if departments:
                return departments
            selected = data.get("selected_department")
            if selected:
                return _normalise_department_list([selected])
        except Exception:
            continue
    return []


def _load_departments_from_sql_dump():
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    dump_path = os.path.join(project_root, "evolve_db_dump.sql")
    if not os.path.exists(dump_path):
        return []
    try:
        header = None
        dept_index = None
        values = []
        reading = False
        with open(dump_path, "r", encoding="utf-8", errors="ignore") as handle:
            for raw_line in handle:
                line = raw_line.rstrip("\n")
                if line.startswith("COPY public.evaluation_results "):
                    columns_part = line.split("(", 1)[1].rsplit(")", 1)[0]
                    header = [column.strip() for column in columns_part.split(",")]
                    dept_index = header.index("department") if "department" in header else None
                    reading = True
                    continue
                if reading:
                    if line == "\\.":
                        break
                    if dept_index is None:
                        continue
                    parts = line.split("\t")
                    if len(parts) > dept_index:
                        values.append(parts[dept_index])
        return _normalise_department_list(values)
    except Exception as e:
        print(f"SQL dump department fallback failed: {e}")
        return []


def _load_departments_from_csv():
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    csv_path = os.path.join(project_root, "data", "raw", "ratemyprofessor_sample.csv")
    if not os.path.exists(csv_path):
        return []
    try:
        df = pd.read_csv(csv_path, usecols=["department_name"])
        return _normalise_department_list(df["department_name"].dropna().tolist())
    except Exception as e:
        print(f"CSV department fallback failed: {e}")
        return []


@app.get("/api/fairness/departments")
async def get_fairness_departments():
    """Return only departments that can actually run a fairness audit.

    We intentionally do not fall back to the raw CSV department list here,
    because that list can include departments with no usable evaluation/gender
    data on the deployed database. Those options caused the selector to show
    departments that failed when selected.
    """
    sources_checked = []

    try:
        from src.fairness.audit import load_data as load_fairness_data, get_available_departments
        df = load_fairness_data(engine)
        departments = get_available_departments(df, include_overall=True, require_fairness_ready=True)
        sources_checked.append("evaluation_results/live_or_sql_fallback")
        return {
            "departments": departments or [FAIRNESS_OVERALL_LABEL],
            "source": "fairness_data_source",
            "sources_checked": sources_checked,
        }
    except Exception as e:
        print(f"Fairness data department load failed: {e}")
        sources_checked.append("evaluation_results_failed")
        return {
            "departments": [FAIRNESS_OVERALL_LABEL],
            "source": "safe_overall_only_fallback",
            "sources_checked": sources_checked,
        }


@app.get("/api/fairness/latest")
async def get_latest_fairness_report():
    files = glob.glob(os.path.join("reports", "fairness_report_*.json"))
    if not files:
        raise HTTPException(404, "No fairness reports found. Run audit first.")
    latest = max(files, key=os.path.getmtime)
    with open(latest, "r") as f:
        return json.load(f)


@app.post("/api/fairness/run")
async def run_fairness_audit(department: Optional[str] = Query(None)):
    """Run a department-specific fairness audit and return that exact report.

    The previous implementation launched the audit as a subprocess and then
    guessed the newest JSON file from the reports folder. On some deployments
    that could return an older CS/Engineering report, making the graph and
    metrics look unchanged even after selecting another department. This version
    runs the audit in-process and returns the report object produced for the
    selected department.
    """
    try:
        from src.fairness.audit import (
            load_data as load_fairness_data,
            resolve_selected_department,
            compute_fairness_metrics,
            detect_department_peer_bias,
            generate_fairness_report,
            send_alert,
            is_overall_department,
            _department_frame,
        )

        df = load_fairness_data(engine)
        selected_department = resolve_selected_department(df, department)
        metrics_source = df if is_overall_department(selected_department) else _department_frame(df, selected_department)
        if metrics_source.empty:
            raise HTTPException(status_code=404, detail=f"No usable fairness data found for department: {department}")

        metrics = compute_fairness_metrics(metrics_source)
        department_bias = detect_department_peer_bias(df, selected_department)
        report, _html_path = generate_fairness_report(
            df,
            metrics,
            department_bias,
            selected_department,
            output_dir="reports",
        )
        try:
            send_alert(report, engine)
        except Exception as alert_error:
            print(f"Fairness audit alert/log save failed: {alert_error}")
        return report
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/validation/run")
async def run_validation():
    try:
        result = subprocess.run(
            ["python", "src/validation/hypothesis_testing.py"],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        )
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"Script failed: {result.stderr}")
        files = glob.glob(os.path.join("reports", "validation_report_*.json"))
        if not files:
            raise HTTPException(status_code=404, detail="No validation report generated.")
        latest = max(files, key=os.path.getctime)
        with open(latest, "r") as f:
            return json.load(f)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/validation/latest")
async def get_latest_validation_report():
    files = glob.glob(os.path.join("reports", "validation_report_*.json"))
    if not files:
        raise HTTPException(404, "No validation report found. Run validation first.")
    latest = max(files, key=os.path.getctime)
    with open(latest, "r") as f:
        return json.load(f)


@app.get("/api/stats")
async def get_dashboard_stats():
    avg_score = pd.read_sql("SELECT AVG(final_evaluation_score) FROM evaluation_results", engine).iloc[0, 0]
    bias_value = 0.0
    files = glob.glob(os.path.join("reports", "fairness_report_*.json"))
    if files:
        latest = max(files, key=os.path.getctime)
        with open(latest, "r") as f:
            data = json.load(f)
            bias_value = data.get("fairness_metrics", {}).get("demographic_parity_difference", 0.0)
    blockchain_count = 0
    try:
        inspector = sa.inspect(engine)
        if inspector.has_table("blockchain_audit_logs"):
            blockchain_count = pd.read_sql("SELECT COUNT(*) FROM blockchain_audit_logs", engine).iloc[0, 0]
        if (not blockchain_count) and inspector.has_table("evaluation_results_with_blockchain"):
            blockchain_count = pd.read_sql("SELECT COUNT(*) FROM evaluation_results_with_blockchain", engine).iloc[0, 0]
    except Exception:
        blockchain_count = 0
    return {
        "average_score": round(float(avg_score or 0), 2),
        "bias_detected": round(float(bias_value or 0), 3),
        "blockchain_logged": int(blockchain_count),
        "formula_version": FORMULA_VERSION
    }


@app.get("/api/audit/all")
async def get_audit_trail_paginated(page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=100)):
    offset = (page - 1) * limit
    try:
        inspector = sa.inspect(engine)

        if inspector.has_table("blockchain_audit_logs"):
            total = pd.read_sql("SELECT COUNT(*) FROM blockchain_audit_logs", engine).iloc[0, 0]
            if int(total or 0) > 0:
                df = pd.read_sql(
                    sa.text("""
                        SELECT
                            faculty_id,
                            final_score,
                            blockchain_tx_hash,
                            result_hash,
                            timestamp,
                            status,
                            formula_version
                        FROM blockchain_audit_logs
                        ORDER BY timestamp DESC, id DESC
                        LIMIT :limit OFFSET :offset
                    """),
                    engine,
                    params={"limit": limit, "offset": offset}
                )
                df = df.where(pd.notnull(df), None)
                return {
                    "transactions": make_serializable(df.to_dict(orient="records")),
                    "audit_source": "blockchain_audit_logs",
                    "formula_version": FORMULA_VERSION,
                    "pagination": {
                        "page": page,
                        "limit": limit,
                        "total": int(total),
                        "total_pages": (int(total) + limit - 1) // limit if total > 0 else 0
                    }
                }

        if not inspector.has_table("evaluation_results_with_blockchain"):
            return {"transactions": [], "audit_source": "none", "pagination": {"page": page, "limit": limit, "total": 0, "total_pages": 0}}

        columns = [col["name"] for col in inspector.get_columns("evaluation_results_with_blockchain")]
        score_col = "final_evaluation_score" if "final_evaluation_score" in columns else "NULL"
        tx_hash_col = "blockchain_tx_hash" if "blockchain_tx_hash" in columns else "NULL"
        result_hash_col = "result_hash" if "result_hash" in columns else "NULL"
        ts_col = "timestamp" if "timestamp" in columns else ("logged_at" if "logged_at" in columns else "CURRENT_TIMESTAMP")
        query = f"""
            SELECT
                faculty_id,
                {score_col} as final_score,
                {tx_hash_col} as blockchain_tx_hash,
                {result_hash_col} as result_hash,
                {ts_col} as timestamp,
                'legacy_pre_seven_factor' as formula_version,
                'Legacy audit table from earlier scoring version; regenerate canonical hashes.' as status
            FROM evaluation_results_with_blockchain
            ORDER BY {ts_col} DESC
            LIMIT :limit OFFSET :offset
        """
        df = pd.read_sql(sa.text(query), engine, params={"limit": limit, "offset": offset})
        df = df.where(pd.notnull(df), None)
        total = pd.read_sql("SELECT COUNT(*) FROM evaluation_results_with_blockchain", engine).iloc[0, 0]
        return {
            "transactions": make_serializable(df.to_dict(orient="records")),
            "audit_source": "evaluation_results_with_blockchain_legacy",
            "formula_version": "legacy_pre_seven_factor",
            "pagination": {
                "page": page,
                "limit": limit,
                "total": int(total),
                "total_pages": (int(total) + limit - 1) // limit if total > 0 else 0
            }
        }
    except Exception as e:
        print(f"Audit paginated query failed: {e}")
        return {"transactions": [], "audit_source": "error", "pagination": {"page": page, "limit": limit, "total": 0, "total_pages": 0}}


@app.get("/health")
async def health_check():
    db_status = "ok"
    try:
        with engine.connect() as conn:
            conn.execute(sa.text("SELECT 1"))
    except Exception:
        db_status = "down"
    blockchain_status = "connected" if w3.is_connected() else "disconnected"
    try:
        inspector = sa.inspect(engine)
        ml_status = "ok" if inspector.has_table("shap_explanations") else "missing"
    except Exception:
        ml_status = "missing"
    return {
        "status": "healthy" if db_status == "ok" else "degraded",
        "database": db_status,
        "blockchain": blockchain_status,
        "ml_models": ml_status,
        "timestamp": datetime.now().isoformat()
    }


@app.get("/api/ethics/pending")
async def get_pending_reviews():
    df = pd.read_sql("""
        SELECT er.*, ebm.member_name
        FROM ethics_reviews er
        LEFT JOIN ethics_board_members ebm ON er.reviewer_id = ebm.id
        WHERE er.decision = 'pending'
        ORDER BY er.reviewed_at DESC
    """, engine)
    return make_serializable(df.to_dict(orient="records"))


@app.post("/api/ethics/approve/{review_id}")
async def approve_review(review_id: int, comments: str = ""):
    with engine.begin() as conn:
        conn.execute(
            sa.text("UPDATE ethics_reviews SET decision = 'approved', comments = :comments WHERE id = :rid"),
            {"comments": comments, "rid": review_id}
        )
    return {"status": "approved"}


@app.post("/api/fairness/mitigate")
async def run_bias_mitigation():
    df = pd.read_sql("SELECT * FROM evaluation_results", engine)
    df, applied = mitigate_bias(df)
    if applied:
        with engine.begin() as conn:
            for _, row in df.iterrows():
                conn.execute(
                    sa.text("UPDATE evaluation_results SET mitigated_score = :ms WHERE faculty_id = :fid"),
                    {"ms": row["mitigated_score"], "fid": int(row["faculty_id"])}
                )
        return {"message": "Bias mitigation applied", "applied": True}
    return {"message": "No mitigation needed", "applied": False}


@app.get("/api/analytics/overview")
async def get_analytics_overview():
    score_dist = pd.read_sql("""
        SELECT floor(final_evaluation_score * 2) / 2 as bucket, COUNT(*) as count
        FROM evaluation_results
        GROUP BY bucket
        ORDER BY bucket
    """, engine)
    dept_comp = pd.read_sql("""
        SELECT department, AVG(final_evaluation_score) as avg_score, COUNT(*) as count
        FROM evaluation_results
        GROUP BY department
        ORDER BY avg_score DESC
        LIMIT 10
    """, engine)
    gender_fair = pd.read_sql("""
        SELECT f.gender, AVG(e.final_evaluation_score) as avg_score, COUNT(*) as count
        FROM evaluation_results e
        JOIN faculty f ON e.faculty_id = f.faculty_id
        GROUP BY f.gender
    """, engine)
    return {
        "score_distribution": make_serializable(score_dist.to_dict(orient="records")),
        "department_comparison": make_serializable(dept_comp.to_dict(orient="records")),
        "gender_fairness": make_serializable(gender_fair.to_dict(orient="records"))
    }
