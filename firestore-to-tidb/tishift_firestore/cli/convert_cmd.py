"""convert command — generate TiDB DDL from the scan report."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import click
from rich.console import Console

from tishift_firestore.config import load_config
from tishift_firestore.connection import tidb_connection
from tishift_firestore.core.convert import decide_policy, emit_ddl
from tishift_firestore.core.scan.indexes import CompositeIndex, IndexField
from tishift_firestore.core.scan.type_inferrer import FieldHistogram


log = logging.getLogger(__name__)
console = Console()


@click.command()
@click.option("--config", "-c", required=True, type=click.Path(exists=True))
@click.option("--scan-report", "-r", required=True, type=click.Path(exists=True))
@click.option("--output-dir", "-o", default="tishift-output", type=click.Path())
@click.option("--dry-run", is_flag=True, help="Emit SQL files but don't apply.")
@click.option("--apply", is_flag=True, help="Apply 01-create-tables.sql to TiDB.")
def convert_cmd(config: str, scan_report: str, output_dir: str,
                dry_run: bool, apply: bool) -> None:
    """Generate DDL from a scan report; optionally apply create-tables to TiDB."""
    if dry_run and apply:
        raise click.UsageError("--dry-run and --apply are mutually exclusive.")
    if not dry_run and not apply:
        dry_run = True

    cfg = load_config(config)
    report = json.loads(Path(scan_report).read_text())

    histograms_by_collection = _reconstruct_histograms(report)
    indexes = _reconstruct_indexes(report)

    plan = decide_policy(
        histograms_by_collection=histograms_by_collection,
        indexes=indexes,
        convert_cfg=cfg.convert,
    )
    artifact = emit_ddl(
        plan=plan,
        histograms_by_collection=histograms_by_collection,
        indexes=indexes,
        convert_cfg=cfg.convert,
    )

    out = Path(output_dir)
    artifact.write_all(out)
    log.info("Wrote DDL files to %s", out)

    flagged = [c for c in plan.collections if c.flagged_for_review]
    if flagged:
        console.print(
            f"[yellow]{len(flagged)} collection(s) have flagged-for-review fields. "
            "See convert-advisor.md.[/yellow]"
        )

    if apply:
        _apply_create_tables(cfg, out / "01-create-tables.sql")


def _reconstruct_histograms(report: dict) -> dict[str, dict[str, FieldHistogram]]:
    out: dict[str, dict[str, FieldHistogram]] = {}
    for c in report.get("collections", []):
        out[c["name"]] = {}
        for path, hist_dict in c.get("fields", {}).items():
            from collections import Counter
            h = FieldHistogram(field_path=path)
            h.type_counts = Counter(hist_dict.get("types", {}))
            ratio = hist_dict.get("presence_ratio", 1.0)
            h.sample_size = 100
            h.seen_count = int(100 * ratio)
            h.max_observed_string_len = hist_dict.get("max_observed_string_len", 0)
            h.max_observed_bytes_mb = hist_dict.get("max_observed_bytes_mb", 0.0)
            h.server_timestamp_sentinels_seen = hist_dict.get(
                "server_timestamp_sentinels_seen", 0
            )
            h.map_keys_union = set(hist_dict.get("map_keys_union", []))
            h.array_element_types = Counter(hist_dict.get("array_element_types", {}))
            out[c["name"]][path] = h
    return out


def _reconstruct_indexes(report: dict) -> list[CompositeIndex]:
    out: list[CompositeIndex] = []
    for idx in report.get("composite_indexes", []):
        fields = [
            IndexField(name=f["name"], order=f.get("order", "ASC"))
            for f in idx.get("fields", [])
        ]
        out.append(
            CompositeIndex(
                collection_or_group=idx["collection_or_group"],
                scope=idx.get("scope", "COLLECTION"),
                fields=fields,
            )
        )
    return out


def _apply_create_tables(cfg, ddl_path: Path) -> None:
    """Run each CREATE TABLE statement against TiDB."""
    sql = ddl_path.read_text()
    statements = [s.strip() for s in sql.split(";\n") if s.strip()]
    with tidb_connection(cfg.target) as conn:
        with conn.cursor() as cur:
            for stmt in statements:
                cur.execute(stmt)
            conn.commit()
    console.print(f"[green]Applied {len(statements)} CREATE TABLE statements.[/green]")
