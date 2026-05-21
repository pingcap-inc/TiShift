"""AWS DMS adapter — config emission + status polling.

TiShift does NOT provision DMS resources from scratch. The adapter:
1. Validates customer-supplied ARNs
2. Emits a DMS task config (JSON) for the customer to apply
3. Polls the task via boto3 (loaded lazily — install extra: tishift-mongodb[aws-dms])
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from tishift_mongodb.config import TiShiftConfig


log = logging.getLogger(__name__)


# AWS ARN canonical form: arn:partition:service:region:account-id:resource-type:resource
# DMS-specific: partition ∈ {aws, aws-cn, aws-us-gov}, service = dms
_DMS_ARN_RE = re.compile(
    r"^arn:aws(?:-cn|-us-gov)?:dms:"
    r"[a-z0-9-]+:"          # region
    r"\d{12}:"              # account id
    r"(rep|endpoint|task):" # DMS resource type
    r"[A-Z0-9]+$"           # DMS-issued resource identifier
)


def _validate_dms_arn(arn: str, *, label: str) -> None:
    """Validate ARN format. Empty falls through to the dedicated 'required' check."""
    if not arn:
        return
    if not _DMS_ARN_RE.fullmatch(arn):
        raise ValueError(
            f"{label} {arn!r} does not match DMS ARN format "
            r"arn:aws:dms:<region>:<account>:<rep|endpoint|task>:<id>"
        )


@dataclass
class DMSTaskConfig:
    """Subset of DMS replication-task config we emit."""
    name: str
    replication_instance_arn: str
    source_endpoint_arn: str
    target_endpoint_arn: str
    migration_type: str = "full-load-and-cdc"
    table_mappings: dict = field(default_factory=lambda: {
        "rules": [
            {
                "rule-type": "selection",
                "rule-id": "1",
                "rule-name": "1",
                "object-locator": {
                    "schema-name": "%",
                    "table-name": "%",
                },
                "rule-action": "include",
                "filters": [],
            }
        ]
    })
    replication_task_settings: dict = field(default_factory=lambda: {
        "TargetMetadata": {"SupportLobs": True},
        "FullLoadSettings": {"TargetTablePrepMode": "DO_NOTHING"},
    })

    def to_aws_payload(self) -> dict:
        return {
            "ReplicationTaskIdentifier": self.name,
            "SourceEndpointArn": self.source_endpoint_arn,
            "TargetEndpointArn": self.target_endpoint_arn,
            "ReplicationInstanceArn": self.replication_instance_arn,
            "MigrationType": self.migration_type,
            "TableMappings": json.dumps(self.table_mappings),
            "ReplicationTaskSettings": json.dumps(self.replication_task_settings),
        }


def emit_task_config(
    cfg: TiShiftConfig, *, output_path: str | Path = "tishift-output/dms-task-config.json"
) -> Path:
    """Write a DMS task config the customer can apply via AWS CLI/Console."""
    if not cfg.load.aws_dms.source_endpoint_arn:
        raise ValueError(
            "load.aws_dms.source_endpoint_arn is required for the aws-dms strategy"
        )
    if not cfg.load.aws_dms.target_endpoint_arn:
        raise ValueError(
            "load.aws_dms.target_endpoint_arn is required for the aws-dms strategy"
        )
    if not cfg.load.aws_dms.replication_instance_arn:
        raise ValueError(
            "load.aws_dms.replication_instance_arn is required for the aws-dms strategy"
        )

    _validate_dms_arn(cfg.load.aws_dms.source_endpoint_arn, label="source_endpoint_arn")
    _validate_dms_arn(cfg.load.aws_dms.target_endpoint_arn, label="target_endpoint_arn")
    _validate_dms_arn(cfg.load.aws_dms.replication_instance_arn, label="replication_instance_arn")

    task = DMSTaskConfig(
        name=f"tishift-mongo-to-tidb-{cfg.source.database}",
        replication_instance_arn=cfg.load.aws_dms.replication_instance_arn,
        source_endpoint_arn=cfg.load.aws_dms.source_endpoint_arn,
        target_endpoint_arn=cfg.load.aws_dms.target_endpoint_arn,
    )

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(task.to_aws_payload(), indent=2))
    log.info("Wrote DMS task config to %s", path)
    log.info("Apply via: aws dms create-replication-task --cli-input-json file://%s", path)
    return path


def poll_task_status(task_arn: str, *, region: str = "us-east-1") -> dict:
    """Poll a DMS task. Requires boto3 (install extra: aws-dms)."""
    try:
        import boto3  # type: ignore[import-not-found]
    except ImportError as e:
        raise RuntimeError(
            "boto3 not installed. Install with: pip install tishift-mongodb[aws-dms]"
        ) from e

    client = boto3.client("dms", region_name=region)
    resp = client.describe_replication_tasks(
        Filters=[{"Name": "replication-task-arn", "Values": [task_arn]}]
    )
    if not resp.get("ReplicationTasks"):
        raise RuntimeError(f"DMS task {task_arn} not found")
    task = resp["ReplicationTasks"][0]
    return {
        "status": task.get("Status"),
        "stop_reason": task.get("StopReason"),
        "stats": task.get("ReplicationTaskStats", {}),
    }
