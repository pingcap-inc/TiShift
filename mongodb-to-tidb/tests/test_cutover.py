"""Tests for cutover plan generation."""

from __future__ import annotations

from tishift_mongodb.config import (
    LoadConfig,
    SourceConfig,
    SyncConfig,
    TargetConfig,
    TiShiftConfig,
)
from tishift_mongodb.core.sync.cutover import generate_cutover_plan


def _stub_cfg(provider: str = "direct-changestream") -> TiShiftConfig:
    return TiShiftConfig(
        source=SourceConfig(
            uri="mongodb://h/d",
            database="d",
        ),
        target=TargetConfig(
            host="h", port=4000, user="u",
            password="pw",  # type: ignore[arg-type]
            database="d", tls=True, tier="byoc",
        ),
        sync=SyncConfig(provider=provider),  # type: ignore[arg-type]
    )


def test_weekend_no_cdc():
    plan = generate_cutover_plan(_stub_cfg(), "weekend")
    assert not plan.requires_cdc
    md = plan.to_markdown()
    assert "Cutover Plan" in md


def test_minutes_requires_cdc_direct():
    plan = generate_cutover_plan(_stub_cfg("direct-changestream"), "minutes")
    assert plan.requires_cdc
    assert plan.provider == "direct-changestream"
    assert any("direct-changestream" in s for s in plan.steps)


def test_hours_requires_cdc_dms():
    plan = generate_cutover_plan(_stub_cfg("aws-dms"), "hours")
    assert plan.requires_cdc
    assert plan.provider == "aws-dms"
    assert any("DMS" in s for s in plan.steps)


def test_debezium_provider():
    plan = generate_cutover_plan(_stub_cfg("debezium"), "minutes")
    assert plan.requires_cdc
    assert plan.provider == "debezium"
    assert any("Debezium" in s for s in plan.steps)


def test_longer_no_cdc():
    plan = generate_cutover_plan(_stub_cfg(), "longer")
    assert not plan.requires_cdc
