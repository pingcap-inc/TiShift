"""Core data models for TiShift HeatWave."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Severity(str, Enum):
    BLOCKER = "BLOCKER"
    WARNING = "WARNING"
    COMPATIBLE = "COMPATIBLE"


@dataclass
class HeatWaveMetadata:
    """Server-level metadata collected during scan (SKILL.md Step 1.1/1.2, 2.1b).

    All fields are optional so the collector degrades gracefully against
    plain MySQL (no HeatWave cluster, no OCI-specific variables). Binlog
    settings gated for continue replication (binlog_format, binlog_row_image,
    binlog_expire_logs_seconds, log_bin, binlog_transaction_compression) are
    NOT duplicated here — see BinlogPrecheckResult / core/scan/collectors/binlog.py,
    the single source of truth for those five variables.
    """

    mysql_version: str | None = None
    version_comment: str | None = None  # "MySQL Enterprise - Cloud" on OCI
    has_rapid_cluster: bool = False
    rapid_node_count: int = 0  # HeatWave RAPID analytics cluster node count
    binlog_row_value_options: str | None = None  # HW-WARNING-5 if 'PARTIAL_JSON'
    gtid_mode: str | None = None
    character_set_server: str | None = None
    collation_server: str | None = None
    transaction_isolation: str | None = None
    sql_mode: str | None = None
    lower_case_table_names: int | None = None
    max_connections: int | None = None
    # MySQL replication topology (HA/primary-secondary architecture), distinct
    # from the RAPID analytics cluster above. Requires REPLICATION CLIENT.
    read_only: bool | None = None
    super_read_only: bool | None = None
    is_replica: bool = False  # this node replicates from another (SHOW REPLICA STATUS)
    replica_source_host: str | None = None
    connected_replica_count: int = 0  # downstream replicas (SHOW REPLICAS)
    connected_replica_hosts: list[str] = field(default_factory=list)


@dataclass
class QueryLogSignals:
    """Facts that would require query-log analysis to detect (not yet wired to
    a collector — no query-log collector exists yet). Defaults assume none
    detected; callers can override once such a collector exists.

    xa_detected -> BLOCKER-5, udf_count -> BLOCKER-6, xml_function_detected ->
    BLOCKER-7, get_lock_detected -> WARNING-5, sql_calc_found_rows_detected ->
    WARNING-6, savepoint_detected -> WARNING-7, enterprise_features -> HW-WARNING-3.
    """

    xa_detected: bool = False
    udf_count: int = 0
    xml_function_detected: bool = False
    get_lock_detected: bool = False
    sql_calc_found_rows_detected: bool = False
    savepoint_detected: bool = False
    enterprise_features: list[str] = field(default_factory=list)


@dataclass
class BinlogVariableCheck:
    """One row of the binlog/continue-replication readiness precheck (rules/binlog_check.py)."""

    variable: str
    rule_id: str | None  # None for informational-only checks (server_id, expire_logs_days)
    actual: str | None
    required: str
    status: str  # pass | fail | warn | info
    why: str
    recommended: str | None = None


@dataclass
class BinlogPrecheckResult:
    checks: list[BinlogVariableCheck] = field(default_factory=list)
    continue_replication_ready: bool = True  # False if any gated check has status == "fail"


@dataclass
class ColumnInfo:
    schema_name: str
    table_name: str
    column_name: str
    ordinal_position: int
    data_type: str
    column_type: str  # full type incl. length/unsigned, e.g. "bigint unsigned"
    is_nullable: bool
    column_default: str | None = None
    character_maximum_length: int | None = None
    numeric_precision: int | None = None
    numeric_scale: int | None = None
    charset: str | None = None
    collation: str | None = None
    extra: str = ""  # auto_increment, VIRTUAL GENERATED, ...
    is_vector: bool = False  # MySQL 9 VECTOR type
    excluded_from_rapid: bool = False  # NOT SECONDARY columns


@dataclass
class TableInfo:
    schema_name: str
    table_name: str
    engine: str  # InnoDB, or Lakehouse for external tables
    row_estimate: int
    data_bytes: int
    index_bytes: int
    create_options: str = ""  # raw CREATE_OPTIONS, e.g. SECONDARY_ENGINE="RAPID"
    charset: str | None = None
    collation: str | None = None
    is_rapid_loaded: bool = False  # offloaded to the HeatWave cluster
    is_lakehouse: bool = False  # data lives in Object Storage, not InnoDB
    auto_increment: int | None = None
    partition_method: str | None = None
    columns: list[ColumnInfo] = field(default_factory=list)


@dataclass
class IndexInfo:
    schema_name: str
    table_name: str
    index_name: str
    index_type: str  # BTREE, FULLTEXT, SPATIAL
    is_unique: bool
    columns: list[str] = field(default_factory=list)


@dataclass
class ConstraintInfo:
    schema_name: str
    table_name: str
    constraint_name: str
    constraint_type: str  # PRIMARY KEY, FOREIGN KEY, UNIQUE, CHECK
    definition: str = ""
    foreign_table: str | None = None


@dataclass
class RoutineInfo:
    schema_name: str
    routine_name: str
    kind: str  # PROCEDURE or FUNCTION
    definition: str
    external_language: str = "SQL"  # JAVASCRIPT for MLE stored programs
    is_deterministic: bool = False


@dataclass
class TriggerInfo:
    schema_name: str
    table_name: str
    trigger_name: str
    timing: str  # BEFORE / AFTER
    event: str  # INSERT / UPDATE / DELETE
    definition: str = ""


@dataclass
class EventInfo:
    schema_name: str
    event_name: str
    schedule: str
    definition: str = ""


@dataclass
class ViewInfo:
    schema_name: str
    view_name: str
    is_updatable: bool = False  # information_schema.VIEWS.IS_UPDATABLE == 'YES'


@dataclass
class SchemaInventory:
    tables: list[TableInfo] = field(default_factory=list)
    columns: list[ColumnInfo] = field(default_factory=list)
    indexes: list[IndexInfo] = field(default_factory=list)
    constraints: list[ConstraintInfo] = field(default_factory=list)
    routines: list[RoutineInfo] = field(default_factory=list)
    triggers: list[TriggerInfo] = field(default_factory=list)
    events: list[EventInfo] = field(default_factory=list)
    views: list[ViewInfo] = field(default_factory=list)
    # HeatWave-specific inventory
    rapid_tables: list[str] = field(default_factory=list)
    lakehouse_tables: list[str] = field(default_factory=list)
    automl_schemas: list[str] = field(default_factory=list)  # ML_SCHEMA_<user>
    vector_columns: list[str] = field(default_factory=list)
    js_routines: list[str] = field(default_factory=list)
    unsupported_collations: list[str] = field(default_factory=list)


@dataclass
class CleanupFinding:
    """One DDL cleanup rule hit (see rules/ddl_cleanup.py)."""

    rule_id: str
    risk: str  # blocker | assess | harmless
    table: str | None
    matched_text: str
    action_taken: str  # commented_out | commented_out_with_suggestion | statement_commented_out | kept
    suggestion: str | None = None


@dataclass
class DDLCleanupResult:
    """Output of the convert-phase DDL cleanup over a whole script."""

    sql: str = ""
    findings: list[CleanupFinding] = field(default_factory=list)
    rapid_tables: list[str] = field(default_factory=list)
    tiflash_statements: list[str] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)


@dataclass
class CompatibilityFinding:
    rule_id: str
    severity: Severity
    feature: str
    count: int
    action: str


@dataclass
class AssessmentResult:
    blockers: list[CompatibilityFinding] = field(default_factory=list)
    warnings: list[CompatibilityFinding] = field(default_factory=list)
    compatible: list[str] = field(default_factory=list)


@dataclass
class CategoryScore:
    name: str
    max_points: int
    score: int
    deductions: list[str] = field(default_factory=list)


@dataclass
class ReadinessScore:
    overall: int
    categories: list[CategoryScore] = field(default_factory=list)
    rating: str = ""
