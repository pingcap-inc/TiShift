"""Binlog/continue-replication readiness precheck evaluator (Phase 2 of SKILL.md).

Pure function over a {variable: value} dict — no DB access — so it is
testable against fixtures without a live HeatWave connection. See
tishift_heatwave/rules/binlog_check.py for the rule definitions, and
docs/sync-guide.md / references/compatibility-rules.md for the human-facing
version of these same rules (HW-WARNING-4, HW-WARNING-6..9).

This precheck only gates continue replication (Phase 7 sync); a failing result does not block
a cutover-only migration.
"""

from __future__ import annotations

from tishift_heatwave.models import BinlogPrecheckResult, BinlogVariableCheck
from tishift_heatwave.rules.binlog_check import INFORMATIONAL_VARIABLES, REQUIRED_RULES


def evaluate_binlog_config(variables: dict[str, str | None]) -> BinlogPrecheckResult:
    """Validate collected SHOW VARIABLES output against the continue-replication readiness rules."""
    result = BinlogPrecheckResult()

    for rule in REQUIRED_RULES:
        actual = variables.get(rule.variable)
        ok = rule.check(actual)
        status = "pass" if ok else "fail"
        if ok and rule.recommended_check is not None and not rule.recommended_check(actual):
            status = "warn"
        result.checks.append(
            BinlogVariableCheck(
                variable=rule.variable,
                rule_id=rule.rule_id,
                actual=actual,
                required=rule.required,
                status=status,
                why=rule.why,
                recommended=rule.recommended,
            )
        )
        if status == "fail":
            result.continue_replication_ready = False

    server_id = variables.get("server_id")
    result.checks.append(
        BinlogVariableCheck(
            variable="server_id",
            rule_id=None,
            actual=server_id,
            required="non-zero, unique per source",
            status="warn" if server_id in (None, "0") else "info",
            why=INFORMATIONAL_VARIABLES["server_id"],
        )
    )
    result.checks.append(
        BinlogVariableCheck(
            variable="expire_logs_days",
            rule_id=None,
            actual=variables.get("expire_logs_days"),
            required="(informational only)",
            status="info",
            why=INFORMATIONAL_VARIABLES["expire_logs_days"],
        )
    )

    return result
