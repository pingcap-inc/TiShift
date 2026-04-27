"""Typed data models returned by scan collectors.

These are the contracts between scan, convert, load, check, and sync. Every
core function takes and returns instances of these models — never untyped
dicts.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ColumnInfo(BaseModel):
    schema: str
    table: str
    name: str
    ordinal: int
    data_type: str          # e.g., 'integer', 'uuid', 'jsonb', 'text[]'
    udt_name: str           # e.g., 'int4', 'uuid', 'jsonb', '_text'
    is_nullable: bool
    default: str | None
    is_identity: bool
    is_generated: bool
    generation_expr: str | None
    char_max_length: int | None
    numeric_precision: int | None
    numeric_scale: int | None


class IndexInfo(BaseModel):
    schema: str
    table: str
    name: str
    index_type: str         # 'btree', 'gin', 'gist', 'hash', 'brin'
    is_unique: bool
    is_primary: bool
    definition: str


class TableInfo(BaseModel):
    schema: str
    name: str
    kind: Literal["table", "partitioned", "view", "matview"]
    persistence: Literal["permanent", "unlogged", "temp"]
    row_estimate: int
    total_bytes: int
    table_bytes: int
    index_bytes: int
    has_triggers: bool
    has_rls_enabled: bool
    has_rls_forced: bool


class FunctionInfo(BaseModel):
    schema: str
    name: str
    language: str           # 'plpgsql', 'sql', 'c', etc.
    kind: Literal["function", "procedure", "aggregate", "window"]
    volatility: Literal["immutable", "stable", "volatile"]
    security_definer: bool
    definition: str
    line_count: int
    has_cursor: bool
    has_dynamic_sql: bool
    has_exception_block: bool
    has_returning_clause: bool
    references_auth_helpers: bool
    references_pg_net: bool
    references_extensions_schema: bool


class TriggerInfo(BaseModel):
    schema: str
    table: str
    name: str
    timing: Literal["BEFORE", "AFTER", "INSTEAD OF"]
    event: Literal["INSERT", "UPDATE", "DELETE", "TRUNCATE"]
    action_statement: str


class RLSPolicyFinding(BaseModel):
    """A single row-level-security policy — the Supabase #1 blocker.

    Extracted verbatim from pg_policy; never translated to target DDL. The
    convert phase emits these to 05-rls-rewrite-checklist.md for the
    application / middleware rewrite team.
    """

    schema: str
    table: str
    name: str
    command: Literal["SELECT", "INSERT", "UPDATE", "DELETE", "ALL"]
    is_permissive: bool
    roles: list[str]
    using_expr: str | None
    check_expr: str | None
    references_auth_uid: bool
    references_auth_jwt: bool
    references_subquery_or_join: bool
    complexity: Literal["simple", "moderate", "complex"]


class ExtensionInfo(BaseModel):
    name: str
    version: str
    schema: str
    is_supabase_platform: bool   # pgsodium, supabase_vault, pgjwt, pg_graphql,
                                  # pg_net, pg_cron, wrappers


class PlatformSignals(BaseModel):
    """Supabase service-layer presence. Drives the Application Coupling score."""

    has_auth: bool
    auth_user_count: int
    has_storage: bool
    storage_object_count: int
    has_realtime: bool
    supabase_realtime_slot_active: bool
    has_graphql: bool
    pg_graphql_active: bool
    pg_cron_active_jobs: int
    pg_cron_jobs_with_extension_deps: int
    has_wrappers: bool
    wrappers_foreign_table_count: int
    pgsodium_key_count: int
    vault_secrets_count: int
    pg_net_call_sites: int
    grants_to_anon_count: int
    grants_to_authenticated_count: int
    postgrest_likely_in_use: bool


class ServerMetadata(BaseModel):
    pg_version: str
    pg_version_num: int
    encoding: str
    wal_level: str
    max_connections: int
    is_neon_extension_present: bool   # sanity check — should be False on Supabase
    connection_mode: Literal["direct", "session_pooler"]
    free_tier_ipv6_only_detected: bool


class SchemaInventory(BaseModel):
    scanned_at: datetime
    server: ServerMetadata
    tables: list[TableInfo]
    columns: list[ColumnInfo]
    indexes: list[IndexInfo]
    functions: list[FunctionInfo]
    triggers: list[TriggerInfo]
    rls_policies: list[RLSPolicyFinding]
    extensions: list[ExtensionInfo]
    platform: PlatformSignals


class ScoreBreakdown(BaseModel):
    schema_score: float
    data_score: float
    query_score: float
    code_score: float
    ops_score: float
    total: float
    rating: Literal["EXCELLENT", "GOOD", "MODERATE", "CHALLENGING", "DIFFICULT"]
    deductions: list[str]


class Finding(BaseModel):
    id: str                 # "BLOCKER-1", "WARNING-7", etc.
    severity: Literal["blocker", "warning", "compatible"]
    feature: str
    count: int
    action: str
    evidence: list[dict] = []  # per-occurrence detail


class ExternalWorkItem(BaseModel):
    item: str               # "PostgREST API replacement"
    triggered_by: str       # "grants_to_anon > 0 OR pg_graphql_active"
    description: str
    recommended_sequence: int


class AssessmentResult(BaseModel):
    inventory: SchemaInventory
    findings: list[Finding]
    external_work: list[ExternalWorkItem]
    score: ScoreBreakdown
