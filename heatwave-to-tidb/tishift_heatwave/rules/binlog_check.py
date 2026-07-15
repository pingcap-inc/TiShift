"""Binlog / continue-replication readiness precheck rule registry — scan phase.

Single source of truth for the SHOW VARIABLES check that decides whether a
HeatWave source is ready for TiDB DM continue replication (Phase 7 / docs/sync-guide.md).
Kept in lockstep with references/compatibility-rules.md (HW-WARNING-4..9)
and the required-value table in docs/sync-guide.md.

This precheck only gates continue replication (Phase 7 sync) — cutover-only migrations do not
need a passing binlog configuration.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

QUERY = (
    "SHOW VARIABLES WHERE Variable_name IN "
    "('log_bin','server_id','binlog_format','binlog_row_image',"
    "'binlog_expire_logs_seconds','expire_logs_days',"
    "'binlog_transaction_compression','binlog_row_value_options')"
)


@dataclass(frozen=True)
class BinlogRule:
    variable: str
    rule_id: str
    required: str  # human-readable requirement shown in reports
    why: str
    check: Callable[[str | None], bool]  # True if the actual value satisfies `required`
    recommended: str | None = None
    recommended_check: Callable[[str | None], bool] | None = None


def _equals(expected: str) -> Callable[[str | None], bool]:
    def check(value: str | None) -> bool:
        return value is not None and value.strip().upper() == expected.upper()

    return check


def _empty() -> Callable[[str | None], bool]:
    def check(value: str | None) -> bool:
        return value is not None and value.strip() == ""

    return check


def _int_at_least(minimum: int) -> Callable[[str | None], bool]:
    def check(value: str | None) -> bool:
        try:
            return value is not None and int(value) >= minimum
        except ValueError:
            return False

    return check


# One rule per gated variable. Order matches the required-value table in
# docs/sync-guide.md so a report iterates in the same order a reader sees it.
REQUIRED_RULES: list[BinlogRule] = [
    BinlogRule(
        variable="log_bin",
        rule_id="HW-WARNING-6",
        required="ON",
        why="Enables binary logging, which DM uses to replicate changes to TiDB",
        check=_equals("ON"),
    ),
    BinlogRule(
        variable="binlog_format",
        rule_id="HW-WARNING-7",
        required="ROW",
        why="Captures all data changes accurately (other formats miss edge cases)",
        check=_equals("ROW"),
    ),
    BinlogRule(
        variable="binlog_row_image",
        rule_id="HW-WARNING-8",
        required="FULL",
        why="Includes all column values in events for safe conflict resolution",
        check=_equals("FULL"),
    ),
    BinlogRule(
        variable="binlog_expire_logs_seconds",
        rule_id="HW-WARNING-4",
        required=">= 86400 (1 day)",
        recommended=">= 604800 (7 days)",
        why="Ensures DM can access consecutive logs during migration",
        check=_int_at_least(86400),
        recommended_check=_int_at_least(604800),
    ),
    BinlogRule(
        variable="binlog_transaction_compression",
        rule_id="HW-WARNING-9",
        required="OFF",
        why="DM does not support transaction compression",
        check=_equals("OFF"),
    ),
    BinlogRule(
        variable="binlog_row_value_options",
        rule_id="HW-WARNING-5",
        required="'' (empty, not PARTIAL_JSON)",
        why=(
            "DM cannot parse binlog rows written under partial-JSON mode — "
            "PARTIAL_JSON causes silent replication corruption on JSON columns, "
            "not a clean failure"
        ),
        check=_empty(),
    ),
]

# Collected by the same query for visibility, but not gated with a strict
# required value — the user's spec doesn't set one for these, and they are
# MySQL/HeatWave footguns rather than hard DM requirements.
INFORMATIONAL_VARIABLES: dict[str, str] = {
    "server_id": (
        "Must be non-zero and unique per source; 0 disables binary logging "
        "entirely, which silently breaks replication rather than failing cleanly"
    ),
    "expire_logs_days": (
        "Legacy pre-8.0 retention setting, superseded by "
        "binlog_expire_logs_seconds on MySQL 8.0+/HeatWave; expect 0 here "
        "(meaning 'deferred to binlog_expire_logs_seconds') and rely on that instead"
    ),
}
