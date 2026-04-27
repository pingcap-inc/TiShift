"""Tests for OceanBase → TiDB type mapping."""

from tishift_ob.rules.type_mapping import map_mysql_mode_type, map_oracle_mode_type


class TestMysqlMode:
    def test_int(self):
        assert map_mysql_mode_type("INT", "int(11)").tidb_type == "int(11)"

    def test_bigint(self):
        assert map_mysql_mode_type("BIGINT", "bigint(20)").tidb_type == "bigint(20)"

    def test_varchar(self):
        assert map_mysql_mode_type("VARCHAR", "varchar(100)").tidb_type == "varchar(100)"

    def test_datetime(self):
        assert map_mysql_mode_type("DATETIME").tidb_type == "DATETIME"

    def test_json(self):
        assert map_mysql_mode_type("JSON").tidb_type == "JSON"

    def test_enum(self):
        r = map_mysql_mode_type("ENUM", "enum('a','b','c')")
        assert r.tidb_type == "enum('a','b','c')"

    def test_all_standard_types(self):
        for t in ["INT", "BIGINT", "SMALLINT", "TINYINT", "FLOAT", "DOUBLE",
                   "DECIMAL", "VARCHAR", "CHAR", "TEXT", "LONGTEXT",
                   "BLOB", "LONGBLOB", "DATE", "DATETIME", "TIMESTAMP",
                   "JSON", "BIT", "BINARY", "VARBINARY"]:
            r = map_mysql_mode_type(t)
            assert not r.lossy


class TestOracleMode:
    def test_number_int(self):
        assert map_oracle_mode_type("NUMBER", data_precision=9, data_scale=0).tidb_type == "INT"

    def test_number_bigint(self):
        assert map_oracle_mode_type("NUMBER", data_precision=18, data_scale=0).tidb_type == "BIGINT"

    def test_number_decimal(self):
        assert map_oracle_mode_type("NUMBER", data_precision=10, data_scale=2).tidb_type == "DECIMAL(10,2)"

    def test_number_no_precision(self):
        r = map_oracle_mode_type("NUMBER")
        assert r.tidb_type == "DECIMAL(38,10)"
        assert r.lossy

    def test_varchar2(self):
        assert map_oracle_mode_type("VARCHAR2", data_length=100).tidb_type == "VARCHAR(100)"

    def test_varchar2_char_semantics(self):
        assert map_oracle_mode_type("VARCHAR2", data_length=100, char_used="C").tidb_type == "VARCHAR(400)"

    def test_date_to_datetime(self):
        """CRITICAL: Oracle-mode DATE must map to DATETIME."""
        r = map_oracle_mode_type("DATE")
        assert r.tidb_type == "DATETIME"
        assert "time" in r.comment.lower()

    def test_timestamp(self):
        assert map_oracle_mode_type("TIMESTAMP", data_scale=6).tidb_type == "DATETIME(6)"

    def test_timestamp_capped(self):
        r = map_oracle_mode_type("TIMESTAMP", data_scale=9)
        assert r.tidb_type == "DATETIME(6)"
        assert r.lossy

    def test_clob(self):
        assert map_oracle_mode_type("CLOB").tidb_type == "LONGTEXT"

    def test_blob(self):
        assert map_oracle_mode_type("BLOB").tidb_type == "LONGBLOB"

    def test_raw(self):
        assert map_oracle_mode_type("RAW", data_length=16).tidb_type == "VARBINARY(16)"

    def test_rowid(self):
        assert map_oracle_mode_type("ROWID").tidb_type == "VARCHAR(18)"

    def test_float(self):
        assert map_oracle_mode_type("FLOAT").tidb_type == "DOUBLE"

    def test_binary_float(self):
        assert map_oracle_mode_type("BINARY_FLOAT").tidb_type == "FLOAT"

    def test_unknown(self):
        r = map_oracle_mode_type("ANYDATA")
        assert r.lossy
        assert "unmapped" in r.comment
