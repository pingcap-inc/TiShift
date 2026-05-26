"""scan: full scan + JSON report + Rich CLI summary."""

from __future__ import annotations

import logging

import click
from rich.console import Console
from rich.table import Table

from tishift_mongodb.config import load_config


log = logging.getLogger(__name__)
console = Console()


@click.command()
@click.option("--config", "-c", required=True, type=click.Path(exists=True))
@click.option("--format", "fmts", multiple=True,
              type=click.Choice(["cli", "json"]), default=["cli"])
@click.option("--output", "-o", default="tishift-reports/mongodb-scan-report.json",
              type=click.Path())
def scan_cmd(config: str, fmts: tuple[str, ...], output: str) -> None:
    """Sample MongoDB, infer schema (BSON-aware), inventory indexes + aggregations."""
    from tishift_mongodb.core.scan.reporter import run_scan
    cfg = load_config(config)
    report = run_scan(cfg)

    if "json" in fmts:
        report.write_json(output)
        log.info("Wrote scan report to %s", output)

    if "cli" in fmts:
        _print_report(report)


def _print_report(report) -> None:
    table = Table(title=f"Scan: {report.database} ({report.topology.topology})")
    table.add_column("Collection")
    table.add_column("Est. docs", justify="right")
    table.add_column("Sampled", justify="right")
    table.add_column("ID type")
    table.add_column("Fields", justify="right")
    table.add_column("Polymorphic", justify="right")

    for c in report.collections:
        poly = sum(1 for f in c.field_histograms.values() if f.is_polymorphic())
        table.add_row(
            c.name,
            f"{c.estimated_count:,}",
            f"{c.sampled_count:,}",
            c.id_type,
            str(len(c.field_histograms)),
            str(poly),
        )

    console.print(table)
    console.print(f"\n[bold]Mongo version:[/bold] {report.topology.mongo_version}")
    console.print(f"[bold]Indexes:[/bold] {len(report.indexes)}")
    console.print(f"[bold]Aggregation pipelines:[/bold] {len(report.aggregations)}")
    console.print(f"[bold]GridFS:[/bold] {report.has_gridfs}")
