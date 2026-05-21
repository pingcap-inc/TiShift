"""Configuration models. YAML in, validated pydantic models out."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


FirestoreMode = Literal["native", "datastore"]
TiDBTier = Literal["starter", "essential", "dedicated", "byoc"]
SchemaPolicy = Literal["auto", "json-mostly", "hybrid", "normalized"]
LoadStrategy = Literal[
    "auto",
    "direct",
    "dataflow-cloudimport",
    "dataflow-lightning",
    "dataflow-lightning-sharded",
]
GeoPointMapping = Literal["lat_lng_columns", "json"]
PolyFieldDecision = Literal["coerce-to-string", "coerce-to-double", "json", "skip"]


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False)


class StagingConfig(_Base):
    gcs_bucket: str
    gcs_prefix: str = "firestore-export/"
    region: str


class SourceConfig(_Base):
    project_id: str
    database_id: str = "(default)"
    service_account_key: str = ""
    mode: FirestoreMode = "native"
    staging: StagingConfig


class TargetConfig(_Base):
    host: str
    port: int = 4000
    user: str
    # SecretStr keeps the value out of repr(), str(), pydantic error messages,
    # and JSON dumps unless explicitly unwrapped via .get_secret_value().
    # Access at use sites with cfg.target.password.get_secret_value().
    password: SecretStr
    database: str
    tls: bool = True

    # Path to a PEM-format CA bundle for verifying the TiDB server certificate.
    # Strongly recommended for production. If unset and tls=True, the system
    # default CA store is used (may not include TiDB Cloud's CA on some images).
    tls_ca: str = ""

    # Set to True only for explicitly insecure local development against an
    # untrusted self-signed cert. Production deployments MUST leave this False.
    tls_insecure_skip_verify: bool = False

    tier: TiDBTier = "byoc"


class ScanConfig(_Base):
    sample_size_per_collection: int = 200
    full_scan_threshold_docs: int = 5000
    subcollection_max_depth: int = 10
    parent_sample_for_subcollections: int = 100

    @field_validator("sample_size_per_collection", "full_scan_threshold_docs",
                     "subcollection_max_depth", "parent_sample_for_subcollections")
    @classmethod
    def positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("must be > 0")
        return v


class PerCollectionConvertOverride(_Base):
    policy: SchemaPolicy | None = None
    flatten_columns: list[str] = Field(default_factory=list)
    json_columns: list[str] = Field(default_factory=list)
    geopoint_mapping: dict[str, GeoPointMapping] = Field(default_factory=dict)
    poly_fields: dict[str, "PolyFieldOverride"] = Field(default_factory=dict)


class PolyFieldOverride(_Base):
    decision: PolyFieldDecision


PerCollectionConvertOverride.model_rebuild()


class ConvertConfig(_Base):
    schema_policy_default: SchemaPolicy = "auto"
    preserve_document_ids: bool = True
    emit_foreign_keys: bool = True
    per_collection: dict[str, PerCollectionConvertOverride] = Field(default_factory=dict)


class DataflowConfig(_Base):
    region: str = "us-central1"
    machine_type: str = "n2-standard-4"
    max_workers: int = 200
    autoscaling: str = "THROUGHPUT_BASED"
    network: str = "default"
    subnetwork: str = ""
    use_public_ips: bool = False


class LightningConfig(_Base):
    backend: str = "local"
    pd_addr: str = ""
    sorted_kv_dir: str = "/data/lightning-sort"


class LoadConfig(_Base):
    strategy: LoadStrategy = "auto"
    dataflow: DataflowConfig = Field(default_factory=DataflowConfig)
    lightning: LightningConfig = Field(default_factory=LightningConfig)
    shard_groups: list[list[str]] = Field(default_factory=list)


class CheckConfig(_Base):
    sample_size: int = 1000


class BigQueryConfig(_Base):
    project_id: str = ""
    dataset_id: str = "firestore_export"
    polling_interval_seconds: int = 30


class SyncConfig(_Base):
    enabled: bool = False
    bigquery: BigQueryConfig = Field(default_factory=BigQueryConfig)


class LoggingConfig(_Base):
    level: str = "INFO"
    format: Literal["json", "text"] = "json"
    audit_log_path: str = "./tishift-output/audit.jsonl"


class MetricsConfig(_Base):
    enabled: bool = True
    port: int = 9090


class TiShiftConfig(_Base):
    source: SourceConfig
    target: TargetConfig
    scan: ScanConfig = Field(default_factory=ScanConfig)
    convert: ConvertConfig = Field(default_factory=ConvertConfig)
    load: LoadConfig = Field(default_factory=LoadConfig)
    check: CheckConfig = Field(default_factory=CheckConfig)
    sync: SyncConfig = Field(default_factory=SyncConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)


_ENV_VAR_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")


class EnvVarMissingError(RuntimeError):
    """Raised when a ${VAR} in the config has no corresponding environment variable.

    Strict-by-default behavior — silently substituting empty strings for missing
    env vars hides config errors, can produce empty passwords / empty service
    account paths, and degrades to confusing downstream failures.
    """


def _interpolate_env(value: str) -> str:
    """Replace ${VAR} with environment variable values.

    Raises EnvVarMissingError if any referenced env var is unset. Strict by
    design: an unset password env var should fail loudly at config load, not
    silently produce an empty-string credential.
    """
    missing: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        var_name = match.group(1)
        if var_name not in os.environ:
            missing.append(var_name)
            return ""
        return os.environ[var_name]

    result = _ENV_VAR_PATTERN.sub(_replace, value)
    if missing:
        unique = sorted(set(missing))
        raise EnvVarMissingError(
            f"config references environment variable(s) that are not set: {unique}. "
            "Export them or change the config to not reference them."
        )
    return result


def _interpolate_tree(obj: object) -> object:
    if isinstance(obj, str):
        return _interpolate_env(obj)
    if isinstance(obj, dict):
        return {k: _interpolate_tree(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_interpolate_tree(item) for item in obj]
    return obj


def load_config(path: str | Path) -> TiShiftConfig:
    """Load and validate a tishift-firestore.yaml file.

    Environment variables referenced as ${VAR} in string values are
    interpolated from os.environ. Missing vars become empty strings (caught
    later by pydantic validation where required).
    """
    text = Path(path).read_text(encoding="utf-8")
    raw = yaml.safe_load(text)
    if not isinstance(raw, dict):
        raise ValueError(f"Config at {path} must be a YAML mapping at the top level.")
    interpolated = _interpolate_tree(raw)
    return TiShiftConfig.model_validate(interpolated)
