"""AWS DMS sync adapter — polls an existing customer DMS task."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass


log = logging.getLogger(__name__)


@dataclass
class DMSSyncStatus:
    status: str
    lag_seconds: int
    stop_reason: str


def poll_dms_sync(task_arn: str, *, region: str = "us-east-1") -> DMSSyncStatus:
    """One-shot status read. Returns lag in seconds if available."""
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
    stats = task.get("ReplicationTaskStats", {})
    lag = int(stats.get("ElapsedTimeMillis", 0) / 1000)
    return DMSSyncStatus(
        status=task.get("Status", "unknown"),
        lag_seconds=lag,
        stop_reason=task.get("StopReason", ""),
    )


def poll_until_caught_up(
    task_arn: str, *, region: str = "us-east-1",
    target_lag_seconds: int = 5, poll_interval: int = 30,
) -> DMSSyncStatus:
    """Block until lag < target. Returns last status."""
    while True:
        status = poll_dms_sync(task_arn, region=region)
        log.info("DMS sync: status=%s lag=%ds", status.status, status.lag_seconds)
        if status.lag_seconds < target_lag_seconds:
            return status
        time.sleep(poll_interval)
