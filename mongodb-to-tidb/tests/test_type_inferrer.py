"""Tests for sample-based BSON-aware type inference."""

from __future__ import annotations

from tishift_mongodb.core.scan.type_inferrer import (
    FieldHistogram,
    classify,
    infer_field_type,
    update_histogram,
    walk_document,
)


def test_classify_scalars():
    assert classify(None) == "null"
    assert classify(True) == "Boolean"
    assert classify(42) == "Int32"
    assert classify(2**40) == "Int64"
    assert classify(3.14) == "Double"
    assert classify("x") == "String"
    assert classify([1, 2]) == "Array"


def test_classify_bson_sentinels():
    assert classify({"_type": "ObjectId", "value": "..."}) == "ObjectId"
    assert classify({"_type": "Decimal128", "value": "1.5"}) == "Decimal128"
    assert classify({"_type": "UUID", "value": "..."}) == "UUID"
    assert classify({"_type": "Binary", "subtype": 0, "base64": ""}) == "Binary"
    assert classify({"_type": "Date", "iso": "..."}) == "Date"


def test_classify_dbref_by_structure():
    assert classify({"$ref": "users", "$id": "abc"}) == "DBRef"


def test_classify_subdocument():
    assert classify({"foo": "bar"}) == "Object"


def test_histogram_homogeneous_string():
    h = FieldHistogram(field_path="email")
    for _ in range(100):
        update_histogram(h, "a@b.c")
    assert h.dominant_type() == "String"
    assert not h.is_polymorphic()


def test_histogram_polymorphic_price():
    """The classic polymorphic-price case from sample-schema.json."""
    h = FieldHistogram(field_path="price")
    for _ in range(8):
        update_histogram(h, 19.99)
    update_histogram(h, {"amount": 24.99, "currency": "USD"})
    update_histogram(h, {"_type": "Decimal128", "value": "49.99"})
    assert h.is_polymorphic()
    assert infer_field_type(h) == "polymorphic"


def test_histogram_sparse_field():
    h = FieldHistogram(field_path="deprecated_id")
    update_histogram(h, "L-123")
    for _ in range(9):
        update_histogram(h, None)
    assert h.is_sparse()
    assert h.presence_ratio() < 0.75


def test_histogram_csfle_detection():
    h = FieldHistogram(field_path="encrypted")
    update_histogram(h, {"_type": "Binary", "subtype": 6, "base64": ""})
    assert h.has_csfle()


def test_walk_document_skips_top_level_id():
    doc = {"_id": "abc", "name": "Alice"}
    h = walk_document(doc)
    assert "_id" not in h
    assert "name" in h


def test_walk_document_nested():
    doc = {"address": {"street": "Main", "city": "SF"}}
    h = walk_document(doc)
    assert "address" in h
    assert "address.street" in h
    assert "address.city" in h


def test_walk_skips_typed_sentinels():
    doc = {"created_at": {"_type": "Date", "iso": "2026-01-01T00:00:00Z"}}
    h = walk_document(doc)
    assert "created_at" in h
    assert "created_at.iso" not in h
    assert h["created_at"].dominant_type() == "Date"


def test_walk_skips_dbref_internals():
    doc = {"user_ref": {"$ref": "users", "$id": "abc"}}
    h = walk_document(doc)
    assert "user_ref" in h
    assert "user_ref.$ref" not in h
    assert h["user_ref"].dominant_type() == "DBRef"
