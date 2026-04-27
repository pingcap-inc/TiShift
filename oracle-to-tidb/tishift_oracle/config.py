"""Configuration model for TiShift Oracle."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator


class SourceConfig(BaseModel):
    model_config = {"protected_namespaces": (), "populate_by_name": True}

    host: str = "localhost"
    port: int = 1521
    service_name: str = ""
    connection_string: str = ""
    user: str = ""
    password: str = ""
    schema: str = "*"
    mode: Literal["thin", "thick"] = "thin"
    wallet_location: str = ""

    @model_validator(mode="after")
    def resolve_env_vars(self) -> "SourceConfig":
        if self.password.startswith("${") and self.password.endswith("}"):
            env_key = self.password[2:-1]
            self.password = os.environ.get(env_key, "")
        return self


class TargetConfig(BaseModel):
    host: str = "localhost"
    port: int = 4000
    user: str = "root"
    password: str = ""
    database: str = ""
    tls: bool = True
    tier: Literal["starter", "essential", "dedicated", "self-hosted"] = "starter"

    @model_validator(mode="after")
    def resolve_env_vars(self) -> "TargetConfig":
        if self.password.startswith("${") and self.password.endswith("}"):
            env_key = self.password[2:-1]
            self.password = os.environ.get(env_key, "")
        return self


class AIConfig(BaseModel):
    provider: Literal["openai", "none"] = "none"
    api_key: str = ""
    model: str = ""


class OutputConfig(BaseModel):
    dir: Path = Path("./tishift-reports")
    formats: list[str] = Field(default_factory=lambda: ["cli", "json", "html"])


class LoggingConfig(BaseModel):
    level: str = "info"
    file: str = "tishift-oracle.log"


class MetricsConfig(BaseModel):
    enabled: bool = False
    port: int = 9090


class TiShiftOracleConfig(BaseModel):
    source: SourceConfig = Field(default_factory=SourceConfig)
    target: TargetConfig = Field(default_factory=TargetConfig)
    ai: AIConfig = Field(default_factory=AIConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)


def load_config(path: Path) -> TiShiftOracleConfig:
    """Load and validate configuration from a YAML file."""
    with open(path) as f:
        raw = yaml.safe_load(f)
    return TiShiftOracleConfig.model_validate(raw or {})
