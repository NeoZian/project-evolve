"""Canonical seven-factor scoring model for Project Evolve.

This module is deliberately dependency-light so that the backend, XAI scripts,
PDF export, and audit regeneration job can all call exactly the same scoring
logic. Keeping the formula in one place ensures that the backend, frontend,
XAI, PDF, and audit layers use the same model definition.
"""
from __future__ import annotations

from collections import OrderedDict
from typing import Any, Dict, Mapping, Optional

import math

FORMULA_VERSION = "evolve_seven_factor_v2.0_2026_06"

# These weights sum to 1.00. The order is also the display order used in the UI.
FACTOR_WEIGHTS = OrderedDict([
    ("student_feedback_rating", 0.25),
    ("peer_score", 0.20),
    ("performance_score", 0.15),
    ("nlp_sentiment_score", 0.10),
    ("course_material_score", 0.05),
    ("service_score", 0.15),
    ("pd_score", 0.10),
])

FACTOR_LABELS = {
    "student_feedback_rating": "Student Feedback",
    "peer_score": "Peer Review",
    "performance_score": "Performance",
    "nlp_sentiment_score": "NLP Sentiment",
    "course_material_score": "Course Material",
    "service_score": "Service Contribution",
    "pd_score": "Professional Development",
}

FACTOR_DESCRIPTIONS = {
    "student_feedback_rating": "Average student rating associated with the faculty member. In the prototype this is mapped from RateMyProfessor student_star values.",
    "peer_score": "Synthetic/proxy peer-review score used to demonstrate how rubric-based peer observation would enter the framework.",
    "performance_score": "Normalized student outcome indicator derived from avg_grade as clip((avg_grade / 4.0) * 5.0, 1, 5). It is indirect evidence, not a direct professor attribute.",
    "nlp_sentiment_score": "Text-tone score from student comments. The current DistilBERT implementation maps POSITIVE to 4.8, NEGATIVE to 1.8, and missing/short comments to 3.0.",
    "course_material_score": "Course-material readability/proxy score derived from generated syllabus text. Real deployment should replace this with rubric-based analysis of actual course artifacts.",
    "service_score": "Synthetic/proxy academic service contribution score computed from total service hours as clip(total_service_hours / 40.0, 1, 5).",
    "pd_score": "Synthetic/proxy professional-development score computed from total PD hours as clip(total_pd_hours / 20.0, 1, 5).",
}

FACTOR_SOURCES = {
    "student_feedback_rating": "Public student-feedback dataset, aggregated by faculty_id.",
    "peer_score": "Synthetic peer_reviews table/proxy evidence.",
    "performance_score": "performance_metrics avg_grade normalized to the 1-5 scoring scale.",
    "nlp_sentiment_score": "DistilBERT sentiment label stored in evaluation_results.",
    "course_material_score": "Readability-derived course-material proxy stored in evaluation_results.",
    "service_score": "Synthetic service_contributions hours aggregated and normalized.",
    "pd_score": "Synthetic professional_development hours aggregated and normalized.",
}


def _to_float(value: Any, default: float = 0.0) -> float:
    """Convert database/JSON values to float safely."""
    if value is None:
        return default
    try:
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except Exception:
        return default


def clamp_score(value: Any, low: float = 1.0, high: float = 5.0) -> float:
    """Clamp a numeric score into the 1-5 Project Evolve scale."""
    f = _to_float(value, default=low)
    return max(low, min(high, f))


def normalize_performance_score(avg_grade: Any) -> float:
    """Convert avg_grade, usually on a 0-4 style scale, to the 1-5 factor scale."""
    return clamp_score((_to_float(avg_grade) / 4.0) * 5.0)


def calculate_seven_factor_score(values: Mapping[str, Any], *, rounded: bool = True) -> float:
    """Calculate the canonical seven-factor final score.

    Accepted keys are the factor keys in FACTOR_WEIGHTS. For convenience,
    if performance_score is absent but avg_grade exists, performance_score is
    computed from avg_grade.
    """
    factor_values = dict(values)
    if "performance_score" not in factor_values and "avg_grade" in factor_values:
        factor_values["performance_score"] = normalize_performance_score(factor_values.get("avg_grade"))

    score = 0.0
    for key, weight in FACTOR_WEIGHTS.items():
        score += weight * clamp_score(factor_values.get(key, 0.0))

    score = clamp_score(score)
    return round(score, 2) if rounded else score


def build_factor_breakdown(values: Mapping[str, Any]) -> list[Dict[str, Any]]:
    """Return ordered, UI-ready factor metadata for all seven contributors."""
    factor_values = dict(values)
    if "performance_score" not in factor_values and "avg_grade" in factor_values:
        factor_values["performance_score"] = normalize_performance_score(factor_values.get("avg_grade"))

    rows = []
    for key, weight in FACTOR_WEIGHTS.items():
        value = clamp_score(factor_values.get(key, 0.0))
        rows.append({
            "key": key,
            "label": FACTOR_LABELS[key],
            "value": round(value, 2),
            "weight": weight,
            "weight_percent": round(weight * 100, 1),
            "weighted_contribution": round(value * weight, 4),
            "description": FACTOR_DESCRIPTIONS[key],
            "source": FACTOR_SOURCES[key],
        })
    return rows


def canonical_audit_payload(
    row: Mapping[str, Any],
    *,
    evaluation_id: Optional[int] = None,
    timestamp: Optional[str] = None,
    scope: str = "row_level_evaluation",
) -> Dict[str, Any]:
    """Build the canonical audit payload that should be hashed.

    The payload includes the formula version and all seven factors. Including
    the formula version protects audit interpretability if the model is revised
    later.
    """
    factors = {item["key"]: item["value"] for item in build_factor_breakdown(row)}
    payload: Dict[str, Any] = {
        "formula_version": FORMULA_VERSION,
        "hash_scope": scope,
        "faculty_id": int(_to_float(row.get("faculty_id"), 0)),
        "faculty_name": row.get("faculty_name"),
        "department": row.get("department"),
        "final_evaluation_score": round(_to_float(row.get("final_evaluation_score")), 2),
        "factors": factors,
        "weights": dict(FACTOR_WEIGHTS),
    }
    if evaluation_id is not None:
        payload["evaluation_id"] = int(evaluation_id)
    if timestamp is not None:
        payload["timestamp"] = timestamp
    return payload
