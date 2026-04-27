"""Tests for CockroachDB → TiDB type mapping."""

from tishift_crdb.rules.type_mapping import map_crdb_type


class TestIntegerMapping:
    def test_int_is_bigint(self):
        """CRITICAL: CRDB INT must map to BIGINT (64-bit)."""
        result = map_crdb_type("INT")
        assert result.tidb_type == "BIGINT"

    def test_int8_is_bigint(self):
        result = map_crdb_type("INT8")
        assert result.tidb_type == "BIGINT"

    def test_int64_is_bigint(self):
        result = map_crdb_type("INT64")
        assert result.tidb_type == "BIGINT"

    def test_integer_is_bigint(self):
        result = map_crdb_type("INTEGER")
        assert result.tidb_type == "BIGINT"

    def test_int4_is_int(self):
        result = map_crdb_type("INT4")
        assert result.tidb_type == "INT"

    def test_smallint(self):
        result = map_crdb_type("SMALLINT")
        assert result.tidb_type == "SMALLINT"

    def test_bool(self):
        result = map_crdb_type("BOOL")
        assert result.tidb_type == "TINYINT(1)"


class TestFloatMapping:
    def test_float4(self):
        assert map_crdb_type("FLOAT4").tidb_type == "FLOAT"

    def test_float8(self):
        assert map_crdb_type("FLOAT8").tidb_type == "DOUBLE"

    def test_double_precision(self):
        assert map_crdb_type("DOUBLE PRECISION").tidb_type == "DOUBLE"

    def test_decimal(self):
        result = map_crdb_type("DECIMAL", numeric_precision=10, numeric_scale=2)
        assert result.tidb_type == "DECIMAL(10,2)"


class TestSerialMapping:
    def test_serial(self):
        result = map_crdb_type("SERIAL")
        assert result.tidb_type == "BIGINT"
        assert "unique_rowid" in result.comment


class TestUuidMapping:
    def test_uuid(self):
        result = map_crdb_type("UUID")
        assert result.tidb_type == "CHAR(36)"

    def test_uuid_with_default(self):
        result = map_crdb_type("UUID", column_default="gen_random_uuid()")
        assert result.tidb_type == "CHAR(36)"
        assert "UUID()" in result.comment


class TestStringMapping:
    def test_string_unbounded(self):
        result = map_crdb_type("STRING")
        assert result.tidb_type == "TEXT"

    def test_string_with_length(self):
        result = map_crdb_type("STRING", character_maximum_length=100)
        assert result.tidb_type == "VARCHAR(100)"

    def test_text(self):
        assert map_crdb_type("TEXT").tidb_type == "TEXT"

    def test_varchar(self):
        result = map_crdb_type("VARCHAR", character_maximum_length=255)
        assert result.tidb_type == "VARCHAR(255)"

    def test_char(self):
        result = map_crdb_type("CHAR", character_maximum_length=10)
        assert result.tidb_type == "CHAR(10)"


class TestBinaryMapping:
    def test_bytes(self):
        assert map_crdb_type("BYTES").tidb_type == "LONGBLOB"

    def test_bytea(self):
        assert map_crdb_type("BYTEA").tidb_type == "LONGBLOB"

    def test_bytes_with_length(self):
        result = map_crdb_type("BYTES", character_maximum_length=16)
        assert result.tidb_type == "VARBINARY(16)"


class TestDateTimeMapping:
    def test_date(self):
        assert map_crdb_type("DATE").tidb_type == "DATE"

    def test_timestamp(self):
        assert map_crdb_type("TIMESTAMP").tidb_type == "DATETIME(6)"

    def test_timestamptz(self):
        result = map_crdb_type("TIMESTAMPTZ")
        assert result.tidb_type == "DATETIME(6)"
        assert "UTC" in result.comment

    def test_interval(self):
        result = map_crdb_type("INTERVAL")
        assert result.tidb_type == "VARCHAR(40)"


class TestJsonMapping:
    def test_jsonb(self):
        result = map_crdb_type("JSONB")
        assert result.tidb_type == "JSON"
        assert "operator" in result.comment.lower() or "rewrite" in result.comment.lower()

    def test_json(self):
        assert map_crdb_type("JSON").tidb_type == "JSON"


class TestSpecialMapping:
    def test_array(self):
        result = map_crdb_type("ARRAY")
        assert result.tidb_type == "JSON"
        assert result.lossy is True

    def test_int_array(self):
        result = map_crdb_type("INT[]")
        assert result.tidb_type == "JSON"
        assert result.lossy is True

    def test_geometry(self):
        assert map_crdb_type("GEOMETRY").tidb_type == "GEOMETRY"

    def test_geography(self):
        result = map_crdb_type("GEOGRAPHY")
        assert result.tidb_type == "GEOMETRY"
        assert result.lossy is True

    def test_inet(self):
        assert map_crdb_type("INET").tidb_type == "VARCHAR(45)"

    def test_oid(self):
        assert map_crdb_type("OID").tidb_type == "INT UNSIGNED"

    def test_unknown_fallback(self):
        result = map_crdb_type("REGCLASS")
        assert result.lossy is True
        assert "unmapped" in result.comment
