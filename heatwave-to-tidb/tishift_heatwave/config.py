"""Configuration loading and validation for TiShift HeatWave."""

from __future__ import annotations

import os
import re
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

VALID_TIERS = ("starter", "essential", "dedicated", "self-hosted")


class SourceConfig(BaseModel):
    host: str
    port: int = 3306
    user: str
    password: str = ""
    database: str
    tls: bool = True
    # CA certificate for TLS verification. HeatWave uses a self-signed CA —
    # download it from the console (DB System -> Connect) or extract it with
    # `openssl s_client -starttls mysql -showcerts`. Empty means system CAs.
    ssl_ca: str = ""
    # HeatWave DB Systems live in a private VCN subnet. Informational only for
    # now — documents the tunnel host/user in the config file; no command
    # reads or prints it yet.
    bastion_host: str = ""
    bastion_user: str = ""


class TargetConfig(BaseModel):
    host: str
    port: int = 4000
    user: str
    password: str = ""
    database: str
    tls: bool = True
    ssl_ca: str = ""
    tier: str = "starter"

    @field_validator("tier")
    @classmethod
    def _normalize_tier(cls, value: str) -> str:
        tier = value.strip().lower()
        if tier not in VALID_TIERS:
            raise ValueError(f"tier must be one of {', '.join(VALID_TIERS)}; got {value!r}")
        return tier


class CloudConfig(BaseModel):
    """TiDB Cloud settings (required for Starter/Essential ticloud CLI import)."""

    cluster_id: str = ""
    project_id: str = ""


class AIConfig(BaseModel):
    provider: str = "none"
    api_key: str = ""
    model: str = ""


class OutputConfig(BaseModel):
    dir: str = "./tishift-reports"
    formats: list[str] = Field(default_factory=lambda: ["cli", "json"])


class LoggingConfig(BaseModel):
    level: str = "info"
    file: str = "tishift-heatwave.log"


class MetricsConfig(BaseModel):
    enabled: bool = False
    port: int = 9090


class TiShiftHeatWaveConfig(BaseModel):
    source: SourceConfig
    target: TargetConfig
    cloud: CloudConfig = Field(default_factory=CloudConfig)
    ai: AIConfig = Field(default_factory=AIConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)


_ENV_REF = re.compile(r"\$\{([^}]+)\}")


def _resolve_env_vars(value: str) -> str:
    """Resolve ${ENV_VAR} references in a string, including embedded ones
    (e.g. ``prefix-${REGION}``). Unset variables are left as-is so the
    resulting connection error names the missing placeholder."""
    return _ENV_REF.sub(lambda m: os.environ.get(m.group(1), m.group(0)), value)


def load_config(path: Path) -> TiShiftHeatWaveConfig:
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
    return TiShiftHeatWaveConfig(**resolved)
