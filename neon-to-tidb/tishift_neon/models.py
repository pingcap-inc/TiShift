"""Core data models for TiShift Neon."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Severity(str, Enum):
    BLOCKER = "BLOCKER"
    WARNING = "WARNING"
    COMPATIBLE = "COMPATIBLE"


@dataclass
class ColumnInfo:
    schema_name: str
    table_name: str
    column_name: str
    ordinal_position: int
    data_type: str
    udt_name: str
    is_nullable: bool
    column_default: str | None = None
    character_maximum_length: int | None = None
    numeric_precision: int | None = None
    numeric_scale: int | None = None
    is_identity: bool = False
    is_generated: bool = False


@dataclass
class TableInfo:
    schema_name: str
    table_name: str
    kind: str  # 'r' table, 'p' partitioned, 'v' view, 'm' matview
    persistence: str  # 'p' permanent, 'u' unlogged, 't' temp
    row_estimate: int
    total_bytes: int
    has_rls: bool = False
    has_triggers: bool = False
    columns: list[ColumnInfo] = field(default_factory=list)


@dataclass
class IndexInfo:
    schema_name: str
    table_name: str
    index_name: str
    index_def: str
    index_type: str = "btree"


@dataclass
class ConstraintInfo:
    schema_name: str
    table_name: str
    constraint_name: str
    constraint_type: str  # 'p' PK, 'f' FK, 'u' UNIQUE, 'c' CHECK, 'x' EXCLUDE
    definition: str
    foreign_table: str | None = None


@dataclass
class RoutineInfo:
    schema_name: str
    routine_name: str
    kind: str  # 'f' function, 'p' procedure
    language: str
    definition: str
    is_volatile: bool = True
    is_security_definer: bool = False
    return_type: str = ""


@dataclass
class CustomTypeInfo:
    schema_name: str
    type_name: str
    type_type: str  # 'c' composite, 'e' enum, 'r' range, 'd' domain
    type_detail: str = ""


@dataclass
class SchemaInventory:
    tables: list[TableInfo] = field(default_factory=list)
    columns: list[ColumnInfo] = field(default_factory=list)
    indexes: list[IndexInfo] = field(default_factory=list)
    constraints: list[ConstraintInfo] = field(default_factory=list)
    routines: list[RoutineInfo] = field(default_factory=list)
    custom_types: list[CustomTypeInfo] = field(default_factory=list)
    extensions: list[str] = field(default_factory=list)
    sequences: list[dict] = field(default_factory=list)
    inheritance: list[dict] = field(default_factory=list)
    rls_policies: list[dict] = field(default_factory=list)
    unlogged_tables: list[dict] = field(default_factory=list)


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
