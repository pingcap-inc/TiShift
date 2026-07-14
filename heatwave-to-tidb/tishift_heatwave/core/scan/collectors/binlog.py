"""Binlog/continue-replication readiness variable collector.

Runs the SHOW VARIABLES precheck query (rules/binlog_check.QUERY) against a
live source connection. Kept separate from the validation logic in
core/scan/analyzers/binlog_check.py so the validator stays testable against
plain dict fixtures without a database.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pymysql

from tishift_heatwave.rules.binlog_check import QUERY


def fetch_binlog_variables(conn: pymysql.Connection) -> dict[str, str | None]:
    """Run the SHOW VARIABLES query and return {Variable_name: Value}."""
    with conn.cursor() as cur:
        cur.execute(QUERY)
        rows = cur.fetchall()
    return {row["Variable_name"]: row["Value"] for row in rows}
