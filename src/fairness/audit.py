"""
Fairness & Bias Audit Module for Project Evolve.

This module audits demographic parity, group score gaps, department gaps,
and selected-department score/peer-review bias visualizations. Equalized odds is not
reported as a final metric because the prototype does not have real expert
ground-truth labels; that limitation is explicitly stated in the JSON/HTML
reports.
"""

import argparse
import os
import json
from datetime import datetime

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from dotenv import load_dotenv
from fairlearn.metrics import demographic_parity_difference, demographic_parity_ratio
from jinja2 import Template
from sqlalchemy import create_engine, text

THRESHOLD = 0.1
SCORE_THRESHOLD = 4.0
DEFAULT_DEPARTMENT_PATTERN = "CS|Engineering|Computer Science"


def _project_root():
    return os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


def _load_evaluation_results_from_sql_dump():
    """Load the bundled evaluation_results demo data used by the original graph."""
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
        "student_feedback_rating", "nlp_sentiment_score", "avg_grade"
    ]
    for column in needed:
        if column not in df.columns:
            df[column] = np.nan
    numeric_columns = [
        "faculty_id", "experience_years", "final_evaluation_score",
        "peer_score", "student_feedback_rating", "nlp_sentiment_score", "avg_grade"
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
            e.avg_grade
        FROM evaluation_results e
    """
    try:
        df = pd.read_sql(query, engine)
        if not df.empty:
            df["department"] = df["department"].fillna("Unknown")
            df["gender"] = df["gender"].fillna("Unknown")
            return df
    except Exception as e:
        print(f"Database fairness data load failed, using bundled dump fallback: {e}")

    fallback = _load_evaluation_results_from_sql_dump()
    if fallback.empty:
        raise RuntimeError("No fairness data available from database or bundled SQL dump.")
    return fallback


def resolve_selected_department(df, selected_department=None):
    """Return a valid department name for department-specific visualizations."""
    departments = sorted(str(d) for d in df["department"].dropna().unique())
    if selected_department:
        for department in departments:
            if department.lower() == selected_department.lower():
                return department
        # Allow partial matches from URL/query parameters.
        for department in departments:
            if selected_department.lower() in department.lower():
                return department
    if departments:
        # Preserve the old demo emphasis when available, otherwise use first department.
        cs_like = df[df["department"].str.contains(DEFAULT_DEPARTMENT_PATTERN, case=False, na=False)]
        if not cs_like.empty:
            return str(cs_like.iloc[0]["department"])
        return departments[0]
    return "Unknown"


def detect_department_peer_bias(df, selected_department):
    """Detect peer-review score gaps by gender inside the selected department."""
    dept_df = df[df["department"].astype(str).str.lower() == str(selected_department).lower()]
    target_group = dept_df[dept_df["gender"] == "Female"]
    control_group = dept_df[dept_df["gender"] == "Male"]

    if target_group.empty or control_group.empty:
        return {
            "bias_detected": False,
            "reason": "Insufficient data",
            "selected_department": selected_department,
            "target_group_mean_peer": None,
            "control_group_mean_peer": None,
            "difference": None,
            "message": f"Insufficient male/female peer-review data to detect department-specific peer-score bias in {selected_department}."
        }

    mean_peer_target = float(target_group["peer_score"].mean())
    mean_peer_control = float(control_group["peer_score"].mean())
    diff = mean_peer_control - mean_peer_target
    bias_detected = bool(diff > 0.2)

    return {
        "bias_detected": bias_detected,
        "selected_department": selected_department,
        "target_group_mean_peer": round(mean_peer_target, 3),
        "control_group_mean_peer": round(mean_peer_control, 3),
        "difference": round(float(diff), 3),
        "message": (
            f"Female faculty in {selected_department} have {diff:.2f} lower peer scores than male colleagues."
            if bias_detected else
            f"No significant peer-review score gap detected in {selected_department}."
        )
    }


def compute_fairness_metrics(df):
    """
    Compute fairness metrics for the favorable outcome final_score >= threshold.

    Equalized odds is intentionally omitted from the final metric set because it
    needs a real ground-truth label and a model prediction label. This prototype
    has simulated expert validation only.
    """
    favorable = (df["final_evaluation_score"] >= SCORE_THRESHOLD).astype(int)
    sensitive = df["gender"]

    dp_diff = demographic_parity_difference(
        favorable,
        favorable,
        sensitive_features=sensitive
    )
    dp_ratio = demographic_parity_ratio(
        favorable,
        favorable,
        sensitive_features=sensitive
    )

    gender_means = df.groupby("gender")["final_evaluation_score"].mean()
    gender_counts = df["gender"].value_counts()
    dept_means = df.groupby("department")["final_evaluation_score"].mean()
    intersectional = (
        df.groupby(["gender", "department"])["final_evaluation_score"]
        .mean()
        .reset_index()
    )

    return {
        "demographic_parity_difference": float(round(dp_diff, 4)),
        "demographic_parity_ratio": float(round(dp_ratio, 4)),
        "equalized_odds_difference": None,
        "equalized_odds_note": "Not computed because real expert ground-truth labels are not available in this prototype.",
        "mean_score_by_gender": {str(k): float(v) for k, v in gender_means.to_dict().items()},
        "count_by_gender": {str(k): int(v) for k, v in gender_counts.to_dict().items()},
        "mean_score_by_department": {str(k): float(v) for k, v in dept_means.to_dict().items()},
        "intersectional_gender_department_mean": [
            {
                "gender": str(row["gender"]),
                "department": str(row["department"]),
                "mean_score": float(row["final_evaluation_score"])
            }
            for _, row in intersectional.iterrows()
        ],
        "threshold_used": SCORE_THRESHOLD
    }


def generate_fairness_report(df, metrics, department_bias_result, selected_department, output_dir="reports"):
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    dept_df = df[df["department"].astype(str).str.lower() == str(selected_department).lower()]

    # Use the selected department for BOTH charts. Earlier versions used the
    # whole dataset in the first chart and only the selected department in the
    # second chart, which made the page look unchanged when a different
    # department was selected.
    plot_df = dept_df.copy()

    plt.figure(figsize=(12, 5))

    plt.subplot(1, 2, 1)
    if not plot_df.empty and plot_df["gender"].nunique() > 0:
        sns.boxplot(
            data=plot_df,
            x="gender",
            y="final_evaluation_score",
            hue="gender",
            palette="Set2",
            legend=False,
        )
        plt.title(f"Final Score Distribution in {selected_department}")
        plt.ylabel("Evaluation Score")
    else:
        plt.text(0.5, 0.5, f"No faculty data for {selected_department}", ha="center", va="center")
        plt.title(f"Final Score Distribution in {selected_department}")
        plt.ylabel("Evaluation Score")

    plt.subplot(1, 2, 2)
    if not plot_df.empty and plot_df["gender"].nunique() > 0:
        sns.boxplot(
            data=plot_df,
            x="gender",
            y="peer_score",
            hue="gender",
            palette="Set1",
            legend=False,
        )
        plt.title(f"Peer Score in {selected_department}")
        plt.ylabel("Peer Score")
    else:
        plt.text(0.5, 0.5, f"No faculty data for {selected_department}", ha="center", va="center")
        plt.title(f"Peer Score in {selected_department}")
        plt.ylabel("Peer Score")

    plt.tight_layout()
    safe_department = "".join(c if c.isalnum() else "_" for c in str(selected_department)).strip("_") or "department"
    plot_path = os.path.join(output_dir, f"fairness_plots_{safe_department}_{timestamp}.png")
    plt.savefig(plot_path)
    plt.close()

    bias_alert = False
    alert_messages = []
    if abs(metrics["demographic_parity_difference"]) > THRESHOLD:
        bias_alert = True
        alert_messages.append(
            f"Demographic parity difference ({metrics['demographic_parity_difference']}) exceeds threshold {THRESHOLD}."
        )
    if department_bias_result.get("bias_detected", False):
        bias_alert = True
        alert_messages.append(department_bias_result["message"])

    department_peer_by_gender = {}
    if not dept_df.empty:
        department_peer_by_gender = {
            str(k): float(v)
            for k, v in dept_df.groupby("gender")["peer_score"].mean().to_dict().items()
        }

    report = {
        "timestamp": timestamp,
        "threshold": THRESHOLD,
        "score_threshold": SCORE_THRESHOLD,
        "selected_department": selected_department,
        "available_departments": sorted(str(d) for d in df["department"].dropna().unique()),
        "bias_alert": bias_alert,
        "alert_message": " ".join(alert_messages) if alert_messages else f"No critical bias alert for the selected department: {selected_department}.",
        "fairness_metrics": metrics,
        "injected_bias_analysis": department_bias_result,
        "department_peer_by_gender": department_peer_by_gender,
        "plot_path": plot_path,
        "methodology_note": (
            "This prototype audits demographic parity, score gaps, and selected-department peer-review score gaps. "
            "Equalized odds is deferred until real expert ground-truth labels are collected."
        )
    }
    report = convert_to_serializable(report)

    json_path = os.path.join(output_dir, f"fairness_report_{timestamp}.json")
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2)

    html_template = """
    <!DOCTYPE html>
    <html>
    <head><title>Fairness Audit Report - Project Evolve</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; }
        .alert { background: #ffcccc; padding: 15px; border-left: 5px solid red; }
        .good { background: #ccffcc; padding: 15px; border-left: 5px solid green; }
        table { border-collapse: collapse; width: 100%; margin: 20px 0; }
        th, td { border: 1px solid #ddd; padding: 8px; text-align: center; }
        th { background-color: #f2f2f2; }
        img { max-width: 100%; margin: 20px 0; }
    </style>
    </head>
    <body>
    <h1>Fairness Audit Report - Project Evolve</h1>
    <p>Generated: {{ timestamp }}</p>
    <p><strong>Selected department:</strong> {{ selected_department }}</p>
    <p><strong>Methodology note:</strong> {{ methodology_note }}</p>
    {% if bias_alert %}
    <div class="alert"><strong>Bias Alert:</strong> {{ alert_message }}</div>
    {% else %}
    <div class="good"><strong>No critical bias alert.</strong> {{ alert_message }}</div>
    {% endif %}

    <h2>Fairness Metrics</h2>
    <table>
        <tr><th>Metric</th><th>Value</th><th>Note</th></tr>
        <tr><td>Demographic Parity Difference</td><td>{{ fairness_metrics.demographic_parity_difference }}</td><td>Alert threshold: {{ threshold }}</td></tr>
        <tr><td>Demographic Parity Ratio</td><td>{{ fairness_metrics.demographic_parity_ratio }}</td><td>Common target: above 0.8</td></tr>
        <tr><td>Equalized Odds Difference</td><td>N/A</td><td>{{ fairness_metrics.equalized_odds_note }}</td></tr>
    </table>

    <h2>Mean Scores by Gender</h2>
    <table>
        <tr><th>Gender</th><th>Mean Final Score</th><th>Count</th></tr>
        {% for gender, score in fairness_metrics.mean_score_by_gender.items() %}
        <tr><td>{{ gender }}</td><td>{{ "%.3f"|format(score) }}</td><td>{{ fairness_metrics.count_by_gender[gender] }}</td></tr>
        {% endfor %}
    </table>

    <h2>Selected Department Peer Score Gap</h2>
    <p>{{ injected_bias_analysis.message }}</p>

    <h2>Visualizations</h2>
    <img src="{{ plot_path }}" alt="Fairness plots">
    </body>
    </html>
    """
    html_output = Template(html_template).render(**report)
    html_path = os.path.join(output_dir, f"fairness_report_{timestamp}.html")
    with open(html_path, "w") as f:
        f.write(html_output)

    print(f"Fairness report saved to {html_path}")
    return report, html_path


def send_alert(report, engine):
    if not report["bias_alert"]:
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

    print("\n" + "=" * 50)
    print("ALERT TO ETHICS BOARD")
    print(report["alert_message"])
    print("=" * 50 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Project Evolve fairness audit")
    parser.add_argument("--department", default=None, help="Department to use for the peer-score visualization and department-specific bias check")
    args = parser.parse_args()

    load_dotenv()
    DATABASE_URL = os.getenv(
        "DATABASE_URL",
        "postgresql://evolve_user:strongpassword@localhost/evolve_db"
    )
    engine = create_engine(DATABASE_URL)
    df = load_data(engine)
    selected_department = resolve_selected_department(df, args.department)
    selected_df = df[df["department"].astype(str).str.lower() == str(selected_department).lower()]
    metrics_source = selected_df if not selected_df.empty else df
    metrics = compute_fairness_metrics(metrics_source)
    department_bias = detect_department_peer_bias(df, selected_department)
    report, html_path = generate_fairness_report(df, metrics, department_bias, selected_department)
    send_alert(report, engine)
    print(f"HTML report location: {html_path}")
