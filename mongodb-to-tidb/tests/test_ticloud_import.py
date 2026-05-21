"""Tests for ticloud_import validation."""

from __future__ import annotations

import pytest

from tishift_mongodb.core.load.ticloud_import import (
    CloudImportRequest,
    InvalidCloudImportRequestError,
)


def test_valid_request():
    req = CloudImportRequest(
        cluster_id="cluster-123",
        source_type="NDJSON",
        source_url="s3://bucket/path/",
        file_pattern="*.ndjson",
        target_database="mydb",
    )
    args = req.to_cli_args()
    assert args[0] == "ticloud"
    assert "--cluster-id" in args
    assert "cluster-123" in args


def test_rejects_cluster_id_with_flag_injection():
    with pytest.raises(InvalidCloudImportRequestError):
        CloudImportRequest(
            cluster_id="--evil",
            source_type="NDJSON",
            source_url="s3://b/p/",
            file_pattern="*",
            target_database="d",
        )


def test_rejects_unknown_source_type():
    with pytest.raises(InvalidCloudImportRequestError):
        CloudImportRequest(
            cluster_id="ok",
            source_type="UNKNOWN",
            source_url="s3://b/p/",
            file_pattern="*",
            target_database="d",
        )


def test_rejects_non_storage_url():
    with pytest.raises(InvalidCloudImportRequestError):
        CloudImportRequest(
            cluster_id="ok",
            source_type="NDJSON",
            source_url="http://example.com/",
            file_pattern="*",
            target_database="d",
        )


def test_rejects_target_db_with_special_chars():
    with pytest.raises(InvalidCloudImportRequestError):
        CloudImportRequest(
            cluster_id="ok",
            source_type="NDJSON",
            source_url="s3://b/p/",
            file_pattern="*",
            target_database="bad`db",
        )
