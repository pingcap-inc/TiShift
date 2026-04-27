"""Config loading and validation.

Config lives in a YAML file with env-var interpolation for secrets. The schema
filter hardcodes the 14 Supabase-internal schemas that must never be migrated:
scan queries apply it at the SQL WHERE clause; load commands refuse to run
with a wildcard schema filter.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator


SUPABASE_INTERNAL_SCHEMAS: frozenset[str] = frozenset(
    {
        "auth",
        "storage",
        "realtime",
        "_realtime",
        "extensions",
        "graphql",
        "graphql_public",
        "supabase_migrations",
        "vault",
        "pgsodium",
        "pgsodium_masks",
        "net",
        "pgbouncer",
        "_analytics",
    }
)


class SourceConfig(BaseModel):
    host: str
    port: int = 5432
    user: str
    password: str
    database: str = "postgres"
    sslmode: str = "require"
    schema_include: list[str] = Field(default_factory=lambda: ["public"])
    schema_exclude: list[str] = Field(
        default_factory=lambda: sorted(SUPABASE_INTERNAL_SCHEMAS)
    )

    @field_validator("port")
    @classmethod
    def reject_transaction_mode_port(cls, v: int) -> int:
        if v == 6543:
            raise ValueError(
                "port 6543 (Supavisor transaction mode) is refused — it breaks pg_dump, "
                "prepared statements, and logical replication. Use port 5432 on the "
                "session-mode pooler host or the direct endpoint."
            )
        return v

    @field_validator("schema_include")
    @classmethod
    def reject_wildcard(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("schema_include cannot be empty")
        if "*" in v:
            raise ValueError(
                "wildcard schema_include is refused. Supabase projects have 14 "
                "platform-internal schemas (auth, storage, realtime, vault, pgsodium, "
                "etc.) that must never be migrated. List user schemas explicitly."
            )
        overlap = set(v) & SUPABASE_INTERNAL_SCHEMAS
        if overlap:
            raise ValueError(
                f"schema_include contains Supabase-internal schemas: {sorted(overlap)}. "
                "These hold platform state (auth users, storage metadata, encryption "
                "keys, Realtime subscriptions) and cannot be migrated."
            )
        return v


class TargetConfig(BaseModel):
    host: str
    port: int = 4000
    user: str
    password: str
    database: str
    tls: bool = True
    tier: Literal["starter", "essential", "dedicated", "self-hosted"] = "starter"


class CloudConfig(BaseModel):
    cluster_id: str | None = None
    project_id: str | None = None


class AWSConfig(BaseModel):
    region: str = "us-east-1"
    profile: str = "default"


class AIConfig(BaseModel):
    provider: Literal["none", "openai"] = "none"
    api_key: str | None = None
    model: str = ""


class OutputConfig(BaseModel):
    dir: Path = Path("./tishift-reports")
    formats: list[Literal["cli", "json", "html", "pdf"]] = Field(
        default_factory=lambda: ["cli", "json"]
    )


class LoggingConfig(BaseModel):
    level: Literal["debug", "info", "warning", "error"] = "info"
    file: str | None = None


class MetricsConfig(BaseModel):
    enabled: bool = False
    port: int = 9090


class SyncConfig(BaseModel):
    slot_name: str = "tishift_migration"
    publication_name: str = "tishift_pub"
    replication_host: str | None = None
    replication_port: int = 5432

    @field_validator("slot_name")
    @classmethod
    def reject_realtime_slot(cls, v: str) -> str:
        if v.startswith("supabase_realtime") or v.startswith("realtime"):
            raise ValueError(
                f"slot_name '{v}' collides with Supabase Realtime's own slot. "
                "Pick a distinct name (default: 'tishift_migration')."
            )
        return v


class Config(BaseModel):
    source: SourceConfig
    target: TargetConfig
    cloud: CloudConfig = Field(default_factory=CloudConfig)
    aws: AWSConfig = Field(default_factory=AWSConfig)
    ai: AIConfig = Field(default_factory=AIConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)
    sync: SyncConfig = Field(default_factory=SyncConfig)


_ENV_VAR_PATTERN = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")


def _interpolate_env(raw: str) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        value = os.environ.get(name)
        if value is None:
            raise KeyError(f"environment variable {name} is not set")
        return value

    return _ENV_VAR_PATTERN.sub(replace, raw)


def load_config(path: Path) -> Config:
    """Load and validate a tishift-supabase config file.

    Expands ${ENV_VAR} references at load time. Raises pydantic.ValidationError
    on schema / invariant violations (including transaction-pooler port,
    wildcard schema filter, Realtime-slot-name collision).
    """
    raw = path.read_text()
    interpolated = _interpolate_env(raw)
    data = yaml.safe_load(interpolated)
    return Config.model_validate(data)
