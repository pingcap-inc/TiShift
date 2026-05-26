"""convert: generate TiDB DDL from scan report."""

from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path

import click
from rich.console import Console

from tishift_mongodb.config import load_config
from tishift_mongodb.core.convert.ddl_emitter import emit_ddl
from tishift_mongodb.core.convert.policy import decide_policy
from tishift_mongodb.core.scan.indexes import IndexField, IndexInfo
from tishift_mongodb.core.scan.type_inferrer import FieldHistogram


log = logging.getLogger(__name__)
console = Console()


@click.command()
@click.option("--config", "-c", required=True, type=click.Path(exists=True))
@click.option("--scan-report", "-r", required=True, type=click.Path(exists=True))
@click.option("--output-dir", "-o", default="tishift-output", type=click.Path())
@click.option("--dry-run", is_flag=True)
@click.option("--apply", is_flag=True)
def convert_cmd(config: str, scan_report: str, output_dir: str,
                dry_run: bool, apply: bool) -> None:
    """Generate DDL from a scan report; optionally apply CREATE TABLE to TiDB."""
    if dry_run and apply:
        raise click.UsageError("--dry-run and --apply are mutually exclusive.")
    if not dry_run and not apply:
        dry_run = True

    cfg = load_config(config)
    report = json.loads(Path(scan_report).read_text())

    histograms_by_collection = _reconstruct_histograms(report)
    indexes = _reconstruct_indexes(report)
    id_types = {c["name"]: c.get("id_type", "ObjectId") for c in report.get("collections", [])}

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
        id_types=id_types,
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
            h = FieldHistogram(field_path=path)
            h.type_counts = Counter(hist_dict.get("types", {}))
            ratio = hist_dict.get("presence_ratio", 1.0)
            h.sample_size = 100
            h.seen_count = int(100 * ratio)
            h.max_observed_string_len = hist_dict.get("max_observed_string_len", 0)
            h.max_observed_binary_size_mb = hist_dict.get("max_observed_binary_size_mb", 0.0)
            h.binary_subtypes_seen = Counter(hist_dict.get("binary_subtypes", {}))
            h.subdocument_keys_union = set(hist_dict.get("subdocument_keys", []))
            h.array_element_types = Counter(hist_dict.get("array_element_types", {}))
            out[c["name"]][path] = h
    return out


def _reconstruct_indexes(report: dict) -> list[IndexInfo]:
    out: list[IndexInfo] = []
    for idx in report.get("indexes", []):
        fields = [
            IndexField(name=f["name"], direction=f.get("direction", 1))
            for f in idx.get("fields", [])
        ]
        out.append(
            IndexInfo(
                name=idx.get("name", ""),
                collection=idx.get("collection", ""),
                fields=fields,
                unique=idx.get("unique", False),
                sparse=idx.get("sparse", False),
                ttl_seconds=idx.get("ttl_seconds"),
                partial_filter=idx.get("partial_filter"),
                is_geospatial=idx.get("is_geospatial", False),
                is_text=idx.get("is_text", False),
                is_wildcard=idx.get("is_wildcard", False),
            )
        )
    return out


def _apply_create_tables(cfg, ddl_path: Path) -> None:
    from tishift_mongodb.connection import tidb_connection
    sql = ddl_path.read_text()
    statements = [s.strip() for s in sql.split(";\n") if s.strip()]
    with tidb_connection(cfg.target) as conn:
        with conn.cursor() as cur:
            for stmt in statements:
                cur.execute(stmt)
            conn.commit()
    console.print(f"[green]Applied {len(statements)} CREATE TABLE statements.[/green]")
