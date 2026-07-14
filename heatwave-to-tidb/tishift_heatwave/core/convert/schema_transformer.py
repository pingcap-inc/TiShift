"""Convert-phase orchestration: DDL cleanup → validation → TiFlash emission.

Pipeline per statement:

1. ddl_cleaner comments out HeatWave-only syntax (TISHIFT-REMOVED markers)
2. modified statements are re-parsed with sqlglot (MySQL dialect) to verify
   the cleanup left valid syntax; failures are reported, never silently dropped
3. each RAPID table gets `ALTER TABLE ... SET TIFLASH REPLICA n` emitted
   immediately after its CREATE TABLE statement, inline in the output SQL

TiFlash replica statements are emitted on every tier (TiDB Cloud Starter
included); only --tiflash-replicas 0 downgrades the ALTER to an informational
comment. Note: replicas created before data load mean TiFlash replicates
during the import, which slows large loads — this trade-off is recorded in
the cleanup report.

Later mapping stages (collation remaps, spatial→JSON per
references/type-mapping.md) plug in after cleanup; they are not implemented yet.
"""

from __future__ import annotations

import re

from tishift_heatwave.core.convert.ddl_cleaner import (
    clean_statement,
    is_create_table,
    mask_sql,
    normalize_table_name,
    split_statements,
)
from tishift_heatwave.models import DDLCleanupResult

_EXISTING_TIFLASH_RE = re.compile(
    r"ALTER\s+TABLE\s+(?P<name>(?:`[^`]+`|\w+)(?:\s*\.\s*(?:`[^`]+`|\w+))?)"
    r"\s+SET\s+TIFLASH\s+REPLICA\b",
    re.I,
)


def _existing_tiflash_tables(sql: str) -> set[str]:
    masked = mask_sql(sql)
    return {
        normalize_table_name(sql[m.start("name") : m.end("name")])
        for m in _EXISTING_TIFLASH_RE.finditer(masked)
    }


def _validate_mysql(stmt: str) -> str | None:
    """Re-parse a cleaned statement; return an error string or None."""
    try:
        import sqlglot

        sqlglot.parse(stmt, read="mysql")
        return None
    except Exception as exc:  # sqlglot raises several error types
        return str(exc).splitlines()[0]


def transform_schema(
    sql: str,
    tier: str = "starter",
    tiflash_replicas: int = 2,
) -> DDLCleanupResult:
    """Clean a DDL script and inline TiFlash replica statements."""
    result = DDLCleanupResult()
    tier_normalized = (tier or "starter").strip().lower()
    already_replicated = _existing_tiflash_tables(sql)

    parts: list[str] = []
    for stmt in split_statements(sql):
        new_stmt, findings, is_rapid, table_raw = clean_statement(stmt)
        parts.append(new_stmt)
        result.findings.extend(findings)

        if new_stmt != stmt:
            error = _validate_mysql(new_stmt)
            if error:
                result.parse_errors.append(f"{table_raw or '<statement>'}: {error}")

        if is_rapid and table_raw and is_create_table(stmt):
            normalized = normalize_table_name(table_raw)
            result.rapid_tables.append(normalized)
            if normalized in already_replicated:
                continue
            alter = f"ALTER TABLE {table_raw} SET TIFLASH REPLICA {tiflash_replicas};"
            if tiflash_replicas > 0:
                parts.append(f"\n\n{alter}\n")
                result.tiflash_statements.append(alter)
            else:
                parts.append(
                    f"\n-- TISHIFT-INFO [HW-DDL-1]: TiFlash replica not emitted "
                    f"(tier={tier_normalized}, replicas={tiflash_replicas}); "
                    f"to enable later run: {alter}\n"
                )

    result.sql = "".join(parts)
    return result
