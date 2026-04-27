"""Tests for Oracle → TiDB type mapping rules."""

import pytest

from tishift_oracle.rules.type_mapping import MappedType, map_oracle_type


class TestNumericMapping:
    def test_number_tinyint(self):
        result = map_oracle_type("NUMBER", data_precision=2, data_scale=0)
        assert result.tidb_type == "TINYINT"

    def test_number_smallint(self):
        result = map_oracle_type("NUMBER", data_precision=4, data_scale=0)
        assert result.tidb_type == "SMALLINT"

    def test_number_int(self):
        result = map_oracle_type("NUMBER", data_precision=9, data_scale=0)
        assert result.tidb_type == "INT"

    def test_number_bigint(self):
        result = map_oracle_type("NUMBER", data_precision=18, data_scale=0)
        assert result.tidb_type == "BIGINT"

    def test_number_decimal(self):
        result = map_oracle_type("NUMBER", data_precision=10, data_scale=2)
        assert result.tidb_type == "DECIMAL(10,2)"

    def test_number_no_precision(self):
        result = map_oracle_type("NUMBER")
        assert result.tidb_type == "DECIMAL(38,10)"
        assert result.lossy is True
        assert "no precision" in result.comment

    def test_number_high_precision(self):
        result = map_oracle_type("NUMBER", data_precision=70, data_scale=5)
        assert result.tidb_type == "DECIMAL(65,30)"
        assert result.lossy is True

    def test_float(self):
        result = map_oracle_type("FLOAT")
        assert result.tidb_type == "DOUBLE"

    def test_binary_float(self):
        result = map_oracle_type("BINARY_FLOAT")
        assert result.tidb_type == "FLOAT"

    def test_binary_double(self):
        result = map_oracle_type("BINARY_DOUBLE")
        assert result.tidb_type == "DOUBLE"

    def test_integer(self):
        result = map_oracle_type("INTEGER")
        assert result.tidb_type == "INT"


class TestStringMapping:
    def test_varchar2_byte(self):
        result = map_oracle_type("VARCHAR2", data_length=100, char_used="B")
        assert result.tidb_type == "VARCHAR(100)"

    def test_varchar2_char_semantics(self):
        result = map_oracle_type("VARCHAR2", data_length=100, char_used="C")
        assert result.tidb_type == "VARCHAR(400)"

    def test_varchar2_default(self):
        result = map_oracle_type("VARCHAR2", data_length=50)
        assert result.tidb_type == "VARCHAR(50)"

    def test_nvarchar2(self):
        result = map_oracle_type("NVARCHAR2", data_length=100)
        assert result.tidb_type == "VARCHAR(400)"

    def test_char(self):
        result = map_oracle_type("CHAR", data_length=10)
        assert result.tidb_type == "CHAR(10)"

    def test_nchar(self):
        result = map_oracle_type("NCHAR", data_length=10)
        assert result.tidb_type == "CHAR(40)"

    def test_clob(self):
        result = map_oracle_type("CLOB")
        assert result.tidb_type == "LONGTEXT"

    def test_nclob(self):
        result = map_oracle_type("NCLOB")
        assert result.tidb_type == "LONGTEXT"

    def test_long(self):
        result = map_oracle_type("LONG")
        assert result.tidb_type == "LONGTEXT"
        assert "deprecated" in result.comment


class TestBinaryMapping:
    def test_blob(self):
        result = map_oracle_type("BLOB")
        assert result.tidb_type == "LONGBLOB"

    def test_raw(self):
        result = map_oracle_type("RAW", data_length=16)
        assert result.tidb_type == "VARBINARY(16)"

    def test_long_raw(self):
        result = map_oracle_type("LONG RAW")
        assert result.tidb_type == "LONGBLOB"
        assert "DMS" in result.comment


class TestDateTimeMapping:
    def test_date_maps_to_datetime(self):
        """CRITICAL: Oracle DATE must map to DATETIME, never DATE."""
        result = map_oracle_type("DATE")
        assert result.tidb_type == "DATETIME"
        assert "DATE" not in result.tidb_type.replace("DATETIME", "")

    def test_timestamp_default(self):
        result = map_oracle_type("TIMESTAMP", data_scale=6)
        assert result.tidb_type == "DATETIME(6)"

    def test_timestamp_3(self):
        result = map_oracle_type("TIMESTAMP(3)", data_scale=3)
        assert result.tidb_type == "DATETIME(3)"

    def test_timestamp_9_capped(self):
        result = map_oracle_type("TIMESTAMP(9)", data_scale=9)
        assert result.tidb_type == "DATETIME(6)"
        assert result.lossy is True
        assert "capped" in result.comment

    def test_timestamp_with_tz(self):
        result = map_oracle_type("TIMESTAMP WITH TIME ZONE")
        assert result.tidb_type == "VARCHAR(40)"

    def test_timestamp_with_local_tz(self):
        result = map_oracle_type("TIMESTAMP WITH LOCAL TIME ZONE", data_scale=6)
        assert "DATETIME" in result.tidb_type

    def test_interval_year_to_month(self):
        result = map_oracle_type("INTERVAL YEAR TO MONTH")
        assert result.tidb_type == "VARCHAR(20)"

    def test_interval_day_to_second(self):
        result = map_oracle_type("INTERVAL DAY TO SECOND")
        assert result.tidb_type == "VARCHAR(30)"


class TestSpecialTypeMapping:
    def test_rowid(self):
        result = map_oracle_type("ROWID")
        assert result.tidb_type == "VARCHAR(18)"

    def test_urowid(self):
        result = map_oracle_type("UROWID")
        assert result.tidb_type == "VARCHAR(18)"

    def test_xmltype(self):
        result = map_oracle_type("XMLTYPE")
        assert result.tidb_type == "LONGTEXT"
        assert "XMLType" in result.comment

    def test_sdo_geometry(self):
        result = map_oracle_type("SDO_GEOMETRY")
        assert result.tidb_type == "LONGTEXT"

    def test_bfile(self):
        result = map_oracle_type("BFILE")
        assert result.tidb_type == "VARCHAR(255)"

    def test_boolean(self):
        result = map_oracle_type("BOOLEAN")
        assert result.tidb_type == "TINYINT(1)"

    def test_unknown_type_fallback(self):
        result = map_oracle_type("ANYDATA")
        assert result.tidb_type == "LONGTEXT"
        assert result.lossy is True
        assert "unmapped" in result.comment
