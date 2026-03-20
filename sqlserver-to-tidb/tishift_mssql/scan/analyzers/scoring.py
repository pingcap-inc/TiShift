"""Readiness scoring model."""

from __future__ import annotations

import re

from tishift_mssql.models import (
    CategoryScore,
    DataProfile,
    FeatureScanResult,
    QueryPatterns,
    SQLServerMetadata,
    SchemaInventory,
    ScoringResult,
)


def _bounded(max_score: int, penalty: int) -> int:
    return max(0, max_score - penalty)


def _count_pattern(definition: str, pattern: str) -> int:
    return len(re.findall(pattern, definition, flags=re.IGNORECASE))


def _sp_deduction(definition: str) -> tuple[int, str]:
    """Heuristic SP complexity deduction aligned to spec bands."""
    loc = len([ln for ln in definition.splitlines() if ln.strip()])
    cursors = _count_pattern(definition, r"\bDECLARE\s+\w+\s+CURSOR\b")
    dynamic = _count_pattern(definition, r"\bsp_executesql\b|\bEXEC\s*\(")
    temp_tables = _count_pattern(definition, r"#\w+")
    nested_calls = _count_pattern(definition, r"\bEXEC\s+\w+\.\w+")

    score = min(loc // 10, 10)
    score += cursors * 5
    score += dynamic * 3
    score += min(temp_tables * 2, 6)
    score += nested_calls * 3

    if loc < 10 and score <= 5:
        return 1, "trivial"
    if loc < 30 and cursors == 0 and score <= 12:
        return 2, "simple"
    if score <= 25:
        return 3, "moderate"
    if score <= 40:
        return 5, "complex"
    return 5, "requires_redesign"


def _major_version(product_version: str | None) -> int | None:
    if not product_version:
        return None
    try:
        return int(product_version.split(".")[0])
    except Exception:
        return None


def compute_scores(
    inventory: SchemaInventory,
    profile: DataProfile,
    metadata: SQLServerMetadata,
    features: FeatureScanResult,
    query_patterns: QueryPatterns | None = None,
    tier: str = "starter",
) -> ScoringResult:
    """Compute weighted scores (25/25/20/20/10) per SQL Server spec."""
    schema_deductions: list[str] = []
    code_deductions: list[str] = []
    query_deductions: list[str] = []
    data_deductions: list[str] = []
    ops_deductions: list[str] = []

    schema_penalty = 0
    deprecated_cols = [c for c in inventory.columns if c.data_type.lower() in {"image", "ntext"}]
    if deprecated_cols:
        schema_penalty += min(3, len(deprecated_cols))
        schema_deductions.append(f"{len(deprecated_cols)} deprecated IMAGE/NTEXT columns")
    hierarchy_cols = [c for c in inventory.columns if c.data_type.lower() == "hierarchyid"]
    if hierarchy_cols:
        schema_penalty += min(4, len(hierarchy_cols) * 2)
        schema_deductions.append(f"{len(hierarchy_cols)} HIERARCHYID columns")
    spatial_cols = [c for c in inventory.columns if c.data_type.lower() in {"geography", "geometry"}]
    if spatial_cols:
        schema_penalty += min(4, len(spatial_cols) * 2)
        schema_deductions.append(f"{len(spatial_cols)} spatial columns")
    variant_cols = [c for c in inventory.columns if c.data_type.lower() == "sql_variant"]
    if variant_cols:
        schema_penalty += min(2, len(variant_cols))
        schema_deductions.append(f"{len(variant_cols)} SQL_VARIANT columns")
    if any(t.is_temporal for t in inventory.tables):
        schema_penalty += 3
        schema_deductions.append("Temporal tables detected")
    if any(t.is_memory_optimized for t in inventory.tables):
        schema_penalty += 2
        schema_deductions.append("Memory optimized tables detected")
    non_dbo_schemas = {s.lower() for s in inventory.schemas if s.lower() != "dbo"}
    if non_dbo_schemas:
        schema_penalty += min(3, len(non_dbo_schemas))
        schema_deductions.append(f"{len(non_dbo_schemas)} non-dbo schemas in use")
    filestream_cols = [c for c in inventory.columns if c.is_filestream]
    if filestream_cols:
        schema_penalty += 2
        schema_deductions.append("FILESTREAM columns detected")
    tsql_computed = [
        c for c in inventory.columns
        if c.is_computed and c.computed_definition and re.search(r"\b(ISNULL|GETDATE|CONVERT|CAST)\b", c.computed_definition, re.IGNORECASE)
    ]
    if tsql_computed:
        schema_penalty += min(3, len(tsql_computed))
        schema_deductions.append(f"{len(tsql_computed)} T-SQL specific computed columns")

    code_penalty = 0
    for routine in inventory.routines:
        if "PROCEDURE" in routine.routine_type.upper() and routine.definition:
            deduction, difficulty = _sp_deduction(routine.definition)
            code_penalty += deduction
            code_deductions.append(f"{routine.schema_name}.{routine.routine_name}: {difficulty} (-{deduction})")
    trigger_deduction = min(8, len(inventory.triggers) * 2)
    if trigger_deduction:
        code_penalty += trigger_deduction
        code_deductions.append(f"{len(inventory.triggers)} triggers (-{trigger_deduction})")
    clr_deduction = min(9, len(inventory.assemblies) * 3)
    if clr_deduction:
        code_penalty += clr_deduction
        code_deductions.append(f"{len(inventory.assemblies)} CLR assemblies (-{clr_deduction})")
    job_deduction = min(3, len(inventory.agent_jobs))
    if job_deduction:
        code_penalty += job_deduction
        code_deductions.append(f"{len(inventory.agent_jobs)} SQL Agent jobs (-{job_deduction})")
    if inventory.assemblies:
        # keep explicit mention for report readability
        code_deductions.append("CLR replacement required")
    if metadata.has_ssis:
        code_penalty += 5
        code_deductions.append("SSIS packages detected (-5)")

    query_penalty = 0
    if query_patterns is None:
        query_score = 16
        query_deductions.append("Query log not included; defaulted to 16/20")
    else:
        construct_counts: dict[str, int] = {}
        for issue in query_patterns.issues:
            construct_counts[issue.construct] = construct_counts.get(issue.construct, 0) + 1
        merge_count = construct_counts.get("merge", 0)
        if merge_count:
            query_penalty += min(4, merge_count)
            query_deductions.append(f"MERGE usage ({merge_count})")
        xml_count = construct_counts.get("for_xml", 0) + construct_counts.get("openxml", 0)
        if xml_count:
            query_penalty += min(3, xml_count)
            query_deductions.append(f"FOR XML/OPENXML usage ({xml_count})")
        apply_count = construct_counts.get("cross_apply", 0) + construct_counts.get("outer_apply", 0)
        if apply_count:
            query_penalty += min(3, apply_count)
            query_deductions.append(f"CROSS/OUTER APPLY usage ({apply_count})")
        pivot_count = construct_counts.get("pivot", 0) + construct_counts.get("unpivot", 0)
        if pivot_count:
            query_penalty += min(2, pivot_count)
            query_deductions.append(f"PIVOT/UNPIVOT usage ({pivot_count})")
        nolock_count = construct_counts.get("nolock", 0)
        if nolock_count:
            query_penalty += min(2, nolock_count)
            query_deductions.append(f"NOLOCK hints ({nolock_count})")
        query_score = _bounded(20, query_penalty)

    data_penalty = 0
    # Tier-specific data size deductions
    if tier == "starter":
        if profile.total_data_mb > 25 * 1024:
            data_penalty += 8
            data_deductions.append("Data exceeds Starter 25 GiB free limit (-8)")
        elif profile.total_data_mb > 20 * 1024:
            data_penalty += 3
            data_deductions.append("Data approaching Starter 25 GiB limit (-3)")
    else:
        if profile.total_data_mb > 500 * 1024:
            data_penalty += 2
            data_deductions.append("Total data > 500 GB")
        if profile.total_data_mb > 1024 * 1024:
            data_penalty += 5
            data_deductions.append("Total data > 1 TB")
        if profile.total_data_mb > 5 * 1024 * 1024:
            data_penalty += 10
            data_deductions.append("Total data > 5 TB")
    if any(ts.data_mb > 100 * 1024 for ts in profile.table_sizes):
        data_penalty += 2
        data_deductions.append("At least one table > 100 GB")
    large_bin_cols = [
        c for c in inventory.columns
        if (c.data_type.lower() == "image") or (c.data_type.lower() == "varbinary" and (c.max_length or 0) < 0)
    ]
    if large_bin_cols:
        data_penalty += min(3, len(large_bin_cols))
        data_deductions.append(f"{len(large_bin_cols)} IMAGE/VARBINARY(MAX) columns")
    if len(inventory.tables) > 1000:
        data_penalty += 2
        data_deductions.append("More than 1000 tables")
    money_cols = [c for c in inventory.columns if c.data_type.lower() in {"money", "smallmoney"}]
    if money_cols:
        data_penalty += min(2, len(money_cols))
        data_deductions.append(f"{len(money_cols)} MONEY/SMALLMONEY columns")
    nvarchar_non_utf8 = [
        c for c in inventory.columns
        if c.data_type.lower() in {"nvarchar", "nchar"}
        and c.collation_name
        and "UTF8" not in c.collation_name.upper()
    ]
    if nvarchar_non_utf8:
        data_penalty += 2
        data_deductions.append("NVARCHAR/NCHAR with non-UTF8 collations")

    ops_penalty = 0
    if tier == "starter":
        if metadata.cdc_enabled:
            ops_penalty += 2
            ops_deductions.append("CDC enabled but Starter has no Changefeed support — sync requires cutover")
        ops_penalty += 2
        ops_deductions.append("Starter tier has no zero-downtime cutover path")
    elif not metadata.cdc_enabled:
        ops_penalty += 5
        ops_deductions.append("CDC not enabled")
    major = _major_version(metadata.product_version)
    if major is not None and major < 13:
        ops_penalty += 2
        ops_deductions.append("SQL Server version < 2016")
    if metadata.db_collation and metadata.db_collation.lower() != "utf8mb4_bin":
        ops_penalty += 1
        ops_deductions.append("Source collation differs from TiDB default")
    if len(non_dbo_schemas) > 0:
        ops_penalty += 2
        ops_deductions.append("Multiple schemas require mapping strategy")
    if metadata.auth_mode.lower() == "windows":
        ops_penalty += 1
        ops_deductions.append("Windows auth mode may require SQL auth for tooling")

    return ScoringResult(
        schema_compatibility=CategoryScore(
            name="Schema Compatibility",
            score=_bounded(25, schema_penalty),
            max_score=25,
            deductions=schema_deductions,
        ),
        code_portability=CategoryScore(
            name="Procedural Code",
            score=_bounded(25, code_penalty),
            max_score=25,
            deductions=code_deductions,
        ),
        query_compatibility=CategoryScore(
            name="Query Compatibility",
            score=query_score,
            max_score=20,
            deductions=query_deductions,
        ),
        data_complexity=CategoryScore(
            name="Data Complexity",
            score=_bounded(20, data_penalty),
            max_score=20,
            deductions=data_deductions,
        ),
        operational_readiness=CategoryScore(
            name="Operational Readiness",
            score=_bounded(10, ops_penalty),
            max_score=10,
            deductions=ops_deductions,
        ),
    )
