"""Tests for BLOCKER and WARNING rule evaluation."""

from __future__ import annotations

from tishift_firestore.rules.compatibility import Checklist, Severity, evaluate


def test_blocker_mongo_api():
    cl = Checklist(mode="mongo-api")
    findings = evaluate(cl)
    ids = [f.rule_id for f in findings]
    assert "BLOCKER-1" in ids


def test_blocker_listeners():
    cl = Checklist(has_realtime_listeners=True)
    findings = evaluate(cl)
    blockers = [f for f in findings if f.severity == Severity.BLOCKER]
    assert any(f.rule_id == "BLOCKER-2" for f in blockers)


def test_blocker_complex_rules():
    cl = Checklist(security_rules_complexity="complex")
    findings = evaluate(cl)
    assert any(f.rule_id == "BLOCKER-3" for f in findings)


def test_blocker_poly_in_indexed():
    cl = Checklist(polymorphic_field_in_indexed_path=True)
    findings = evaluate(cl)
    assert any(f.rule_id == "BLOCKER-4" for f in findings)


def test_blocker_datastore_mode():
    cl = Checklist(mode="datastore")
    findings = evaluate(cl)
    assert any(f.rule_id == "BLOCKER-6" for f in findings)


def test_warning_geopoints():
    cl = Checklist(geopoint_field_count=3)
    findings = evaluate(cl)
    assert any(f.rule_id == "WARNING-1" for f in findings)


def test_warning_large_bytes():
    cl = Checklist(bytes_field_max_size_mb=10)
    findings = evaluate(cl)
    assert any(f.rule_id == "WARNING-2" for f in findings)


def test_warning_many_subcols():
    cl = Checklist(subcollection_count=100)
    findings = evaluate(cl)
    assert any(f.rule_id == "WARNING-3" for f in findings)


def test_warning_server_ts():
    cl = Checklist(server_timestamp_sentinel_detected=True)
    findings = evaluate(cl)
    assert any(f.rule_id == "WARNING-5" for f in findings)


def test_warning_sparse_fields():
    cl = Checklist(sparse_field_ratio=0.5)
    findings = evaluate(cl)
    assert any(f.rule_id == "WARNING-13" for f in findings)


def test_no_findings_on_minimal_checklist():
    """Default Checklist() — no listeners, no geopoints, no sparse fields, etc.

    Should still match a couple of safe defaults (auto-id, timestamps if present).
    Empty checklist has auto_id_generation_in_use=True → WARNING-10.
    """
    cl = Checklist()
    findings = evaluate(cl)
    # Auto-IDs default to True, so WARNING-10 fires.
    assert any(f.rule_id == "WARNING-10" for f in findings)


def test_at_least_5_blockers_and_3_warnings_exist():
    """PLAYBOOK quality gate: ≥5 BLOCKERs and ≥3 WARNINGs."""
    from tishift_firestore.rules.compatibility import ALL_RULES

    blockers_count = 0
    warnings_count = 0

    # Run each rule with a checklist that triggers it.
    # We do this by enumerating known IDs in the file rather than parsing.
    # Verify via the rule-ID prefix on a forced-positive Checklist.
    cl_all = Checklist(
        mode="mongo-api",  # B1
        has_realtime_listeners=True,  # B2
        security_rules_complexity="complex",  # B3
        polymorphic_field_in_indexed_path=True,  # B4
        multiple_databases_in_project=True,
        cross_database_references=True,  # B5
        geopoint_field_count=3,  # W1
        bytes_field_max_size_mb=10, bytes_field_count=200,  # W2
        subcollection_count=100,  # W3
        timestamp_field_count=5,  # W4
        server_timestamp_sentinel_detected=True,  # W5
        composite_index_count=200,  # W6
        polymorphic_field_count=10,  # W7
        total_data_gb_estimate=10000,  # W8
        document_reference_field_count=5,  # W9
        cutover_tolerance="minutes",  # W11
        sparse_field_ratio=0.5,  # W13
    )
    findings = evaluate(cl_all)
    blockers = [f for f in findings if f.severity == Severity.BLOCKER]
    warnings = [f for f in findings if f.severity == Severity.WARNING]
    assert len(blockers) >= 5
    assert len(warnings) >= 3
