"""score command — assess compatibility + compute readiness score."""

from __future__ import annotations

import json
from pathlib import Path

import click
from rich.console import Console

from tishift_firestore.config import load_config
from tishift_firestore.rules.compatibility import Checklist, Severity, evaluate
from tishift_firestore.rules.scoring import score


console = Console()


@click.command()
@click.option("--config", "-c", required=True, type=click.Path(exists=True))
@click.option("--scan-report", "-r", required=True, type=click.Path(exists=True))
@click.option("--has-realtime-listeners/--no-realtime-listeners", default=False,
              help="Answer to Phase 2.2 Q1; default no.")
@click.option("--security-rules-complexity",
              type=click.Choice(["none", "simple", "moderate", "complex"]),
              default="simple")
@click.option("--cutover-tolerance",
              type=click.Choice(["minutes", "hours", "weekend", "longer"]),
              default="weekend")
def score_cmd(config: str, scan_report: str, has_realtime_listeners: bool,
              security_rules_complexity: str, cutover_tolerance: str) -> None:
    """Compute the readiness score from a scan report + user answers."""
    cfg = load_config(config)
    report = json.loads(Path(scan_report).read_text())

    checklist = _build_checklist(
        cfg=cfg, scan_report=report,
        has_realtime_listeners=has_realtime_listeners,
        security_rules_complexity=security_rules_complexity,
        cutover_tolerance=cutover_tolerance,
    )

    findings = evaluate(checklist)
    score_report = score(checklist)

    _print_readiness(score_report, findings, report)


def _build_checklist(*, cfg, scan_report: dict,
                     has_realtime_listeners: bool,
                     security_rules_complexity: str,
                     cutover_tolerance: str) -> Checklist:
    collections = scan_report.get("collections", [])
    indexes = scan_report.get("composite_indexes", [])

    total_polymorphic = 0
    total_fields = 0
    sparse_fields = 0
    has_geo = 0
    has_ts = 0
    has_bytes = 0
    server_ts = False
    subcols = 0
    largest = 0
    total_docs = 0

    for c in collections:
        if "/" in c["name"]:
            subcols += 1
        largest = max(largest, c.get("estimated_count", 0))
        total_docs += c.get("estimated_count", 0)
        for path, hist in c.get("fields", {}).items():
            total_fields += 1
            types = hist.get("types", {})
            if hist.get("is_polymorphic"):
                total_polymorphic += 1
            if hist.get("is_sparse"):
                sparse_fields += 1
            if "geopoint" in types:
                has_geo += 1
            if "timestamp" in types:
                has_ts += 1
            if "bytes" in types:
                has_bytes += 1
            if hist.get("server_timestamp_sentinels_seen", 0) > 0:
                server_ts = True

    sparse_ratio = sparse_fields / total_fields if total_fields else 0

    return Checklist(
        mode=scan_report.get("mode", "native"),
        edition=scan_report.get("edition", "standard"),
        collection_count=sum(1 for c in collections if "/" not in c["name"]),
        subcollection_count=subcols,
        total_document_count_estimate=total_docs,
        total_data_gb_estimate=scan_report.get("data_profile", {}).get("total_storage_gb", 0.0),
        composite_index_count=len(indexes),
        document_reference_field_count=0,  # populated by a deeper inspection pass
        geopoint_field_count=has_geo,
        bytes_field_count=has_bytes,
        bytes_field_max_size_mb=0.0,
        timestamp_field_count=has_ts,
        server_timestamp_sentinel_detected=server_ts,
        polymorphic_field_count=total_polymorphic,
        polymorphic_field_in_indexed_path=False,  # cross-checked separately
        sparse_field_ratio=sparse_ratio,
        subcollection_max_depth=max(
            (c["name"].count("/") for c in collections), default=0
        ) // 2,
        largest_collection_doc_count=largest,
        multiple_databases_in_project=scan_report.get("multiple_databases", False),
        has_realtime_listeners=has_realtime_listeners,
        security_rules_complexity=security_rules_complexity,
        cutover_tolerance=cutover_tolerance,
        firestore_bigquery_export_present=cfg.sync.enabled,
        target_tier=cfg.target.tier,
        byoc_in_same_gcp_project=cfg.target.tier == "byoc",
    )


def _print_readiness(score_report, findings, scan_report) -> None:
    """Print the canonical ═══/─── readiness format."""
    lines = []
    lines.append("READINESS SCORE")
    lines.append("═" * 57)
    lines.append(f"{'Category':<24}Score")
    for c in score_report.categories:
        lines.append(f"{c.name:<24}{c.score}/{c.max}")
    lines.append("─" * 57)
    lines.append(f"{'Overall':<24}{score_report.overall}/100  ({score_report.rating})")
    lines.append("")

    needs_work = [c for c in score_report.categories if c.score < c.max]
    if needs_work:
        lines.append("WHAT NEEDS WORK")
        lines.append("─" * 57)
        for c in needs_work:
            lines.append(f"{c.name} ({c.score}/{c.max}):")
            for reason, points in c.deductions:
                lines.append(f"  * {reason} (−{points})")
        lines.append("")

    ready = [c for c in score_report.categories if c.score == c.max]
    if ready:
        lines.append("WHAT'S READY")
        lines.append("─" * 57)
        for c in ready:
            lines.append(f"* {c.name}: {c.score}/{c.max}")
        lines.append("")

    blockers = [f for f in findings if f.severity == Severity.BLOCKER]
    warnings = [f for f in findings if f.severity == Severity.WARNING]
    if blockers:
        lines.append("BLOCKERS")
        lines.append("─" * 57)
        for f in blockers:
            lines.append(f"  [{f.rule_id}] {f.feature} — {f.action}")
        lines.append("")
    if warnings:
        lines.append("WARNINGS")
        lines.append("─" * 57)
        for f in warnings:
            lines.append(f"  [{f.rule_id}] {f.feature} — {f.action}")
        lines.append("")

    console.print("\n".join(lines))
