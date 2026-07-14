"""Readiness scoring engine — Phase 3 of SKILL.md (Assess & Score).

Pure function over the same CompatibilityContext the compatibility analyzer
uses, plus a few scoring-only facts (total size, valid-index count, network
path, target TiDB version) bundled in ScoringContext. Reuses the exact same
rule.check() functions from rules/compatibility.py so the compatibility
findings and the score deductions can never disagree about what they're
counting.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from tishift_heatwave.models import CategoryScore, ReadinessScore
from tishift_heatwave.rules.compatibility import ALL_RULES, CompatibilityContext
from tishift_heatwave.rules.scoring import (
    BATCH_SIZE,
    CATEGORY_MAX_POINTS,
    POINTS,
    TIER_CAPACITY_BYTES,
    rating_for_score,
)


@dataclass
class ScoringContext:
    compat: CompatibilityContext
    total_size_bytes: int | None = None  # None = not measured / unknown
    tables_without_valid_index: int = 0
    network_path_confirmed: bool = True


def _rule_counts(compat_ctx: CompatibilityContext) -> dict[str, int]:
    return {rule.rule_id: rule.check(compat_ctx) for rule in ALL_RULES}


def _clamp(score: int, max_points: int) -> int:
    return max(0, min(score, max_points))


def _schema_compatibility(ctx: ScoringContext, counts: dict[str, int]) -> CategoryScore:
    max_points = CATEGORY_MAX_POINTS["Schema compatibility"]
    deductions: list[str] = []
    score = max_points

    spatial = counts["BLOCKER-4"]
    if spatial:
        points = spatial * POINTS["spatial_column_set"]
        score -= points
        deductions.append(f"-{points}: {spatial} table(s) with spatial columns (BLOCKER-4)")

    charset = counts["BLOCKER-8"]
    if charset:
        points = charset * POINTS["unsupported_charset_table"]
        score -= points
        deductions.append(
            f"-{points}: {charset} table(s) with an unsupported character set — only "
            f"ascii/latin1/binary/utf8/utf8mb4/gbk are supported (BLOCKER-8)"
        )

    case_collisions = counts["BLOCKER-9"]
    if case_collisions:
        points = case_collisions * POINTS["table_name_case_collision"]
        score -= points
        deductions.append(
            f"-{points}: {case_collisions} table name(s) collide once case is folded "
            f"(source lower_case_table_names != 2) (BLOCKER-9)"
        )

    collation = counts["WARNING-4"]
    if collation:
        deductions.append(
            f"-0: {collation} table(s) with utf8mb4_0900_* collation — maps 1:1, "
            f"supported natively on target TiDB v8.5, no penalty (WARNING-4)"
        )

    fulltext = counts["WARNING-2"]
    if fulltext:
        points = fulltext * POINTS["fulltext_index_no_real_index"]
        score -= points
        deductions.append(
            f"-{points}: {fulltext} FULLTEXT index(es) on {ctx.compat.tier} target — real "
            f"index support is Starter-only (WARNING-2)"
        )

    lc_mismatch = counts["WARNING-8"]
    if lc_mismatch:
        points = POINTS["lower_case_table_names_mismatch"]
        score -= points
        deductions.append(
            f"-{points}: lower_case_table_names={ctx.compat.metadata.lower_case_table_names} "
            f"on source; TiDB Cloud only supports 2 (WARNING-8)"
        )

    updatable_views = counts["WARNING-9"]
    if updatable_views:
        points = updatable_views * POINTS["updatable_view"]
        score -= points
        deductions.append(
            f"-{points}: {updatable_views} updatable view(s) — TiDB views are always "
            f"read-only (WARNING-9)"
        )

    return CategoryScore(
        name="Schema compatibility", max_points=max_points, score=_clamp(score, max_points), deductions=deductions
    )


def _programmable_objects(ctx: ScoringContext, counts: dict[str, int]) -> CategoryScore:
    max_points = CATEGORY_MAX_POINTS["Programmable objects"]
    deductions: list[str] = []
    score = max_points

    procs = counts["BLOCKER-1"]
    if procs:
        batches = math.ceil(procs / BATCH_SIZE)
        points = batches * POINTS["stored_procedure_batch"]
        score -= points
        deductions.append(f"-{points}: {procs} stored procedure(s) ({batches} batch(es) of {BATCH_SIZE}, BLOCKER-1)")

    triggers = counts["BLOCKER-2"]
    if triggers:
        batches = math.ceil(triggers / BATCH_SIZE)
        points = batches * POINTS["trigger_batch"]
        score -= points
        deductions.append(f"-{points}: {triggers} trigger(s) ({batches} batch(es) of {BATCH_SIZE}, BLOCKER-2)")

    events = counts["BLOCKER-3"]
    if events:
        points = events * POINTS["event"]
        score -= points
        deductions.append(f"-{points}: {events} scheduled event(s) (BLOCKER-3)")

    js_routines = counts["HW-BLOCKER-3"]
    if js_routines:
        points = js_routines * POINTS["js_routine"]
        score -= points
        deductions.append(f"-{points}: {js_routines} JavaScript (MLE) routine(s) (HW-BLOCKER-3)")

    if counts["BLOCKER-6"] > 0:
        points = POINTS["udfs_present"]
        score -= points
        deductions.append(f"-{points}: user-defined functions present (BLOCKER-6)")

    return CategoryScore(
        name="Programmable objects", max_points=max_points, score=_clamp(score, max_points), deductions=deductions
    )


def _heatwave_surface(ctx: ScoringContext, counts: dict[str, int]) -> CategoryScore:
    max_points = CATEGORY_MAX_POINTS["HeatWave surface"]
    deductions: list[str] = []
    score = max_points

    if counts["HW-BLOCKER-1"] > 0:
        points = POINTS["lakehouse_present"]
        score -= points
        deductions.append(f"-{points}: Lakehouse external tables present (HW-BLOCKER-1)")

    if counts["HW-BLOCKER-2"] > 0:
        points = POINTS["automl_present"]
        score -= points
        deductions.append(f"-{points}: AutoML/GenAI schemas present (HW-BLOCKER-2)")

    rapid = counts["HW-WARNING-1"]
    if rapid:
        deductions.append(f"-0: {rapid} RAPID-offloaded table(s) — maps to TiFlash, no penalty (HW-WARNING-1)")

    vectors = counts["HW-WARNING-2"]
    if vectors:
        points = vectors * POINTS["vector_column_set"]
        score -= points
        deductions.append(f"-{points}: {vectors} table(s) with VECTOR columns needing index rework (HW-WARNING-2)")

    return CategoryScore(
        name="HeatWave surface", max_points=max_points, score=_clamp(score, max_points), deductions=deductions
    )


def _data_and_load_feasibility(ctx: ScoringContext, counts: dict[str, int]) -> CategoryScore:
    max_points = CATEGORY_MAX_POINTS["Data & load feasibility"]
    deductions: list[str] = []
    score = max_points

    cap = TIER_CAPACITY_BYTES.get(ctx.compat.tier)
    if cap is not None and ctx.total_size_bytes is not None and ctx.total_size_bytes > cap:
        points = POINTS["size_exceeds_tier_capacity"]
        score -= points
        gib = ctx.total_size_bytes / 1024**3
        cap_gib = cap / 1024**3
        deductions.append(f"-{points}: total size {gib:.1f} GiB exceeds {ctx.compat.tier} capacity ({cap_gib:.0f} GiB)")

    if not ctx.network_path_confirmed:
        points = POINTS["no_network_path"]
        score -= points
        deductions.append(f"-{points}: no confirmed network path (bastion/tunnel) to the source")

    if counts["BLOCKER-5"] > 0:
        points = POINTS["xa_present"]
        score -= points
        deductions.append(f"-{points}: XA transactions detected (BLOCKER-5)")

    return CategoryScore(
        name="Data & load feasibility", max_points=max_points, score=_clamp(score, max_points), deductions=deductions
    )


def _cutover_and_continue_replication(ctx: ScoringContext, counts: dict[str, int]) -> CategoryScore:
    max_points = CATEGORY_MAX_POINTS["Cutover & continue replication"]
    deductions: list[str] = []
    score = max_points
    continue_replication_planned = ctx.compat.continue_replication_planned

    if continue_replication_planned and ctx.compat.tier == "starter":
        points = POINTS["continue_replication_required_but_starter"]
        score -= points
        deductions.append(
            f"-{points}: continue replication required but target tier is Starter (cutover-only)"
        )

    if counts["HW-WARNING-6"] > 0:
        points = POINTS["log_bin_off"]
        score -= points
        deductions.append(
            f"-{points}: log_bin is not ON — continue replication categorically impossible (HW-WARNING-6)"
        )

    gtid_bad = continue_replication_planned and (ctx.compat.metadata.gtid_mode or "").upper() != "ON"
    if counts["HW-WARNING-7"] > 0 or counts["HW-WARNING-8"] > 0 or gtid_bad:
        points = POINTS["binlog_format_row_image_or_gtid"]
        score -= points
        reasons = []
        if counts["HW-WARNING-7"] > 0:
            reasons.append("binlog_format != ROW (HW-WARNING-7)")
        if counts["HW-WARNING-8"] > 0:
            reasons.append("binlog_row_image != FULL (HW-WARNING-8)")
        if gtid_bad:
            reasons.append("gtid_mode != ON")
        deductions.append(f"-{points}: {', '.join(reasons)}")

    if counts["HW-WARNING-4"] > 0:
        points = POINTS["binlog_retention"]
        score -= points
        deductions.append(f"-{points}: binlog retention below recommended/minimum threshold (HW-WARNING-4)")

    if counts["HW-WARNING-5"] > 0:
        points = POINTS["binlog_row_value_options"]
        score -= points
        deductions.append(f"-{points}: binlog_row_value_options is not empty (HW-WARNING-5)")

    if counts["HW-WARNING-9"] > 0:
        points = POINTS["binlog_transaction_compression"]
        score -= points
        deductions.append(f"-{points}: binlog_transaction_compression is not OFF (HW-WARNING-9)")

    if continue_replication_planned and ctx.tables_without_valid_index > 0:
        points = ctx.tables_without_valid_index * POINTS["table_without_valid_index"]
        score -= points
        deductions.append(
            f"-{points}: {ctx.tables_without_valid_index} business table(s) without a PK/UNIQUE index"
        )

    return CategoryScore(
        name="Cutover & continue replication",
        max_points=max_points,
        score=_clamp(score, max_points),
        deductions=deductions,
    )


def compute_readiness_score(ctx: ScoringContext) -> ReadinessScore:
    """Compute the 0-100 readiness score with per-category breakdowns."""
    counts = _rule_counts(ctx.compat)

    categories = [
        _schema_compatibility(ctx, counts),
        _programmable_objects(ctx, counts),
        _heatwave_surface(ctx, counts),
        _data_and_load_feasibility(ctx, counts),
        _cutover_and_continue_replication(ctx, counts),
    ]

    overall = sum(c.score for c in categories)
    return ReadinessScore(overall=overall, categories=categories, rating=rating_for_score(overall))
