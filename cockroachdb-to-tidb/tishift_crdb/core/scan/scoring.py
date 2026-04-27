"""Readiness scoring engine for CockroachDB → TiDB migration.

Implements the 5-category weighted model from references/scoring.md.
Category weights: Schema 25, Query 25, Procedural 15, Data 20, Ops 15.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CategoryScore:
    name: str
    score: int
    max_score: int
    deductions: list[str]


@dataclass(frozen=True)
class ScoringResult:
    schema: CategoryScore
    query: CategoryScore
    procedural_code: CategoryScore
    data: CategoryScore
    ops: CategoryScore

    @property
    def total(self) -> int:
        return (
            self.schema.score
            + self.query.score
            + self.procedural_code.score
            + self.data.score
            + self.ops.score
        )

    @property
    def rating(self) -> str:
        t = self.total
        if t >= 90:
            return "excellent"
        if t >= 75:
            return "good"
        if t >= 50:
            return "moderate"
        if t >= 25:
            return "challenging"
        return "difficult"

    def density_note(self, checklist: dict[str, Any]) -> str | None:
        """Return a qualitative note when blocker density is high."""
        table_count = checklist.get("table_count", 0)
        if table_count == 0:
            return None
        blocker_objects = (
            checklist.get("stored_procedure_count", 0)
            + checklist.get("trigger_count", 0)
            + checklist.get("array_column_count", 0)
        )
        total_objects = (
            table_count
            + checklist.get("view_count", 0)
            + checklist.get("sequence_count", 0)
            + blocker_objects
        )
        if total_objects == 0:
            return None
        ratio = blocker_objects / total_objects
        if ratio > 0.3:
            return (
                f"Note: {blocker_objects} blockers across {total_objects} total objects "
                f"({ratio:.0%} density). Migration effort per object is significant "
                f"despite the overall score."
            )
        return None


def _score_schema(checklist: dict[str, Any]) -> CategoryScore:
    score = 25
    deductions: list[str] = []

    arr_count = checklist.get("array_column_count", 0)
    arr_ded = min(arr_count, 5)
    if arr_ded > 0:
        score -= arr_ded
        deductions.append(f"Array columns ({arr_count}): -{arr_ded}")

    if checklist.get("has_custom_types"):
        score -= 4
        deductions.append("Custom composite types: -4")

    if checklist.get("has_spatial_geography"):
        score -= 3
        deductions.append("GEOGRAPHY type: -3")

    if checklist.get("has_interleaved_tables"):
        score -= 3
        deductions.append("Interleaved tables: -3")

    hs_count = checklist.get("hash_sharded_index_count", 0)
    hs_ded = min(hs_count, 3)
    if hs_ded > 0:
        score -= hs_ded
        deductions.append(f"Hash-sharded indexes ({hs_count}): -{hs_ded}")

    inv_count = checklist.get("inverted_index_count", 0)
    inv_ded = min(inv_count, 3)
    if inv_ded > 0:
        score -= inv_ded
        deductions.append(f"Inverted indexes ({inv_count}): -{inv_ded}")

    if checklist.get("has_multi_region"):
        score -= 2
        deductions.append("Multi-region: -2")

    if checklist.get("has_row_level_ttl"):
        score -= 1
        deductions.append("Row-level TTL: -1")

    return CategoryScore("Schema Compatibility", max(score, 0), 25, deductions)


def _score_query(checklist: dict[str, Any]) -> CategoryScore:
    score = 25
    deductions: list[str] = []

    has_any = any(
        checklist.get(k)
        for k in [
            "has_jsonb_operators", "has_writable_ctes", "has_returning_clause",
            "has_full_text_search", "has_array_usage", "has_as_of_system_time",
        ]
    )
    if not has_any and not checklist.get("_query_analyzed", False):
        return CategoryScore("Query Compatibility", 20, 25, ["No query analysis: assume 20/25"])

    jsonb_ops = checklist.get("jsonb_operator_count", 1 if checklist.get("has_jsonb_operators") else 0)
    jb_ded = min(jsonb_ops * 2, 6)
    if jb_ded > 0:
        score -= jb_ded
        deductions.append(f"JSONB operators ({jsonb_ops}): -{jb_ded}")

    if checklist.get("has_writable_ctes"):
        score -= 4
        deductions.append("Writable CTEs: -4")

    if checklist.get("has_returning_clause"):
        score -= 2
        deductions.append("RETURNING clause: -2")

    if checklist.get("has_full_text_search"):
        score -= 3
        deductions.append("Full-text search: -3")

    arr_usage = checklist.get("array_usage_count", 1 if checklist.get("has_array_usage") else 0)
    arr_ded = min(arr_usage, 4)
    if arr_ded > 0:
        score -= arr_ded
        deductions.append(f"Array operations ({arr_usage}): -{arr_ded}")

    if checklist.get("has_as_of_system_time"):
        score -= 1
        deductions.append("AS OF SYSTEM TIME: -1")

    return CategoryScore("Query Compatibility", max(score, 0), 25, deductions)


def _score_procedural(checklist: dict[str, Any]) -> CategoryScore:
    score = 15
    deductions: list[str] = []

    proc_count = checklist.get("stored_procedure_count", 0)
    trigger_count = checklist.get("trigger_count", 0)

    if proc_count == 0 and trigger_count == 0:
        return CategoryScore("Procedural Code", 15, 15, [])

    # Heuristic when no line-level detail
    proc_ded = min(proc_count * 2, 10)
    if proc_ded > 0:
        score -= proc_ded
        deductions.append(f"Procedures ({proc_count}) heuristic: -{proc_ded}")

    trig_ded = min(trigger_count * 2, 6)
    if trig_ded > 0:
        score -= trig_ded
        deductions.append(f"Triggers ({trigger_count}): -{trig_ded}")

    return CategoryScore("Procedural Code", max(score, 0), 15, deductions)


def _score_data(checklist: dict[str, Any]) -> CategoryScore:
    score = 20
    deductions: list[str] = []

    total_mb = checklist.get("total_data_mb", 0)
    if total_mb > 5_000_000:
        score -= 10
        deductions.append(f"Data > 5 TB ({total_mb} MB): -10")
    elif total_mb > 1_000_000:
        score -= 5
        deductions.append(f"Data > 1 TB ({total_mb} MB): -5")
    elif total_mb > 500_000:
        score -= 2
        deductions.append(f"Data > 500 GB ({total_mb} MB): -2")

    largest = checklist.get("largest_table_mb", 0)
    if largest > 100_000:
        score -= 2
        deductions.append(f"Largest table > 100 GB ({largest} MB): -2")

    jsonb_cols = checklist.get("jsonb_column_count", 0)
    jb_ded = min(jsonb_cols, 4)
    if jb_ded > 0:
        score -= jb_ded
        deductions.append(f"JSONB columns ({jsonb_cols}): -{jb_ded}")

    if checklist.get("table_count", 0) > 1000:
        score -= 2
        deductions.append("Table count > 1000: -2")

    return CategoryScore("Data Complexity", max(score, 0), 20, deductions)


def _score_ops(checklist: dict[str, Any], target_tier: str = "starter") -> CategoryScore:
    score = 15
    deductions: list[str] = []

    version_str = str(checklist.get("crdb_version", "24"))
    try:
        major = int(version_str.split(".")[0])
    except (ValueError, IndexError):
        major = 24

    if major < 23:
        score -= 2
        deductions.append(f"CRDB version {major} (< 23, no stored procs): -2")
    if major < 22:
        score -= 2
        deductions.append(f"CRDB version {major} (< 22): -2")

    if checklist.get("has_multi_region") and not checklist.get("has_placement_plan"):
        score -= 2
        deductions.append("Multi-region without placement plan: -2")

    if checklist.get("changefeeds_not_available"):
        score -= 3
        deductions.append("Changefeeds not available: -3")

    if target_tier == "starter":
        total_mb = checklist.get("total_data_mb", 0)
        if total_mb > 25_000:
            score -= 4
            deductions.append(f"Starter: data > 25 GiB ({total_mb} MB): -4")
        score -= 2
        deductions.append("Starter: no CDC support: -2")

    return CategoryScore("Operational Readiness", max(score, 0), 15, deductions)


def score_migration(
    checklist: dict[str, Any],
    target_tier: str = "starter",
) -> ScoringResult:
    """Calculate the full migration readiness score."""
    return ScoringResult(
        schema=_score_schema(checklist),
        query=_score_query(checklist),
        procedural_code=_score_procedural(checklist),
        data=_score_data(checklist),
        ops=_score_ops(checklist, target_tier),
    )
