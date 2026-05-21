"""Tests for the Firestore → TiDB type mapping primitives."""

from __future__ import annotations

from tishift_firestore.rules.type_map import (
    integer_shaped,
    map_bytes,
    map_document_id,
    map_geopoint,
    map_map_as_json,
    map_scalar_boolean,
    map_scalar_number,
    map_scalar_string,
    map_timestamp,
    varchar_size_for,
)


def test_varchar_size_powers_of_two():
    assert varchar_size_for(5) == "VARCHAR(32)"
    assert varchar_size_for(33) == "VARCHAR(64)"
    assert varchar_size_for(200) == "VARCHAR(256)"
    assert varchar_size_for(513) == "VARCHAR(1024)"


def test_varchar_promotes_to_text():
    assert varchar_size_for(15000) == "TEXT"


def test_integer_shaped():
    assert integer_shaped([1.0, 2.0, 3.0])
    assert integer_shaped([])
    assert not integer_shaped([1.5])
    assert not integer_shaped([1.0, 2.5])
    assert not integer_shaped([float(2**60)])  # outside safe-int range


def test_map_scalar_number():
    spec = map_scalar_number(integer_shaped=True, name="age", nullable=True)
    assert spec.sql_type == "BIGINT"
    spec = map_scalar_number(integer_shaped=False, name="price", nullable=True)
    assert spec.sql_type == "DOUBLE"


def test_map_scalar_string_short():
    spec = map_scalar_string(max_observed_len=64, name="email", nullable=False)
    assert spec.sql_type == "VARCHAR(64)"


def test_map_boolean():
    spec = map_scalar_boolean(name="active", nullable=False)
    assert spec.sql_type == "TINYINT(1)"


def test_map_timestamp_with_sentinel():
    spec = map_timestamp(name="created_at", nullable=False, with_server_sentinel=True)
    assert "CURRENT_TIMESTAMP(6)" in spec.default_clause


def test_map_timestamp_no_sentinel():
    spec = map_timestamp(name="updated_at", nullable=True, with_server_sentinel=False)
    assert spec.default_clause == ""


def test_map_geopoint_default():
    specs = map_geopoint(name="location", nullable=True, mode="lat_lng_columns")
    assert len(specs) == 2
    assert specs[0].name == "location_lat"
    assert specs[1].name == "location_lng"
    assert "DECIMAL(9,6)" in specs[0].sql_type


def test_map_geopoint_json_mode():
    specs = map_geopoint(name="location", nullable=True, mode="json")
    assert len(specs) == 1
    assert specs[0].sql_type == "JSON"


def test_map_bytes_inline():
    specs = map_bytes(max_observed_size_mb=1, name="avatar", nullable=True)
    assert len(specs) == 1
    assert specs[0].sql_type == "LONGBLOB"


def test_map_bytes_offload():
    specs = map_bytes(max_observed_size_mb=20, name="document", nullable=True)
    assert len(specs) == 1
    assert "VARCHAR" in specs[0].sql_type
    assert "GCS" in specs[0].comment


def test_map_document_id_default():
    spec = map_document_id()
    assert spec.sql_type == "VARCHAR(20)"


def test_to_ddl_emits_valid_mysql():
    spec = map_scalar_string(max_observed_len=100, name="email", nullable=False)
    ddl = spec.to_ddl()
    assert "`email`" in ddl
    assert "NOT NULL" in ddl
    assert "VARCHAR" in ddl
