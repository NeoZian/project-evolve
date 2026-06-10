"""
Fairness & Bias Audit Module for Project Evolve.

This module audits demographic parity, group score gaps, department gaps,
and intentionally injected synthetic bias. Equalized odds is not reported as a
final metric because the prototype does not have real expert ground-truth
labels; that limitation is explicitly stated in the JSON/HTML reports.
"""

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
    """Load evaluation results and protected/group attributes from PostgreSQL."""
    df = pd.read_sql("""
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
    """, engine)
    return df


def detect_injected_bias(df):
    """Detect synthetic peer-review bias against female faculty in CS/Engineering."""
    target_group = (
        (df["gender"] == "Female") &
        df["department"].str.contains("CS|Engineering|Computer Science", case=False, na=False)
    )
    control_group = (
        (df["gender"] == "Male") &
        df["department"].str.contains("CS|Engineering|Computer Science", case=False, na=False)
    )

    if target_group.sum() == 0 or control_group.sum() == 0:
        return {
            "bias_detected": False,
            "reason": "Insufficient data",
            "target_group_mean_peer": None,
            "control_group_mean_peer": None,
            "difference": None,
            "message": "Insufficient data to detect injected CS/Engineering peer-review bias."
        }

    mean_peer_target = float(df.loc[target_group, "peer_score"].mean())
    mean_peer_control = float(df.loc[control_group, "peer_score"].mean())
    diff = mean_peer_control - mean_peer_target
    bias_detected = bool(diff > 0.2)

    return {
        "bias_detected": bias_detected,
        "target_group_mean_peer": round(mean_peer_target, 3),
        "control_group_mean_peer": round(mean_peer_control, 3),
        "difference": round(float(diff), 3),
        "message": (
            f"Female faculty in CS/Engineering have {diff:.2f} lower peer scores than male colleagues."
            if bias_detected else
            "No significant injected peer-review bias detected."
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


def generate_fairness_report(df, metrics, injected_bias_result, output_dir="reports"):
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    plt.figure(figsize=(12, 5))

    plt.subplot(1, 2, 1)
    sns.boxplot(data=df, x="gender", y="final_evaluation_score", hue="gender", palette="Set2", legend=False)
    plt.title("Final Score Distribution by Gender")
    plt.ylabel("Evaluation Score")

    plt.subplot(1, 2, 2)
    cs_eng = df[df["department"].str.contains("CS|Engineering|Computer Science", case=False, na=False)]
    if not cs_eng.empty:
        sns.boxplot(data=cs_eng, x="gender", y="peer_score", hue="gender", palette="Set1", legend=False)
        plt.title("Peer Score in CS/Engineering Departments")
        plt.ylabel("Peer Score")
    else:
        plt.text(0.5, 0.5, "No CS/Engineering faculty data", ha="center", va="center")
        plt.title("Peer Score in CS/Engineering Departments")

    plt.tight_layout()
    plot_path = os.path.join(output_dir, f"fairness_plots_{timestamp}.png")
    plt.savefig(plot_path)
    plt.close()

    bias_alert = False
    alert_messages = []
    if abs(metrics["demographic_parity_difference"]) > THRESHOLD:
        bias_alert = True
        alert_messages.append(
            f"Demographic parity difference ({metrics['demographic_parity_difference']}) exceeds threshold {THRESHOLD}."
        )
    if injected_bias_result.get("bias_detected", False):
        bias_alert = True
        alert_messages.append(injected_bias_result["message"])

    report = {
        "timestamp": timestamp,
        "threshold": THRESHOLD,
        "score_threshold": SCORE_THRESHOLD,
        "bias_alert": bias_alert,
        "alert_message": " ".join(alert_messages),
        "fairness_metrics": metrics,
        "injected_bias_analysis": injected_bias_result,
        "plot_path": plot_path,
        "methodology_note": (
            "This prototype audits demographic parity, score gaps, and synthetic injected bias. "
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
    <p><strong>Methodology note:</strong> {{ methodology_note }}</p>
    {% if bias_alert %}
    <div class="alert"><strong>Bias Alert:</strong> {{ alert_message }}</div>
    {% else %}
    <div class="good"><strong>No critical bias alert.</strong> All configured alerts are within range.</div>
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

    <h2>Injected Bias Detection</h2>
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
    load_dotenv()
    DATABASE_URL = os.getenv(
        "DATABASE_URL",
        "postgresql://evolve_user:strongpassword@localhost/evolve_db"
    )
    engine = create_engine(DATABASE_URL)
    df = load_data(engine)
    metrics = compute_fairness_metrics(df)
    injected_bias = detect_injected_bias(df)
    report, html_path = generate_fairness_report(df, metrics, injected_bias)
    send_alert(report, engine)
    print(f"HTML report location: {html_path}")
