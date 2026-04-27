"""Configuration loading and validation.

Reads tishift.yaml, expands environment variables, validates with pydantic.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator


def _expand_env_vars(value: Any) -> Any:
    """Recursively expand ${ENV_VAR} references in config values."""
    if isinstance(value, str):
        pattern = re.compile(r"\$\{([^}]+)\}")
        def _replace(match: re.Match[str]) -> str:
            var_name = match.group(1)
            env_val = os.environ.get(var_name)
            if env_val is None:
                raise ValueError(
                    f"Environment variable '{var_name}' is referenced in config but not set"
                )
            return env_val
        return pattern.sub(_replace, value)
    if isinstance(value, dict):
        return {k: _expand_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env_vars(item) for item in value]
    return value


class SourceConfig(BaseModel):
    host: str
    port: int = 3306
    user: str
    password: str = ""
    database: str = "*"
    tls: bool = False


class TargetConfig(BaseModel):
    host: str = ""
    port: int = 4000
    user: str = ""
    password: str = ""
    database: str = ""
    tls: bool = False


class AWSConfig(BaseModel):
    region: str = "us-east-1"
    profile: str | None = None
    db_instance_identifier: str | None = None
    db_cluster_identifier: str | None = None


class AIConfig(BaseModel):
    provider: str = "none"
    api_key: str = ""
    model: str = "gpt-4o"


class OutputConfig(BaseModel):
    dir: str = "./tishift-reports"
    formats: list[str] = Field(default_factory=lambda: ["cli", "json", "html"])


class LoggingConfig(BaseModel):
    level: str = "info"
    file: str | None = None


class MetricsConfig(BaseModel):
    enabled: bool = False
    port: int = 9090


class TiShiftConfig(BaseModel):
    """Top-level configuration for TiShift."""
    source: SourceConfig
    target: TargetConfig = Field(default_factory=TargetConfig)
    aws: AWSConfig = Field(default_factory=AWSConfig)
    ai: AIConfig = Field(default_factory=AIConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)


def load_config(path: Path) -> TiShiftConfig:
    """Load and validate tishift.yaml configuration.

    Environment variable references (${VAR_NAME}) are expanded before
    validation.  Raises ValueError if a referenced env var is not set,
    or if the config file is invalid.
    """
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"Config file must be a YAML mapping, got {type(raw).__name__}")

    expanded = _expand_env_vars(raw)
    return TiShiftConfig(**expanded)
