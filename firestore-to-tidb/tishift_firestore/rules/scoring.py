"""Firestore → TiDB scoring engine.

Reference: references/scoring.md — every deduction must be traceable to a
condition documented there.
"""

from __future__ import annotations

from dataclasses import dataclass

from tishift_firestore.rules.compatibility import Checklist


@dataclass(frozen=True)
class CategoryScore:
    name: str
    score: int
    max: int
    deductions: list[tuple[str, int]]


@dataclass(frozen=True)
class ScoreReport:
    categories: list[CategoryScore]
    overall: int
    rating: str

    def to_dict(self) -> dict:
        return {
            "overall": self.overall,
            "rating": self.rating,
            "categories": [
                {
                    "name": c.name,
                    "score": c.score,
                    "max": c.max,
                    "deductions": [{"reason": r, "points": p} for r, p in c.deductions],
                }
                for c in self.categories
            ],
        }


def _score_schema_inferability(cl: Checklist) -> CategoryScore:
    score, max_score, ded = 25, 25, []

    if cl.mode == "mongo-api":
        # Special case — caller should have aborted in Phase 1.
        ded.append(("mongo-api mode (should redirect)", 25))
        return CategoryScore("Schema Inferability", 0, max_score, ded)

    if cl.polymorphic_field_count > 5:
        score -= 5
        ded.append(("polymorphic_field_count > 5", 5))
    if cl.polymorphic_field_count > 20:
        score -= 5
        ded.append(("polymorphic_field_count > 20", 5))
    if cl.sparse_field_ratio > 0.30:
        score -= 3
        ded.append(("sparse_field_ratio > 0.30", 3))
    if cl.subcollection_max_depth > 5:
        score -= 3
        ded.append(("subcollection_max_depth > 5", 3))
    if cl.mode == "datastore":
        score -= 5
        ded.append(("mode = datastore", 5))

    return CategoryScore("Schema Inferability", max(score, 0), max_score, ded)


def _score_data_complexity(cl: Checklist) -> CategoryScore:
    score, max_score, ded = 20, 20, []

    if cl.total_data_gb_estimate > 1000:
        score -= 4
        ded.append(("total_data_gb > 1000", 4))
    if cl.total_data_gb_estimate > 5000:
        score -= 4
        ded.append(("total_data_gb > 5000 (additional)", 4))
    if cl.bytes_field_max_size_mb > 5 and cl.bytes_field_count > 100:
        score -= 3
        ded.append(("large bytes fields × many", 3))
    if cl.subcollection_count > 50:
        score -= 3
        ded.append(("subcollection_count > 50", 3))
    if cl.largest_collection_doc_count > 1_000_000_000:
        score -= 3
        ded.append(("largest_collection > 1B docs", 3))

    return CategoryScore("Data Complexity", max(score, 0), max_score, ded)


def _score_query_index_coverage(cl: Checklist) -> CategoryScore:
    score, max_score, ded = 25, 25, []

    if cl.composite_index_count > 100:
        score -= 4
        ded.append(("composite_index_count > 100", 4))
    if cl.polymorphic_field_in_indexed_path:
        score -= 8
        ded.append(("polymorphic field in indexed path", 8))
    if cl.security_rules_complexity == "complex":
        score -= 5
        ded.append(("rules gate queries (complex)", 5))

    return CategoryScore("Query/Index Coverage", max(score, 0), max_score, ded)


def _score_application_coupling(cl: Checklist) -> CategoryScore:
    score, max_score, ded = 20, 20, []

    if cl.has_realtime_listeners:
        score -= 10
        ded.append(("realtime listeners", 10))
    if cl.security_rules_complexity == "complex":
        score -= 5
        ded.append(("security rules: complex", 5))
    elif cl.security_rules_complexity == "moderate":
        score -= 3
        ded.append(("security rules: moderate", 3))
    if cl.server_timestamp_sentinel_detected:
        score -= 1
        ded.append(("server-timestamp sentinel used", 1))
    if cl.array_union_remove_sentinel_detected:
        score -= 1
        ded.append(("arrayUnion/arrayRemove sentinel used", 1))
    if cl.transaction_block_count > 50:
        score -= 2
        ded.append(("transaction_block_count > 50", 2))

    return CategoryScore("Application Coupling", max(score, 0), max_score, ded)


def _score_operational_readiness(cl: Checklist) -> CategoryScore:
    score, max_score, ded = 10, 10, []

    if cl.target_tier == "byoc":
        if cl.byoc_in_different_gcp_project:
            score -= 2
            ded.append(("BYOC in different GCP project", 2))
    if cl.target_not_gcp:
        score -= 5
        ded.append(("target not on GCP", 5))
    if not cl.firestore_bigquery_export_present and cl.cutover_tolerance == "minutes":
        score -= 2
        ded.append(("CDC required, BQ extension absent", 2))
    if cl.workload_identity_unavailable:
        score -= 1
        ded.append(("Workload Identity unavailable", 1))

    return CategoryScore("Operational Readiness", max(score, 0), max_score, ded)


_RATING_THRESHOLDS = [
    (85, "EXCELLENT"),
    (70, "GOOD"),
    (55, "MODERATE"),
    (40, "DIFFICULT"),
    (0, "NOT RECOMMENDED"),
]


def _rating_for(score: int) -> str:
    for threshold, label in _RATING_THRESHOLDS:
        if score >= threshold:
            return label
    return "NOT RECOMMENDED"


def score(checklist: Checklist) -> ScoreReport:
    """Compute the 5-category readiness score from a checklist."""
    categories = [
        _score_schema_inferability(checklist),
        _score_data_complexity(checklist),
        _score_query_index_coverage(checklist),
        _score_application_coupling(checklist),
        _score_operational_readiness(checklist),
    ]
    overall = sum(c.score for c in categories)
    return ScoreReport(categories=categories, overall=overall, rating=_rating_for(overall))
