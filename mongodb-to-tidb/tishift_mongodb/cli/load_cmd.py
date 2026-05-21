"""load: orchestrate bulk transfer."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import click
from rich.console import Console

from tishift_mongodb.config import load_config


log = logging.getLogger(__name__)
console = Console()


@click.command()
@click.option("--config", "-c", required=True, type=click.Path(exists=True))
@click.option("--scan-report", "-r", required=True, type=click.Path(exists=True))
@click.option("--strategy", default="auto",
              type=click.Choice([
                  "auto", "direct", "mongodump-lightning", "aws-dms", "datastream",
              ]))
@click.option("--cluster-id", default="", help="TiDB Cloud cluster ID (ticloud import).")
def load_cmd(config: str, scan_report: str, strategy: str, cluster_id: str) -> None:
    """Bulk-load MongoDB data into TiDB."""
    cfg = load_config(config)
    report = json.loads(Path(scan_report).read_text())

    if strategy == "auto":
        strategy = _auto_select(report, cfg)
        log.info("Auto-selected strategy: %s", strategy)

    collections = [c["name"] for c in report.get("collections", [])]

    if strategy == "direct":
        from tishift_mongodb.core.load.direct import load_direct
        results = load_direct(cfg, collections)
        for path, n in results.items():
            console.print(f"  {path}: {n:,} rows")
        return

    if strategy == "mongodump-lightning":
        from tishift_mongodb.core.load.mongodump_loader import run_mongodump_to_staging
        from tishift_mongodb.core.load.lightning import build_lightning_config, run_lightning
        counts = run_mongodump_to_staging(cfg)
        for c, n in counts.items():
            console.print(f"  staged {c}: {n:,} docs → {cfg.load.staging.base_url}")
        toml_path = build_lightning_config(cfg)
        console.print(f"[blue]Wrote Lightning config to {toml_path}[/blue]")
        rc = run_lightning(toml_path, tidb_password=cfg.target.password.get_secret_value())
        if rc != 0:
            raise SystemExit(rc)
        console.print("[green]Lightning ingest complete.[/green]")
        return

    if strategy == "aws-dms":
        from tishift_mongodb.core.load.dms_runner import emit_task_config
        path = emit_task_config(cfg)
        console.print(f"[blue]DMS task config: {path}[/blue]")
        console.print("[yellow]Apply via AWS CLI/Console; then poll with: "
                      "tishift-mongodb load --strategy aws-dms --poll[/yellow]")
        return

    if strategy == "datastream":
        from tishift_mongodb.core.load.datastream_bridge import emit_stream_config
        path = emit_stream_config(cfg)
        console.print(f"[blue]Datastream stream config: {path}[/blue]")
        console.print("[yellow]Apply via gcloud; then customer-side Datastream "
                      "writes to BigQuery and you bridge to TiDB.[/yellow]")
        return


def _auto_select(report: dict, cfg) -> str:
    size_gb = report.get("data_profile", {}).get("total_storage_gb", 0.0)
    if size_gb < 10:
        return "direct"
    if cfg.load.aws_dms.replication_instance_arn:
        return "aws-dms"
    if cfg.load.datastream.stream_id:
        return "datastream"
    return "mongodump-lightning"
