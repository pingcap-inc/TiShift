"""MongoDB → TiDB scoring engine.

Reference: references/scoring.md — every deduction traceable.
Weights: 20 / 20 / 20 / 25 / 15 (Application Coupling higher than other variants
because aggregation pipelines dominate; Operational Readiness higher because
of topology and CDC-provider decisions).
"""

from __future__ import annotations

from dataclasses import dataclass

from tishift_mongodb.rules.compatibility import Checklist


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
    score, max_score, ded = 20, 20, []
    if cl.polymorphic_field_count > 5:
        score -= 4
        ded.append(("polymorphic_field_count > 5", 4))
    if cl.polymorphic_field_count > 20:
        score -= 4
        ded.append(("polymorphic_field_count > 20", 4))
    if cl.sparse_field_ratio > 0.30:
        score -= 3
        ded.append(("sparse_field_ratio > 0.30", 3))
    if cl.subdocument_max_depth > 5:
        score -= 3
        ded.append(("subdocument_max_depth > 5", 3))
    if cl.has_polymorphic_id:
        score -= 6
        ded.append(("polymorphic _id field", 6))
    return CategoryScore("Schema Inferability", max(score, 0), max_score, ded)


def _score_data_complexity(cl: Checklist) -> CategoryScore:
    score, max_score, ded = 20, 20, []
    if cl.total_data_gb_estimate > 1000:
        score -= 4
        ded.append(("total_data_gb > 1000", 4))
    if cl.total_data_gb_estimate > 5000:
        score -= 4
        ded.append(("total_data_gb > 5000 (additional)", 4))
    if cl.has_gridfs:
        score -= 4
        ded.append(("GridFS usage", 4))
    if cl.binary_field_total_gb > 100:
        score -= 2
        ded.append(("binary fields total > 100 GB", 2))
    if cl.largest_collection_doc_count > 1_000_000_000:
        score -= 3
        ded.append(("largest collection > 1B docs", 3))
    return CategoryScore("Data Complexity", max(score, 0), max_score, ded)


def _score_query_index_coverage(cl: Checklist) -> CategoryScore:
    score, max_score, ded = 20, 20, []
    if cl.geospatial_index_count > 0:
        score -= 4
        ded.append(("geospatial indexes", 4))
    if cl.text_index_count > 0 and cl.target_tier in ("starter", "essential"):
        score -= 3
        ded.append(("text indexes on tier without FTS", 3))
    elif cl.text_index_count > 0 and cl.target_tier in ("dedicated", "byoc"):
        score -= 1
        ded.append(("text indexes (FTS parity needs check)", 1))
    if cl.wildcard_index_count > 0:
        score -= 3
        ded.append(("wildcard indexes", 3))
    if cl.polymorphic_field_in_indexed_path:
        score -= 6
        ded.append(("polymorphic field in indexed path", 6))
    if cl.composite_index_count > 200:
        score -= 3
        ded.append(("composite_index_count > 200", 3))
    return CategoryScore("Query/Index Coverage", max(score, 0), max_score, ded)


def _score_application_coupling(cl: Checklist) -> CategoryScore:
    score, max_score, ded = 25, 25, []
    if cl.aggregation_complexity_total > 200:
        score -= 10
        ded.append(("aggregation_complexity_total > 200", 10))
    elif cl.aggregation_complexity_total > 50:
        score -= 6
        ded.append(("aggregation_complexity_total > 50", 6))
    elif cl.aggregation_complexity_total > 10:
        score -= 3
        ded.append(("aggregation_complexity_total > 10", 3))
    if cl.csfle_field_count > 0:
        score -= 5
        ded.append(("CSFLE-encrypted fields present", 5))
    if cl.has_gridfs:
        score -= 3
        ded.append(("GridFS usage requires app change", 3))
    if cl.has_capped_collections:
        score -= 2
        ded.append(("capped collections", 2))
    if cl.transaction_block_count > 50:
        score -= 2
        ded.append(("transaction_block_count > 50", 2))
    return CategoryScore("Application Coupling", max(score, 0), max_score, ded)


def _score_operational_readiness(cl: Checklist) -> CategoryScore:
    score, max_score, ded = 15, 15, []
    if cl.topology == "standalone":
        score -= 6
        ded.append(("standalone topology (no CDC)", 6))
    if cl.topology == "sharded" and cl.load_strategy not in (
        "aws-dms", "datastream", "mongodump-lightning",
    ):
        score -= 3
        ded.append(("sharded cluster with non-parallel load strategy", 3))
    if cl.cutover_tolerance in ("minutes", "hours") and cl.topology == "standalone":
        score -= 4
        ded.append(("low cutover tolerance + standalone", 4))
    if cl.mongo_version < "4.2":
        score -= 2
        ded.append(("mongo_version < 4.2", 2))
    if cl.mongo_version < "4.0":
        score -= 2
        ded.append(("mongo_version < 4.0 (additional)", 2))
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
