"""Preflight: verify connectivity, IAM, and API enablement before any phase."""

from __future__ import annotations

import json
import logging

import click
from rich.console import Console
from rich.table import Table

from tishift_firestore.config import load_config
from tishift_firestore.connection import firestore_client, firestore_admin_client, tidb_connection


log = logging.getLogger(__name__)
console = Console()


@click.command()
@click.option("--config", "-c", required=True, type=click.Path(exists=True))
@click.option("--format", "fmt", default="cli", type=click.Choice(["cli", "json"]))
def preflight_cmd(config: str, fmt: str) -> None:
    """Verify connectivity and IAM before running any other phase."""
    cfg = load_config(config)
    checks: dict[str, object] = {}

    # 1. Firestore reachable
    try:
        admin = firestore_admin_client(cfg.source)
        parent = f"projects/{cfg.source.project_id}"
        dbs = list(admin.list_databases(parent=parent).databases)
        checks["firestore_reachable"] = True
        checks["firestore_databases_listed"] = [d.name.split("/")[-1] for d in dbs]
    except Exception as e:  # noqa: BLE001
        checks["firestore_reachable"] = False
        checks["firestore_error"] = str(e)

    # 2. GCS bucket writable (probe via a tiny write)
    try:
        from google.cloud import storage
        client = storage.Client(project=cfg.source.project_id)
        bucket = client.bucket(cfg.source.staging.gcs_bucket)
        blob = bucket.blob(f"{cfg.source.staging.gcs_prefix}.preflight-probe")
        blob.upload_from_string("ok", content_type="text/plain")
        blob.delete()
        checks["gcs_bucket_writable"] = True
    except Exception as e:  # noqa: BLE001
        checks["gcs_bucket_writable"] = False
        checks["gcs_error"] = str(e)

    # 3. TiDB reachable
    try:
        with tidb_connection(cfg.target, read_only=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT VERSION() AS v")
                row = cur.fetchone()
                checks["tidb_reachable"] = True
                checks["tidb_version"] = row["v"] if row else None
    except Exception as e:  # noqa: BLE001
        checks["tidb_reachable"] = False
        checks["tidb_error"] = str(e)

    # 4. Verdict
    failures = [k for k, v in checks.items() if k.endswith("reachable") and v is False or
                k.endswith("writable") and v is False]
    checks["verdict"] = "READY" if not failures else "NOT_READY"

    if fmt == "json":
        click.echo(json.dumps(checks, indent=2))
        return

    table = Table(title="Preflight")
    table.add_column("Check")
    table.add_column("Result")
    for k, v in checks.items():
        table.add_row(k, str(v))
    console.print(table)

    if checks["verdict"] != "READY":
        raise SystemExit(1)
