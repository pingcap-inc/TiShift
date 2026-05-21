"""Tests for index parsing + classification (pure function)."""

from __future__ import annotations

from tishift_mongodb.core.scan.indexes import (
    fields_in_any_composite_index,
    parse_index_info,
)


def test_parse_simple_unique_index():
    raw = {"name": "email_1", "key": {"email": 1}, "unique": True}
    idx = parse_index_info("users", raw)
    assert idx.name == "email_1"
    assert idx.unique
    assert not idx.sparse
    assert len(idx.fields) == 1
    assert idx.fields[0].name == "email"


def test_parse_compound_index():
    raw = {"name": "country_tier", "key": {"country": 1, "tier": 1}}
    idx = parse_index_info("users", raw)
    assert len(idx.fields) == 2
    assert not idx.is_geospatial
    assert not idx.is_text
    assert not idx.is_wildcard


def test_parse_2dsphere():
    raw = {"name": "loc_2dsphere", "key": {"location": "2dsphere"}}
    idx = parse_index_info("users", raw)
    assert idx.is_geospatial


def test_parse_text():
    raw = {"name": "text_search", "key": {"notes": "text"}}
    idx = parse_index_info("orders", raw)
    assert idx.is_text


def test_parse_wildcard():
    raw = {"name": "wild", "key": {"$**": 1}}
    idx = parse_index_info("attrs", raw)
    assert idx.is_wildcard


def test_parse_ttl():
    raw = {"name": "ttl_idx", "key": {"created_at": 1}, "expireAfterSeconds": 3600}
    idx = parse_index_info("sessions", raw)
    assert idx.ttl_seconds == 3600


def test_fields_in_composite():
    indexes = [
        parse_index_info("users", {"name": "_id_", "key": {"_id": 1}, "unique": True}),
        parse_index_info("users", {"name": "ct", "key": {"country": 1, "tier": 1}}),
        parse_index_info("users", {"name": "email_1", "key": {"email": 1}, "unique": True}),
    ]
    s = fields_in_any_composite_index(indexes, collection="users")
    # Single-field indexes excluded; only compound (ct) contributes
    assert s == {"country", "tier"}
