"""Column-structure parity check between the scan-inferred schema and live TiDB DDL."""

from __future__ import annotations

import re
from dataclasses import dataclass

from tishift_firestore.config import TiShiftConfig
from tishift_firestore.core.convert.ddl_emitter import _table_name
from tishift_firestore.rules.identifiers import quote_ident


@dataclass
class StructureDiff:
    table: str
    missing_in_target: list[str]
    extra_in_target: list[str]
    type_mismatches: list[tuple[str, str, str]]  # (column, expected, actual)

    @property
    def matches(self) -> bool:
        return not (self.missing_in_target or self.extra_in_target or self.type_mismatches)

    def to_dict(self) -> dict:
        return {
            "table": self.table,
            "missing_in_target": self.missing_in_target,
            "extra_in_target": self.extra_in_target,
            "type_mismatches": [
                {"column": c, "expected": e, "actual": a}
                for c, e, a in self.type_mismatches
            ],
            "matches": self.matches,
        }


_DDL_COL_PATTERN = re.compile(r"`(?P<name>\w+)`\s+(?P<type>[A-Z]+(?:\([^)]+\))?)", re.IGNORECASE)


def parse_ddl_columns(create_table_sql: str) -> dict[str, str]:
    """Parse a CREATE TABLE statement into {column_name: column_type}.

    Best-effort regex; for full correctness use a SQL parser. Sufficient for
    structure parity checks against TiDB's SHOW CREATE TABLE output, which is
    canonical-form MySQL.
    """
    cols: dict[str, str] = {}
    body_start = create_table_sql.find("(")
    body_end = create_table_sql.rfind(")")
    if body_start < 0 or body_end < 0:
        return cols
    body = create_table_sql[body_start + 1 : body_end]
    for line in body.split(","):
        line = line.strip()
        if line.upper().startswith(("PRIMARY KEY", "KEY", "UNIQUE", "FOREIGN", "INDEX", "CONSTRAINT")):
            continue
        m = _DDL_COL_PATTERN.match(line)
        if m:
            cols[m["name"]] = m["type"].upper()
    return cols


def fetch_target_table_ddl(cfg: TiShiftConfig, table: str) -> str:
    """Fetch the live SHOW CREATE TABLE output for one table."""
    from tishift_firestore.connection import tidb_connection

    with tidb_connection(cfg.target, read_only=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SHOW CREATE TABLE {quote_ident(table)}")
            row = cur.fetchone()
            if not row:
                raise RuntimeError(f"Table {table} not found in target")
            # The dict cursor returns {'Table': 'foo', 'Create Table': 'CREATE TABLE ...'}
            return str(row["Create Table"])


def compare_structure(
    cfg: TiShiftConfig,
    *,
    collection_path: str,
    expected_ddl: str,
) -> StructureDiff:
    """Compare the convert-time DDL against the live TiDB DDL."""
    table = _table_name(collection_path)
    expected = parse_ddl_columns(expected_ddl)
    try:
        actual_ddl = fetch_target_table_ddl(cfg, table)
        actual = parse_ddl_columns(actual_ddl)
    except RuntimeError:
        return StructureDiff(
            table=table,
            missing_in_target=list(expected.keys()),
            extra_in_target=[],
            type_mismatches=[],
        )

    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    mismatches: list[tuple[str, str, str]] = []
    for col in sorted(set(expected) & set(actual)):
        if expected[col] != actual[col]:
            mismatches.append((col, expected[col], actual[col]))

    return StructureDiff(
        table=table,
        missing_in_target=missing,
        extra_in_target=extra,
        type_mismatches=mismatches,
    )
