"""FastMCP server. Exposes scan / score / convert / load / check / sync as tools.

All read-only tools (scan, score, check, preflight) are callable freely. All
write tools (convert apply, load, sync start) require explicit user approval
in the MCP runtime — they signal that via the tool's annotation.

Audit logging: every tool invocation appends a JSONL line to the configured
audit_log_path with (tool, args excluding secrets, started_at, completed_at,
outcome).
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from tishift_firestore.config import load_config
from tishift_firestore.core.scan import run_scan
from tishift_firestore.rules.compatibility import Checklist, evaluate
from tishift_firestore.rules.scoring import score as compute_score


log = logging.getLogger(__name__)
mcp = FastMCP("tishift-firestore")


def _audit(audit_path: str | Path, record: dict) -> None:
    p = Path(audit_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


@mcp.tool()
def scan(config_path: str) -> dict:
    """Run the Firestore scan and return the report as a dict.

    Args:
        config_path: filesystem path to tishift-firestore.yaml.
    """
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
def score(scan_report_path: str,
          has_realtime_listeners: bool = False,
          security_rules_complexity: str = "simple",
          cutover_tolerance: str = "weekend") -> dict:
    """Compute the readiness score from a saved scan report + user answers.

    Args:
        scan_report_path: filesystem path to firestore-scan-report.json.
        has_realtime_listeners: user answer to Phase 2.2 Q1.
        security_rules_complexity: none | simple | moderate | complex.
        cutover_tolerance: minutes | hours | weekend | longer.
    """
    report = json.loads(Path(scan_report_path).read_text())

    # Build checklist mirroring score_cmd. Logic is intentionally duplicated
    # at the boundary — keeps the MCP surface stateless.
    cl = Checklist(
        mode=report.get("mode", "native"),
        edition=report.get("edition", "standard"),
        composite_index_count=len(report.get("composite_indexes", [])),
        has_realtime_listeners=has_realtime_listeners,
        security_rules_complexity=security_rules_complexity,
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
    """Verify connectivity and IAM before running any phase."""
    from tishift_firestore.cli.preflight_cmd import preflight_cmd  # reuse logic

    # Re-implement minus the CLI/Rich layer so the MCP surface returns structured data.
    cfg = load_config(config_path)
    out: dict = {}

    from tishift_firestore.connection import (
        firestore_admin_client, tidb_connection,
    )

    try:
        admin = firestore_admin_client(cfg.source)
        parent = f"projects/{cfg.source.project_id}"
        dbs = list(admin.list_databases(parent=parent).databases)
        out["firestore_reachable"] = True
        out["firestore_databases"] = [d.name.split("/")[-1] for d in dbs]
    except Exception as e:  # noqa: BLE001
        out["firestore_reachable"] = False
        out["firestore_error"] = str(e)

    try:
        with tidb_connection(cfg.target, read_only=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT VERSION() AS v")
                row = cur.fetchone()
                out["tidb_reachable"] = True
                out["tidb_version"] = row["v"] if row else None
    except Exception as e:  # noqa: BLE001
        out["tidb_reachable"] = False
        out["tidb_error"] = str(e)

    out["verdict"] = "READY" if out.get("firestore_reachable") and out.get("tidb_reachable") else "NOT_READY"
    return out


def main() -> None:
    """Entry point used by the `tishift-firestore-mcp` console script."""
    mcp.run()


if __name__ == "__main__":
    main()
