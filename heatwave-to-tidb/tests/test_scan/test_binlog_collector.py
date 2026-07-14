"""Tests for the binlog variable collector against a fake pymysql connection."""

from tishift_heatwave.core.scan.collectors.binlog import fetch_binlog_variables
from tishift_heatwave.rules.binlog_check import QUERY


class FakeCursor:
    def __init__(self, rows):
        self._rows = rows
        self.executed = None

    def execute(self, sql):
        self.executed = sql

    def fetchall(self):
        return self._rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConnection:
    def __init__(self, rows):
        self._cursor = FakeCursor(rows)

    def cursor(self):
        return self._cursor


def test_fetch_runs_exact_query_and_parses_rows():
    rows = [
        {"Variable_name": "log_bin", "Value": "ON"},
        {"Variable_name": "server_id", "Value": "1"},
        {"Variable_name": "binlog_format", "Value": "ROW"},
    ]
    conn = FakeConnection(rows)

    variables = fetch_binlog_variables(conn)

    assert conn._cursor.executed == QUERY
    assert variables == {"log_bin": "ON", "server_id": "1", "binlog_format": "ROW"}


def test_fetch_returns_empty_dict_for_no_rows():
    conn = FakeConnection([])
    assert fetch_binlog_variables(conn) == {}
