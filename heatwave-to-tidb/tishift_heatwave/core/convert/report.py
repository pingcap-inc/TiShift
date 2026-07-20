"""DDL cleanup report writers — JSON (machine) and Markdown (human)."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from tishift_heatwave.models import DDLCleanupResult
from tishift_heatwave.rules.ddl_cleanup import ALL_RULES

_RISK_BADGE = {
    "info": "🔵 info",
    "assess": "🟠 needs assessment",
    "harmless": "🟢 harmless",
}
_AUTO_BADGE = {"yes": "✅ yes", "partial": "⚠️ partial", "no": "❌ not needed"}


def build_report(
    result: DDLCleanupResult,
    source_file: str,
    tier: str,
    tiflash_replicas: int,
) -> dict:
    counts = Counter(f.rule_id for f in result.findings)
    return {
        "source_file": source_file,
        "tier": tier,
        "tiflash_replicas": tiflash_replicas,
        "summary": {
            rule.rule_id: {
                "description": rule.description,
                "risk": rule.risk,
                "auto_cleanable": rule.auto_cleanable,
                "count": counts.get(rule.rule_id, 0),
            }
            for rule in ALL_RULES
        },
        "findings": [asdict(f) for f in result.findings],
        "rapid_tables": result.rapid_tables,
        "rapid_hint_tables": result.rapid_hint_tables,
        "fulltext_tables": result.fulltext_tables,
        "tiflash_statements": result.tiflash_statements,
        "parse_errors": result.parse_errors,
        "notes": [
            "Removed clauses are preserved as TISHIFT-REMOVED comments in the output SQL.",
            "TiFlash replicas are created before data load; TiFlash replicates during "
            "the import, which slows large loads. Drop and re-add replicas around the "
            "load window if import speed matters.",
        ],
    }


def render_markdown(report: dict) -> str:
    lines = [
        "# DDL Cleanup Report",
        "",
        f"- Source: `{report['source_file']}`",
        f"- Target tier: {report['tier']} · TiFlash replicas: {report['tiflash_replicas']}",
        "",
        "## Rule summary",
        "",
    ]
    # Rules with zero hits are omitted while any rule matched; when nothing
    # matched at all, every rule is shown (0 hits) as evidence of what was
    # checked. The JSON report always keeps the full rule set.
    hit_rules = {rid: s for rid, s in report["summary"].items() if s["count"]}
    display_rules = hit_rules or report["summary"]
    lines += ["| Rule | Syntax | Risk | Auto-cleanable | Hits |", "|---|---|---|---|---|"]
    for rule_id, s in display_rules.items():
        lines.append(
            f"| {rule_id} | {s['description']} | {_RISK_BADGE[s['risk']]} "
            f"| {_AUTO_BADGE[s['auto_cleanable']]} | {s['count']} |"
        )

    lines += ["", "## Findings", ""]
    if report["findings"]:
        lines += ["| Table | Rule | Action | Matched text |", "|---|---|---|---|"]
        for f in report["findings"]:
            lines.append(
                f"| {f['table'] or '-'} | {f['rule_id']} | {f['action_taken']} "
                f"| `{f['matched_text']}` |"
            )
    else:
        lines.append("No HeatWave-only syntax detected.")

    review = [f for f in report["findings"] if f["risk"] == "assess"]
    lines += ["", "## Manual review (🟠 needs assessment)", ""]
    if review:
        for f in review:
            lines.append(f"- **{f['table'] or '-'}** — `{f['matched_text']}`")
            if f.get("suggestion"):
                lines.append(f"  - Suggestion: {f['suggestion']}")
    else:
        lines.append("Nothing to review.")

    lines += ["", "## TiFlash replicas", ""]
    hint_tables = report.get("rapid_hint_tables", [])
    fulltext_tables = report.get("fulltext_tables", [])
    if report["tiflash_statements"]:
        lines += ["```sql", *report["tiflash_statements"], "```"]
    elif report["rapid_tables"] or hint_tables or fulltext_tables:
        lines.append(
            "RAPID (or hint/FULLTEXT-flagged) tables detected but no replica statements "
            f"emitted (replicas={report['tiflash_replicas']}) — "
            "see TISHIFT-INFO comments in the output SQL."
        )
    else:
        lines.append("No RAPID-offloaded tables detected.")
    if hint_tables:
        lines += [
            "",
            "Hint-derived tables (HW-DDL-5: RAPID_COLUMN comments without "
            "SECONDARY_ENGINE — verify RAPID offload status on the live system): "
            + ", ".join(f"`{t}`" for t in hint_tables),
        ]
    if fulltext_tables:
        lines += [
            "",
            "FULLTEXT-index tables (HW-DDL-6: parse-only outside Starter — the TiFlash "
            "replica accelerates scan-based full-text filtering; rewrite "
            "MATCH ... AGAINST queries): " + ", ".join(f"`{t}`" for t in fulltext_tables),
        ]

    if report["parse_errors"]:
        lines += ["", "## Parse errors (cleanup left invalid syntax — fix manually)", ""]
        lines += [f"- {e}" for e in report["parse_errors"]]

    lines += ["", "## Notes", ""]
    lines += [f"- {n}" for n in report["notes"]]
    return "\n".join(lines) + "\n"


def write_reports(
    result: DDLCleanupResult,
    output_dir: Path,
    source_file: str,
    tier: str,
    tiflash_replicas: int,
) -> tuple[Path, Path]:
    """Write JSON + Markdown reports; returns their paths."""
    output_dir.mkdir(parents=True, exist_ok=True)
    report = build_report(result, source_file, tier, tiflash_replicas)
    json_path = output_dir / "ddl-cleanup-report.json"
    md_path = output_dir / "ddl-cleanup-report.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    md_path.write_text(render_markdown(report))
    return json_path, md_path
