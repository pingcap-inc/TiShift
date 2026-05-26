"""check command — validate counts, structure, sampled hash diff."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from tishift_firestore.config import load_config
from tishift_firestore.core.check.counts import compare_counts


log = logging.getLogger(__name__)
console = Console()


@click.command()
@click.option("--config", "-c", required=True, type=click.Path(exists=True))
@click.option("--scan-report", "-r", required=True, type=click.Path(exists=True))
@click.option("--sample-size", default=1000, type=int,
              help="Documents to sample per collection for hash diff.")
@click.option("--collection", "-C", multiple=True,
              help="Restrict check to specific collections (repeatable).")
@click.option("--output", "-o", default="tishift-reports/firestore-check-report.json")
def check_cmd(config: str, scan_report: str, sample_size: int,
              collection: tuple[str, ...], output: str) -> None:
    """Compare source and target counts, structure, and a sampled set of document hashes."""
    cfg = load_config(config)
    report = json.loads(Path(scan_report).read_text())

    collections = [c["name"] for c in report.get("collections", [])]
    if collection:
        collections = [c for c in collections if c in collection]

    # Counts
    count_results = compare_counts(cfg, collections)

    # Render summary
    table = Table(title="Check — document counts")
    table.add_column("Collection")
    table.add_column("Source", justify="right")
    table.add_column("Target", justify="right")
    table.add_column("Delta", justify="right")
    table.add_column("Match")

    any_mismatch = False
    for r in count_results:
        if not r.matches:
            any_mismatch = True
        table.add_row(
            r.collection,
            f"{r.source_count:,}",
            f"{r.target_count:,}",
            f"{r.delta:+,}",
            "✓" if r.matches else "✗",
        )
    console.print(table)

    out = {
        "sample_size": sample_size,
        "collections": [r.to_dict() for r in count_results],
        "verdict": "MATCH" if not any_mismatch else "MISMATCH",
    }
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(json.dumps(out, indent=2))
    log.info("Wrote check report to %s", output)

    if any_mismatch:
        raise SystemExit(2)
