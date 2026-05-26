"""load command — bulk transfer Firestore → TiDB via Dataflow or direct path."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import click
from rich.console import Console

from tishift_firestore.config import load_config
from tishift_firestore.core.load import (
    build_cloudimport_request,
    build_lightning_config,
    load_direct,
    submit_dataflow_jobs,
)
from tishift_firestore.core.load.lightning import run_lightning


log = logging.getLogger(__name__)
console = Console()


@click.command()
@click.option("--config", "-c", required=True, type=click.Path(exists=True))
@click.option("--scan-report", "-r", required=True, type=click.Path(exists=True))
@click.option("--strategy", default="auto",
              type=click.Choice([
                  "auto", "direct", "dataflow-cloudimport",
                  "dataflow-lightning", "dataflow-lightning-sharded",
              ]))
@click.option("--resume", type=click.Path(exists=True), default=None)
@click.option("--cluster-id", default="", help="TiDB Cloud Serverless cluster ID (cloudimport only).")
def load_cmd(config: str, scan_report: str, strategy: str,
             resume: str | None, cluster_id: str) -> None:
    """Bulk-load data from Firestore into TiDB."""
    cfg = load_config(config)
    report = json.loads(Path(scan_report).read_text())

    if strategy == "auto":
        strategy = _auto_select(report, cfg)
        log.info("Auto-selected strategy: %s", strategy)

    collections = [c["name"] for c in report.get("collections", [])]

    if strategy == "direct":
        results = load_direct(cfg, collections)
        for path, n in results.items():
            console.print(f"  {path}: {n:,} rows")
        return

    # All non-direct strategies go through Dataflow + GCS NDJSON.
    read_time = datetime.now(timezone.utc).isoformat()
    state = submit_dataflow_jobs(
        cfg,
        collections=collections,
        state_path=resume or "tishift-output/.load-state.json",
        read_time_iso=read_time,
    )

    if strategy in ("dataflow-lightning", "dataflow-lightning-sharded"):
        cfg_path = build_lightning_config(cfg, state=state)
        console.print(f"[blue]Wrote Lightning config to {cfg_path}[/blue]")
        # Pass the target password to Lightning via env, not via the on-disk TOML.
        rc = run_lightning(cfg_path, tidb_password=cfg.target.password.get_secret_value())
        if rc == 0:
            console.print("[green]Lightning ingest complete.[/green]")
        else:
            console.print(f"[red]Lightning exit code: {rc}[/red]")
            raise SystemExit(rc)

    elif strategy == "dataflow-cloudimport":
        if not cluster_id:
            raise click.UsageError("--cluster-id is required for dataflow-cloudimport.")
        req = build_cloudimport_request(cfg, cluster_id=cluster_id, state=state)
        console.print(f"[blue]Cloud Import: {' '.join(req.to_cli_args())}[/blue]")
        from tishift_firestore.core.load.ticloud_import import submit_cloudimport
        rc = submit_cloudimport(req)
        if rc == 0:
            console.print("[green]Cloud Import submitted.[/green]")
        else:
            raise SystemExit(rc)


def _auto_select(report: dict, cfg) -> str:
    """Auto-select a load strategy based on size and tier."""
    size_gb = report.get("data_profile", {}).get("total_storage_gb", 0.0)
    tier = cfg.target.tier

    if size_gb < 10:
        return "direct"
    if tier in ("starter", "essential"):
        return "dataflow-cloudimport"
    if size_gb > 10_000:
        return "dataflow-lightning-sharded"
    return "dataflow-lightning"
