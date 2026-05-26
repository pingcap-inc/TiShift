"""Tests for the AWS DMS task-config emitter."""

from __future__ import annotations

import json

import pytest

from tishift_mongodb.config import (
    AWSDMSLoadConfig,
    LoadConfig,
    SourceConfig,
    TargetConfig,
    TiShiftConfig,
)
from tishift_mongodb.core.load.dms_runner import emit_task_config


def _cfg(dms: AWSDMSLoadConfig) -> TiShiftConfig:
    return TiShiftConfig(
        source=SourceConfig(uri="mongodb://h/d", database="myapp"),
        target=TargetConfig(
            host="h", port=4000, user="u",
            password="pw",  # type: ignore[arg-type]
            database="d", tls=True, tier="byoc",
        ),
        load=LoadConfig(strategy="aws-dms", aws_dms=dms),
    )


def test_emit_with_all_arns(tmp_path):
    dms = AWSDMSLoadConfig(
        replication_instance_arn="arn:aws:dms:us-east-1:123456789012:rep:ABC123",
        source_endpoint_arn="arn:aws:dms:us-east-1:123456789012:endpoint:SRCXYZ",
        target_endpoint_arn="arn:aws:dms:us-east-1:123456789012:endpoint:TGTXYZ",
    )
    cfg = _cfg(dms)
    path = emit_task_config(cfg, output_path=tmp_path / "dms.json")
    data = json.loads(path.read_text())
    assert "ReplicationTaskIdentifier" in data
    assert "myapp" in data["ReplicationTaskIdentifier"]
    assert data["SourceEndpointArn"] == dms.source_endpoint_arn


def test_emit_missing_source_arn_raises(tmp_path):
    dms = AWSDMSLoadConfig(
        replication_instance_arn="arn:aws:dms:us-east-1:123456789012:rep:R",
        source_endpoint_arn="",
        target_endpoint_arn="arn:aws:dms:us-east-1:123456789012:endpoint:T",
    )
    with pytest.raises(ValueError, match="source_endpoint_arn"):
        emit_task_config(_cfg(dms), output_path=tmp_path / "dms.json")


def test_emit_missing_target_arn_raises(tmp_path):
    dms = AWSDMSLoadConfig(
        replication_instance_arn="arn:aws:dms:us-east-1:123456789012:rep:R",
        source_endpoint_arn="arn:aws:dms:us-east-1:123456789012:endpoint:S",
        target_endpoint_arn="",
    )
    with pytest.raises(ValueError, match="target_endpoint_arn"):
        emit_task_config(_cfg(dms), output_path=tmp_path / "dms.json")


def test_emit_invalid_arn_format_raises(tmp_path):
    """Malformed ARNs are rejected at config-emit time instead of being
    silently passed through to AWS DMS to fail later."""
    dms = AWSDMSLoadConfig(
        replication_instance_arn="not-an-arn",
        source_endpoint_arn="arn:aws:dms:us-east-1:123456789012:endpoint:S",
        target_endpoint_arn="arn:aws:dms:us-east-1:123456789012:endpoint:T",
    )
    with pytest.raises(ValueError, match="DMS ARN format"):
        emit_task_config(_cfg(dms), output_path=tmp_path / "dms.json")


def test_emit_china_partition_accepted(tmp_path):
    """aws-cn and aws-us-gov partitions are valid DMS-region values."""
    dms = AWSDMSLoadConfig(
        replication_instance_arn="arn:aws-cn:dms:cn-north-1:123456789012:rep:R",
        source_endpoint_arn="arn:aws-cn:dms:cn-north-1:123456789012:endpoint:S",
        target_endpoint_arn="arn:aws-cn:dms:cn-north-1:123456789012:endpoint:T",
    )
    path = emit_task_config(_cfg(dms), output_path=tmp_path / "dms.json")
    assert path.exists()
