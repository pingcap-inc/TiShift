"""Data models for TiShift SQL Server scanner."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Any


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


class SPDifficulty(str, Enum):
    TRIVIAL = "trivial"
    SIMPLE = "simple"
    MODERATE = "moderate"
    COMPLEX = "complex"
    REQUIRES_REDESIGN = "requires_redesign"


@dataclass(frozen=True)
class TableInfo:
    schema_name: str
    table_name: str
    row_count: int
    total_mb: float
    used_mb: float
    is_memory_optimized: bool
    is_temporal: bool
    is_heap: bool


@dataclass(frozen=True)
class ColumnInfo:
    schema_name: str
    table_name: str
    column_name: str
    ordinal_position: int
    data_type: str
    max_length: int | None
    precision: int | None
    scale: int | None
    is_nullable: bool
    is_identity: bool
    is_computed: bool
    collation_name: str | None
    computed_definition: str | None
    default_definition: str | None
    is_filestream: bool = False


@dataclass(frozen=True)
class IndexInfo:
    schema_name: str
    table_name: str
    index_name: str
    index_type: str
    is_unique: bool
    is_primary_key: bool
    columns: str
    included_columns: str
    filter_definition: str | None


@dataclass(frozen=True)
class ForeignKeyInfo:
    schema_name: str
    table_name: str
    fk_name: str
    referenced_schema_name: str
    referenced_table_name: str
    columns: str
    referenced_columns: str
    delete_action: str
    update_action: str


@dataclass(frozen=True)
class RoutineInfo:
    schema_name: str
    routine_name: str
    routine_type: str
    definition: str | None
    is_clr: bool
    assembly_name: str | None


@dataclass(frozen=True)
class TriggerInfo:
    schema_name: str
    trigger_name: str
    table_name: str | None
    is_instead_of: bool
    is_clr: bool
    definition: str | None


@dataclass(frozen=True)
class ViewInfo:
    schema_name: str
    view_name: str
    definition: str | None
    is_indexed: bool
    with_schemabinding: bool


@dataclass(frozen=True)
class AssemblyInfo:
    assembly_name: str
    permission_set: str
    clr_name: str | None


@dataclass(frozen=True)
class LinkedServerInfo:
    server_name: str
    product: str | None
    provider: str | None
    data_source: str | None


@dataclass(frozen=True)
class AgentJobInfo:
    job_name: str
    enabled: bool
    description: str | None


@dataclass(frozen=True)
class FeatureUsage:
    pattern_name: str
    object_type: str
    object_name: str
    matched_text: str


@dataclass
class SchemaInventory:
    tables: list[TableInfo] = field(default_factory=list)
    columns: list[ColumnInfo] = field(default_factory=list)
    indexes: list[IndexInfo] = field(default_factory=list)
    foreign_keys: list[ForeignKeyInfo] = field(default_factory=list)
    routines: list[RoutineInfo] = field(default_factory=list)
    triggers: list[TriggerInfo] = field(default_factory=list)
    views: list[ViewInfo] = field(default_factory=list)
    assemblies: list[AssemblyInfo] = field(default_factory=list)
    linked_servers: list[LinkedServerInfo] = field(default_factory=list)
    agent_jobs: list[AgentJobInfo] = field(default_factory=list)
    partition_functions: list[str] = field(default_factory=list)
    schemas: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TableSize:
    schema_name: str
    table_name: str
    row_count: int
    reserved_mb: float
    data_mb: float
    index_mb: float


@dataclass
class DataProfile:
    table_sizes: list[TableSize] = field(default_factory=list)
    total_rows: int = 0
    total_data_mb: float = 0.0
    total_index_mb: float = 0.0


@dataclass
class SQLServerMetadata:
    version: str | None = None
    edition: str | None = None
    product_version: str | None = None
    engine_edition: int | None = None
    cdc_enabled: bool = False
    db_collation: str | None = None
    db_size_mb: float = 0.0
    configuration: dict[str, str] = field(default_factory=dict)
    has_ssis: bool = False
    cpu_count: int | None = None
    auth_mode: str = "sql"


@dataclass
class FeatureScanResult:
    usages: list[FeatureUsage] = field(default_factory=list)

    def has_pattern(self, pattern_name: str) -> bool:
        return any(u.pattern_name == pattern_name for u in self.usages)


@dataclass(frozen=True)
class QueryIssue:
    query_snippet: str
    construct: str
    severity: Severity
    message: str
    transpile_ok: bool


@dataclass
class QueryPatterns:
    total_queries_analyzed: int = 0
    transpile_failures: int = 0
    issues: list[QueryIssue] = field(default_factory=list)


@dataclass(frozen=True)
class Issue:
    type: str
    object_name: str
    severity: Severity
    message: str
    suggestion: str | None = None
    difficulty: SPDifficulty | None = None
    automation_pct: int | None = None


@dataclass
class AssessmentResult:
    blockers: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)
    info: list[Issue] = field(default_factory=list)


@dataclass(frozen=True)
class CategoryScore:
    name: str
    score: int
    max_score: int
    deductions: list[str] = field(default_factory=list)


@dataclass
class ScoringResult:
    schema_compatibility: CategoryScore | None = None
    code_portability: CategoryScore | None = None
    query_compatibility: CategoryScore | None = None
    data_complexity: CategoryScore | None = None
    operational_readiness: CategoryScore | None = None

    @property
    def overall_score(self) -> int:
        categories = [
            self.schema_compatibility,
            self.code_portability,
            self.query_compatibility,
            self.data_complexity,
            self.operational_readiness,
        ]
        return sum(c.score for c in categories if c is not None)

    @property
    def rating(self) -> Rating:
        score = self.overall_score
        if score >= 90:
            return Rating.EXCELLENT
        if score >= 75:
            return Rating.GOOD
        if score >= 50:
            return Rating.MODERATE
        if score >= 25:
            return Rating.CHALLENGING
        return Rating.DIFFICULT

    def density_note(self, checklist: dict) -> str | None:
        """Return a qualitative note when blocker density is high."""
        table_count = checklist.get("table_count", 0)
        if table_count == 0:
            return None
        blocker_objects = (
            checklist.get("stored_procedure_count", 0)
            + checklist.get("trigger_count", 0)
            + checklist.get("assembly_count", 0)
            + checklist.get("linked_server_count", 0)
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


@dataclass
class AutomationCoverage:
    fully_automated_pct: float = 0.0
    fully_automated_includes: list[str] = field(default_factory=list)
    ai_assisted_pct: float = 0.0
    ai_assisted_includes: list[str] = field(default_factory=list)
    manual_required_pct: float = 0.0
    manual_required_includes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TierFitResult:
    tier: str
    fits: bool
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class CostEstimate:
    estimated_monthly_sqlserver_license_usd: float = 0.0
    estimated_monthly_tidb_cloud_usd: float = 0.0
    recommended_tier: str = ""
    assumptions: list[str] = field(default_factory=list)


@dataclass
class ScanReport:
    version: str = "0.1.0"
    generated_at: datetime = field(default_factory=datetime.utcnow)
    source_host: str = ""
    database: str = "*"
    schema_inventory: SchemaInventory = field(default_factory=SchemaInventory)
    data_profile: DataProfile = field(default_factory=DataProfile)
    sqlserver_metadata: SQLServerMetadata = field(default_factory=SQLServerMetadata)
    feature_scan: FeatureScanResult = field(default_factory=FeatureScanResult)
    query_patterns: QueryPatterns | None = None
    assessment: AssessmentResult = field(default_factory=AssessmentResult)
    scoring: ScoringResult = field(default_factory=ScoringResult)
    automation: AutomationCoverage = field(default_factory=AutomationCoverage)
    cost_estimate: CostEstimate | None = None
    target_tier: str = "starter"
    tier_fit: list[TierFitResult] = field(default_factory=list)


def to_dict(value: Any) -> Any:
    """Convert dataclass/enums into JSON-safe nested structures."""
    if is_dataclass(value):
        return {k: to_dict(v) for k, v in asdict(value).items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): to_dict(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_dict(v) for v in value]
    return value
