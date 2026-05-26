"""Cutover plan generation.

Same shape as Firestore — tolerance + provider drive the step list.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from tishift_mongodb.config import TiShiftConfig


CutoverTolerance = Literal["minutes", "hours", "weekend", "longer"]


@dataclass
class CutoverPlan:
    tolerance: CutoverTolerance
    requires_cdc: bool
    provider: str
    steps: list[str]

    def to_markdown(self) -> str:
        lines = [
            "# Cutover Plan",
            "",
            f"Cutover tolerance: **{self.tolerance}**",
            f"CDC required: **{'yes' if self.requires_cdc else 'no'}**",
            f"Provider: **{self.provider if self.requires_cdc else 'n/a'}**",
            "",
            "## Steps",
            "",
        ]
        for i, step in enumerate(self.steps, 1):
            lines.append(f"{i}. {step}")
        return "\n".join(lines)


def generate_cutover_plan(cfg: TiShiftConfig, tolerance: CutoverTolerance) -> CutoverPlan:
    requires_cdc = tolerance in ("minutes", "hours")
    provider = cfg.sync.provider if requires_cdc else "n/a"
    steps: list[str] = []

    if not requires_cdc:
        steps.extend([
            "T-2d: Run `tishift-mongodb load --strategy auto`. mongodump-lightning is the default.",
            "T-2d: Run `tishift-mongodb check`. Resolve any mismatches.",
            "T-1d: Place application into read-only mode against MongoDB.",
            "T-1d: Run final `tishift-mongodb check --full`. Zero mismatches required.",
            "T-0: Switch application config to write to TiDB.",
            "T-0 to T+N days: Retain MongoDB read-only as rollback safety.",
        ])
        return CutoverPlan(tolerance=tolerance, requires_cdc=False, provider=provider, steps=steps)

    if provider == "direct-changestream":
        steps.extend([
            "T-14d: Run bulk load via mongodump-lightning. Note the load completion time.",
            "T-14d: Deploy direct-changestream daemon: `tishift-mongodb sync start --provider direct-changestream --since <LOAD_COMPLETED_AT>`",
            "T-14d to T-0: Monitor `tishift_cdc_lag_seconds`. Target stable <5 minutes.",
            "T-0: Place application into read-only mode against MongoDB.",
            "T-0: Wait for `tishift_cdc_lag_seconds < 5`.",
            "T-0: Run final `tishift-mongodb check --full`. Zero mismatches required.",
            "T-0: Switch application config to TiDB.",
            "T-0+1m: Stop the daemon: `tishift-mongodb sync stop`.",
            "T-0 to T+N days: Retain MongoDB read-only as rollback safety.",
        ])
    elif provider == "aws-dms":
        steps.extend([
            "T-14d: Configure DMS task (full-load-and-cdc). Customer-owned.",
            "T-14d: Run `tishift-mongodb sync start --provider aws-dms --task-arn $TASK_ARN`",
            "T-0: Application read-only. Wait for lag < 5s. Final check. Switch to TiDB. Stop DMS task.",
        ])
    elif provider == "datastream":
        steps.extend([
            "T-14d: Configure Datastream stream + BigQuery destination. Customer-owned.",
            "T-14d: Submit Dataflow streaming job from `tishift-mongodb sync start --provider datastream`",
            "T-0: Application read-only. Wait for lag < 5s. Final check. Switch to TiDB. Stop Dataflow.",
        ])
    elif provider == "debezium":
        steps.extend([
            "T-14d: Apply Debezium source + JDBC sink connector configs to Kafka Connect.",
            "T-14d to T-0: Monitor Kafka Connect REST API for status; lag via topic offsets.",
            "T-0: Application read-only. Wait for lag < 5s. Final check. Switch to TiDB. Pause connectors.",
        ])

    return CutoverPlan(tolerance=tolerance, requires_cdc=True, provider=provider, steps=steps)


def write_cutover_plan(plan: CutoverPlan, output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(plan.to_markdown(), encoding="utf-8")
    return path
