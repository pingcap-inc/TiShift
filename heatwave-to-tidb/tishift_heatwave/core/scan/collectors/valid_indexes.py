"""Valid-indexes precheck collector — SKILL.md Step 7.1.

A continue-replication readiness check like collectors/binlog.py: DM needs a PK or unique
index on every business table to apply row changes deterministically.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pymysql

from tishift_heatwave.rules.valid_indexes import DEFAULT_EXCLUDED_SCHEMAS, build_query


def fetch_tables_without_valid_index(
    conn: pymysql.Connection,
    exclude_schemas: tuple[str, ...] = DEFAULT_EXCLUDED_SCHEMAS,
) -> list[tuple[str, str]]:
    """Return (table_schema, table_name) for every business table lacking a
    PK/UNIQUE index.

    *exclude_schemas* must cover every non-business schema on the actual
    instance being scanned — the default only lists the ones this module
    already knows about (mysql_autopilot/mysql_audit/mysql_tasks plus
    standard MySQL system schemas); ML_SCHEMA_% is excluded unconditionally
    via a NOT LIKE clause since it's a pattern, not a fixed name.
    """
    sql = build_query(exclude_schemas)
    with conn.cursor() as cur:
        cur.execute(sql, tuple(exclude_schemas))
        rows = cur.fetchall()
    return [(r["table_schema"], r["table_name"]) for r in rows]
