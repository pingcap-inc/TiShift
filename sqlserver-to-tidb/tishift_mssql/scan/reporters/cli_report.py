"""CLI report formatter — matches the partner brief scan output format."""

from __future__ import annotations

from collections import Counter

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from tishift_mssql.models import ScanReport, Severity


_RATING_LABEL = {
    "excellent": "[bold green]Excellent[/bold green]",
    "good": "[bold yellow]Good[/bold yellow]",
    "moderate": "[bold dark_orange]Moderate[/bold dark_orange]",
    "challenging": "[bold red]Challenging[/bold red]",
    "difficult": "[bold red]Difficult[/bold red]",
}


def _score_color(score: int, max_score: int) -> str:
    ratio = score / max_score if max_score else 0
    if ratio >= 0.85:
        return "green"
    if ratio >= 0.70:
        return "yellow"
    if ratio >= 0.50:
        return "dark_orange"
    return "red"


def render_cli_report(report: ScanReport, console: Console) -> None:
    """Render the scan report in the compact partner-brief format."""
    scoring = report.scoring
    inv = report.schema_inventory
    auto = report.automation

    # -- Build the scoring summary panel --
    lines: list[str] = []

    # Header
    meta = report.sqlserver_metadata
    lines.append(f"  Source: {report.source_host}")
    lines.append(
        f"  SQL Server {meta.edition or 'unknown'} ({meta.product_version or 'unknown'})"
    )
    lines.append(
        f"  Database: {report.database}  |  "
        f"Tables: {len(inv.tables)}  |  "
        f"Total Size: {report.data_profile.total_data_mb / 1024:.1f} GB"
    )
    lines.append("")

    # Category scores table
    lines.append(f"  {'Category':<24} {'Score':>5}  {'Max':>3}")
    for cat in [
        scoring.schema_compatibility,
        scoring.data_complexity,
        scoring.query_compatibility,
        scoring.code_portability,
        scoring.operational_readiness,
    ]:
        if cat is None:
            continue
        # Use short name for Operational Readiness
        name = "Operational" if "Operational" in cat.name else cat.name
        lines.append(f"  {name:<24} {cat.score:>5}  {cat.max_score:>3}")

    lines.append("")
    rating_label = _RATING_LABEL.get(scoring.rating.value, scoring.rating.value)
    lines.append(f"  Overall Score    {scoring.overall_score}/100")
    lines.append(f"  Rating           {rating_label}")
    total_auto = auto.fully_automated_pct + auto.ai_assisted_pct
    lines.append(f"  Automation %     {total_auto:.1f}%")

    # Findings
    lines.append("")
    lines.append("  Findings")
    lines.append(f"  - Blockers: {len(report.assessment.blockers)}")
    if report.assessment.blockers:
        blocker_types = sorted({i.type for i in report.assessment.blockers})
        for bt in blocker_types:
            lines.append(f"    - {bt}")

    warning_types = sorted({i.type for i in report.assessment.warnings})
    lines.append(f"  - Warnings: {len(report.assessment.warnings)}")
    for wt in warning_types:
        lines.append(f"    - {wt}")

    # Scanned Objects — compact grid
    lines.append("")
    lines.append("  Scanned Objects")
    sp_count = sum(1 for r in inv.routines if "PROCEDURE" in r.routine_type.upper())
    fn_count = sum(1 for r in inv.routines if "FUNCTION" in r.routine_type.upper())
    lines.append(
        f"  Tables {len(inv.tables):>3}  Columns {len(inv.columns):>3}  "
        f"Indexes {len(inv.indexes):>3}"
    )
    lines.append(
        f"  Routines {sp_count + fn_count:>1}  Triggers {len(inv.triggers):>1}  "
        f"Views {len(inv.views):>1}"
    )

    console.print(
        Panel(
            "\n".join(lines),
            title="[bold]SCAN SCORING SUMMARY[/bold]",
            border_style="bright_blue",
            expand=False,
            padding=(1, 2),
        )
    )

    # -- Score Breakdown with deductions --
    scores_table = Table(title="Score Breakdown", show_lines=False, pad_edge=True)
    scores_table.add_column("Category", min_width=24)
    scores_table.add_column("Score", justify="right", min_width=8)
    scores_table.add_column("Deductions", ratio=1)

    for cat in [
        scoring.schema_compatibility,
        scoring.code_portability,
        scoring.query_compatibility,
        scoring.data_complexity,
        scoring.operational_readiness,
    ]:
        if cat is None:
            continue
        color = _score_color(cat.score, cat.max_score)
        deductions_str = "; ".join(cat.deductions[:3]) if cat.deductions else "—"
        if len(cat.deductions) > 3:
            deductions_str += f" (+{len(cat.deductions) - 3} more)"
        scores_table.add_row(
            cat.name,
            f"[{color}]{cat.score}/{cat.max_score}[/{color}]",
            deductions_str,
        )

    console.print(scores_table)

    # -- T-SQL Feature Usage --
    feature_counts: Counter[str] = Counter()
    for usage in report.feature_scan.usages:
        feature_counts[usage.pattern_name] += 1

    if feature_counts:
        console.print("\n[bold]T-SQL Feature Usage[/bold]")
        feat_table = Table(show_header=True, show_lines=False, pad_edge=True)
        feat_table.add_column("Feature", min_width=24)
        feat_table.add_column("Occurrences", justify="right")
        for name, count in feature_counts.most_common():
            feat_table.add_row(name.replace("_", " ").title(), str(count))
        console.print(feat_table)

    # -- Detailed Inventory --
    console.print("\n[bold]Inventory[/bold]")
    inv_table = Table(show_header=False, show_lines=False, pad_edge=True)
    inv_table.add_column("Metric", min_width=28)
    inv_table.add_column("Value", justify="right")
    inv_table.add_row("Stored Procedures", str(sp_count))
    inv_table.add_row("Functions", str(fn_count))
    inv_table.add_row("Triggers", str(len(inv.triggers)))
    inv_table.add_row("CLR Assemblies", str(len(inv.assemblies)))
    inv_table.add_row("SQL Agent Jobs", str(len(inv.agent_jobs)))
    inv_table.add_row("Linked Servers", str(len(inv.linked_servers)))
    inv_table.add_row("Views", str(len(inv.views)))
    inv_table.add_row("Schemas in Use", ", ".join(inv.schemas) if inv.schemas else "dbo")
    console.print(inv_table)

    # -- Issues Detail --
    console.print("\n[bold]Issues Found[/bold]")
    if report.assessment.blockers:
        console.print(f"  [bold red]BLOCKERS: {len(report.assessment.blockers)}[/bold red]")
        for issue in report.assessment.blockers[:10]:
            console.print(f"    [red]•[/red] [{issue.type}] {issue.object_name}: {issue.message}")
        if len(report.assessment.blockers) > 10:
            console.print(f"    ... and {len(report.assessment.blockers) - 10} more")
    else:
        console.print("  [green]No blockers found[/green]")

    if report.assessment.warnings:
        console.print(f"  [yellow]WARNINGS: {len(report.assessment.warnings)}[/yellow]")
        for issue in report.assessment.warnings[:10]:
            console.print(f"    [yellow]•[/yellow] [{issue.type}] {issue.object_name}: {issue.message}")
        if len(report.assessment.warnings) > 10:
            console.print(f"    ... and {len(report.assessment.warnings) - 10} more")

    # -- Automation Coverage --
    console.print("\n[bold]Automation Coverage[/bold]")
    est_table = Table(show_header=False, show_lines=False, pad_edge=True)
    est_table.add_column("Level", min_width=28)
    est_table.add_column("Pct", justify="right")
    est_table.add_row("[green]Automated[/green]", f"{auto.fully_automated_pct:.0f}%")
    est_table.add_row("[yellow]AI-Assisted (needs review)[/yellow]", f"{auto.ai_assisted_pct:.0f}%")
    est_table.add_row("[red]Manual Required[/red]", f"{auto.manual_required_pct:.0f}%")
    console.print(est_table)

    # -- Cost estimate (optional) --
    if report.cost_estimate:
        cost = report.cost_estimate
        console.print("\n[bold]Cost Estimate[/bold]")
        console.print(f"  SQL Server Monthly: ${cost.estimated_monthly_sqlserver_license_usd:,.0f}")
        for assumption in cost.assumptions:
            console.print(f"    • {assumption}")

    # -- TiDB Cloud CTA --
    console.print("")
    console.print("  [bold]Start free → https://tidbcloud.com/free-trial[/bold]")
    console.print("  Free Starter tier — no credit card required")
    console.print()
