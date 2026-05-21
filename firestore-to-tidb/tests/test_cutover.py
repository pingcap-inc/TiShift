"""Tests for cutover plan generation."""

from __future__ import annotations

from tishift_firestore.config import (
    BigQueryConfig,
    ConvertConfig,
    DataflowConfig,
    LightningConfig,
    LoadConfig,
    SourceConfig,
    StagingConfig,
    SyncConfig,
    TargetConfig,
    TiShiftConfig,
)
from tishift_firestore.core.sync.cutover import generate_cutover_plan


def _stub_cfg() -> TiShiftConfig:
    return TiShiftConfig(
        source=SourceConfig(
            project_id="p", database_id="(default)",
            staging=StagingConfig(gcs_bucket="b", region="us"),
        ),
        target=TargetConfig(
            host="h", port=4000, user="u", password="pw",  # type: ignore[arg-type]
            database="d", tls=True, tier="byoc",
        ),
    )


def test_weekend_plan_does_not_require_cdc():
    plan = generate_cutover_plan(_stub_cfg(), "weekend")
    assert not plan.requires_cdc
    assert any("dataflow-lightning" in s.lower() or "load --strategy" in s.lower()
               for s in plan.steps)


def test_minutes_plan_requires_cdc():
    plan = generate_cutover_plan(_stub_cfg(), "minutes")
    assert plan.requires_cdc
    assert any("firestore-bigquery-export" in s for s in plan.steps)
    assert any("sync start" in s for s in plan.steps)


def test_hours_plan_requires_cdc():
    plan = generate_cutover_plan(_stub_cfg(), "hours")
    assert plan.requires_cdc


def test_longer_plan_does_not_require_cdc():
    plan = generate_cutover_plan(_stub_cfg(), "longer")
    assert not plan.requires_cdc


def test_plan_renders_as_markdown():
    plan = generate_cutover_plan(_stub_cfg(), "weekend")
    md = plan.to_markdown()
    assert "# Cutover Plan" in md
    assert "Cutover tolerance:" in md
    for i in range(1, len(plan.steps) + 1):
        assert f"{i}." in md
