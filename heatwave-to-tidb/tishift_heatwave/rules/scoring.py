"""Readiness scoring constants — Phase 3 of SKILL.md (Assess & Score).

Single source of truth for category max points, rating bands, and per-unit
deduction constants, kept in lockstep with references/scoring.md. The actual
category-score computation lives in core/scan/analyzers/scoring.py — the
formulas (batching, thresholds, tier/version gating) are heterogeneous
enough that forcing them into one generic table would hurt readability more
than it would help reuse.
"""

from __future__ import annotations

CATEGORY_MAX_POINTS: dict[str, int] = {
    "Schema compatibility": 30,
    "Programmable objects": 25,
    "HeatWave surface": 20,
    "Data & load feasibility": 15,
    "Cutover & continue replication": 10,
}

# (low, high, rating) — checked in order, first match wins.
RATING_BANDS: list[tuple[int, int, str]] = [
    (85, 100, "READY"),
    (65, 84, "READY WITH WORK"),
    (40, 64, "SIGNIFICANT REWORK"),
    (0, 39, "NOT RECOMMENDED YET"),
]

# Free-tier storage cap; tiers absent from this dict have no modeled hard cap.
TIER_CAPACITY_BYTES: dict[str, int] = {
    "starter": 25 * 1024**3,
}

BATCH_SIZE = 10  # stored procedures / triggers deducted per batch of this many

POINTS = {
    "spatial_column_set": 5,  # BLOCKER-4, per distinct table
    "unsupported_charset_table": 5,  # BLOCKER-8, per distinct table
    "table_name_case_collision": 5,  # BLOCKER-9, per colliding name group
    "fulltext_index_no_real_index": 2,  # WARNING-2, per index
    "lower_case_table_names_mismatch": 2,  # WARNING-8, flat
    "updatable_view": 1,  # WARNING-9, per view
    "stored_procedure_batch": 5,  # BLOCKER-1, per batch of BATCH_SIZE
    "trigger_batch": 5,  # BLOCKER-2, per batch of BATCH_SIZE
    "event": 3,  # BLOCKER-3, per event
    "js_routine": 5,  # HW-BLOCKER-3, per routine
    "udfs_present": 5,  # BLOCKER-6, flat
    "lakehouse_present": 20,  # HW-BLOCKER-1, flat
    "automl_present": 10,  # HW-BLOCKER-2, flat
    "vector_column_set": 3,  # HW-WARNING-2, per distinct table
    "size_exceeds_tier_capacity": 5,  # flat
    "no_network_path": 5,  # flat
    "xa_present": 3,  # BLOCKER-5, flat
    "continue_replication_required_but_starter": 5,  # flat
    "log_bin_off": 5,  # HW-WARNING-6, flat
    "binlog_format_row_image_or_gtid": 3,  # HW-WARNING-7/8 or gtid_mode, flat
    "binlog_retention": 2,  # HW-WARNING-4, flat
    "binlog_row_value_options": 2,  # HW-WARNING-5, flat
    "binlog_transaction_compression": 2,  # HW-WARNING-9, flat
    "table_without_valid_index": 2,  # per table, only when continue replication is planned
}


def rating_for_score(score: int) -> str:
    for low, high, label in RATING_BANDS:
        if low <= score <= high:
            return label
    return "NOT RECOMMENDED YET"
