"""Compatibility rule registry — scan Phase 3 (Assess & Score).

Single source of truth for BLOCKER-*/WARNING-*/HW-BLOCKER-*/HW-WARNING-*
trigger conditions, kept in lockstep with references/compatibility-rules.md.
Each rule's ``check`` returns a count (0 = rule not triggered) computed from
a CompatibilityContext bundling everything the scan collectors have gathered.

Some conditions from compatibility-rules.md need query-log analysis this
project doesn't implement yet (XA transactions, UDFs, XML functions,
GET_LOCK, SQL_CALC_FOUND_ROWS, SAVEPOINT, MySQL Enterprise plugins). Those
rules still exist here and fire correctly once real signals are supplied via
QueryLogSignals; until then they default to "not detected" rather than being
silently omitted.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from tishift_heatwave.models import (
    BinlogPrecheckResult,
    HeatWaveMetadata,
    QueryLogSignals,
    SchemaInventory,
)

SPATIAL_DATA_TYPES = frozenset(
    {
        "geometry",
        "point",
        "linestring",
        "polygon",
        "multipoint",
        "multilinestring",
        "multipolygon",
        "geometrycollection",
    }
)

# Character sets TiDB supports (docs.pingcap.com/tidbcloud/mysql-compatibility
# "Unsupported features" — everything else is rejected outright, not just
# degraded). gbk is TiDB-specific; the rest overlap with MySQL/HeatWave.
SUPPORTED_CHARSETS = frozenset({"ascii", "latin1", "binary", "utf8", "utf8mb4", "gbk"})

# TiDB Cloud only supports lower_case_table_names=2 (case-insensitive
# comparison, original case preserved) — docs.pingcap.com/tidbcloud/mysql-compatibility.
TIDB_LOWER_CASE_TABLE_NAMES = 2


@dataclass
class CompatibilityContext:
    """Everything a compatibility rule needs, gathered by scan collectors
    plus a few facts (query_log) that come from elsewhere until a dedicated
    collector exists for them."""

    inventory: SchemaInventory
    metadata: HeatWaveMetadata
    binlog: BinlogPrecheckResult
    tier: str = "starter"
    continue_replication_planned: bool = False
    query_log: QueryLogSignals = field(default_factory=QueryLogSignals)


@dataclass(frozen=True)
class CompatibilityRule:
    rule_id: str
    severity: str  # "blocker" | "warning"
    feature: str
    action: str
    check: Callable[[CompatibilityContext], int]  # returns a count; 0 = not triggered


def _distinct_tables_with_column(predicate: Callable[[object], bool]) -> Callable[[CompatibilityContext], int]:
    def check(ctx: CompatibilityContext) -> int:
        return len({c.table_name for c in ctx.inventory.columns if predicate(c)})

    return check


def _spatial_column_check(ctx: CompatibilityContext) -> int:
    return len({c.table_name for c in ctx.inventory.columns if c.data_type in SPATIAL_DATA_TYPES})


def _unsupported_charset_check(ctx: CompatibilityContext) -> int:
    return len(
        {
            c.table_name
            for c in ctx.inventory.columns
            if c.charset and c.charset.lower() not in SUPPORTED_CHARSETS
        }
    )


def _case_insensitive_name_collision_check(ctx: CompatibilityContext) -> int:
    """Count table-name groups that only differ by case.

    Harmless when lower_case_table_names already matches TiDB's required
    value 2 (source already treats them as case-insensitive, so the source
    itself could not have two such tables). Only a real blocker when the
    source is more case-sensitive (0 or 1) and genuinely holds colliding
    names that TiDB cannot represent as separate tables.
    """
    if ctx.metadata.lower_case_table_names == TIDB_LOWER_CASE_TABLE_NAMES:
        return 0
    lowered: dict[str, set[str]] = {}
    for t in ctx.inventory.tables:
        lowered.setdefault(t.table_name.lower(), set()).add(t.table_name)
    return sum(1 for names in lowered.values() if len(names) > 1)


def _binlog_fail_gate(rule_id: str) -> Callable[[CompatibilityContext], int]:
    def check(ctx: CompatibilityContext) -> int:
        if not ctx.continue_replication_planned:
            return 0
        return sum(1 for c in ctx.binlog.checks if c.rule_id == rule_id and c.status == "fail")

    return check


BLOCKER_RULES: list[CompatibilityRule] = [
    CompatibilityRule(
        rule_id="BLOCKER-1",
        severity="blocker",
        feature="Stored procedures — parsed but cannot execute",
        action="Convert to application code (Python/Go/Java/JS)",
        check=lambda ctx: sum(1 for r in ctx.inventory.routines if r.kind.upper() == "PROCEDURE"),
    ),
    CompatibilityRule(
        rule_id="BLOCKER-2",
        severity="blocker",
        feature="Triggers — parsed but cannot execute",
        action="Move logic to application middleware",
        check=lambda ctx: len(ctx.inventory.triggers),
    ),
    CompatibilityRule(
        rule_id="BLOCKER-3",
        severity="blocker",
        feature="Scheduled events — not supported",
        action="Use cron, Kubernetes CronJob, or OCI Functions + scheduler",
        check=lambda ctx: len(ctx.inventory.events),
    ),
    CompatibilityRule(
        rule_id="BLOCKER-4",
        severity="blocker",
        feature="Spatial/GIS columns — data type, functions, and indexes all unsupported",
        action="Convert columns to JSON with COMMENT 'was: <original_type>'",
        check=_spatial_column_check,
    ),
    CompatibilityRule(
        rule_id="BLOCKER-5",
        severity="blocker",
        feature="XA distributed transactions — not supported",
        action="Refactor to single-shard transactions or saga pattern",
        check=lambda ctx: int(ctx.query_log.xa_detected),
    ),
    CompatibilityRule(
        rule_id="BLOCKER-6",
        severity="blocker",
        feature="User-defined functions — not supported",
        action="Convert to application-layer functions",
        check=lambda ctx: ctx.query_log.udf_count,
    ),
    CompatibilityRule(
        rule_id="BLOCKER-7",
        severity="blocker",
        feature="XML functions (ExtractValue, UpdateXML) — not supported",
        action="Process XML in application layer",
        check=lambda ctx: int(ctx.query_log.xml_function_detected),
    ),
    CompatibilityRule(
        rule_id="BLOCKER-8",
        severity="blocker",
        feature="Unsupported character set — TiDB only supports ascii/latin1/binary/utf8/utf8mb4/gbk",
        action="Convert affected columns to a supported charset (utf8mb4 by default) before export",
        check=_unsupported_charset_check,
    ),
    CompatibilityRule(
        rule_id="BLOCKER-9",
        severity="blocker",
        feature=(
            "Table names that only differ by case — source is case-sensitive "
            "(lower_case_table_names != 2) but TiDB Cloud only supports 2 (case-insensitive)"
        ),
        action="Rename one of each colliding pair before migrating — TiDB cannot represent both",
        check=_case_insensitive_name_collision_check,
    ),
    CompatibilityRule(
        rule_id="HW-BLOCKER-1",
        severity="blocker",
        feature="Lakehouse external tables — data lives in Object Storage, not InnoDB",
        action=(
            "Materialize to InnoDB before export, or re-point the analytics "
            "pipeline; no TiDB equivalent for external tables"
        ),
        check=lambda ctx: len(ctx.inventory.lakehouse_tables),
    ),
    CompatibilityRule(
        rule_id="HW-BLOCKER-2",
        severity="blocker",
        feature="HeatWave AutoML / GenAI (ML_TRAIN, ML_PREDICT_*, ML_EMBED_*) — no TiDB equivalent",
        action=(
            "Re-host models on external ML serving (OCI Data Science, "
            "SageMaker, vLLM); exclude ML_SCHEMA_* schemas from migration"
        ),
        check=lambda ctx: len(ctx.inventory.automl_schemas),
    ),
    CompatibilityRule(
        rule_id="HW-BLOCKER-3",
        severity="blocker",
        feature="JavaScript (MLE) stored programs — not supported",
        action="Convert to application code; the convert phase emits JS stubs",
        check=lambda ctx: len(ctx.inventory.js_routines),
    ),
]

WARNING_RULES: list[CompatibilityRule] = [
    CompatibilityRule(
        rule_id="WARNING-2",
        severity="warning",
        feature=(
            "FULLTEXT indexes — real index support is Starter-only (and region-limited); "
            "Essential, Dedicated, and self-hosted only parse the syntax, they don't index"
        ),
        action=(
            "Starter: confirm your region supports FULLTEXT indexes "
            "(docs.pingcap.com/tidbcloud/vector-search-full-text-search-sql). "
            "Essential/Dedicated/self-hosted: add a TiFlash replica on the table — "
            "columnar scans accelerate scan-based full-text filtering (LIKE/REGEXP) "
            "in place of the index (convert emits this, rule HW-DDL-6); rewrite "
            "MATCH ... AGAINST queries, or use Elasticsearch/Meilisearch for "
            "relevance-ranked search"
        ),
        check=lambda ctx: (
            sum(1 for i in ctx.inventory.indexes if i.index_type.upper() == "FULLTEXT")
            if ctx.tier != "starter"
            else 0
        ),
    ),
    CompatibilityRule(
        rule_id="WARNING-3",
        severity="warning",
        feature="AUTO_INCREMENT — unique but NOT sequential",
        action=(
            "Consider AUTO_RANDOM for high-insert tables; if the application truly needs "
            "sequential IDs, TiDB's MySQL Compatibility Mode allocates them sequentially "
            "at a throughput cost"
        ),
        check=lambda ctx: sum(1 for t in ctx.inventory.tables if t.auto_increment is not None),
    ),
    CompatibilityRule(
        rule_id="WARNING-4",
        severity="warning",
        feature="utf8mb4_0900_* collations (MySQL 8 default)",
        action=(
            "Maps 1:1 to the same collation on TiDB (utf8mb4_0900_* supported "
            "natively since v7.4; target TiDB Cloud is v8.5) — no action needed"
        ),
        check=_distinct_tables_with_column(
            lambda c: (c.collation or "").lower().startswith("utf8mb4_0900")
        ),
    ),
    CompatibilityRule(
        rule_id="WARNING-5",
        severity="warning",
        feature="GET_LOCK/RELEASE_LOCK — limited implementation",
        action="Test advisory locking behavior; consider Redis-based locks",
        check=lambda ctx: int(ctx.query_log.get_lock_detected),
    ),
    CompatibilityRule(
        rule_id="WARNING-6",
        severity="warning",
        feature="SQL_CALC_FOUND_ROWS — works but triggers full table scan",
        action="Replace with separate COUNT(*) query",
        check=lambda ctx: int(ctx.query_log.sql_calc_found_rows_detected),
    ),
    CompatibilityRule(
        rule_id="WARNING-7",
        severity="warning",
        feature="SAVEPOINT — pessimistic mode only",
        action="Ensure pessimistic transaction mode is enabled (default in TiDB)",
        check=lambda ctx: int(ctx.query_log.savepoint_detected),
    ),
    CompatibilityRule(
        rule_id="WARNING-8",
        severity="warning",
        feature="lower_case_table_names mismatch — TiDB Cloud only supports value 2",
        action=(
            "Verify no application code depends on case-sensitive table-name matching; "
            "TiDB always compares table names case-insensitively regardless of the "
            "source's setting"
        ),
        check=lambda ctx: int(
            ctx.metadata.lower_case_table_names is not None
            and ctx.metadata.lower_case_table_names != TIDB_LOWER_CASE_TABLE_NAMES
        ),
    ),
    CompatibilityRule(
        rule_id="WARNING-9",
        severity="warning",
        feature="Updatable views (IS_UPDATABLE=YES) — TiDB views are always read-only",
        action="Redirect writes that currently go through the view to the underlying table(s) directly",
        check=lambda ctx: sum(1 for v in ctx.inventory.views if v.is_updatable),
    ),
    CompatibilityRule(
        rule_id="HW-WARNING-1",
        severity="warning",
        feature="RAPID analytics offload (SECONDARY_ENGINE=RAPID)",
        action=(
            "Maps to TiFlash replicas (convert emits ALTER TABLE ... SET TIFLASH "
            "REPLICA n after each RAPID table's CREATE TABLE, on every tier) — "
            "not a loss of function"
        ),
        check=lambda ctx: len(ctx.inventory.rapid_tables),
    ),
    CompatibilityRule(
        rule_id="HW-WARNING-2",
        severity="warning",
        feature="MySQL 9 VECTOR columns",
        action=(
            "TiDB Cloud supports VECTOR; re-create indexes with TiDB syntax and "
            "re-verify distance functions. GenAI embeddings must be regenerated externally"
        ),
        check=_distinct_tables_with_column(lambda c: c.is_vector),
    ),
    CompatibilityRule(
        rule_id="HW-WARNING-3",
        severity="warning",
        feature="MySQL Enterprise add-ons (TDE, data masking, audit plugin, firewall)",
        action=(
            "Map to TiDB Cloud equivalents: encryption at rest (default), "
            "audit logging (Dedicated), data masking in application layer"
        ),
        check=lambda ctx: len(ctx.query_log.enterprise_features),
    ),
    CompatibilityRule(
        rule_id="HW-WARNING-4",
        severity="warning",
        feature="Short binlog retention risks DM losing position during initial load",
        action="Raise retention to >= 86400s (1 day, hard minimum), 604800s (7 days) recommended",
        check=_binlog_fail_gate("HW-WARNING-4"),
    ),
    CompatibilityRule(
        rule_id="HW-WARNING-5",
        severity="warning",
        feature="binlog_row_value_options = 'PARTIAL_JSON' — DM cannot parse partial-JSON binlog rows",
        action="SET GLOBAL binlog_row_value_options = ''; before starting sync",
        check=lambda ctx: int(
            ctx.continue_replication_planned
            and (ctx.metadata.binlog_row_value_options or "").upper() == "PARTIAL_JSON"
        ),
    ),
    CompatibilityRule(
        rule_id="HW-WARNING-6",
        severity="warning",
        feature="Binary logging disabled — nothing for DM to replicate from",
        action="Enable log_bin (requires a restart) before starting sync",
        check=_binlog_fail_gate("HW-WARNING-6"),
    ),
    CompatibilityRule(
        rule_id="HW-WARNING-7",
        severity="warning",
        feature="Non-ROW binlog format misses edge cases in data changes",
        action="Set binlog_format = ROW before starting sync",
        check=_binlog_fail_gate("HW-WARNING-7"),
    ),
    CompatibilityRule(
        rule_id="HW-WARNING-8",
        severity="warning",
        feature="Partial row images are unsafe for conflict resolution",
        action="Set binlog_row_image = FULL before starting sync",
        check=_binlog_fail_gate("HW-WARNING-8"),
    ),
    CompatibilityRule(
        rule_id="HW-WARNING-9",
        severity="warning",
        feature="DM does not support transaction compression",
        action="SET GLOBAL binlog_transaction_compression = 'OFF'; before starting sync",
        check=_binlog_fail_gate("HW-WARNING-9"),
    ),
]

ALL_RULES: list[CompatibilityRule] = [*BLOCKER_RULES, *WARNING_RULES]

COMPATIBLE_FEATURES: list[str] = [
    "InnoDB engine (TiDB's only engine — always compatible)",
    "Foreign keys — enforced natively (TiDB v6.6+; target TiDB Cloud is v8.5). "
    "TiDB Cloud DM's precheck still reports FK warnings even when the migration "
    "is safe — see the FK Pre-upgrade Checklist before dismissing",
    "JSON columns (full JSON path support)",
    "ENUM/SET types",
    "utf8mb4 charset",
    "Window functions and CTEs",
    "Prepared statements",
    "Pessimistic transactions (default mode)",
    "RANGE/LIST/HASH/KEY partitioning",
    "Online DDL (distributed implementation)",
    "Generated columns (VIRTUAL and STORED)",
    "Views (standard SQL views — read-only; see WARNING-9 for updatable-view usage)",
    "Analytic queries previously offloaded to RAPID — run on TiFlash instead",
]
