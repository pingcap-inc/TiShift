"""Postgres → TiDB type mapping.

Spec: references/type-mapping.md. Runtime equivalent lives here.
"""

from __future__ import annotations

# Minimal starter map. The full table is in references/type-mapping.md; this
# module will be fleshed out during convert implementation.
PG_TO_TIDB_BASIC: dict[str, str] = {
    "smallint": "SMALLINT",
    "integer": "INT",
    "bigint": "BIGINT",
    "text": "TEXT",
    "boolean": "TINYINT(1)",
    "uuid": "VARCHAR(36)",
    "json": "JSON",
    "jsonb": "JSON",
    "date": "DATE",
    "timestamp without time zone": "DATETIME(6)",
    "timestamp with time zone": "DATETIME(6)",
    "bytea": "LONGBLOB",
}
