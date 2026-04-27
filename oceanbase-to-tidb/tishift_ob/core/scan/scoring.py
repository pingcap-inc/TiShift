"""Readiness scoring engine for OceanBase → TiDB migration.

Dual-mode scoring:
  MySQL mode:  Schema 25, Procedural 15, Query 20, Data 20, Ops 20
  Oracle mode: Schema 20, Procedural 30, Query 20, Data 20, Ops 10
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
    ob_mode: str

    @property
    def total(self) -> int:
        return (
            self.schema.score + self.procedural_code.score
            + self.query.score + self.data.score + self.ops.score
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


# ── MySQL mode scoring ──────────────────────────────────────────────

def _mysql_schema(c: dict[str, Any]) -> CategoryScore:
    s, d = 25, []
    if c.get("has_tablegroups"):
        s -= 3; d.append("TABLEGROUP: -3")
    if c.get("has_primary_zone"):
        s -= 2; d.append("PRIMARY_ZONE: -2")
    if c.get("has_locality"):
        s -= 2; d.append("LOCALITY: -2")
    if c.get("has_resource_units"):
        s -= 2; d.append("Resource units: -2")
    if c.get("has_global_indexes"):
        s -= 2; d.append("Global indexes: -2")
    if c.get("has_spatial"):
        s -= 3; d.append("Spatial columns: -3")
    cp = min(c.get("composite_partition_count", 0), 3)
    if cp:
        s -= cp; d.append(f"Composite partitions ({c.get('composite_partition_count', 0)}): -{cp}")
    return CategoryScore("Schema Compatibility", max(s, 0), 25, d)


def _mysql_proc(c: dict[str, Any]) -> CategoryScore:
    s, d = 15, []
    pc = c.get("stored_procedure_count", 0)
    tc = c.get("trigger_count", 0)
    if pc == 0 and tc == 0:
        return CategoryScore("Procedural Code", 15, 15, [])
    pd = min(pc * 2, 10)
    if pd:
        s -= pd; d.append(f"Procedures ({pc}): -{pd}")
    td = min(tc * 2, 6)
    if td:
        s -= td; d.append(f"Triggers ({tc}): -{td}")
    return CategoryScore("Procedural Code", max(s, 0), 15, d)


def _mysql_query(c: dict[str, Any]) -> CategoryScore:
    s, d = 20, []
    if not c.get("_query_analyzed"):
        return CategoryScore("Query Compatibility", 18, 20, ["No query analysis: assume 18/20"])
    hints = c.get("ob_hint_count", 0)
    hd = min(hints, 2)
    if hd:
        s -= hd; d.append(f"OB hints ({hints}): -{hd}")
    uf = c.get("unsupported_function_count", 0)
    ud = min(uf, 5)
    if ud:
        s -= ud; d.append(f"Unsupported functions ({uf}): -{ud}")
    return CategoryScore("Query Compatibility", max(s, 0), 20, d)


def _mysql_ops(c: dict[str, Any], tier: str) -> CategoryScore:
    s, d = 20, []
    if c.get("cdc_not_available", True):
        s -= 5; d.append("No MySQL-binlog-compatible CDC: -5")
    v = str(c.get("ob_version", "4.0"))
    try:
        major = float(v.split(".")[0])
    except (ValueError, IndexError):
        major = 4.0
    if major < 4:
        s -= 3; d.append(f"OB version < 4.0 ({v}): -3")
    if c.get("collation_mismatch"):
        s -= 2; d.append("Collation mismatch: -2")
    if tier == "starter":
        mb = c.get("total_data_mb", 0)
        if mb > 25_000:
            s -= 5; d.append(f"Starter: data > 25 GiB ({mb} MB): -5")
        s -= 2; d.append("Starter: no CDC: -2")
    return CategoryScore("Operational Readiness", max(s, 0), 20, d)


# ── Oracle mode scoring ─────────────────────────────────────────────

def _oracle_schema(c: dict[str, Any]) -> CategoryScore:
    s, d = 20, []
    if c.get("has_tablegroups"):
        s -= 3; d.append("TABLEGROUP: -3")
    if c.get("has_oracle_types"):
        s -= 3; d.append("Oracle types: -3")
    if c.get("has_primary_zone"):
        s -= 2; d.append("PRIMARY_ZONE: -2")
    if c.get("has_locality"):
        s -= 2; d.append("LOCALITY: -2")
    if c.get("has_object_types"):
        s -= 3; d.append("Object types: -3")
    if c.get("has_xmltype"):
        s -= 3; d.append("XMLType: -3")
    return CategoryScore("Schema Compatibility", max(s, 0), 20, d)


def _oracle_proc(c: dict[str, Any]) -> CategoryScore:
    s, d = 30, []
    pc = c.get("stored_procedure_count", 0) + c.get("function_count", 0)
    pkg = c.get("package_count", 0)
    tc = c.get("trigger_count", 0)
    if pc == 0 and pkg == 0 and tc == 0:
        return CategoryScore("Procedural Code", 30, 30, [])
    pd = min(pc * 2, 20)
    if pd:
        s -= pd; d.append(f"Procedures/functions ({pc}): -{pd}")
    pkd = min(pkg * 3, 9)
    if pkd:
        s -= pkd; d.append(f"Packages ({pkg}): -{pkd}")
    td = min(tc * 2, 10)
    if td:
        s -= td; d.append(f"Triggers ({tc}): -{td}")
    return CategoryScore("Procedural Code", max(s, 0), 30, d)


def _oracle_query(c: dict[str, Any]) -> CategoryScore:
    s, d = 20, []
    if not c.get("_query_analyzed"):
        return CategoryScore("Query Compatibility", 16, 20, ["No query analysis: assume 16/20"])
    cb = min(c.get("connect_by_count", 0) * 2, 6)
    if cb:
        s -= cb; d.append(f"CONNECT BY: -{cb}")
    rn = min(c.get("rownum_count", 0), 3)
    if rn:
        s -= rn; d.append(f"ROWNUM: -{rn}")
    pj = min(c.get("plus_join_count", 0), 3)
    if pj:
        s -= pj; d.append(f"(+) joins: -{pj}")
    la = min(c.get("listagg_count", 0), 2)
    if la:
        s -= la; d.append(f"LISTAGG: -{la}")
    return CategoryScore("Query Compatibility", max(s, 0), 20, d)


def _oracle_ops(c: dict[str, Any], tier: str) -> CategoryScore:
    s, d = 10, []
    if c.get("cdc_not_available", True):
        s -= 3; d.append("No MySQL-binlog CDC: -3")
    cs = c.get("nls_characterset", "AL32UTF8")
    if cs != "AL32UTF8":
        s -= 2; d.append(f"Non-UTF8 charset ({cs}): -2")
    if tier == "starter":
        if c.get("total_data_mb", 0) > 25_000:
            s -= 3; d.append("Starter: data > 25 GiB: -3")
    return CategoryScore("Operational Readiness", max(s, 0), 10, d)


# ── Shared ──────────────────────────────────────────────────────────

def _score_data(c: dict[str, Any], max_pts: int = 20) -> CategoryScore:
    s, d = max_pts, []
    mb = c.get("total_data_mb", 0)
    if mb > 5_000_000:
        s -= 10; d.append(f"Data > 5 TB: -10")
    elif mb > 1_000_000:
        s -= 5; d.append(f"Data > 1 TB: -5")
    elif mb > 500_000:
        s -= 2; d.append(f"Data > 500 GB: -2")
    if c.get("largest_table_mb", 0) > 100_000:
        s -= 2; d.append("Largest table > 100 GB: -2")
    if c.get("table_count", 0) > 1000:
        s -= 2; d.append("Table count > 1000: -2")
    ld = min(c.get("lob_column_count", 0), 4)
    if ld:
        s -= ld; d.append(f"LOB columns: -{ld}")
    return CategoryScore("Data Complexity", max(s, 0), max_pts, d)


def score_migration(
    checklist: dict[str, Any],
    ob_mode: str = "mysql",
    target_tier: str = "starter",
) -> ScoringResult:
    """Calculate readiness score, branching by OceanBase mode."""
    if ob_mode == "oracle":
        return ScoringResult(
            schema=_oracle_schema(checklist),
            procedural_code=_oracle_proc(checklist),
            query=_oracle_query(checklist),
            data=_score_data(checklist),
            ops=_oracle_ops(checklist, target_tier),
            ob_mode="oracle",
        )
    return ScoringResult(
        schema=_mysql_schema(checklist),
        procedural_code=_mysql_proc(checklist),
        query=_mysql_query(checklist),
        data=_score_data(checklist),
        ops=_mysql_ops(checklist, target_tier),
        ob_mode="mysql",
    )
