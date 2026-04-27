"""Core data models for TiShift Spanner."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Severity(str, Enum):
    BLOCKER = "BLOCKER"
    WARNING = "WARNING"
    COMPATIBLE = "COMPATIBLE"


@dataclass
class ColumnInfo:
    table_name: str
    column_name: str
    ordinal_position: int
    spanner_type: str
    is_nullable: bool
    column_default: str | None = None
    is_generated: bool = False
    generation_expression: str | None = None
    allow_commit_timestamp: bool = False


@dataclass
class TableInfo:
    table_name: str
    parent_table_name: str | None = None
    on_delete_action: str | None = None
    row_deletion_policy: str | None = None
    row_count: int = 0
    total_bytes: int = 0
    columns: list[ColumnInfo] = field(default_factory=list)


@dataclass
class IndexInfo:
    table_name: str
    index_name: str
    index_type: str
    is_unique: bool
    is_null_filtered: bool = False
    parent_table_name: str | None = None
    columns: list[str] = field(default_factory=list)


@dataclass
class ForeignKeyInfo:
    constraint_name: str
    child_table: str
    child_columns: list[str]
    parent_table: str
    parent_columns: list[str]
    delete_rule: str = "NO ACTION"


@dataclass
class SchemaInventory:
    tables: list[TableInfo] = field(default_factory=list)
    indexes: list[IndexInfo] = field(default_factory=list)
    foreign_keys: list[ForeignKeyInfo] = field(default_factory=list)
    views: list[dict] = field(default_factory=list)
    sequences: list[dict] = field(default_factory=list)
    change_streams: list[dict] = field(default_factory=list)
    database_options: dict[str, str] = field(default_factory=dict)


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
