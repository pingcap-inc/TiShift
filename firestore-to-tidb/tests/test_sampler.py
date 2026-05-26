"""Tests for the sample-size planning policy."""

from __future__ import annotations

from tishift_firestore.config import ScanConfig
from tishift_firestore.core.scan.sampler import plan_sample


def test_full_scan_below_threshold():
    cfg = ScanConfig(full_scan_threshold_docs=5000)
    plan = plan_sample("small", estimated_count=2000, cfg=cfg)
    assert plan.full_scan
    assert plan.target_sample_size == 2000


def test_default_sample_size_for_medium_collection():
    cfg = ScanConfig(sample_size_per_collection=200, full_scan_threshold_docs=5000)
    plan = plan_sample("medium", estimated_count=10000, cfg=cfg)
    assert not plan.full_scan
    # 1% of 10000 = 100; max(200, 100) = 200
    assert plan.target_sample_size == 200


def test_1_percent_for_large_collection():
    cfg = ScanConfig(sample_size_per_collection=200, full_scan_threshold_docs=5000)
    plan = plan_sample("large", estimated_count=1_000_000, cfg=cfg)
    # 1% = 10000; max(200, 10000) = 10000; capped at 5000
    assert plan.target_sample_size == 5000


def test_cap_at_5000():
    cfg = ScanConfig(sample_size_per_collection=200, full_scan_threshold_docs=5000)
    plan = plan_sample("huge", estimated_count=100_000_000, cfg=cfg)
    assert plan.target_sample_size == 5000
