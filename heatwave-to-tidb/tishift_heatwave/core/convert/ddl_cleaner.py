"""DDL cleanup engine — comment-preserving removal of HeatWave-only syntax.

Nothing is deleted: cleaned clauses are converted to plain MySQL comments
tagged TISHIFT-REMOVED so the original text stays auditable in the output.
Only plain `/* */` and `--` comments are emitted — never `/*! */` or `/*T! */`
executable comments. If a removed clause itself contains `*/`, the engine
falls back to a `--` line comment so the wrapping comment cannot close early.

Idempotent by construction: rule patterns run against a masked copy of the
SQL where string literals and comments are blanked out, so text inside an
existing TISHIFT-REMOVED comment can never re-match.
"""

from __future__ import annotations

import re

from tishift_heatwave.models import CleanupFinding
from tishift_heatwave.rules.ddl_cleanup import (
    ALTER_SECONDARY_STMT,
    CLAUSE_RULES,
    RAPID_COLUMN_RULE,
)

REMOVED_TAG = "TISHIFT-REMOVED"
REVIEW_TAG = "TISHIFT-REVIEW"

_TABLE_NAME = r"(?:`[^`]+`|\w+)(?:\s*\.\s*(?:`[^`]+`|\w+))?"
_CREATE_TABLE_RE = re.compile(
    rf"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<name>{_TABLE_NAME})", re.I
)
_ALTER_TABLE_RE = re.compile(rf"ALTER\s+TABLE\s+(?P<name>{_TABLE_NAME})", re.I)
_PRIMARY_KEY_RE = re.compile(r"\bPRIMARY\s+KEY\s*\((?P<cols>[^)]*)\)", re.I)


def mask_sql(sql: str) -> str:
    """Return a same-length copy with string literals and comments blanked out.

    Quote characters and comment delimiters are preserved at their positions;
    only the interior content is replaced with 'x'. Because lengths match,
    match spans on the masked text map 1:1 onto the original.
    """
    out = list(sql)
    i = 0
    n = len(sql)
    while i < n:
        c = sql[i]
        if c in ("'", '"', "`"):
            quote = c
            j = i + 1
            while j < n:
                if sql[j] == "\\" and quote != "`" and j + 1 < n:
                    j += 2
                    continue
                if sql[j] == quote:
                    if j + 1 < n and sql[j + 1] == quote:  # doubled-quote escape
                        j += 2
                        continue
                    break
                j += 1
            for k in range(i + 1, min(j, n)):
                out[k] = "x"
            i = j + 1
        elif sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            end = n if end == -1 else end + 2
            for k in range(i, end):
                out[k] = "x"
            i = end
        elif c == "#" or (sql.startswith("--", i) and (i + 2 >= n or sql[i + 2] in " \t\r\n")):
            end = sql.find("\n", i)
            end = n if end == -1 else end
            for k in range(i, end):
                out[k] = "x"
            i = end
        else:
            i += 1
    return "".join(out)


def split_statements(sql: str) -> list[str]:
    """Split a script on top-level ';', preserving all text (comments,
    whitespace) attached to the following chunk."""
    masked = mask_sql(sql)
    statements = []
    start = 0
    for i, ch in enumerate(masked):
        if ch == ";":
            statements.append(sql[start : i + 1])
            start = i + 1
    if sql[start:].strip():
        statements.append(sql[start:])
    return statements


def normalize_table_name(raw: str) -> str:
    return re.sub(r"[`\s]", "", raw).lower()


def _collapse(text: str) -> str:
    return " ".join(text.split())


def _comment_out(rule_id: str, clause: str) -> str:
    clause = _collapse(clause)
    if "*/" in clause:
        # A block comment would close early — degrade to a line comment.
        return f"\n-- {REMOVED_TAG} [{rule_id}]: {clause}\n"
    return f" /* {REMOVED_TAG} [{rule_id}]: {clause} */"


def _split_cols(raw: str) -> list[str]:
    return [c.split("(")[0].replace("`", "").strip() for c in raw.split(",") if c.strip()]


def _pk_cols(stmt: str, masked: str) -> list[str]:
    m = _PRIMARY_KEY_RE.search(masked)
    if not m:
        return []
    return _split_cols(stmt[m.start("cols") : m.end("cols")])


def _clustering_suggestion(cols: list[str], pk_cols: list[str]) -> str:
    """Alternative for a removed CLUSTERING BY — suggestion only, never applied.

    Must not contain '*' + '/' so it can be embedded in a block comment.
    """
    lowered = [c.lower() for c in cols]
    pk_lowered = [c.lower() for c in pk_cols]
    col_list = ", ".join(cols)
    if pk_lowered and lowered == pk_lowered[: len(lowered)]:
        return (
            f"clustering columns ({col_list}) match the primary key prefix - "
            "consider making the primary key CLUSTERED in TiDB"
        )
    return (
        f"consider a secondary index on ({col_list}); "
        "evaluate table partitioning if data locality matters"
    )


def _statement_table(stmt: str, masked: str) -> str | None:
    """Extract the raw (original quoting preserved) table name, if any."""
    for pattern in (_CREATE_TABLE_RE, _ALTER_TABLE_RE):
        m = pattern.search(masked)
        if m:
            return stmt[m.start("name") : m.end("name")].strip()
    return None


def is_create_table(stmt: str) -> bool:
    return bool(_CREATE_TABLE_RE.search(mask_sql(stmt)))


def clean_statement(stmt: str) -> tuple[str, list[CleanupFinding], bool, str | None]:
    """Apply all cleanup rules to one statement.

    Returns (new_statement, findings, is_rapid_table, raw_table_name).
    """
    findings: list[CleanupFinding] = []
    masked = mask_sql(stmt)
    table_raw = _statement_table(stmt, masked)
    table = normalize_table_name(table_raw) if table_raw else None

    # Statement-level HW-DDL-2: ALTER TABLE ... SECONDARY_LOAD / SECONDARY_UNLOAD
    stripped = stmt.strip()
    if ALTER_SECONDARY_STMT.match(stripped):
        leading_ws = stmt[: len(stmt) - len(stmt.lstrip())]
        collapsed = _collapse(stripped)
        findings.append(
            CleanupFinding(
                rule_id="HW-DDL-2",
                risk="blocker",
                table=table,
                matched_text=collapsed,
                action_taken="statement_commented_out",
            )
        )
        return f"{leading_ws}-- {REMOVED_TAG} [HW-DDL-2]: {collapsed}\n", findings, False, table_raw

    # Clause-level rules
    matches: list[tuple[int, int, object]] = []
    for rule in CLAUSE_RULES:
        for m in rule.pattern.finditer(masked):
            matches.append((m.start(), m.end(), rule))
    matches.sort(key=lambda t: t[0])

    pk_cols = _pk_cols(stmt, masked)
    parts: list[str] = []
    prev = 0
    last_end = 0
    is_rapid = False
    for start, end, rule in matches:
        if start < last_end:  # overlapping match from another rule — skip
            continue
        orig = stmt[start:end]
        clause = re.sub(r"^\s*,\s*", "", orig)
        replacement = _comment_out(rule.rule_id, clause)
        suggestion = None
        if rule.rule_id == "HW-DDL-3":
            cols_m = re.search(r"\((?P<cols>[^)]*)\)", clause)
            cols = _split_cols(cols_m.group("cols")) if cols_m else []
            suggestion = _clustering_suggestion(cols, pk_cols)
            replacement += f"\n  /* {REVIEW_TAG} [HW-DDL-3]: {suggestion} */"
        if rule.rule_id == "HW-DDL-1" and re.search(r"rapid", orig, re.I):
            is_rapid = True
        parts.append(stmt[prev:start])
        parts.append(replacement)
        findings.append(
            CleanupFinding(
                rule_id=rule.rule_id,
                risk=rule.risk,
                table=table,
                matched_text=_collapse(clause),
                action_taken=rule.action_taken,
                suggestion=suggestion,
            )
        )
        prev = end
        last_end = end
    parts.append(stmt[prev:])
    new_stmt = "".join(parts)

    # HW-DDL-4 detection (keep as-is, report only). Runs on the original text
    # because it targets literal content; the masked check confirms the
    # COMMENT keyword itself is not inside a string or comment.
    for m in RAPID_COLUMN_RULE.pattern.finditer(stmt):
        if masked[m.start() : m.start() + 7].upper() == "COMMENT":
            findings.append(
                CleanupFinding(
                    rule_id="HW-DDL-4",
                    risk="harmless",
                    table=table,
                    matched_text=_collapse(m.group(0)),
                    action_taken="kept",
                )
            )

    return new_stmt, findings, is_rapid, table_raw
