"""Tests for the cloud-agnostic storage URI handling.

Tests parse_url and join exhaustively. The fs_for / ensure_writable / list_files
functions are integration-tested separately (require live backends or MinIO).
"""

from __future__ import annotations

import pytest

from tishift_mongodb.storage import join, parse_url


def test_parse_s3():
    scheme, rem = parse_url("s3://bucket/prefix/")
    assert scheme == "s3"
    assert rem == "bucket/prefix/"


def test_parse_gs():
    scheme, rem = parse_url("gs://bucket/prefix/")
    assert scheme == "gs"
    assert rem == "bucket/prefix/"


def test_parse_azure():
    scheme, rem = parse_url("azure://container/prefix/")
    assert scheme == "azure"


def test_parse_local_file():
    scheme, rem = parse_url("file:///tmp/staging/")
    assert scheme == "file"


def test_parse_local_scheme():
    scheme, rem = parse_url("local:///mnt/staging/")
    assert scheme == "local"


def test_parse_rejects_unsupported():
    with pytest.raises(ValueError):
        parse_url("http://example.com/")


def test_parse_rejects_bare_path():
    with pytest.raises(ValueError):
        parse_url("/tmp/staging")


def test_join_s3():
    out = join("s3://bucket/prefix/", "dump", "users")
    assert out == "s3://bucket/prefix/dump/users"


def test_join_gs():
    out = join("gs://bucket/", "dump", "users", "part-0001.ndjson")
    assert out == "gs://bucket/dump/users/part-0001.ndjson"


def test_join_local():
    out = join("file:///mnt/staging/", "dump", "users")
    assert out == "file:///mnt/staging/dump/users"


def test_join_strips_redundant_slashes():
    out = join("s3://bucket///", "/dump/", "/users/")
    assert out == "s3://bucket/dump/users"
