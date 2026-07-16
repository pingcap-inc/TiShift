"""Convert-phase orchestration: DDL cleanup → validation → TiFlash emission.

Pipeline per statement:

1. ddl_cleaner comments out HeatWave-only syntax (TISHIFT-REMOVED markers)
2. modified statements are re-parsed with sqlglot (MySQL dialect) to verify
   the cleanup left valid syntax; failures are reported, never silently dropped
3. each RAPID table gets `ALTER TABLE ... SET TIFLASH REPLICA n` emitted
   immediately after its CREATE TABLE statement, inline in the output SQL.
   Tables with RAPID_COLUMN comment hints but no SECONDARY_ENGINE clause
   (HW-DDL-5 — dumps often strip table options) get the same ALTER plus a
   TISHIFT-REVIEW comment asking for verification on the live system

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
    REVIEW_TAG,
    clean_statement,
    is_create_table,
    mask_sql,
    normalize_table_name,
    split_statements,
)
from tishift_heatwave.models import CleanupFinding, DDLCleanupResult

_EXISTING_TIFLASH_RE = re.compile(
    r"ALTER\s+TABLE\s+(?P<name>(?:`[^`]+`|\w+)(?:\s*\.\s*(?:`[^`]+`|\w+))?)"
    r"\s+SET\s+TIFLASH\s+REPLICA\b",
    re.I,
)

# HW-DDL-5 info comments emitted on a previous run (tiflash_replicas=0 path);
# matched on the raw text because comments are blanked out by mask_sql.
_EXISTING_HINT_NOTE_RE = re.compile(
    r"\[HW-DDL-5\][^\n]*?\bALTER\s+TABLE\s+"
    r"(?P<name>(?:`[^`]+`|\w+)(?:\s*\.\s*(?:`[^`]+`|\w+))?)",
    re.I,
)


def _existing_tiflash_tables(sql: str) -> set[str]:
    masked = mask_sql(sql)
    return {
        normalize_table_name(sql[m.start("name") : m.end("name")])
        for m in _EXISTING_TIFLASH_RE.finditer(masked)
    }


def _existing_hint_notes(sql: str) -> set[str]:
    return {
        normalize_table_name(m.group("name")) for m in _EXISTING_HINT_NOTE_RE.finditer(sql)
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
    already_noted = _existing_hint_notes(sql)

    parts: list[str] = []
    for stmt in split_statements(sql):
        new_stmt, findings, is_rapid, table_raw = clean_statement(stmt)
        parts.append(new_stmt)
        result.findings.extend(findings)

        if new_stmt != stmt:
            error = _validate_mysql(new_stmt)
            if error:
                result.parse_errors.append(f"{table_raw or '<statement>'}: {error}")

        # HW-DDL-5: RAPID_COLUMN comment hints without SECONDARY_ENGINE imply
        # the table was likely RAPID-offloaded (dumps often strip table options).
        has_hint = not is_rapid and any(f.rule_id == "HW-DDL-4" for f in findings)

        if (is_rapid or has_hint) and table_raw and is_create_table(stmt):
            normalized = normalize_table_name(table_raw)
            if is_rapid:
                result.rapid_tables.append(normalized)
            else:
                result.rapid_hint_tables.append(normalized)
            if normalized in already_replicated or (has_hint and normalized in already_noted):
                continue
            alter = f"ALTER TABLE {table_raw} SET TIFLASH REPLICA {tiflash_replicas};"
            rule_id = "HW-DDL-1" if is_rapid else "HW-DDL-5"
            if tiflash_replicas > 0:
                if has_hint:
                    parts.append(
                        f"\n\n/* {REVIEW_TAG} [HW-DDL-5]: RAPID_COLUMN comment hints suggest "
                        f"this table may be RAPID-offloaded in HeatWave - verify on the live "
                        f"system before relying on the replica */\n{alter}\n"
                    )
                else:
                    parts.append(f"\n\n{alter}\n")
                result.tiflash_statements.append(alter)
            else:
                parts.append(
                    f"\n-- TISHIFT-INFO [{rule_id}]: TiFlash replica not emitted "
                    f"(tier={tier_normalized}, replicas={tiflash_replicas}); "
                    f"to enable later run: {alter}\n"
                )
            if has_hint:
                result.findings.append(
                    CleanupFinding(
                        rule_id="HW-DDL-5",
                        risk="assess",
                        table=normalized,
                        matched_text=f"RAPID_COLUMN comment hints on {table_raw}",
                        action_taken=(
                            "tiflash_replica_emitted" if tiflash_replicas > 0 else "noted_only"
                        ),
                        suggestion=(
                            "table has RAPID_COLUMN column comments but no SECONDARY_ENGINE "
                            "clause - confirm RAPID offload status on the live HeatWave system "
                            "and drop the TiFlash replica if analytics offload is not needed"
                        ),
                    )
                )

    result.sql = "".join(parts)
    return result
