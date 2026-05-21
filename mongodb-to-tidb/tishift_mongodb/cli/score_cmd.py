"""score: assess compatibility + compute readiness score."""

from __future__ import annotations

import json
from pathlib import Path

import click
from rich.console import Console

from tishift_mongodb.config import load_config
from tishift_mongodb.rules.compatibility import Checklist, Severity, evaluate
from tishift_mongodb.rules.scoring import score


console = Console()


@click.command()
@click.option("--config", "-c", required=True, type=click.Path(exists=True))
@click.option("--scan-report", "-r", required=True, type=click.Path(exists=True))
@click.option("--cutover-tolerance",
              type=click.Choice(["minutes", "hours", "weekend", "longer"]),
              default="weekend")
def score_cmd(config: str, scan_report: str, cutover_tolerance: str) -> None:
    """Compute the readiness score from a scan report + user answers."""
    cfg = load_config(config)
    report = json.loads(Path(scan_report).read_text())

    checklist = _build_checklist(cfg=cfg, scan_report=report,
                                  cutover_tolerance=cutover_tolerance)
    findings = evaluate(checklist)
    score_report = score(checklist)

    _print_readiness(score_report, findings, report)


def _build_checklist(*, cfg, scan_report: dict, cutover_tolerance: str) -> Checklist:
    collections = scan_report.get("collections", [])
    indexes = scan_report.get("indexes", [])
    aggregations = scan_report.get("aggregations", [])

    polymorphic_count = 0
    sparse_count = 0
    total_fields = 0
    has_polymorphic_id = False
    geo = 0
    text = 0
    wild = 0
    partial = 0
    ttl = 0
    dbref = 0
    decimal128 = 0
    binary = 0
    csfle = 0
    date_fields = 0
    max_subdoc_depth = 0
    has_capped = False
    max_binary_mb = 0.0

    for c in collections:
        if c.get("has_polymorphic_id"):
            has_polymorphic_id = True
        if c.get("capped"):
            has_capped = True
        for path, hist in c.get("fields", {}).items():
            total_fields += 1
            types = hist.get("types", {})
            if hist.get("is_polymorphic"):
                polymorphic_count += 1
            if hist.get("is_sparse"):
                sparse_count += 1
            if "Decimal128" in types:
                decimal128 += 1
            if "Binary" in types:
                binary += 1
                if hist.get("has_csfle"):
                    csfle += 1
                max_binary_mb = max(max_binary_mb, hist.get("max_observed_binary_size_mb", 0))
            if "Date" in types:
                date_fields += 1
            if "DBRef" in types:
                dbref += 1
            depth = path.count(".")
            max_subdoc_depth = max(max_subdoc_depth, depth)

    for idx in indexes:
        if idx.get("is_geospatial"):
            geo += 1
        if idx.get("is_text"):
            text += 1
        if idx.get("is_wildcard"):
            wild += 1
        if idx.get("partial_filter"):
            partial += 1
        if idx.get("ttl_seconds") is not None:
            ttl += 1

    agg_total = sum(a.get("complexity", 0) for a in aggregations)
    sparse_ratio = sparse_count / total_fields if total_fields else 0

    largest = max((c.get("estimated_count", 0) for c in collections), default=0)
    total_data_gb = scan_report.get("data_profile", {}).get("total_storage_gb", 0.0)

    return Checklist(
        topology=scan_report.get("topology", "replica_set"),
        mongo_version=scan_report.get("mongo_version", "7.0"),
        collection_count=len(collections),
        total_data_gb_estimate=total_data_gb,
        composite_index_count=sum(1 for i in indexes if len(i.get("fields", [])) >= 2),
        geospatial_index_count=geo,
        text_index_count=text,
        wildcard_index_count=wild,
        partial_index_count=partial,
        ttl_index_count=ttl,
        dbref_field_count=dbref,
        decimal128_field_count=decimal128,
        binary_field_count=binary,
        csfle_field_count=csfle,
        date_field_count=date_fields,
        has_polymorphic_id=has_polymorphic_id,
        polymorphic_field_count=polymorphic_count,
        polymorphic_field_in_indexed_path=False,  # cross-checked separately
        sparse_field_ratio=sparse_ratio,
        subdocument_max_depth=max_subdoc_depth,
        largest_collection_doc_count=largest,
        has_capped_collections=has_capped,
        has_gridfs=scan_report.get("has_gridfs", False),
        binary_field_max_size_mb=max_binary_mb,
        aggregation_pipeline_count=len(aggregations),
        aggregation_complexity_total=agg_total,
        aggregation_advisor_enabled=cfg.convert.aggregation_advisor.enabled,
        cutover_tolerance=cutover_tolerance,
        target_tier=cfg.target.tier,
        storage_backend=cfg.load.staging.backend,
        load_strategy=cfg.load.strategy,
    )


def _print_readiness(score_report, findings, scan_report) -> None:
    """Print canonical ═══/─── readiness format."""
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
