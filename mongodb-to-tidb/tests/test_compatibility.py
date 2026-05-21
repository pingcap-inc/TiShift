"""Tests for BLOCKER / WARNING rule evaluation."""

from __future__ import annotations

from tishift_mongodb.rules.compatibility import Checklist, Severity, evaluate


def test_blocker_standalone_cdc():
    cl = Checklist(topology="standalone", cutover_tolerance="hours")
    findings = evaluate(cl)
    assert any(f.rule_id == "BLOCKER-1" for f in findings)


def test_blocker_polymorphic_id():
    cl = Checklist(has_polymorphic_id=True)
    findings = evaluate(cl)
    assert any(f.rule_id == "BLOCKER-2" for f in findings)


def test_blocker_csfle():
    cl = Checklist(csfle_field_count=3)
    findings = evaluate(cl)
    assert any(f.rule_id == "BLOCKER-3" for f in findings)


def test_blocker_heavy_agg_no_advisor():
    cl = Checklist(aggregation_complexity_total=150, aggregation_advisor_enabled=False)
    findings = evaluate(cl)
    assert any(f.rule_id == "BLOCKER-4" for f in findings)


def test_blocker_poly_in_indexed():
    cl = Checklist(polymorphic_field_in_indexed_path=True)
    findings = evaluate(cl)
    assert any(f.rule_id == "BLOCKER-5" for f in findings)


def test_blocker_gridfs():
    cl = Checklist(has_gridfs=True)
    findings = evaluate(cl)
    assert any(f.rule_id == "BLOCKER-6" for f in findings)


def test_blocker_pre42_transactions():
    cl = Checklist(mongo_version="4.0", transaction_block_count=5)
    findings = evaluate(cl)
    assert any(f.rule_id == "BLOCKER-7" for f in findings)


def test_warning_geospatial():
    cl = Checklist(geospatial_index_count=3)
    findings = evaluate(cl)
    assert any(f.rule_id == "WARNING-1" for f in findings)


def test_warning_text_on_lower_tier():
    cl = Checklist(text_index_count=2, target_tier="starter")
    findings = evaluate(cl)
    assert any(f.rule_id == "WARNING-2" for f in findings)


def test_warning_wildcard():
    cl = Checklist(wildcard_index_count=1)
    findings = evaluate(cl)
    assert any(f.rule_id == "WARNING-3" for f in findings)


def test_warning_ttl_indexes():
    cl = Checklist(ttl_index_count=2)
    findings = evaluate(cl)
    assert any(f.rule_id == "WARNING-5" for f in findings)


def test_warning_sparse():
    cl = Checklist(sparse_field_ratio=0.5)
    findings = evaluate(cl)
    assert any(f.rule_id == "WARNING-13" for f in findings)


def test_warning_decimal128():
    cl = Checklist(decimal128_field_count=2)
    findings = evaluate(cl)
    assert any(f.rule_id == "WARNING-11" for f in findings)


def test_at_least_5_blockers_3_warnings():
    """PLAYBOOK quality gate: ≥5 BLOCKERs and ≥3 WARNINGs."""
    cl = Checklist(
        topology="standalone", cutover_tolerance="hours",
        has_polymorphic_id=True,
        csfle_field_count=3,
        aggregation_complexity_total=150, aggregation_advisor_enabled=False,
        polymorphic_field_in_indexed_path=True,
        has_gridfs=True,
        mongo_version="4.0", transaction_block_count=5,
        geospatial_index_count=2,
        text_index_count=1, target_tier="starter",
        wildcard_index_count=1,
        partial_index_count=1,
        ttl_index_count=1,
        has_capped_collections=True,
        aggregation_pipeline_count=10,
        decimal128_field_count=2,
        total_data_gb_estimate=2000,
        sparse_field_ratio=0.5,
        binary_field_max_size_mb=10,
    )
    findings = evaluate(cl)
    blockers = [f for f in findings if f.severity == Severity.BLOCKER]
    warnings = [f for f in findings if f.severity == Severity.WARNING]
    assert len(blockers) >= 5
    assert len(warnings) >= 3
