"""Configuration loading and validation for TiShift Neon."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field


class SourceConfig(BaseModel):
    host: str
    port: int = 5432
    user: str
    password: str = ""
    database: str
    sslmode: str = "require"


class TargetConfig(BaseModel):
    host: str
    port: int = 4000
    user: str
    password: str = ""
    database: str
    tls: bool = True
    tier: str = "starter"


class AIConfig(BaseModel):
    provider: str = "none"
    api_key: str = ""
    model: str = ""


class OutputConfig(BaseModel):
    dir: str = "./tishift-reports"
    formats: list[str] = Field(default_factory=lambda: ["cli", "json"])


class LoggingConfig(BaseModel):
    level: str = "info"
    file: str = "tishift-neon.log"


class MetricsConfig(BaseModel):
    enabled: bool = False
    port: int = 9090


class TiShiftNeonConfig(BaseModel):
    source: SourceConfig
    target: TargetConfig
    ai: AIConfig = Field(default_factory=AIConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)


def _resolve_env_vars(value: str) -> str:
    """Resolve ${ENV_VAR} references in a string."""
    if value.startswith("${") and value.endswith("}"):
        env_name = value[2:-1]
        return os.environ.get(env_name, value)
    return value


def load_config(path: Path) -> TiShiftNeonConfig:
    """Load and validate configuration from a YAML file."""
    import yaml

    with path.open() as f:
        raw = yaml.safe_load(f)

    # Resolve environment variables in string values
    def resolve(obj: dict | list | str | int | float | bool | None) -> dict | list | str | int | float | bool | None:
        if isinstance(obj, dict):
            return {k: resolve(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [resolve(v) for v in obj]
        if isinstance(obj, str):
            return _resolve_env_vars(obj)
        return obj

    resolved = resolve(raw)
    return TiShiftNeonConfig(**resolved)
