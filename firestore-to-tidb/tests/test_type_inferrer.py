"""Tests for sample-based type inference."""

from __future__ import annotations

from tishift_firestore.core.scan.type_inferrer import (
    FieldHistogram,
    classify,
    infer_field_type,
    update_histogram,
    walk_document,
)


def test_classify_scalars():
    assert classify(None) == "null"
    assert classify(True) == "boolean"
    assert classify(False) == "boolean"
    assert classify(42) == "number"
    assert classify(3.14) == "number"
    assert classify("hello") == "string"
    assert classify([1, 2, 3]) == "array"


def test_classify_typed_sentinels():
    """Synthetic _type-tagged dicts from sample-schema.json."""
    assert classify({"_type": "timestamp", "iso": "2026-01-01T00:00:00Z"}) == "timestamp"
    assert classify({"_type": "geopoint", "lat": 1.0, "lng": 2.0}) == "geopoint"
    assert classify({"_type": "reference", "path": "users/abc"}) == "reference"
    assert classify({"_type": "bytes", "base64": "aGVsbG8="}) == "bytes"


def test_classify_map():
    assert classify({"key": "val"}) == "map"
    assert classify({}) == "map"


def test_histogram_homogeneous_string():
    h = FieldHistogram(field_path="email")
    for v in ["a@b.c", "x@y.z", "p@q.r"]:
        update_histogram(h, v)
    assert h.dominant_type() == "string"
    assert not h.is_polymorphic()
    assert not h.is_sparse()
    assert infer_field_type(h) == "string"


def test_histogram_polymorphic():
    h = FieldHistogram(field_path="price")
    for v in [19.99, 24.99, 49.99]:
        update_histogram(h, v)
    update_histogram(h, {"amount": 24.99, "currency": "USD"})
    assert h.is_polymorphic()
    assert infer_field_type(h) == "polymorphic"


def test_histogram_dominant_with_nulls():
    h = FieldHistogram(field_path="age")
    # 8 numbers, 2 nulls = 80% presence → dominant=number, nullable, NOT sparse.
    for v in [25, 30, 35, 40, 45, 50, 55, 60, None, None]:
        update_histogram(h, v)
    assert h.dominant_type() == "number"
    assert h.is_nullable()
    assert not h.is_sparse()
    assert h.presence_ratio() == 0.8


def test_histogram_sparse():
    h = FieldHistogram(field_path="deprecated_legacy_id")
    # 1 string in 10 docs — sparse
    update_histogram(h, "L-123")
    for _ in range(9):
        update_histogram(h, None)
    assert h.is_sparse()
    assert h.presence_ratio() < 0.75


def test_histogram_dominant_95_pct():
    h = FieldHistogram(field_path="mostly_str")
    for _ in range(19):
        update_histogram(h, "x")
    update_histogram(h, 42)  # 1 outlier — 95% rule says "string" still
    # Total: 19 string, 1 number — 19/20 = 95% triggers the dominant rule.
    assert infer_field_type(h) == "string"


def test_walk_document_nested():
    doc = {"_id": "abc", "name": "Alice", "address": {"street": "Main", "city": "SF"}}
    h = walk_document(doc)
    assert "name" in h
    assert "address" in h
    assert "address.street" in h
    assert "address.city" in h
    assert h["address"].dominant_type() == "map"
    assert h["address"].map_keys_union == {"street", "city"}


def test_walk_skips_typed_sentinels():
    """Typed sentinels are leaves, not maps to recurse into."""
    doc = {"created_at": {"_type": "timestamp", "iso": "2026-01-01T00:00:00Z"}}
    h = walk_document(doc)
    # Should record created_at as timestamp; should NOT create created_at.iso
    assert "created_at" in h
    assert "created_at.iso" not in h
    assert h["created_at"].dominant_type() == "timestamp"


def test_histogram_bytes_size_tracking():
    h = FieldHistogram(field_path="blob")
    update_histogram(h, {"_type": "bytes", "base64": "AA" * 1024 * 1024})  # ~1.5MB encoded
    assert h.max_observed_bytes_mb > 0
