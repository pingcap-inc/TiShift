"""Configuration models. YAML in, validated pydantic models out."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


Topology = Literal["standalone", "replica_set", "sharded", "auto"]
TiDBTier = Literal["starter", "essential", "dedicated", "byoc"]
SchemaPolicy = Literal["auto", "json-mostly", "hybrid", "normalized"]
LoadStrategy = Literal[
    "auto", "direct", "mongodump-lightning", "aws-dms", "datastream",
]
SyncProvider = Literal["direct-changestream", "aws-dms", "datastream", "debezium"]
StorageBackend = Literal["s3", "gs", "azure", "local"]
ResumeTokenStorage = Literal["file", "tidb"]
PolyFieldDecision = Literal[
    "coerce-to-string", "coerce-to-int", "coerce-to-double",
    "coerce-to-decimal", "json", "skip",
]


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False)


class SourceConfig(_Base):
    uri: str
    database: str
    topology_hint: Topology = "auto"
    tls_ca_file: str = ""
    tls_client_cert_key_file: str = ""

    @field_validator("uri")
    @classmethod
    def _uri_shape(cls, v: str) -> str:
        if not (v.startswith("mongodb://") or v.startswith("mongodb+srv://")):
            raise ValueError(
                "source.uri must start with mongodb:// or mongodb+srv://"
            )
        return v


class TargetConfig(_Base):
    host: str
    port: int = 4000
    user: str
    # SecretStr keeps the value out of repr()/str()/JSON dumps. Access at use
    # sites with cfg.target.password.get_secret_value().
    password: SecretStr
    database: str
    tls: bool = True
    tls_ca: str = ""
    tls_insecure_skip_verify: bool = False
    tier: TiDBTier = "dedicated"


class StagingConfig(_Base):
    backend: StorageBackend = "local"
    base_url: str = "file:///tmp/tishift-staging/"
    region: str = ""

    @field_validator("base_url")
    @classmethod
    def _backend_url_prefix(cls, v: str) -> str:
        # Validation deferred to use site so the user can override at runtime
        # without re-validating the whole config; here we just check shape.
        if not re.match(r"^(s3|gs|azure|local|file)://", v):
            raise ValueError(
                "staging.base_url must start with s3://, gs://, azure://, "
                "local://, or file://"
            )
        return v


class MongodumpConfig(_Base):
    parallel_collections: int = 4
    per_shard_parallel: bool = True
    use_oplog: bool = True


class LightningConfig(_Base):
    backend: str = "local"
    pd_addr: str = ""
    sorted_kv_dir: str = "/data/lightning-sort"


class AWSDMSLoadConfig(_Base):
    replication_instance_arn: str = ""
    source_endpoint_arn: str = ""
    target_endpoint_arn: str = ""


class DatastreamLoadConfig(_Base):
    stream_id: str = ""
    region: str = ""
    bigquery_dataset_id: str = "mongo_export"


class LoadConfig(_Base):
    strategy: LoadStrategy = "auto"
    staging: StagingConfig = Field(default_factory=StagingConfig)
    mongodump: MongodumpConfig = Field(default_factory=MongodumpConfig)
    lightning: LightningConfig = Field(default_factory=LightningConfig)
    aws_dms: AWSDMSLoadConfig = Field(default_factory=AWSDMSLoadConfig)
    datastream: DatastreamLoadConfig = Field(default_factory=DatastreamLoadConfig)


class ScanConfig(_Base):
    sample_size_per_collection: int = 200
    full_scan_threshold_docs: int = 5000
    subdocument_max_depth: int = 10
    inventory_aggregations: bool = True
    inventory_indexes: bool = True

    @field_validator("sample_size_per_collection", "full_scan_threshold_docs",
                     "subdocument_max_depth")
    @classmethod
    def positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("must be > 0")
        return v


class PolyFieldOverride(_Base):
    decision: PolyFieldDecision


class PerCollectionConvertOverride(_Base):
    policy: SchemaPolicy | None = None
    flatten_columns: list[str] = Field(default_factory=list)
    json_columns: list[str] = Field(default_factory=list)
    poly_fields: dict[str, PolyFieldOverride] = Field(default_factory=dict)


class AggregationAdvisorConfig(_Base):
    enabled: bool = True
    completion_fn: str = ""


class ConvertConfig(_Base):
    schema_policy_default: SchemaPolicy = "auto"
    preserve_object_ids: bool = True
    emit_foreign_keys: bool = True
    aggregation_advisor: AggregationAdvisorConfig = Field(default_factory=AggregationAdvisorConfig)
    per_collection: dict[str, PerCollectionConvertOverride] = Field(default_factory=dict)


class CheckConfig(_Base):
    sample_size: int = 1000


class AWSDMSSyncConfig(_Base):
    task_arn: str = ""


class DatastreamSyncConfig(_Base):
    stream_id: str = ""
    bigquery_dataset_id: str = "mongo_export"
    polling_interval_seconds: int = 30


class DebeziumSyncConfig(_Base):
    bootstrap_servers: str = ""
    source_connector_name: str = ""
    jdbc_sink_connector_name: str = ""


class SyncPartition(_Base):
    name: str
    collections: list[str] = Field(default_factory=list)


class SyncConfig(_Base):
    enabled: bool = False
    provider: SyncProvider = "direct-changestream"
    resume_token_storage: ResumeTokenStorage = "file"
    resume_token_table: str = "_tishift_cdc_state"
    partitions: list[SyncPartition] = Field(default_factory=list)
    aws_dms: AWSDMSSyncConfig = Field(default_factory=AWSDMSSyncConfig)
    datastream: DatastreamSyncConfig = Field(default_factory=DatastreamSyncConfig)
    debezium: DebeziumSyncConfig = Field(default_factory=DebeziumSyncConfig)


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

    Strict-by-default behavior — silent empty substitution hides config errors,
    produces empty passwords or unset paths, and degrades to confusing downstream
    failures.
    """


def _interpolate_env(value: str) -> str:
    """Replace ${VAR} with environment variable values. Strict: missing vars raise."""
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
            f"config references environment variable(s) that are not set: {unique}"
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
    """Load and validate a tishift-mongodb.yaml file."""
    text = Path(path).read_text(encoding="utf-8")
    raw = yaml.safe_load(text)
    if not isinstance(raw, dict):
        raise ValueError(f"Config at {path} must be a YAML mapping.")
    interpolated = _interpolate_tree(raw)
    return TiShiftConfig.model_validate(interpolated)
