"""Compatibility analyzer — Phase 3 of SKILL.md (Assess & Score).

Pure function over collected scan data (SchemaInventory, HeatWaveMetadata,
BinlogPrecheckResult) — no DB access — so it's testable against fixtures.
Applies every rule in rules/compatibility.py and returns an AssessmentResult
(blockers, warnings, compatible features), matching
references/compatibility-rules.md's Output Format.
"""

from __future__ import annotations

from tishift_heatwave.models import (
    AssessmentResult,
    BinlogPrecheckResult,
    CompatibilityFinding,
    HeatWaveMetadata,
    QueryLogSignals,
    SchemaInventory,
    Severity,
)
from tishift_heatwave.rules.compatibility import (
    BLOCKER_RULES,
    COMPATIBLE_FEATURES,
    WARNING_RULES,
    CompatibilityContext,
)


def assess_compatibility(
    inventory: SchemaInventory,
    metadata: HeatWaveMetadata,
    binlog: BinlogPrecheckResult,
    tier: str = "starter",
    continue_replication_planned: bool = False,
    query_log: QueryLogSignals | None = None,
) -> AssessmentResult:
    """Evaluate every compatibility rule and return the assessment result."""
    ctx = CompatibilityContext(
        inventory=inventory,
        metadata=metadata,
        binlog=binlog,
        tier=tier,
        continue_replication_planned=continue_replication_planned,
        query_log=query_log or QueryLogSignals(),
    )

    result = AssessmentResult()

    for rule in BLOCKER_RULES:
        count = rule.check(ctx)
        if count > 0:
            result.blockers.append(
                CompatibilityFinding(
                    rule_id=rule.rule_id,
                    severity=Severity.BLOCKER,
                    feature=rule.feature,
                    count=count,
                    action=rule.action,
                )
            )

    for rule in WARNING_RULES:
        count = rule.check(ctx)
        if count > 0:
            result.warnings.append(
                CompatibilityFinding(
                    rule_id=rule.rule_id,
                    severity=Severity.WARNING,
                    feature=rule.feature,
                    count=count,
                    action=rule.action,
                )
            )

    result.compatible = list(COMPATIBLE_FEATURES)

    return result
