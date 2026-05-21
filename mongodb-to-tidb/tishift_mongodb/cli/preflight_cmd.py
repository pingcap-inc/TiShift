"""preflight: verify connectivity, IAM, staging-writability."""

from __future__ import annotations

import json
import logging

import click
from rich.console import Console
from rich.table import Table

from tishift_mongodb.config import load_config


log = logging.getLogger(__name__)
console = Console()


@click.command()
@click.option("--config", "-c", required=True, type=click.Path(exists=True))
@click.option("--format", "fmt", default="cli", type=click.Choice(["cli", "json"]))
def preflight_cmd(config: str, fmt: str) -> None:
    """Verify connectivity before running any other phase."""
    cfg = load_config(config)
    checks: dict[str, object] = {}

    # 1. Mongo reachable
    try:
        from tishift_mongodb.connection import mongo_client
        from tishift_mongodb.core.scan.topology_detect import detect_topology
        client = mongo_client(cfg.source)
        topology = detect_topology(client)
        checks["mongo_reachable"] = True
        checks["mongo_topology"] = topology.topology
        checks["mongo_version"] = topology.mongo_version
    except Exception as e:  # noqa: BLE001
        checks["mongo_reachable"] = False
        checks["mongo_error"] = str(e)

    # 2. TiDB reachable
    try:
        from tishift_mongodb.connection import tidb_connection
        with tidb_connection(cfg.target, read_only=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT VERSION() AS v")
                row = cur.fetchone()
                checks["tidb_reachable"] = True
                checks["tidb_version"] = row["v"] if row else None
    except Exception as e:  # noqa: BLE001
        checks["tidb_reachable"] = False
        checks["tidb_error"] = str(e)

    # 3. Staging writable
    try:
        from tishift_mongodb.storage import ensure_writable
        ensure_writable(cfg.load.staging.base_url)
        checks["staging_writable"] = True
    except Exception as e:  # noqa: BLE001
        checks["staging_writable"] = False
        checks["staging_error"] = str(e)

    failures = [
        k for k, v in checks.items()
        if (k.endswith("reachable") or k.endswith("writable")) and v is False
    ]
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
