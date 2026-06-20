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
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))

            conn.execute(sa.text("""
                CREATE TABLE IF NOT EXISTS blockchain_audit_logs (
                    id SERIAL PRIMARY KEY,
                    evaluation_id INTEGER,
                    faculty_id INTEGER NOT NULL,
                    result_hash TEXT NOT NULL,
                    blockchain_tx_hash TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'logged'
                )
            """))
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
                ROUND(AVG(nlp_sentiment_score)::numeric, 2) AS nlp_sentiment_score,
                ROUND(AVG(course_quality_score)::numeric, 2) AS course_quality_score
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
    df = pd.read_sql(
        sa.text("""
            SELECT
                faculty_id,
                faculty_name,
                department,
                ROUND(AVG(final_evaluation_score)::numeric, 2) AS final_evaluation_score,
                ROUND(AVG(course_quality_score)::numeric, 2) AS course_quality_score,
                ROUND(AVG(student_feedback_rating)::numeric, 2) AS student_feedback_rating,
                ROUND(AVG(peer_score)::numeric, 2) AS peer_score,
                ROUND(AVG(nlp_sentiment_score)::numeric, 2) AS nlp_sentiment_score,
                ROUND(AVG(avg_grade)::numeric, 2) AS avg_grade
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

    return {
        "faculty_id": int(row["faculty_id"]),
        "faculty_name": row["faculty_name"],
        "department": row["department"],
        "final_evaluation_score": float(row["final_evaluation_score"]),
        "course_quality_score": float(row.get("course_quality_score", 0)),
        "key_factors": {
            "student_feedback": float(row["student_feedback_rating"]),
            "peer_review": float(row["peer_score"]),
            "nlp_sentiment": float(row["nlp_sentiment_score"]),
            "performance": float(row["avg_grade"])
        }
    }


@app.get("/explanation/{faculty_id}")
async def get_explanation(faculty_id: int):
    df_shap = pd.read_sql(
        sa.text("""
            SELECT shap_values_json, base_value
            FROM shap_explanations
            WHERE faculty_id = :faculty_id
        """),
        engine,
        params={"faculty_id": faculty_id}
    )
    if df_shap.empty:
        return {
            "final_score": 0,
            "top_positive_factors": [],
            "top_negative_factors": [],
            "full_explanation": "Explanation not available. Run SHAP precomputation first."
        }
    row = df_shap.iloc[0]
    shap_dict = json.loads(row["shap_values_json"])
    base = float(row["base_value"])
    df_eval = pd.read_sql(
        sa.text("SELECT final_evaluation_score FROM evaluation_results WHERE faculty_id = :faculty_id"),
        engine,
        params={"faculty_id": faculty_id}
    )
    final_score = float(df_eval.iloc[0]["final_evaluation_score"]) if not df_eval.empty else base
    positive, negative = [], []
    for feature, value in shap_dict.items():
        item = {"feature": feature.replace("_", " ").title(), "contribution": round(float(value), 3)}
        if value > 0:
            positive.append(item)
        else:
            negative.append(item)
    positive.sort(key=lambda x: x["contribution"], reverse=True)
    negative.sort(key=lambda x: x["contribution"])
    explanation_text = f"The base prediction is {base:.2f}. "
    if positive:
        explanation_text += "Positive contributors: " + ", ".join([f"{p['feature']} (+{p['contribution']})" for p in positive[:3]]) + ". "
    if negative:
        explanation_text += "Negative contributors: " + ", ".join([f"{n['feature']} ({n['contribution']})" for n in negative[:3]]) + "."
    return {
        "final_score": final_score,
        "base_value": base,
        "top_positive_factors": positive[:3],
        "top_negative_factors": negative[:3],
        "full_explanation": explanation_text
    }


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
        html_path = f"explanations/lime_{faculty_id}.html"
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
    try:
        inspector = sa.inspect(engine)
        if not inspector.has_table("evaluation_results_with_blockchain"):
            return {
                "faculty_id": faculty_id,
                "final_score": 0,
                "blockchain_tx_hash": "0xPending",
                "result_hash": "N/A",
                "timestamp": str(datetime.utcnow()),
                "status": "No blockchain table found yet."
            }
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
        if df.empty:
            return {
                "faculty_id": faculty_id,
                "final_score": 0,
                "blockchain_tx_hash": "0xPending",
                "result_hash": "N/A",
                "timestamp": str(datetime.utcnow()),
                "status": "No blockchain record found."
            }
        row = df.iloc[0]
        timestamp_value = row.get("timestamp", row.get("logged_at", datetime.utcnow()))
        return {
            "faculty_id": int(row["faculty_id"]),
            "final_score": float(row.get("final_evaluation_score", 0)),
            "blockchain_tx_hash": row.get("blockchain_tx_hash", "0xPending"),
            "result_hash": row.get("result_hash", "N/A"),
            "timestamp": str(timestamp_value),
            "status": "Tamper-proof audit record available on private blockchain."
        }
    except Exception as e:
        print(f"Audit endpoint error: {e}")
        return {
            "faculty_id": faculty_id,
            "final_score": 0,
            "blockchain_tx_hash": "0xPending",
            "result_hash": "N/A",
            "timestamp": str(datetime.utcnow()),
            "status": "Blockchain audit currently unavailable."
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
    """Generate a complete faculty audit PDF with evaluation factors, recommendations, and blockchain hashes."""

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
                ROUND(AVG(course_quality_score)::numeric, 2) AS course_quality_score,
                ROUND(AVG(student_feedback_rating)::numeric, 2) AS student_feedback_rating,
                ROUND(AVG(peer_score)::numeric, 2) AS peer_score,
                ROUND(AVG(nlp_sentiment_score)::numeric, 2) AS nlp_sentiment_score,
                ROUND(AVG(avg_grade)::numeric, 2) AS avg_grade
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
    student_feedback = score(row.get("student_feedback_rating"))
    peer_review = score(row.get("peer_score"))
    nlp_sentiment = score(row.get("nlp_sentiment_score"))
    performance = score(row.get("avg_grade"))
    course_quality = score(row.get("course_quality_score"))

    result_hash = "Not available"
    transaction_hash = "Not available"
    audit_timestamp = "Not available"
    audit_status = "No blockchain audit record was found for this faculty member."

    inspector = sa.inspect(engine)
    try:
        if inspector.has_table("evaluation_results_with_blockchain"):
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
                audit_status = "Tamper-proof audit record available on private blockchain."

        if (transaction_hash == "Not available" or result_hash == "Not available") and inspector.has_table("blockchain_audit_logs"):
            log_df = pd.read_sql(
                sa.text("""
                    SELECT result_hash, blockchain_tx_hash, timestamp, status
                    FROM blockchain_audit_logs
                    WHERE faculty_id = :faculty_id
                    ORDER BY timestamp DESC
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
    except Exception as e:
        print(f"PDF audit lookup failed: {e}")

    if contract is not None and result_hash == "Not available":
        try:
            onchain = contract.functions.getEvaluation(faculty_id).call()
            result_hash = fmt(onchain[2], result_hash)
            audit_timestamp = fmt(datetime.fromtimestamp(onchain[1]), audit_timestamp)
            audit_status = "Result hash was retrieved from the private blockchain contract."
        except Exception as e:
            print(f"PDF blockchain contract lookup failed: {e}")

    recommendations = []
    if nlp_sentiment < 3:
        recommendations.append([
            "Improve Clarity in Explanations",
            "Student comments and NLP topic modeling indicate possible confusion in course delivery. Add concrete examples, visual aids, and short summary recaps during lectures."
        ])
    if student_feedback < 3.5:
        recommendations.append([
            "Boost Student Engagement",
            "Student feedback is below the preferred range. Increase interactive activities, office-hour visibility, and opportunities for student participation."
        ])
    if peer_review < 3.5:
        recommendations.append([
            "Schedule Peer Observation",
            "Peer review score is below the target level. A peer teaching observation can identify practical pedagogical improvements."
        ])
    if course_quality < 3.5:
        recommendations.append([
            "Strengthen Course Materials",
            "Course quality score suggests room for improvement. Review syllabus alignment, learning materials, assignments, and assessment rubrics."
        ])
    if performance < 3.5:
        recommendations.append([
            "Support Student Success",
            "Student performance indicators are below the target range. Consider early intervention, formative assessments, and additional learning support."
        ])
    if final_score > 4.2:
        recommendations.append([
            "Exceptional Performance",
            "Outstanding results across evaluation metrics. Continue current best practices and consider mentoring junior faculty or leading departmental initiatives."
        ])
    if not recommendations:
        recommendations.append([
            "Maintain Continuous Improvement",
            "Overall indicators are stable. Continue monitoring student feedback, peer observations, course quality, and performance outcomes each term."
        ])

    shap_summary = "Explanation not available. Run SHAP precomputation first."
    try:
        df_shap = pd.read_sql(
            sa.text("""
                SELECT shap_values_json, base_value
                FROM shap_explanations
                WHERE faculty_id = :faculty_id
            """),
            engine,
            params={"faculty_id": faculty_id}
        )
        if not df_shap.empty:
            shap_dict = json.loads(df_shap.iloc[0]["shap_values_json"])
            ordered = sorted(shap_dict.items(), key=lambda item: abs(float(item[1])), reverse=True)[:5]
            shap_summary = ", ".join([f"{k.replace('_', ' ').title()}: {float(v):+.3f}" for k, v in ordered])
    except Exception as e:
        print(f"PDF SHAP lookup failed: {e}")

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.65 * inch,
        leftMargin=0.65 * inch,
        topMargin=0.55 * inch,
        bottomMargin=0.55 * inch,
        title=f"Project Evolve Audit Report - Faculty {faculty_id}"
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ProjectEvolveTitle",
        parent=styles["Title"],
        fontSize=18,
        leading=22,
        spaceAfter=12,
        textColor=colors.HexColor("#1f2937")
    )
    section_style = ParagraphStyle(
        "ProjectEvolveSection",
        parent=styles["Heading2"],
        fontSize=13,
        leading=16,
        spaceBefore=10,
        spaceAfter=8,
        textColor=colors.HexColor("#1d4ed8")
    )
    normal = ParagraphStyle(
        "ProjectEvolveNormal",
        parent=styles["BodyText"],
        fontSize=9.5,
        leading=13,
        spaceAfter=6,
    )
    small = ParagraphStyle(
        "ProjectEvolveSmall",
        parent=styles["BodyText"],
        fontSize=8,
        leading=10,
    )

    def p(text, style=normal):
        return Paragraph(str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"), style)

    def table(rows, widths=None):
        t = Table(rows, colWidths=widths, hAlign="LEFT")
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5edff")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#111827")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("LEADING", (0, 0), (-1, -1), 10.5),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#cbd5e1")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        return t

    story = []
    story.append(Paragraph("Project Evolve - Complete Faculty Audit Report", title_style))
    story.append(p(f"Generated on: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC", small))
    story.append(Spacer(1, 8))

    story.append(Paragraph("Faculty Overview", section_style))
    story.append(table([
        [p("Field", small), p("Value", small)],
        [p("Faculty ID", small), p(faculty_id, small)],
        [p("Name", small), p(fmt(row.get("faculty_name")), small)],
        [p("Department", small), p(fmt(row.get("department")), small)],
        [p("Final Evaluation Score", small), p(fmt(final_score), small)],
    ], [2.0 * inch, 4.3 * inch]))

    story.append(Paragraph("Evaluation Factors", section_style))
    story.append(table([
        [p("Factor", small), p("Score / Value", small), p("Purpose", small)],
        [p("Student Feedback", small), p(fmt(student_feedback), small), p("Aggregated student survey rating.", small)],
        [p("Peer Review", small), p(fmt(peer_review), small), p("Structured peer evaluation score.", small)],
        [p("NLP Sentiment", small), p(fmt(nlp_sentiment), small), p("Sentiment analysis of qualitative comments.", small)],
        [p("Student Performance", small), p(fmt(performance), small), p("Anonymised grade or success-rate indicator.", small)],
        [p("Course Quality", small), p(fmt(course_quality), small), p("Course material and design quality indicator.", small)],
    ], [2.0 * inch, 1.3 * inch, 3.0 * inch]))

    story.append(Paragraph("Explainable AI Summary", section_style))
    story.append(p(shap_summary, normal))

    story.append(Paragraph("Blockchain Audit Details", section_style))
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
    story.append(p("This report is generated by Project Evolve to support fair, transparent, and auditable faculty development decisions.", small))

    doc.build(story)
    buffer.seek(0)
    return Response(
        content=buffer.getvalue(),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=project_evolve_complete_audit_{faculty_id}.pdf",
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "X-Project-Evolve-PDF-Version": "2"
        }
    )


@app.get("/api/fairness/departments")
async def get_fairness_departments():
    """Return all departments available for the fairness audit selector."""
    try:
        df = pd.read_sql(
            sa.text("""
                SELECT DISTINCT department
                FROM evaluation_results
                WHERE department IS NOT NULL AND TRIM(department) <> ''
                ORDER BY department
            """),
            engine
        )
        departments = [str(value) for value in df["department"].dropna().tolist()]
        return {"departments": departments}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not load departments: {e}")


@app.get("/api/fairness/latest")
async def get_latest_fairness_report():
    files = glob.glob(os.path.join("reports", "fairness_report_*.json"))
    if not files:
        raise HTTPException(404, "No fairness reports found. Run audit first.")
    latest = max(files, key=os.path.getctime)
    with open(latest, "r") as f:
        return json.load(f)


@app.post("/api/fairness/run")
async def run_fairness_audit(department: Optional[str] = Query(None)):
    try:
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        cmd = ["python", "src/fairness/audit.py"]
        if department:
            cmd.extend(["--department", department])

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=project_root
        )
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"Fairness audit failed: {result.stderr}")
        files = glob.glob(os.path.join("reports", "fairness_report_*.json"))
        if not files:
            raise HTTPException(status_code=404, detail="No fairness report generated.")
        latest = max(files, key=os.path.getctime)
        with open(latest, "r") as f:
            return json.load(f)
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
        if inspector.has_table("evaluation_results_with_blockchain"):
            blockchain_count = pd.read_sql("SELECT COUNT(*) FROM evaluation_results_with_blockchain", engine).iloc[0, 0]
    except Exception:
        blockchain_count = 0
    return {
        "average_score": round(float(avg_score or 0), 2),
        "bias_detected": round(float(bias_value or 0), 3),
        "blockchain_logged": int(blockchain_count)
    }


@app.get("/api/audit/all")
async def get_audit_trail_paginated(page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=100)):
    offset = (page - 1) * limit
    try:
        inspector = sa.inspect(engine)
        if not inspector.has_table("evaluation_results_with_blockchain"):
            return {"transactions": [], "pagination": {"page": page, "limit": limit, "total": 0, "total_pages": 0}}
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
                {ts_col} as timestamp
            FROM evaluation_results_with_blockchain
            ORDER BY {ts_col} DESC
            LIMIT :limit OFFSET :offset
        """
        df = pd.read_sql(sa.text(query), engine, params={"limit": limit, "offset": offset})
        df = df.where(pd.notnull(df), None)
        total = pd.read_sql("SELECT COUNT(*) FROM evaluation_results_with_blockchain", engine).iloc[0, 0]
        return {
            "transactions": make_serializable(df.to_dict(orient="records")),
            "pagination": {
                "page": page,
                "limit": limit,
                "total": int(total),
                "total_pages": (int(total) + limit - 1) // limit if total > 0 else 0
            }
        }
    except Exception as e:
        print(f"Audit paginated query failed: {e}")
        return {"transactions": [], "pagination": {"page": page, "limit": limit, "total": 0, "total_pages": 0}}


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
