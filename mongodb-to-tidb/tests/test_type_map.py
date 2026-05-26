"""Tests for the BSON → TiDB type mapping primitives."""

from __future__ import annotations

from tishift_mongodb.rules.type_map import (
    integer_shaped,
    map_binary,
    map_boolean,
    map_date,
    map_dbref,
    map_decimal128,
    map_double,
    map_int32,
    map_int64,
    map_objectid,
    map_scalar_string,
    map_uuid,
    varchar_size_for,
)


def test_varchar_size_powers_of_two():
    assert varchar_size_for(5) == "VARCHAR(32)"
    assert varchar_size_for(33) == "VARCHAR(64)"
    assert varchar_size_for(200) == "VARCHAR(256)"


def test_varchar_promotes_to_text():
    assert varchar_size_for(15000) == "TEXT"


def test_map_int32():
    assert map_int32(name="age", nullable=True).sql_type == "INT"


def test_map_int64():
    assert map_int64(name="big", nullable=False).sql_type == "BIGINT"


def test_map_double():
    assert map_double(name="x", nullable=True).sql_type == "DOUBLE"


def test_map_decimal128_covers_significand():
    spec = map_decimal128(name="amount", nullable=True)
    assert "DECIMAL(38,11)" == spec.sql_type


def test_map_boolean():
    assert map_boolean(name="active", nullable=False).sql_type == "TINYINT(1)"


def test_map_date():
    assert map_date(name="created_at", nullable=False).sql_type == "DATETIME(6)"


def test_map_objectid_default_hex():
    assert map_objectid().sql_type == "VARCHAR(24)"


def test_map_objectid_binary_alternative():
    assert map_objectid(as_binary=True).sql_type == "BINARY(12)"


def test_map_uuid():
    assert map_uuid(name="u", nullable=True).sql_type == "BINARY(16)"


def test_map_binary_inline_for_small():
    specs = map_binary(max_observed_size_mb=1.0, name="blob", nullable=True, subtype=0)
    assert len(specs) == 1
    assert specs[0].sql_type == "LONGBLOB"


def test_map_binary_offload_for_large():
    specs = map_binary(max_observed_size_mb=20.0, name="blob", nullable=True, subtype=0)
    assert len(specs) == 1
    assert "VARCHAR" in specs[0].sql_type


def test_map_binary_csfle_subtype_6():
    specs = map_binary(max_observed_size_mb=0.1, name="enc", nullable=True, subtype=6)
    assert len(specs) == 1
    assert "CSFLE" in specs[0].comment


def test_map_dbref():
    assert map_dbref(name="ref", nullable=True).sql_type == "VARCHAR(1500)"


def test_map_scalar_string_short():
    spec = map_scalar_string(max_observed_len=64, name="email", nullable=False)
    assert spec.sql_type == "VARCHAR(64)"


def test_integer_shaped():
    assert integer_shaped([1.0, 2.0, 3.0])
    assert integer_shaped([])
    assert not integer_shaped([1.5])
    assert not integer_shaped([float(2**60)])


def test_to_ddl_emits_valid_mysql():
    spec = map_scalar_string(max_observed_len=100, name="email", nullable=False)
    ddl = spec.to_ddl()
    assert "`email`" in ddl
    assert "NOT NULL" in ddl
    assert "VARCHAR" in ddl
