"""Configuration loading for TiShift SQL Server."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field


_ENV_PATTERN = re.compile(r"\$\{([^}]+)\}")


def _expand_env_vars(value: Any) -> Any:
    if isinstance(value, str):
        def replace(match: re.Match[str]) -> str:
            var_name = match.group(1)
            env_value = os.getenv(var_name)
            if env_value is None:
                raise ValueError(f"Environment variable '{var_name}' is referenced but not set")
            return env_value

        return _ENV_PATTERN.sub(replace, value)
    if isinstance(value, dict):
        return {k: _expand_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env_vars(v) for v in value]
    return value


class SourceConfig(BaseModel):
    host: str
    port: int = 1433
    instance: str | None = None
    user: str
    password: str = ""
    database: str = "*"
    auth: Literal["sql", "windows"] = "sql"
    domain: str | None = None
    encrypt: bool = True
    trust_server_certificate: bool = True


TiDBCloudTier = Literal["starter", "essential", "dedicated", "self-hosted"]


class TargetConfig(BaseModel):
    host: str = ""
    port: int = 4000
    user: str = ""
    password: str = ""
    database: str = ""
    tls: bool = True
    tier: TiDBCloudTier = "starter"


class TiDBCloudConfig(BaseModel):
    cluster_id: str = ""
    project_id: str = ""
    import_concurrency: int = 1


class AWSConfig(BaseModel):
    region: str = "us-east-1"
    profile: str | None = None


class AIConfig(BaseModel):
    provider: str = "none"
    api_key: str = ""
    model: str = ""


class OutputConfig(BaseModel):
    dir: str = "./tishift-reports"
    formats: list[str] = Field(default_factory=lambda: ["cli", "json", "html"])


class LoggingConfig(BaseModel):
    level: str = "info"
    file: str | None = "tishift-mssql.log"


class MetricsConfig(BaseModel):
    enabled: bool = False
    port: int = 9090


class TiShiftMSSQLConfig(BaseModel):
    source: SourceConfig
    target: TargetConfig = Field(default_factory=TargetConfig)
    cloud: TiDBCloudConfig = Field(default_factory=TiDBCloudConfig)
    aws: AWSConfig = Field(default_factory=AWSConfig)
    ai: AIConfig = Field(default_factory=AIConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)


def load_config(path: Path) -> TiShiftMSSQLConfig:
    """Load YAML config, expand ${VAR}, and validate with pydantic."""
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError("Config file must be a YAML mapping")
    expanded = _expand_env_vars(raw)
    return TiShiftMSSQLConfig(**expanded)
