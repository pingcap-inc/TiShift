"""Tests for the readiness scoring engine."""

from __future__ import annotations

from tishift_firestore.rules.compatibility import Checklist
from tishift_firestore.rules.scoring import score


def test_perfect_score():
    cl = Checklist(
        mode="native",
        edition="standard",
        collection_count=10,
        total_data_gb_estimate=50,
        composite_index_count=5,
        has_realtime_listeners=False,
        security_rules_complexity="simple",
        cutover_tolerance="weekend",
        target_tier="byoc",
        byoc_in_same_gcp_project=True,
        firestore_bigquery_export_present=True,
    )
    s = score(cl)
    assert s.overall == 100
    assert s.rating == "EXCELLENT"


def test_listeners_drop_coupling():
    cl = Checklist(
        mode="native", edition="standard",
        composite_index_count=5,
        has_realtime_listeners=True,
        security_rules_complexity="simple",
    )
    s = score(cl)
    # Application Coupling category should lose 10 points
    coupling = next(c for c in s.categories if c.name == "Application Coupling")
    assert coupling.score == 10  # 20 - 10


def test_worked_example_from_scoring_md():
    """Matches the example in references/scoring.md."""
    cl = Checklist(
        mode="native", edition="standard",
        total_data_gb_estimate=7000,
        composite_index_count=87,
        polymorphic_field_count=8,
        polymorphic_field_in_indexed_path=False,
        sparse_field_ratio=0.18,
        subcollection_count=23,
        subcollection_max_depth=3,
        has_realtime_listeners=True,
        security_rules_complexity="moderate",
        server_timestamp_sentinel_detected=True,
        cutover_tolerance="weekend",
        target_tier="byoc",
        byoc_in_same_gcp_project=True,
        firestore_bigquery_export_present=True,
    )
    s = score(cl)
    # From scoring.md: 20 + 12 + 25 + 6 + 10 = 73
    assert s.overall == 73
    assert s.rating == "GOOD"


def test_mongo_api_redirects():
    cl = Checklist(mode="mongo-api")
    s = score(cl)
    schema = next(c for c in s.categories if c.name == "Schema Inferability")
    assert schema.score == 0


def test_categories_sum_to_100():
    """No deduction overflow — scores never exceed the max."""
    cl = Checklist()  # all defaults
    s = score(cl)
    assert sum(c.max for c in s.categories) == 100
    for c in s.categories:
        assert 0 <= c.score <= c.max


def test_data_complexity_decreases_with_size():
    small = Checklist(total_data_gb_estimate=10).model_copy()
    huge = Checklist(total_data_gb_estimate=10_000).model_copy()
    assert score(small).overall > score(huge).overall
