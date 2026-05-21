"""Tests for the readiness scoring engine."""

from __future__ import annotations

from tishift_mongodb.rules.compatibility import Checklist
from tishift_mongodb.rules.scoring import score


def test_perfect_score():
    cl = Checklist(
        topology="replica_set",
        mongo_version="7.0",
        composite_index_count=10,
        cutover_tolerance="weekend",
        target_tier="dedicated",
    )
    s = score(cl)
    assert s.overall == 100
    assert s.rating == "EXCELLENT"


def test_standalone_topology_hurts_ops():
    cl = Checklist(topology="standalone")
    s = score(cl)
    ops = next(c for c in s.categories if c.name == "Operational Readiness")
    assert ops.score <= 9  # 15 - 6 (standalone)


def test_aggregation_heavy_hurts_coupling():
    cl = Checklist(aggregation_complexity_total=250)
    s = score(cl)
    coupling = next(c for c in s.categories if c.name == "Application Coupling")
    assert coupling.score == 15  # 25 - 10


def test_polymorphic_id_hurts_inferability():
    cl = Checklist(has_polymorphic_id=True)
    s = score(cl)
    schema = next(c for c in s.categories if c.name == "Schema Inferability")
    assert schema.score == 14  # 20 - 6


def test_categories_sum_to_100():
    cl = Checklist()
    s = score(cl)
    assert sum(c.max for c in s.categories) == 100


def test_worked_example_from_scoring_md():
    """Matches references/scoring.md example."""
    cl = Checklist(
        topology="replica_set",
        mongo_version="7.0",
        total_data_gb_estimate=800,
        composite_index_count=45,
        geospatial_index_count=2,
        polymorphic_field_count=6,
        sparse_field_ratio=0.18,
        subdocument_max_depth=4,
        aggregation_pipeline_count=12,
        aggregation_complexity_total=75,
        cutover_tolerance="weekend",
        target_tier="byoc",
    )
    s = score(cl)
    # From scoring.md worked example: 86 / 100 → EXCELLENT
    assert s.overall == 86
    assert s.rating == "EXCELLENT"


def test_csfle_hurts_coupling():
    cl = Checklist(csfle_field_count=3)
    s = score(cl)
    coupling = next(c for c in s.categories if c.name == "Application Coupling")
    assert coupling.score == 20  # 25 - 5
