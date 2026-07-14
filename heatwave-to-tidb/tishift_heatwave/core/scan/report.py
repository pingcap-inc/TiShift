"""Scan report writers — JSON (machine), Markdown (human), CLI (terminal).

Mirrors the structure already established for the convert-phase report
(core/convert/report.py): build_report() assembles a plain dict matching the
Output Format documented in references/compatibility-rules.md and
references/scoring.md, then each renderer formats that same dict.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from tishift_heatwave.core.scan.orchestrator import ScanResult

_SEVERITY_BADGE = {"BLOCKER": "🔴", "WARNING": "🟠"}


def _human_bytes(n: int) -> str:
    size = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} {unit}"
        size /= 1024
    return f"{size:.1f} TiB"


def build_report(result: ScanResult) -> dict:
    inv = result.inventory
    meta = result.metadata

    fk_tables = {c.table_name for c in inv.constraints if c.constraint_type == "FOREIGN KEY"}
    auto_increment_tables = [t.table_name for t in inv.tables if t.auto_increment is not None]

    return {
        "schema": result.schema,
        "tier": result.tier,
        "continue_replication_planned": result.continue_replication_planned,
        "summary": {
            "table_count": len(inv.tables),
            "total_size_bytes": result.total_size_bytes,
            "index_count": len(inv.indexes),
            "column_count": len(inv.columns),
            "auto_increment_table_count": len(auto_increment_tables),
            "foreign_key_table_count": len(fk_tables),
            "rapid_table_count": len(inv.rapid_tables),
            "lakehouse_table_count": len(inv.lakehouse_tables),
            "automl_schema_count": len(inv.automl_schemas),
            "vector_column_count": len(inv.vector_columns),
            "js_routine_count": len(inv.js_routines),
            "stored_procedure_count": sum(1 for r in inv.routines if r.kind.upper() == "PROCEDURE"),
            "trigger_count": len(inv.triggers),
            "event_count": len(inv.events),
            "view_count": len(inv.views),
            "updatable_view_count": sum(1 for v in inv.views if v.is_updatable),
            "tables_without_valid_index_count": len(result.tables_without_valid_index),
        },
        "topology": {
            "mysql_version": meta.mysql_version,
            "version_comment": meta.version_comment,
            "has_rapid_cluster": meta.has_rapid_cluster,
            "rapid_node_count": meta.rapid_node_count,
            "lower_case_table_names": meta.lower_case_table_names,
            "read_only": meta.read_only,
            "super_read_only": meta.super_read_only,
            "is_replica": meta.is_replica,
            "replica_source_host": meta.replica_source_host,
            "connected_replica_count": meta.connected_replica_count,
            "connected_replica_hosts": meta.connected_replica_hosts,
        },
        "binlog_precheck": {
            "continue_replication_ready": result.binlog.continue_replication_ready,
            "checks": [asdict(c) for c in result.binlog.checks],
        },
        "tables_without_valid_index": [
            f"{schema}.{table}" for schema, table in result.tables_without_valid_index
        ],
        "assessment": {
            "blockers": [asdict(f) for f in result.assessment.blockers],
            "warnings": [asdict(f) for f in result.assessment.warnings],
            "compatible": result.assessment.compatible,
        },
        "score": {
            "overall": result.score.overall,
            "rating": result.score.rating,
            "categories": [asdict(c) for c in result.score.categories],
        },
    }


def render_cli(report: dict) -> str:
    s = report["summary"]
    t = report["topology"]
    lines = [
        "=== HeatWave Scan Report ===",
        f"Schema: {report['schema']}   Target tier: {report['tier']}   Continue replication planned: {'yes' if report['continue_replication_planned'] else 'no'}",
        "",
        "-- Summary --",
        f"Tables: {s['table_count']}   Total size: {_human_bytes(s['total_size_bytes'])}   "
        f"Indexes: {s['index_count']}   Columns: {s['column_count']}",
        f"Auto-increment tables: {s['auto_increment_table_count']}   "
        f"Foreign-key tables: {s['foreign_key_table_count']}",
        f"RAPID cluster: {'yes' if t['has_rapid_cluster'] else 'no'} "
        f"({t['rapid_node_count']} node(s))   RAPID-offloaded tables: {s['rapid_table_count']}",
        f"Lakehouse tables: {s['lakehouse_table_count']}   AutoML schemas: {s['automl_schema_count']}   "
        f"VECTOR columns: {s['vector_column_count']}",
        f"Stored procedures: {s['stored_procedure_count']}   Triggers: {s['trigger_count']}   "
        f"Events: {s['event_count']}   JS routines: {s['js_routine_count']}",
        f"Views: {s['view_count']} ({s['updatable_view_count']} updatable)   "
        f"lower_case_table_names: {t['lower_case_table_names']} (TiDB Cloud requires 2)",
    ]

    if t["is_replica"]:
        lines.append(f"Replication topology: secondary (replicating from {t['replica_source_host']})")
    elif t["connected_replica_count"]:
        lines.append(
            f"Replication topology: primary, {t['connected_replica_count']} downstream replica(s) "
            f"({', '.join(t['connected_replica_hosts'])})"
        )
    else:
        lines.append("Replication topology: standalone (no replicas detected)")

    if report["continue_replication_planned"]:
        lines.append(f"Tables without a valid index: {s['tables_without_valid_index_count']}")

    lines += ["", "-- Binlog / continue-replication readiness --", f"continue_replication_ready: {report['binlog_precheck']['continue_replication_ready']}"]
    for c in report["binlog_precheck"]["checks"]:
        marker = {"pass": "✅", "warn": "⚠️ ", "fail": "❌", "info": "ℹ️ "}[c["status"]]
        lines.append(f"  {marker} {c['variable']}: {c['actual']} (required: {c['required']})")

    blockers = report["assessment"]["blockers"]
    lines += ["", f"-- Blockers ({len(blockers)}) --"]
    if blockers:
        for f in blockers:
            lines.append(f"  🔴 {f['rule_id']}: {f['feature']} (count={f['count']})")
            lines.append(f"     -> {f['action']}")
    else:
        lines.append("  (none)")

    warnings = report["assessment"]["warnings"]
    lines += ["", f"-- Warnings ({len(warnings)}) --"]
    if warnings:
        for f in warnings:
            lines.append(f"  🟠 {f['rule_id']}: {f['feature']} (count={f['count']})")
            lines.append(f"     -> {f['action']}")
    else:
        lines.append("  (none)")

    score = report["score"]
    lines += ["", f"-- Readiness Score: {score['overall']}/100 ({score['rating']}) --"]
    for cat in score["categories"]:
        lines.append(f"  {cat['name']:<32s} {cat['score']:>3d}/{cat['max_points']}")
        for d in cat["deductions"]:
            lines.append(f"      {d}")

    return "\n".join(lines) + "\n"


def render_markdown(report: dict) -> str:
    s = report["summary"]
    t = report["topology"]
    score = report["score"]
    lines = [
        "# HeatWave Scan Report",
        "",
        f"- Schema: `{report['schema']}`",
        f"- Target tier: {report['tier']} · Continue replication planned: {report['continue_replication_planned']}",
        f"- MySQL version: {t['mysql_version']} ({t['version_comment'] or 'community build'})",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Tables | {s['table_count']} |",
        f"| Total size | {_human_bytes(s['total_size_bytes'])} |",
        f"| Indexes | {s['index_count']} |",
        f"| Columns | {s['column_count']} |",
        f"| Auto-increment tables | {s['auto_increment_table_count']} |",
        f"| Foreign-key tables | {s['foreign_key_table_count']} |",
        f"| RAPID cluster | {'yes' if t['has_rapid_cluster'] else 'no'} ({t['rapid_node_count']} node(s)) |",
        f"| RAPID-offloaded tables | {s['rapid_table_count']} |",
        f"| Lakehouse tables | {s['lakehouse_table_count']} |",
        f"| AutoML schemas | {s['automl_schema_count']} |",
        f"| VECTOR columns | {s['vector_column_count']} |",
        f"| Stored procedures / Triggers / Events / JS routines | "
        f"{s['stored_procedure_count']} / {s['trigger_count']} / {s['event_count']} / {s['js_routine_count']} |",
        f"| Views (updatable) | {s['view_count']} ({s['updatable_view_count']}) |",
        f"| lower_case_table_names | {t['lower_case_table_names']} (TiDB Cloud requires 2) |",
    ]
    if report["continue_replication_planned"]:
        lines.append(f"| Tables without a valid index | {s['tables_without_valid_index_count']} |")

    lines += ["", "## Replication topology", ""]
    if t["is_replica"]:
        lines.append(f"Secondary — replicating from `{t['replica_source_host']}`.")
    elif t["connected_replica_count"]:
        hosts = ", ".join(t["connected_replica_hosts"])
        lines.append(f"Primary — {t['connected_replica_count']} downstream replica(s): {hosts}.")
    else:
        lines.append("Standalone — no replicas detected.")

    lines += ["", "## Binlog / continue-replication readiness", "", f"`continue_replication_ready = {report['binlog_precheck']['continue_replication_ready']}`", ""]
    lines += ["| Variable | Status | Actual | Required | Rule |", "|---|---|---|---|---|"]
    for c in report["binlog_precheck"]["checks"]:
        lines.append(f"| {c['variable']} | {c['status']} | {c['actual']} | {c['required']} | {c['rule_id'] or '-'} |")

    lines += ["", "## Blockers", ""]
    if report["assessment"]["blockers"]:
        lines += ["| Rule | Feature | Count | Action |", "|---|---|---|---|"]
        for f in report["assessment"]["blockers"]:
            lines.append(f"| {f['rule_id']} | {f['feature']} | {f['count']} | {f['action']} |")
    else:
        lines.append("None detected.")

    lines += ["", "## Warnings", ""]
    if report["assessment"]["warnings"]:
        lines += ["| Rule | Feature | Count | Action |", "|---|---|---|---|"]
        for f in report["assessment"]["warnings"]:
            lines.append(f"| {f['rule_id']} | {f['feature']} | {f['count']} | {f['action']} |")
    else:
        lines.append("None detected.")

    lines += ["", f"## Readiness Score: {score['overall']}/100 ({score['rating']})", ""]
    lines += ["| Category | Score | Deductions |", "|---|---|---|"]
    for cat in score["categories"]:
        deductions = "<br>".join(cat["deductions"]) if cat["deductions"] else "-"
        lines.append(f"| {cat['name']} | {cat['score']}/{cat['max_points']} | {deductions} |")

    return "\n".join(lines) + "\n"


def write_reports(report: dict, output_dir: Path, formats: tuple[str, ...]) -> dict[str, Path]:
    """Write the requested report formats; returns {format: path} for files written."""
    written: dict[str, Path] = {}
    if "json" in formats:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "tishift-heatwave-report.json"
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
        written["json"] = path
    if "md" in formats or "markdown" in formats:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "tishift-heatwave-report.md"
        path.write_text(render_markdown(report))
        written["md"] = path
    return written
