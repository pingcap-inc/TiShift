"""Readiness scoring engine for Oracle → TiDB migration.

Implements the 5-category weighted model from references/scoring.md.
Category weights: Schema 20, Procedural Code 30, Query 20, Data 20, Ops 10.
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
    procedural_code: CategoryScore
    query: CategoryScore
    data: CategoryScore
    ops: CategoryScore

    @property
    def total(self) -> int:
        return (
            self.schema.score
            + self.procedural_code.score
            + self.query.score
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


def _score_schema(checklist: dict[str, Any]) -> CategoryScore:
    score = 20
    deductions: list[str] = []

    if checklist.get("has_xmltype_columns"):
        score -= 4
        deductions.append("XMLType columns: -4")
    if checklist.get("has_sdo_geometry"):
        score -= 4
        deductions.append("SDO_GEOMETRY columns: -4")
    if checklist.get("has_object_types"):
        score -= 3
        deductions.append("Oracle object types: -3")
    if checklist.get("has_varrays") or checklist.get("has_nested_tables"):
        score -= 3
        deductions.append("VARRAY/nested tables: -3")
    if checklist.get("has_bfile_columns"):
        score -= 2
        deductions.append("BFILE columns: -2")
    if checklist.get("has_long_columns"):
        score -= 1
        deductions.append("LONG/LONG RAW columns: -1")

    synonym_count = checklist.get("synonym_count", 0)
    syn_ded = min(synonym_count, 2)
    if syn_ded > 0:
        score -= syn_ded
        deductions.append(f"Synonyms ({synonym_count}): -{syn_ded}")

    non_default = checklist.get("non_default_schema_count", 0)
    schema_ded = min(non_default, 3)
    if schema_ded > 0:
        score -= schema_ded
        deductions.append(f"Non-default schemas ({non_default}): -{schema_ded}")

    return CategoryScore("Schema Compatibility", max(score, 0), 20, deductions)


ProcedureInfo = dict[str, Any]
"""Expected keys: lines, has_autonomous_tx, has_pipe_row, has_dynamic_sql,
has_dbms_sql, has_bulk_collect, has_forall, has_cursor."""


def _classify_procedure(proc: ProcedureInfo) -> tuple[int, str]:
    """Return (deduction_points, complexity_label) for one procedure/function."""
    lines = proc.get("lines", 0)

    if proc.get("has_autonomous_tx"):
        return 5, "requires_redesign"
    if proc.get("has_pipe_row"):
        return 4, "requires_redesign"
    if proc.get("has_dynamic_sql") or proc.get("has_dbms_sql"):
        if lines > 100:
            return 5, "requires_redesign"
        return 4, "complex"
    if proc.get("has_bulk_collect") or proc.get("has_forall"):
        return 3, "moderate"
    if proc.get("has_cursor") or lines >= 100:
        return 3, "moderate"
    if lines < 10 and not proc.get("has_cursor"):
        return 1, "trivial"
    if lines < 30:
        return 2, "simple"
    return 2, "simple"


def _score_procedural_code(
    checklist: dict[str, Any],
    procedures: list[ProcedureInfo] | None = None,
) -> CategoryScore:
    score = 30
    deductions: list[str] = []

    total_procs = (
        checklist.get("stored_procedure_count", 0)
        + checklist.get("function_count", 0)
    )
    pkg_count = checklist.get("package_count", 0)
    trigger_count = checklist.get("trigger_count", 0)

    if total_procs == 0 and pkg_count == 0 and trigger_count == 0:
        return CategoryScore("Procedural Code", 30, 30, [])

    # Per-procedure deductions (if detailed info available)
    if procedures:
        for proc in procedures:
            pts, label = _classify_procedure(proc)
            score -= pts
            name = proc.get("name", "unknown")
            deductions.append(f"{name} ({label}): -{pts}")
    else:
        # Heuristic: deduct 2 per procedure when no detail available
        proc_ded = min(total_procs * 2, 20)
        if proc_ded > 0:
            score -= proc_ded
            deductions.append(f"Procedures/functions ({total_procs}) heuristic: -{proc_ded}")

    # Package overhead
    pkg_ded = min(pkg_count * 3, 9)
    if pkg_ded > 0:
        score -= pkg_ded
        deductions.append(f"Packages ({pkg_count}): -{pkg_ded}")

    # Trigger deductions
    trig_ded = min(trigger_count * 2, 10)
    if trig_ded > 0:
        score -= trig_ded
        deductions.append(f"Triggers ({trigger_count}): -{trig_ded}")

    return CategoryScore("Procedural Code", max(score, 0), 30, deductions)


def _score_query(checklist: dict[str, Any]) -> CategoryScore:
    score = 20
    deductions: list[str] = []

    # If no source analysis, assume 16/20
    has_any_query_data = any(
        checklist.get(k)
        for k in [
            "has_connect_by",
            "has_rownum_usage",
            "has_plus_join_syntax",
            "has_listagg",
            "has_model_clause",
            "has_xml_functions",
        ]
    )
    if not has_any_query_data and not checklist.get("_query_analyzed", False):
        return CategoryScore("Query Compatibility", 16, 20, ["No query analysis: assume 16/20"])

    connect_by = checklist.get("connect_by_count", 1 if checklist.get("has_connect_by") else 0)
    cb_ded = min(connect_by * 2, 6)
    if cb_ded > 0:
        score -= cb_ded
        deductions.append(f"CONNECT BY ({connect_by}): -{cb_ded}")

    rownum = checklist.get("rownum_count", 1 if checklist.get("has_rownum_usage") else 0)
    rn_ded = min(rownum, 3)
    if rn_ded > 0:
        score -= rn_ded
        deductions.append(f"ROWNUM ({rownum}): -{rn_ded}")

    plus_join = checklist.get("plus_join_count", 1 if checklist.get("has_plus_join_syntax") else 0)
    pj_ded = min(plus_join, 3)
    if pj_ded > 0:
        score -= pj_ded
        deductions.append(f"(+) joins ({plus_join}): -{pj_ded}")

    listagg = checklist.get("listagg_count", 1 if checklist.get("has_listagg") else 0)
    la_ded = min(listagg, 2)
    if la_ded > 0:
        score -= la_ded
        deductions.append(f"LISTAGG ({listagg}): -{la_ded}")

    if checklist.get("has_model_clause"):
        score -= 4
        deductions.append("MODEL clause: -4")

    xml_count = checklist.get("xml_function_count", 0)
    xml_ded = min(xml_count * 2, 4)
    if xml_ded > 0:
        score -= xml_ded
        deductions.append(f"XML functions ({xml_count}): -{xml_ded}")

    return CategoryScore("Query Compatibility", max(score, 0), 20, deductions)


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

    lob_count = checklist.get("lob_column_count", 0)
    lob_ded = min(lob_count, 5)
    if lob_ded > 0:
        score -= lob_ded
        deductions.append(f"LOB columns ({lob_count}): -{lob_ded}")

    if checklist.get("table_count", 0) > 1000:
        score -= 2
        deductions.append("Table count > 1000: -2")

    if checklist.get("has_long_columns"):
        score -= 1
        deductions.append("LONG columns: -1")

    return CategoryScore("Data Complexity", max(score, 0), 20, deductions)


def _score_ops(checklist: dict[str, Any], target_tier: str = "starter") -> CategoryScore:
    score = 10
    deductions: list[str] = []

    if checklist.get("supplemental_logging_min", "YES") != "YES":
        score -= 3
        deductions.append("Supplemental logging not enabled: -3")

    version_str = str(checklist.get("oracle_version", "19"))
    try:
        major = int(version_str.split(".")[0])
    except (ValueError, IndexError):
        major = 19
    if major < 12:
        score -= 2
        deductions.append(f"Oracle version {major} (pre-12c): -2")

    charset = checklist.get("nls_characterset", "AL32UTF8")
    if charset != "AL32UTF8":
        score -= 2
        deductions.append(f"Non-UTF8 charset ({charset}): -2")
    if charset == "US7ASCII":
        score -= 1
        deductions.append("US7ASCII additional risk: -1")

    # Tier-specific
    if target_tier == "starter":
        total_mb = checklist.get("total_data_mb", 0)
        if total_mb > 25_000:
            score -= 5
            deductions.append(f"Starter tier: data > 25 GiB ({total_mb} MB): -5")
        elif total_mb > 20_000:
            score -= 2
            deductions.append(f"Starter tier: data > 20 GiB ({total_mb} MB): -2")
        score -= 2
        deductions.append("Starter tier: no CDC support: -2")

    return CategoryScore("Operational Readiness", max(score, 0), 10, deductions)


def score_migration(
    checklist: dict[str, Any],
    procedures: list[ProcedureInfo] | None = None,
    target_tier: str = "starter",
) -> ScoringResult:
    """Calculate the full migration readiness score.

    Args:
        checklist: Structured checklist from Phase 2.5.
        procedures: Optional list of per-procedure detail dicts for fine-grained
            Procedural Code scoring. If None, uses heuristic based on counts.
        target_tier: Target TiDB Cloud tier (starter/essential/dedicated/self-hosted).

    Returns:
        ScoringResult with per-category scores and overall total/rating.
    """
    return ScoringResult(
        schema=_score_schema(checklist),
        procedural_code=_score_procedural_code(checklist, procedures),
        query=_score_query(checklist),
        data=_score_data(checklist),
        ops=_score_ops(checklist, target_tier),
    )
