"""Data models for the TiShift scan pipeline.

All types used as inputs/outputs of core functions live here.
Frozen dataclasses for immutable query results, mutable for containers
built incrementally.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Severity(str, Enum):
    BLOCKER = "blocker"
    WARNING = "warning"
    INFO = "info"


class Rating(str, Enum):
    EXCELLENT = "excellent"
    GOOD = "good"
    MODERATE = "moderate"
    CHALLENGING = "challenging"
    DIFFICULT = "difficult"


class TargetDeployment(str, Enum):
    CLOUD = "cloud"
    SELF_HOSTED = "self-hosted"


class SPDifficulty(str, Enum):
    TRIVIAL = "trivial"
    SIMPLE = "simple"
    MODERATE = "moderate"
    COMPLEX = "complex"
    REQUIRES_REDESIGN = "requires_redesign"


# ---------------------------------------------------------------------------
# Schema Inventory (from Collector 1)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TableInfo:
    table_schema: str
    table_name: str
    engine: str | None
    row_format: str | None
    table_rows: int
    data_length: int
    index_length: int
    auto_increment: int | None
    table_collation: str | None
    create_options: str | None


@dataclass(frozen=True)
class ColumnInfo:
    table_schema: str
    table_name: str
    column_name: str
    ordinal_position: int
    column_default: str | None
    is_nullable: str
    data_type: str
    column_type: str
    character_set_name: str | None
    collation_name: str | None
    column_key: str
    extra: str
    generation_expression: str | None


@dataclass(frozen=True)
class IndexInfo:
    table_schema: str
    table_name: str
    index_name: str
    non_unique: int
    index_type: str
    columns: str  # comma-separated


@dataclass(frozen=True)
class ForeignKeyInfo:
    constraint_schema: str
    table_name: str
    constraint_name: str
    referenced_table_schema: str | None
    referenced_table_name: str | None
    columns: str  # comma-separated
    ref_columns: str  # comma-separated


@dataclass(frozen=True)
class RoutineInfo:
    routine_schema: str
    routine_name: str
    routine_type: str  # PROCEDURE or FUNCTION
    data_type: str | None
    routine_body: str | None
    routine_definition: str | None
    is_deterministic: str
    security_type: str
    definer: str | None


@dataclass(frozen=True)
class TriggerInfo:
    trigger_schema: str
    trigger_name: str
    event_manipulation: str
    event_object_table: str
    action_statement: str | None
    action_timing: str


@dataclass(frozen=True)
class ViewInfo:
    table_schema: str
    table_name: str
    view_definition: str | None
    check_option: str | None
    is_updatable: str
    definer: str | None
    security_type: str | None


@dataclass(frozen=True)
class EventInfo:
    event_schema: str
    event_name: str
    event_type: str
    execute_at: str | None
    interval_value: str | None
    interval_field: str | None
    event_definition: str | None
    status: str


@dataclass(frozen=True)
class PartitionInfo:
    table_schema: str
    table_name: str
    partition_name: str | None
    partition_method: str | None
    partition_expression: str | None
    partition_description: str | None
    subpartition_method: str | None
    subpartition_expression: str | None


@dataclass(frozen=True)
class CharsetUsage:
    character_set_name: str | None
    collation_name: str | None
    column_count: int


@dataclass
class SchemaInventory:
    """Complete schema inventory from information_schema."""
    tables: list[TableInfo] = field(default_factory=list)
    columns: list[ColumnInfo] = field(default_factory=list)
    indexes: list[IndexInfo] = field(default_factory=list)
    foreign_keys: list[ForeignKeyInfo] = field(default_factory=list)
    routines: list[RoutineInfo] = field(default_factory=list)
    triggers: list[TriggerInfo] = field(default_factory=list)
    views: list[ViewInfo] = field(default_factory=list)
    events: list[EventInfo] = field(default_factory=list)
    partitions: list[PartitionInfo] = field(default_factory=list)
    charset_usage: list[CharsetUsage] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Data Profile (from Collector 3)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TableSize:
    table_schema: str
    table_name: str
    table_rows: int
    data_mb: float
    index_mb: float
    total_mb: float


@dataclass(frozen=True)
class BlobColumn:
    table_schema: str
    table_name: str
    column_name: str
    data_type: str


@dataclass
class DataProfile:
    """Data sizing and shape information."""
    table_sizes: list[TableSize] = field(default_factory=list)
    blob_columns: list[BlobColumn] = field(default_factory=list)
    total_data_mb: float = 0.0
    total_index_mb: float = 0.0
    total_rows: int = 0


# ---------------------------------------------------------------------------
# Aurora Metadata (from Collector 4)
# ---------------------------------------------------------------------------

@dataclass
class AuroraMetadata:
    """Aurora-specific server metadata."""
    aurora_version: str | None = None
    mysql_version: str | None = None
    version_comment: str | None = None
    binlog_format: str | None = None
    binlog_row_image: str | None = None
    character_set_server: str | None = None
    collation_server: str | None = None
    transaction_isolation: str | None = None
    sql_mode: str | None = None
    max_connections: int | None = None
    innodb_buffer_pool_size: int | None = None
    lower_case_table_names: int | None = None
    explicit_defaults_for_timestamp: str | None = None


# ---------------------------------------------------------------------------
# Query Patterns (from Collector 2 — optional)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class QueryDigest:
    digest_text: str
    count_star: int
    sum_timer_wait: int
    sum_rows_affected: int
    sum_rows_sent: int
    sum_rows_examined: int


@dataclass(frozen=True)
class QueryIssue:
    digest_text: str
    construct: str  # e.g. "XML_EXTRACT", "GET_LOCK", "XA"
    severity: Severity
    message: str
    suggestion: str


@dataclass
class QueryPatterns:
    """Query pattern analysis from performance_schema."""
    digests: list[QueryDigest] = field(default_factory=list)
    issues: list[QueryIssue] = field(default_factory=list)
    total_digests_analyzed: int = 0


# ---------------------------------------------------------------------------
# Assessment Result (from compatibility analyzer)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Issue:
    type: str  # e.g. "stored_procedure", "trigger", "spatial"
    object_name: str
    severity: Severity
    message: str
    suggestion: str | None = None
    ai_suggestion: str | None = None
    summary: str | None = None
    difficulty: SPDifficulty | None = None
    automation_pct: int | None = None


@dataclass
class AssessmentResult:
    """Compatibility assessment output."""
    blockers: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)
    info: list[Issue] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Scoring Result (from scoring analyzer)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CategoryScore:
    name: str
    score: int
    max_score: int
    deductions: list[str] = field(default_factory=list)


@dataclass
class ScoringResult:
    """Migration readiness scores."""
    schema_compatibility: CategoryScore | None = None
    data_complexity: CategoryScore | None = None
    query_compatibility: CategoryScore | None = None
    procedural_code: CategoryScore | None = None
    operational_readiness: CategoryScore | None = None

    @property
    def overall_score(self) -> int:
        total = 0
        for cat in [
            self.schema_compatibility,
            self.data_complexity,
            self.query_compatibility,
            self.procedural_code,
            self.operational_readiness,
        ]:
            if cat is not None:
                total += cat.score
        return total

    @property
    def max_score(self) -> int:
        return 100

    @property
    def rating(self) -> Rating:
        s = self.overall_score
        if s >= 90:
            return Rating.EXCELLENT
        if s >= 75:
            return Rating.GOOD
        if s >= 50:
            return Rating.MODERATE
        if s >= 25:
            return Rating.CHALLENGING
        return Rating.DIFFICULT

    def density_note(self, checklist: dict) -> str | None:
        """Return a qualitative note when blocker density is high."""
        table_count = checklist.get("table_count", 0)
        if table_count == 0:
            return None
        blocker_objects = (
            checklist.get("stored_procedure_count", 0)
            + checklist.get("function_count", 0)
            + checklist.get("trigger_count", 0)
            + checklist.get("event_count", 0)
        )
        total_objects = (
            table_count
            + checklist.get("view_count", 0)
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


# ---------------------------------------------------------------------------
# Automation Coverage (from automation analyzer)
# ---------------------------------------------------------------------------

@dataclass
class AutomationCoverage:
    """What percentage of migration is automated."""
    fully_automated_pct: float = 0.0
    fully_automated_includes: list[str] = field(default_factory=list)
    ai_assisted_pct: float = 0.0
    ai_assisted_includes: list[str] = field(default_factory=list)
    manual_required_pct: float = 0.0
    manual_required_includes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# AI Stored Procedure Analysis (Phase 2)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SPComplexity:
    loc: int
    cursor_count: int
    dynamic_sql_count: int
    temp_table_count: int
    control_flow_count: int
    nested_calls: int
    transaction_statements: int


@dataclass
class SPAIAnalysis:
    routine_schema: str
    routine_name: str
    routine_type: str  # PROCEDURE or FUNCTION
    complexity: SPComplexity
    difficulty: SPDifficulty
    automation_pct: int | None = None
    summary: str | None = None
    suggested_approach: str | None = None
    equivalent_code: dict[str, str] = field(default_factory=dict)
    tidb_compatible_sql: str | None = None
    warnings: list[str] = field(default_factory=list)
    provider: str | None = None
    model: str | None = None


# ---------------------------------------------------------------------------
# Cost Analysis (Phase 2)
# ---------------------------------------------------------------------------

@dataclass
class CloudWatchMetrics:
    """CloudWatch metric averages and maxima over the last 30 days."""
    averages: dict[str, float] = field(default_factory=dict)
    maximums: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class CostBreakdown:
    compute: float
    storage: float
    io: float


@dataclass(frozen=True)
class TiDBRecommendation:
    tier: str
    nodes: int
    vcpu: int
    ram_gb: int
    storage_gb: int
    monthly_estimate: float


@dataclass
class CostAnalysis:
    aurora_monthly_estimate: float
    tidb_monthly_estimate: float
    savings_pct: float
    aurora_breakdown: CostBreakdown
    tidb_recommendation: TiDBRecommendation
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Scan Report (top-level output)
# ---------------------------------------------------------------------------

@dataclass
class ScanReport:
    """Complete scan report — the output of run_scan()."""
    version: str = "1.0.0"
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    target: str = "cloud"
    source_host: str = ""
    database: str = ""
    schema_inventory: SchemaInventory = field(default_factory=SchemaInventory)
    data_profile: DataProfile = field(default_factory=DataProfile)
    aurora_metadata: AuroraMetadata = field(default_factory=AuroraMetadata)
    query_patterns: QueryPatterns | None = None
    assessment: AssessmentResult = field(default_factory=AssessmentResult)
    scoring: ScoringResult = field(default_factory=ScoringResult)
    automation: AutomationCoverage = field(default_factory=AutomationCoverage)
    sp_analysis: list[SPAIAnalysis] = field(default_factory=list)
    cost_analysis: CostAnalysis | None = None
