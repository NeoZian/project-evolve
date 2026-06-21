"""
Fairness & Bias Audit Module for Project Evolve.

This module generates department-specific fairness reports. The selected
department controls both the metrics and the visualization so the frontend never
falls back to an old CS/Engineering graph.
"""

import argparse
import os
import json
from datetime import datetime

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from dotenv import load_dotenv
from jinja2 import Template
from sqlalchemy import create_engine, text

try:
    from fairlearn.metrics import demographic_parity_difference, demographic_parity_ratio
except Exception:  # Keep deployed demo working even when fairlearn is unavailable.
    demographic_parity_difference = None
    demographic_parity_ratio = None

THRESHOLD = 0.1
SCORE_THRESHOLD = 4.0


def _project_root():
    return os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


def _safe_float(value, default=0.0):
    try:
        if value is None or (isinstance(value, float) and np.isnan(value)):
            return default
        return float(value)
    except Exception:
        return default


def _manual_demographic_parity(favorable, sensitive):
    data = pd.DataFrame({"favorable": favorable.astype(int), "sensitive": sensitive.astype(str)})
    rates = data.groupby("sensitive")["favorable"].mean().dropna()
    if rates.empty:
        return 0.0, 1.0
    max_rate = float(rates.max())
    min_rate = float(rates.min())
    diff = max_rate - min_rate
    ratio = 1.0 if max_rate == 0 else min_rate / max_rate
    return diff, ratio


def _load_evaluation_results_from_sql_dump():
    """Load bundled evaluation_results demo data if live DB is unavailable."""
    dump_path = os.path.join(_project_root(), "evolve_db_dump.sql")
    if not os.path.exists(dump_path):
        return pd.DataFrame()

    header = None
    rows = []
    reading = False
    with open(dump_path, "r", encoding="utf-8", errors="ignore") as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\n")
            if line.startswith("COPY public.evaluation_results "):
                columns_part = line.split("(", 1)[1].rsplit(")", 1)[0]
                header = [column.strip() for column in columns_part.split(",")]
                reading = True
                continue
            if reading:
                if line == "\\.":
                    break
                values = line.split("\t")
                if header and len(values) == len(header):
                    rows.append(values)

    if not header or not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=header)
    needed = [
        "faculty_id", "faculty_name", "department", "gender",
        "experience_years", "final_evaluation_score", "peer_score",
        "student_feedback_rating", "nlp_sentiment_score", "avg_grade",
        "course_quality_score", "course_material_score"
    ]
    for column in needed:
        if column not in df.columns:
            df[column] = np.nan

    numeric_columns = [
        "faculty_id", "experience_years", "final_evaluation_score",
        "peer_score", "student_feedback_rating", "nlp_sentiment_score",
        "avg_grade", "course_quality_score", "course_material_score"
    ]
    for column in numeric_columns:
        df[column] = pd.to_numeric(df[column].replace("\\N", np.nan), errors="coerce")

    df["department"] = df["department"].replace("\\N", "Unknown").fillna("Unknown")
    df["gender"] = df["gender"].replace("\\N", "Unknown").fillna("Unknown")
    return df[needed]


def convert_to_serializable(obj):
    if isinstance(obj, (np.integer, np.int64)):
        return int(obj)
    if isinstance(obj, (np.floating, np.float64)):
        return float(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, dict):
        return {key: convert_to_serializable(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [convert_to_serializable(item) for item in obj]
    return obj


def load_data(engine):
    """Load fairness data from PostgreSQL, with bundled SQL dump fallback."""
    query = """
        SELECT
            e.faculty_id,
            e.faculty_name,
            e.department,
            e.gender,
            e.experience_years,
            e.final_evaluation_score,
            e.peer_score,
            e.student_feedback_rating,
            e.nlp_sentiment_score,
            e.avg_grade,
            e.course_quality_score,
            e.course_material_score
        FROM evaluation_results e
    """
    try:
        df = pd.read_sql(query, engine)
        if not df.empty:
            df["department"] = df["department"].replace("\\N", "Unknown").fillna("Unknown")
            df["gender"] = df["gender"].replace("\\N", "Unknown").fillna("Unknown")
            return df
    except Exception as e:
        print(f"Database fairness data load failed, using bundled dump fallback: {e}")

    fallback = _load_evaluation_results_from_sql_dump()
    if fallback.empty:
        raise RuntimeError("No fairness data available from database or bundled SQL dump.")
    return fallback


def get_available_departments(df):
    departments = []
    seen = set()
    for value in df.get("department", pd.Series(dtype=str)).dropna().tolist():
        department = str(value).strip()
        if not department or department == "\\N" or department.lower() in {"nan", "none", "null"}:
            continue
        key = department.lower()
        if key not in seen:
            seen.add(key)
            departments.append(department)
    return sorted(departments, key=lambda item: item.lower())


def resolve_selected_department(df, selected_department=None):
    """Resolve query text to one valid department. No hardcoded CS fallback."""
    departments = get_available_departments(df)
    if selected_department:
        wanted = str(selected_department).strip().lower()
        for department in departments:
            if department.lower() == wanted:
                return department
        for department in departments:
            if wanted in department.lower() or department.lower() in wanted:
                return department
    return departments[0] if departments else "Unknown"


def _department_frame(df, selected_department):
    return df[df["department"].astype(str).str.lower() == str(selected_department).lower()].copy()


def detect_department_peer_bias(df, selected_department):
    """Detect peer-review score gaps by gender inside the selected department."""
    dept_df = _department_frame(df, selected_department)
    group_means = dept_df.groupby("gender")["peer_score"].mean().dropna().to_dict()

    female_mean = group_means.get("Female")
    male_mean = group_means.get("Male")
    if female_mean is None or male_mean is None:
        return {
            "bias_detected": False,
            "reason": "Insufficient data",
            "selected_department": selected_department,
            "target_group_mean_peer": None if female_mean is None else round(float(female_mean), 3),
            "control_group_mean_peer": None if male_mean is None else round(float(male_mean), 3),
            "difference": None,
            "message": f"Insufficient male/female peer-review data to detect department-specific peer-score bias in {selected_department}."
        }

    diff = float(male_mean - female_mean)
    bias_detected = bool(abs(diff) > 0.2)
    direction = "male peer scores are higher" if diff > 0 else "female peer scores are higher"

    return {
        "bias_detected": bias_detected,
        "selected_department": selected_department,
        "target_group_mean_peer": round(float(female_mean), 3),
        "control_group_mean_peer": round(float(male_mean), 3),
        "difference": round(diff, 3),
        "message": (
            f"Possible peer-review score gap in {selected_department}: {direction} by {abs(diff):.2f}."
            if bias_detected else
            f"No significant peer-review score gap detected in {selected_department}."
        )
    }


def compute_fairness_metrics(df):
    """Compute demographic parity and score summaries for the supplied dataframe."""
    scoped_df = df.copy()
    if scoped_df.empty:
        return {
            "demographic_parity_difference": 0.0,
            "demographic_parity_ratio": 1.0,
            "equalized_odds_difference": None,
            "equalized_odds_note": "Not computed because real expert ground-truth labels are not available in this prototype.",
            "mean_score_by_gender": {},
            "count_by_gender": {},
            "mean_peer_by_gender": {},
            "mean_student_feedback_by_gender": {},
            "mean_nlp_sentiment_by_gender": {},
            "mean_course_quality_by_gender": {},
            "record_count": 0,
            "threshold_used": SCORE_THRESHOLD,
        }

    scoped_df["final_evaluation_score"] = pd.to_numeric(scoped_df["final_evaluation_score"], errors="coerce")
    scoped_df = scoped_df.dropna(subset=["final_evaluation_score", "gender"])
    favorable = (scoped_df["final_evaluation_score"] >= SCORE_THRESHOLD).astype(int)
    sensitive = scoped_df["gender"].astype(str)

    if demographic_parity_difference and demographic_parity_ratio:
        try:
            dp_diff = demographic_parity_difference(favorable, favorable, sensitive_features=sensitive)
            dp_ratio = demographic_parity_ratio(favorable, favorable, sensitive_features=sensitive)
        except Exception:
            dp_diff, dp_ratio = _manual_demographic_parity(favorable, sensitive)
    else:
        dp_diff, dp_ratio = _manual_demographic_parity(favorable, sensitive)

    def grouped_mean(column):
        if column not in scoped_df.columns:
            return {}
        values = pd.to_numeric(scoped_df[column], errors="coerce")
        temp = scoped_df.assign(_metric=values)
        return {str(k): round(float(v), 4) for k, v in temp.groupby("gender")["_metric"].mean().dropna().to_dict().items()}

    gender_counts = scoped_df["gender"].value_counts().to_dict()

    return {
        "demographic_parity_difference": round(float(dp_diff), 4),
        "demographic_parity_ratio": round(float(dp_ratio), 4),
        "equalized_odds_difference": None,
        "equalized_odds_note": "Not computed because real expert ground-truth labels are not available in this prototype.",
        "mean_score_by_gender": grouped_mean("final_evaluation_score"),
        "count_by_gender": {str(k): int(v) for k, v in gender_counts.items()},
        "mean_peer_by_gender": grouped_mean("peer_score"),
        "mean_student_feedback_by_gender": grouped_mean("student_feedback_rating"),
        "mean_nlp_sentiment_by_gender": grouped_mean("nlp_sentiment_score"),
        "mean_course_quality_by_gender": grouped_mean("course_quality_score"),
        "record_count": int(len(scoped_df)),
        "threshold_used": SCORE_THRESHOLD,
    }


def _make_selected_department_plot(dept_df, selected_department, output_dir, timestamp):
    safe_department = "".join(c if c.isalnum() else "_" for c in str(selected_department)).strip("_") or "department"
    plot_path = os.path.join(output_dir, f"fairness_plots_{safe_department}_{timestamp}.png")

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    fig.suptitle(f"Fairness Audit for {selected_department}", fontsize=15, fontweight="bold")

    if dept_df.empty:
        for ax in axes:
            ax.text(0.5, 0.5, f"No data found for {selected_department}", ha="center", va="center")
            ax.set_axis_off()
    else:
        summary = dept_df.groupby("gender").agg(
            final_score=("final_evaluation_score", "mean"),
            peer_score=("peer_score", "mean"),
            count=("faculty_id", "count"),
        ).reset_index()

        axes[0].bar(summary["gender"], summary["final_score"])
        axes[0].set_title(f"Average Final Score by Gender\n{selected_department}")
        axes[0].set_ylabel("Final Evaluation Score")
        axes[0].set_ylim(0, 5)
        for idx, row in summary.iterrows():
            axes[0].text(idx, row["final_score"] + 0.05, f"{row['final_score']:.2f}\nn={int(row['count'])}", ha="center", fontsize=9)

        axes[1].bar(summary["gender"], summary["peer_score"])
        axes[1].set_title(f"Average Peer Score by Gender\n{selected_department}")
        axes[1].set_ylabel("Peer Score")
        axes[1].set_ylim(0, 5)
        for idx, row in summary.iterrows():
            axes[1].text(idx, row["peer_score"] + 0.05, f"{row['peer_score']:.2f}\nn={int(row['count'])}", ha="center", fontsize=9)

    plt.tight_layout()
    plt.savefig(plot_path, dpi=140, bbox_inches="tight")
    plt.close(fig)
    return plot_path


def generate_fairness_report(df, metrics, department_bias_result, selected_department, output_dir="reports"):
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    dept_df = _department_frame(df, selected_department)
    plot_path = _make_selected_department_plot(dept_df, selected_department, output_dir, timestamp)

    bias_alert = False
    alert_messages = []
    if abs(_safe_float(metrics.get("demographic_parity_difference"))) > THRESHOLD:
        bias_alert = True
        alert_messages.append(
            f"Demographic parity difference ({metrics['demographic_parity_difference']}) exceeds threshold {THRESHOLD} in {selected_department}."
        )
    if department_bias_result.get("bias_detected", False):
        bias_alert = True
        alert_messages.append(department_bias_result["message"])

    department_peer_by_gender = metrics.get("mean_peer_by_gender", {})

    report = {
        "timestamp": timestamp,
        "threshold": THRESHOLD,
        "score_threshold": SCORE_THRESHOLD,
        "selected_department": selected_department,
        "metric_scope": f"Selected department only: {selected_department}",
        "available_departments": get_available_departments(df),
        "bias_alert": bias_alert,
        "alert_message": " ".join(alert_messages) if alert_messages else f"No critical bias alert for the selected department: {selected_department}.",
        "fairness_metrics": metrics,
        "injected_bias_analysis": department_bias_result,
        "department_peer_by_gender": department_peer_by_gender,
        "plot_path": plot_path,
        "methodology_note": (
            "The selected department controls this report. Metrics, gender counts, peer-score gaps, "
            "and the visualization are all calculated only from rows belonging to the selected department."
        ),
    }
    report = convert_to_serializable(report)

    json_path = os.path.join(output_dir, f"fairness_report_{timestamp}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    html_template = """
    <!DOCTYPE html><html><head><title>Fairness Audit Report - Project Evolve</title></head><body>
    <h1>Fairness Audit Report - Project Evolve</h1>
    <p><strong>Generated:</strong> {{ timestamp }}</p>
    <p><strong>Selected department:</strong> {{ selected_department }}</p>
    <p><strong>Metric scope:</strong> {{ metric_scope }}</p>
    <p>{{ methodology_note }}</p>
    <p><strong>Status:</strong> {{ alert_message }}</p>
    <h2>Metrics</h2>
    <ul>
      <li>Demographic parity difference: {{ fairness_metrics.demographic_parity_difference }}</li>
      <li>Demographic parity ratio: {{ fairness_metrics.demographic_parity_ratio }}</li>
      <li>Record count: {{ fairness_metrics.record_count }}</li>
    </ul>
    <h2>Selected Department Peer Score Gap</h2>
    <p>{{ injected_bias_analysis.message }}</p>
    <h2>Visualization</h2>
    <img src="{{ plot_path }}" alt="Fairness plots" style="max-width:100%;">
    </body></html>
    """
    html_path = os.path.join(output_dir, f"fairness_report_{timestamp}.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(Template(html_template).render(**report))

    print(f"Fairness report saved to {html_path}")
    return report, html_path


def send_alert(report, engine):
    if not report.get("bias_alert"):
        return
    try:
        with engine.begin() as conn:
            board_id = conn.execute(
                text("SELECT id FROM ethics_board_members WHERE is_active = true LIMIT 1")
            ).scalar()
            if board_id:
                conn.execute(
                    text("""
                        INSERT INTO ethics_reviews (faculty_id, reviewer_id, review_type, decision, comments)
                        VALUES (NULL, :board_id, 'bias_alert', 'pending', :alert_msg)
                    """),
                    {"board_id": board_id, "alert_msg": report["alert_message"]}
                )
    except Exception as e:
        print(f"Ethics alert logging skipped: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Project Evolve fairness audit")
    parser.add_argument("--department", default=None, help="Department to audit")
    args = parser.parse_args()

    load_dotenv()
    DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://evolve_user:strongpassword@localhost/evolve_db")
    engine = create_engine(DATABASE_URL)
    df = load_data(engine)
    selected_department = resolve_selected_department(df, args.department)
    selected_df = _department_frame(df, selected_department)
    metrics = compute_fairness_metrics(selected_df)
    department_bias = detect_department_peer_bias(df, selected_department)
    report, html_path = generate_fairness_report(df, metrics, department_bias, selected_department)
    send_alert(report, engine)
    print(f"HTML report location: {html_path}")
