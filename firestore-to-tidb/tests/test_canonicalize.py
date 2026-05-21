"""Tests for the deterministic canonicalization used by hash-diff checks."""

from __future__ import annotations

from datetime import datetime, timezone

from tishift_firestore.core.check.hash_diff import canonicalize, hash_document


def test_canonicalize_scalars():
    assert canonicalize(None) is None
    assert canonicalize(True) is True
    assert canonicalize(42) == 42
    assert canonicalize("x") == "x"


def test_canonicalize_dict_sorts_keys():
    d1 = {"b": 1, "a": 2}
    d2 = {"a": 2, "b": 1}
    assert hash_document(d1) == hash_document(d2)


def test_canonicalize_geopoint():
    g = {"_type": "geopoint", "lat": 37.7749, "lng": -122.4194}
    out = canonicalize(g)
    assert out == {"$geo": [37.7749, -122.4194]}


def test_canonicalize_geopoint_rounds_to_6dp():
    g = {"_type": "geopoint", "lat": 37.7749001234567, "lng": -122.4194}
    out = canonicalize(g)
    assert out["$geo"][0] == 37.7749


def test_canonicalize_reference():
    r = {"_type": "reference", "path": "users/abc"}
    out = canonicalize(r)
    assert out == {"$ref": "users/abc"}


def test_canonicalize_timestamp():
    t = {"_type": "timestamp", "iso": "2026-01-01T00:00:00Z"}
    out = canonicalize(t)
    assert out == "2026-01-01T00:00:00Z"


def test_canonicalize_bytes():
    b = {"_type": "bytes", "base64": "aGVsbG8="}
    out = canonicalize(b)
    assert out == {"$bytes": "aGVsbG8="}


def test_hash_stable_across_key_order():
    d1 = {"name": "Alice", "tags": ["a", "b"], "loc": {"_type": "geopoint", "lat": 1.0, "lng": 2.0}}
    d2 = {"tags": ["a", "b"], "loc": {"_type": "geopoint", "lat": 1.0, "lng": 2.0}, "name": "Alice"}
    assert hash_document(d1) == hash_document(d2)


def test_hash_changes_with_value():
    d1 = {"x": 1}
    d2 = {"x": 2}
    assert hash_document(d1) != hash_document(d2)


def test_canonicalize_datetime_object():
    dt = datetime(2026, 1, 15, 3, 14, 15, 123456, tzinfo=timezone.utc)
    out = canonicalize(dt)
    assert "2026-01-15T03:14:15" in out
    assert "+00:00" in out or out.endswith("Z")
