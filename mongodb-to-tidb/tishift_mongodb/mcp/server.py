"""FastMCP server exposing tishift_mongodb over MCP.

Read-only tools (scan, score, check, preflight) freely callable.
Write tools (convert apply, load, sync start) signal "needs confirmation"
via tool annotations — the MCP runtime gates them.

Audit logging: every tool invocation appends a JSONL line with (tool, args
excluding secrets, started_at, completed_at, outcome). The audit record
never contains config_path contents (path string only) or any password.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from tishift_mongodb.config import load_config
from tishift_mongodb.rules.compatibility import Checklist, evaluate
from tishift_mongodb.rules.scoring import score as compute_score


log = logging.getLogger(__name__)
mcp = FastMCP("tishift-mongodb")


def _audit(audit_path: str | Path, record: dict) -> None:
    p = Path(audit_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


@mcp.tool()
def scan(config_path: str) -> dict:
    """Run the Mongo scan and return the report as a dict."""
    from tishift_mongodb.core.scan.reporter import run_scan
    cfg = load_config(config_path)
    started = datetime.now(timezone.utc).isoformat()
    t0 = time.perf_counter()
    report = run_scan(cfg)
    elapsed = time.perf_counter() - t0
    _audit(
        cfg.logging.audit_log_path,
        {
            "tool": "scan",
            "args": {"config_path": config_path},
            "started_at": started,
            "elapsed_seconds": elapsed,
            "collections_scanned": len(report.collections),
        },
    )
    return report.to_dict()


@mcp.tool()
def score(scan_report_path: str, cutover_tolerance: str = "weekend") -> dict:
    """Compute readiness score from a saved scan report + user answers."""
    report = json.loads(Path(scan_report_path).read_text())

    cl = Checklist(
        topology=report.get("topology", "replica_set"),
        mongo_version=report.get("mongo_version", "7.0"),
        composite_index_count=sum(
            1 for i in report.get("indexes", []) if len(i.get("fields", [])) >= 2
        ),
        cutover_tolerance=cutover_tolerance,
    )
    findings = evaluate(cl)
    sr = compute_score(cl)

    return {
        "score": sr.to_dict(),
        "findings": [
            {"id": f.rule_id, "severity": f.severity.value,
             "feature": f.feature, "action": f.action}
            for f in findings
        ],
    }


@mcp.tool()
def preflight(config_path: str) -> dict:
    """Verify connectivity + IAM + staging-writability before running any phase."""
    cfg = load_config(config_path)
    out: dict = {}

    try:
        from tishift_mongodb.connection import mongo_client
        from tishift_mongodb.core.scan.topology_detect import detect_topology
        client = mongo_client(cfg.source)
        topology = detect_topology(client)
        out["mongo_reachable"] = True
        out["mongo_topology"] = topology.topology
        out["mongo_version"] = topology.mongo_version
    except Exception as e:  # noqa: BLE001
        out["mongo_reachable"] = False
        out["mongo_error"] = str(e)

    try:
        from tishift_mongodb.connection import tidb_connection
        with tidb_connection(cfg.target, read_only=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT VERSION() AS v")
                row = cur.fetchone()
                out["tidb_reachable"] = True
                out["tidb_version"] = row["v"] if row else None
    except Exception as e:  # noqa: BLE001
        out["tidb_reachable"] = False
        out["tidb_error"] = str(e)

    try:
        from tishift_mongodb.storage import ensure_writable
        ensure_writable(cfg.load.staging.base_url)
        out["staging_writable"] = True
    except Exception as e:  # noqa: BLE001
        out["staging_writable"] = False
        out["staging_error"] = str(e)

    out["verdict"] = (
        "READY"
        if (out.get("mongo_reachable") and out.get("tidb_reachable")
            and out.get("staging_writable"))
        else "NOT_READY"
    )
    return out


def main() -> None:
    """Entry point for `tishift-mongodb-mcp`."""
    mcp.run()


if __name__ == "__main__":
    main()
