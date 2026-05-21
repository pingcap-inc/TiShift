"""sync command — CDC bridge orchestration."""

from __future__ import annotations

import logging

import click
from rich.console import Console

from tishift_firestore.config import load_config
from tishift_firestore.core.sync import (
    build_install_manifest,
    generate_cutover_plan,
    start_bridge,
)
from tishift_firestore.core.sync.cutover import write_cutover_plan


log = logging.getLogger(__name__)
console = Console()


@click.group()
def sync_cmd() -> None:
    """CDC sync via the firestore-bigquery-export bridge."""


@sync_cmd.command("install-manifest")
@click.option("--config", "-c", required=True, type=click.Path(exists=True))
@click.option("--collections", "-C", required=True,
              help="Comma-separated collection names.")
@click.option("--output", "-o", default="tishift-output/sync-install.sh")
def install_manifest_cmd(config: str, collections: str, output: str) -> None:
    """Emit a shell script the customer runs to install firestore-bigquery-export per collection."""
    cfg = load_config(config)
    cols = [c.strip() for c in collections.split(",") if c.strip()]
    path = build_install_manifest(cfg, collections=cols, output_path=output)
    console.print(f"[green]Wrote install manifest to {path}[/green]")
    console.print(
        "[yellow]The customer must run this script ≥7 days before cutover.[/yellow]"
    )


@sync_cmd.command("start")
@click.option("--config", "-c", required=True, type=click.Path(exists=True))
@click.option("--since", required=True, help="ISO8601 timestamp of the load's read_time.")
@click.option("--collections", "-C", required=True,
              help="Comma-separated collection names.")
def start_cmd(config: str, since: str, collections: str) -> None:
    """Submit Dataflow streaming jobs that bridge BQ → TiDB."""
    cfg = load_config(config)
    cols = [c.strip() for c in collections.split(",") if c.strip()]
    job_ids = start_bridge(cfg, since_timestamp_iso=since, collections=cols)
    for jid in job_ids:
        console.print(f"  {jid}")


@sync_cmd.command("plan")
@click.option("--config", "-c", required=True, type=click.Path(exists=True))
@click.option("--tolerance",
              type=click.Choice(["minutes", "hours", "weekend", "longer"]),
              required=True)
@click.option("--output", "-o", default="tishift-output/cutover-plan.md")
def plan_cmd(config: str, tolerance: str, output: str) -> None:
    """Generate a tolerance-appropriate cutover plan."""
    cfg = load_config(config)
    plan = generate_cutover_plan(cfg, tolerance)  # type: ignore[arg-type]
    path = write_cutover_plan(plan, output)
    console.print(f"[green]Wrote cutover plan to {path}[/green]")
