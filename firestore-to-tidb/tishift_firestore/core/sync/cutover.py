"""Cutover plan generator. Renders a step-by-step plan as Markdown."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from tishift_firestore.config import TiShiftConfig


CutoverTolerance = Literal["minutes", "hours", "weekend", "longer"]


@dataclass
class CutoverPlan:
    tolerance: CutoverTolerance
    requires_cdc: bool
    steps: list[str]

    def to_markdown(self) -> str:
        lines = [
            "# Cutover Plan",
            "",
            f"Cutover tolerance: **{self.tolerance}**",
            f"CDC required: **{'yes' if self.requires_cdc else 'no'}**",
            "",
            "## Steps",
            "",
        ]
        for i, step in enumerate(self.steps, 1):
            lines.append(f"{i}. {step}")
        return "\n".join(lines)


def generate_cutover_plan(cfg: TiShiftConfig, tolerance: CutoverTolerance) -> CutoverPlan:
    """Generate a tolerance-appropriate cutover plan."""

    requires_cdc = tolerance in ("minutes", "hours")
    steps: list[str] = []

    if requires_cdc:
        steps.extend([
            "T-14d: Install firestore-bigquery-export on all in-scope collections (customer-run).",
            "T-7d: Run `tishift-firestore load --strategy dataflow-lightning`. Note read_time as T-bulk.",
            "T-7d: Run `tishift-firestore check`. Resolve any count or hash mismatches.",
            "T-7d to T-0: Start sync via `tishift-firestore sync start --since T-bulk`.",
            "T-7d to T-0: Monitor `tishift_cdc_lag_seconds` metric; tune Dataflow workers if growing.",
            "T-0: Place application into read-only mode against Firestore.",
            "T-0: Wait for `tishift_cdc_lag_seconds < 5`.",
            "T-0: Run final `tishift-firestore check --full`. Zero mismatches required.",
            "T-0: Switch application config to write to TiDB.",
            "T-0+1m: Stop the sync job via `tishift-firestore sync stop`.",
            "T-0 to T+N days: Retain Firestore in read-only mode as rollback safety.",
        ])
    else:
        steps.extend([
            "T-2d: Run `tishift-firestore load --strategy auto`.",
            "T-2d: Run `tishift-firestore check`. Resolve any mismatches.",
            "T-1d: Place application into read-only mode against Firestore.",
            "T-1d: Run final `tishift-firestore check --full`.",
            "T-0: Switch application config to write to TiDB.",
            "T-0 to T+N days: Retain Firestore in read-only mode as rollback safety.",
        ])

    return CutoverPlan(tolerance=tolerance, requires_cdc=requires_cdc, steps=steps)


def write_cutover_plan(plan: CutoverPlan, output_path: str | Path) -> Path:
    """Write the plan as Markdown to the given path."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(plan.to_markdown(), encoding="utf-8")
    return path
