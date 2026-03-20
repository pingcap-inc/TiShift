"""CLI report formatter — plain-text format matching Aurora TiShift output."""

from __future__ import annotations

from rich.console import Console

from tishift_mssql.models import ScanReport


_RATING_LABEL = {
    "excellent": "Excellent",
    "good": "Good",
    "moderate": "Moderate",
    "challenging": "Challenging",
    "difficult": "Difficult",
}

_BORDER = "  " + "═" * 59
_SEP = "    " + "─" * 57


def render_cli_report(report: ScanReport, console: Console) -> None:
    """Render the scan report as plain text matching the Aurora TiShift format."""
    scoring = report.scoring
    inv = report.schema_inventory
    auto = report.automation
    meta = report.sqlserver_metadata
    assessment = report.assessment

    total_gb = report.data_profile.total_data_mb / 1024
    sp_count = sum(1 for r in inv.routines if "PROCEDURE" in r.routine_type.upper())
    fn_count = sum(1 for r in inv.routines if "FUNCTION" in r.routine_type.upper())

    # ── Build plain-text output ──
    out = console.print

    out(_BORDER)
    out("    TiShift — Migration Readiness Report")
    out(_BORDER)
    out("")
    out(f"    Source: {report.source_host}")
    out(f"    SQL Server: {meta.edition or 'unknown'} ({meta.product_version or 'unknown'})")
    out(f"    Database: {report.database}")
    out(f"    Tables: {len(inv.tables)} | Total Size: {total_gb:.1f} GB")

    # ── Scoring Summary ──
    out("")
    out("    SCAN SCORING SUMMARY")
    out(_SEP)
    out(f"    {'Category':<24}{'Score':>5}  {'Max':>3}")
    for cat in [
        scoring.schema_compatibility,
        scoring.data_complexity,
        scoring.query_compatibility,
        scoring.code_portability,
        scoring.operational_readiness,
    ]:
        if cat is None:
            continue
        name = "Operational" if "Operational" in cat.name else cat.name
        out(f"    {name:<24}{cat.score:>5}  {cat.max_score:>3}")
    out(_SEP)

    rating = _RATING_LABEL.get(scoring.rating.value, scoring.rating.value)
    out(f"    Overall Score   {scoring.overall_score}/100")
    out(f"    Rating          {rating}")

    # ── Findings ──
    out("")
    out("    FINDINGS")
    out(_SEP)

    blocker_groups: dict[str, list] = {}
    for issue in assessment.blockers:
        blocker_groups.setdefault(issue.type, []).append(issue)

    out(f"    Blockers: {len(assessment.blockers)}")
    if not assessment.blockers:
        out("      (none)")
    for btype, issues in sorted(blocker_groups.items()):
        msg = issues[0].message
        suggestion = issues[0].suggestion or ""
        count_str = f" ({len(issues)})" if len(issues) > 1 else ""
        out(f"      • {btype}{count_str} — {msg}")
        if suggestion:
            out(f"        → {suggestion}")

    warning_groups: dict[str, list] = {}
    for issue in assessment.warnings:
        warning_groups.setdefault(issue.type, []).append(issue)

    out("")
    out(f"    Warnings: {len(assessment.warnings)}")
    for wtype, issues in sorted(warning_groups.items()):
        msg = issues[0].message
        count_str = f" ({len(issues)})" if len(issues) > 1 else ""
        suggestion = issues[0].suggestion or ""
        out(f"      • {wtype}{count_str} — {msg}")
        if suggestion:
            out(f"        → {suggestion}")

    # ── Automation Coverage ──
    out("")
    out("    AUTOMATION COVERAGE")
    out(_SEP)

    auto_desc = ", ".join(auto.fully_automated_includes[:4]) if auto.fully_automated_includes else ""
    ai_desc = ", ".join(auto.ai_assisted_includes[:2]) if auto.ai_assisted_includes else ""
    manual_desc = ", ".join(auto.manual_required_includes[:3]) if auto.manual_required_includes else ""

    auto_line = f"    Automated:    {auto.fully_automated_pct:>3.0f}%"
    if auto_desc:
        auto_line += f" — {auto_desc}"
    out(auto_line)

    ai_line = f"    AI-assisted:  {auto.ai_assisted_pct:>3.0f}%"
    if ai_desc:
        ai_line += f" — {ai_desc}"
    out(ai_line)

    manual_line = f"    Manual:       {auto.manual_required_pct:>3.0f}%"
    if manual_desc:
        manual_line += f" — {manual_desc}"
    out(manual_line)

    # ── Scanned Objects ──
    out("")
    out("    SCANNED OBJECTS")
    out(_SEP)
    out(
        f"    Tables {len(inv.tables):<4}  Columns {len(inv.columns):<4}  "
        f"Indexes {len(inv.indexes)}"
    )
    second_line = f"    Routines {sp_count + fn_count:<2}  Triggers {len(inv.triggers):<2}  Views {len(inv.views)}"
    if inv.assemblies:
        second_line += f"  CLR {len(inv.assemblies)}"
    if inv.agent_jobs:
        second_line += f"  Jobs {len(inv.agent_jobs)}"
    out(second_line)

    # ── Cost Comparison (optional) ──
    if report.cost_estimate:
        cost = report.cost_estimate
        out("")
        out("    COST COMPARISON")
        out(_SEP)
        out(f"    Current SQL Server Monthly:  ~${cost.estimated_monthly_sqlserver_license_usd:,.0f}")
        if cost.estimated_monthly_tidb_cloud_usd > 0:
            out(f"    Estimated TiDB Cloud:         ~${cost.estimated_monthly_tidb_cloud_usd:,.0f}")
            if cost.estimated_monthly_sqlserver_license_usd > 0:
                savings = (
                    (cost.estimated_monthly_sqlserver_license_usd - cost.estimated_monthly_tidb_cloud_usd)
                    / cost.estimated_monthly_sqlserver_license_usd * 100
                )
                out(f"    Projected Savings:            ~{savings:.0f}%")

    # ── CTA ──
    out("")
    out(_SEP)
    out("    TiDB Cloud Starter — free tier, no credit card required")
    out("    https://tidbcloud.com/free-trial")
    out(_BORDER)
    out("")
