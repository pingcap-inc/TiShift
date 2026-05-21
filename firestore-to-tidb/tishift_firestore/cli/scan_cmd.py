"""scan command — runs the full scan and writes the JSON report."""

from __future__ import annotations

import logging
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from tishift_firestore.config import load_config
from tishift_firestore.core.scan import run_scan


log = logging.getLogger(__name__)
console = Console()


@click.command()
@click.option("--config", "-c", required=True, type=click.Path(exists=True))
@click.option("--format", "fmts", multiple=True,
              type=click.Choice(["cli", "json"]), default=["cli"])
@click.option("--output", "-o", default="tishift-reports/firestore-scan-report.json",
              type=click.Path())
def scan_cmd(config: str, fmts: tuple[str, ...], output: str) -> None:
    """Sample Firestore collections, infer schema, list composite indexes."""
    cfg = load_config(config)
    report = run_scan(cfg)

    if "json" in fmts:
        report.write_json(output)
        log.info("Wrote scan report to %s", output)

    if "cli" in fmts:
        _print_report(report)


def _print_report(report) -> None:
    table = Table(title=f"Scan: {report.project_id}/{report.database_id} ({report.mode})")
    table.add_column("Collection")
    table.add_column("Est. docs")
    table.add_column("Sampled")
    table.add_column("Fields")
    table.add_column("Polymorphic")
    table.add_column("Subcollections")

    for c in report.collections:
        poly = sum(1 for f in c.field_histograms.values() if f.is_polymorphic())
        table.add_row(
            c.name,
            f"{c.estimated_count:,}",
            f"{c.sampled_count:,}",
            str(len(c.field_histograms)),
            str(poly),
            str(len(c.subcollection_names)),
        )

    console.print(table)
    console.print(f"\n[bold]Composite indexes:[/bold] {len(report.composite_indexes)}")
    console.print(f"[bold]Location:[/bold] {report.location}")
    console.print(f"[bold]Edition:[/bold] {report.edition}")
