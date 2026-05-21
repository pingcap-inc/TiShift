"""Tests for BSON-aware canonicalization used by hash-diff checks."""

from __future__ import annotations

from tishift_mongodb.core.check.hash_diff import (
    CANONICALIZATION_VERSION,
    canonicalize,
    hash_document,
)


def test_canonicalization_version_is_v2():
    """Bumped from Firestore v1 because BSON adds new typed values."""
    assert CANONICALIZATION_VERSION == 2


def test_objectid():
    out = canonicalize({"_type": "ObjectId", "value": "6479a1c0d3b1234567890abc"})
    assert out == {"$oid": "6479a1c0d3b1234567890abc"}


def test_decimal128():
    out = canonicalize({"_type": "Decimal128", "value": "49.99999999999"})
    assert out == {"$dec": "49.99999999999"}


def test_uuid():
    out = canonicalize({"_type": "UUID", "value": "550e8400-e29b-41d4-a716-446655440000"})
    assert out == {"$uuid": "550e8400-e29b-41d4-a716-446655440000"}


def test_binary_preserves_subtype():
    out = canonicalize({"_type": "Binary", "subtype": 0, "base64": "AAA="})
    assert out == {"$bin": "AAA=", "$type": 0}


def test_csfle_binary_subtype_6():
    out = canonicalize({"_type": "Binary", "subtype": 6, "base64": "encrypted=="})
    assert out["$type"] == 6


def test_date_iso_passthrough():
    out = canonicalize({"_type": "Date", "iso": "2026-01-15T03:14:15.123Z"})
    assert out == "2026-01-15T03:14:15.123Z"


def test_timestamp():
    out = canonicalize({"_type": "Timestamp", "time": 1700000000, "inc": 1})
    assert out == {"$ts": (1700000000, 1)}


def test_regex():
    out = canonicalize({"_type": "Regex", "pattern": "^foo", "flags": "i"})
    assert out == {"$regex": "^foo", "$opts": "i"}


def test_dbref():
    out = canonicalize({"_type": "DBRef", "$ref": "users", "$id": "abc"})
    assert out == {"$dbref": ["users", "abc"]}


def test_dbref_by_structure():
    out = canonicalize({"$ref": "users", "$id": "abc"})
    assert out == {"$dbref": ["users", "abc"]}


def test_dict_keys_sorted():
    d1 = {"b": 1, "a": 2}
    d2 = {"a": 2, "b": 1}
    assert hash_document(d1) == hash_document(d2)


def test_hash_changes_with_value():
    assert hash_document({"x": 1}) != hash_document({"x": 2})


def test_nested_canonical():
    doc = {
        "id": "abc",
        "items": [
            {"sku": "S-1", "qty": 2},
            {"sku": "S-2", "qty": 1},
        ],
        "ref": {"_type": "DBRef", "$ref": "products", "$id": "xyz"},
    }
    canonical = canonicalize(doc)
    assert canonical["ref"] == {"$dbref": ["products", "xyz"]}
    assert isinstance(canonical["items"], list)
