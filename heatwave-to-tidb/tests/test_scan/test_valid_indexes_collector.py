"""Tests for fetch_tables_without_valid_index."""

from tests.test_scan.fake_connection import ScriptedConnection

from tishift_heatwave.core.scan.collectors.valid_indexes import fetch_tables_without_valid_index


def test_returns_tables_missing_a_valid_index():
    conn = ScriptedConnection(
        [
            (
                "information_schema.tables",
                [
                    {"table_name": "audit_log", "table_schema": "myapp"},
                    {"table_name": "staging_events", "table_schema": "myapp"},
                ],
            )
        ]
    )

    result = fetch_tables_without_valid_index(conn)

    assert result == [("myapp", "audit_log"), ("myapp", "staging_events")]


def test_empty_result_when_all_tables_have_a_valid_index():
    conn = ScriptedConnection([("information_schema.tables", [])])
    assert fetch_tables_without_valid_index(conn) == []


def test_default_excluded_schemas_bound_as_parameters_not_interpolated():
    conn = ScriptedConnection([("information_schema.tables", [])])

    fetch_tables_without_valid_index(conn)

    sql, params = conn.executed[0]
    assert params == (
        "mysql",
        "performance_schema",
        "information_schema",
        "sys",
        "mysql_autopilot",
        "mysql_audit",
        "mysql_tasks",
    )
    # These schema names have no reason to appear anywhere in the fixed SQL
    # text itself — unlike "information_schema", which legitimately appears
    # as the literal FROM-clause qualifier regardless of parameter binding.
    for schema in ("mysql_autopilot", "mysql_audit", "mysql_tasks"):
        assert schema not in sql
    assert sql.count("%s") == len(params)
    assert "ML\\_SCHEMA\\_%" in sql


def test_custom_excluded_schemas_change_placeholder_count():
    conn = ScriptedConnection([("information_schema.tables", [])])

    fetch_tables_without_valid_index(conn, exclude_schemas=("mysql", "sys"))

    sql, params = conn.executed[0]
    assert params == ("mysql", "sys")
    assert sql.count("%s") == 2
