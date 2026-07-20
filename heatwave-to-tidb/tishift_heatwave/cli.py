"""TiShift HeatWave CLI — entry point for the tishift-heatwave command."""

import click

from tishift_heatwave import __version__


@click.group()
@click.version_option(version=__version__, prog_name="tishift-heatwave")
def main() -> None:
    """MySQL HeatWave to TiDB migration toolkit."""


def _load_config_or_fail(config_path: str):
    """Load and validate the YAML config, converting the usual failure modes
    (missing file, invalid YAML, schema errors) into clean CLI errors instead
    of tracebacks."""
    from pathlib import Path

    from pydantic import ValidationError

    from tishift_heatwave.config import load_config

    try:
        return load_config(Path(config_path))
    except FileNotFoundError:
        raise click.ClickException(f"Config file not found: {config_path}") from None
    except ValidationError as exc:
        raise click.ClickException(f"Invalid config {config_path}:\n{exc}") from None


REPORT_FORMATS = ("cli", "json", "md")


@main.command()
@click.option("--config", default="tishift-heatwave.yaml", help="Path to config file.")
@click.option("--database", default=None, help="Schema to scan (default: source.database from config).")
@click.option(
    "--continue-replication",
    "--cdc",  # legacy alias
    "continue_replication_planned",
    is_flag=True,
    help=(
        "Include continue-replication (TiDB Cloud DM) readiness checks "
        "(binlog rules, valid-indexes precheck) in scoring."
    ),
)
@click.option(
    "--no-network-path",
    is_flag=True,
    help="Score as if no confirmed network path exists for the load phase (Data & load feasibility).",
)
@click.option("--ai", is_flag=True, help="Enable AI-powered stored-program analysis (not yet implemented).")
@click.option(
    "--format",
    "formats",
    multiple=True,
    default=(),
    help="Output format(s): cli, json, md (default: output.formats from config, else cli).",
)
@click.option(
    "--output-dir",
    default=None,
    help="Report output directory (default: output.dir from config).",
)
@click.option("--quiet", is_flag=True, help="Suppress the CLI text summary (files are still written).")
def scan(
    config: str,
    database: str | None,
    continue_replication_planned: bool,
    no_network_path: bool,
    ai: bool,
    formats: tuple[str, ...],
    output_dir: str | None,
    quiet: bool,
) -> None:
    """Scan a MySQL HeatWave DB System and produce a readiness report.

    Connects to the source, runs every scan collector (server metadata,
    replication topology, schema inventory, binlog / continue-replication
    precheck, and — with --continue-replication — the valid-indexes precheck),
    applies the compatibility rules and readiness scoring, and prints/writes
    the result.
    """
    from pathlib import Path

    import pymysql

    from tishift_heatwave.connection import connect_source
    from tishift_heatwave.core.scan.orchestrator import run_scan
    from tishift_heatwave.core.scan.report import build_report, render_cli, write_reports

    cfg = _load_config_or_fail(config)
    schema = database or cfg.source.database

    formats = formats or tuple(cfg.output.formats)
    formats = tuple("md" if f == "markdown" else f for f in formats)
    unsupported = sorted(set(formats) - set(REPORT_FORMATS))
    if unsupported:
        click.echo(
            f"Note: unsupported format(s) skipped: {', '.join(unsupported)} "
            f"(supported: {', '.join(REPORT_FORMATS)})."
        )

    try:
        conn = connect_source(cfg.source)
    except pymysql.Error as exc:
        raise click.ClickException(f"Could not connect to source: {exc}") from None

    try:
        result = run_scan(
            conn,
            schema,
            tier=cfg.target.tier,
            continue_replication_planned=continue_replication_planned,
            network_path_confirmed=not no_network_path,
        )
    finally:
        conn.close()

    report = build_report(result)

    if not quiet and "cli" in formats:
        click.echo(render_cli(report))

    out_dir = Path(output_dir or cfg.output.dir)
    written = write_reports(report, out_dir, formats)
    for fmt, path in written.items():
        click.echo(f"Wrote {fmt}: {path}")

    if ai:
        click.echo("Note: --ai stored-program analysis is not yet implemented.")


@main.command()
@click.option(
    "--ddl-file",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="SQL file with CREATE TABLE statements (SHOW CREATE TABLE / mysqldump output).",
)
@click.option("--scan-report", default=None, help="Path to scan report JSON (not yet implemented).")
@click.option(
    "--tier",
    default="starter",
    show_default=True,
    help="Target TiDB tier: starter, essential, dedicated, self-hosted.",
)
@click.option(
    "--tiflash-replicas",
    default=2,
    show_default=True,
    help="TiFlash replica count emitted after each RAPID table's CREATE TABLE (0 to disable).",
)
@click.option("--dry-run", is_flag=True, help="Print a diff and summary without writing files.")
@click.option("--output-dir", default="./tishift-reports", help="Output directory.")
def convert(
    ddl_file: str | None,
    scan_report: str | None,
    tier: str,
    tiflash_replicas: int,
    dry_run: bool,
    output_dir: str,
) -> None:
    """Convert HeatWave schema to TiDB-compatible DDL.

    HeatWave-only syntax is converted to plain MySQL comments (tagged
    TISHIFT-REMOVED) so the original clauses stay auditable in the output.
    Each RAPID-offloaded table gets `ALTER TABLE ... SET TIFLASH REPLICA n`
    emitted immediately after its CREATE TABLE statement.
    """
    import difflib
    from pathlib import Path

    from tishift_heatwave.core.convert.report import build_report, write_reports
    from tishift_heatwave.core.convert.schema_transformer import transform_schema

    if ddl_file is None:
        raise click.UsageError(
            "--ddl-file is required (scan-report-driven convert is not yet implemented)."
        )

    original = Path(ddl_file).read_text()
    result = transform_schema(original, tier=tier, tiflash_replicas=tiflash_replicas)
    report = build_report(result, ddl_file, tier, tiflash_replicas)

    if dry_run:
        diff = difflib.unified_diff(
            original.splitlines(keepends=True),
            result.sql.splitlines(keepends=True),
            fromfile=ddl_file,
            tofile="converted-schema.sql",
        )
        click.echo("".join(diff))
    else:
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        schema_path = out_dir / "converted-schema.sql"
        schema_path.write_text(result.sql)
        json_path, md_path = write_reports(result, out_dir, ddl_file, tier, tiflash_replicas)
        click.echo(f"Wrote {schema_path}")
        click.echo(f"Wrote {json_path}")
        click.echo(f"Wrote {md_path}")

    click.echo("")
    # Zero-hit rules are hidden while any rule matched; if nothing matched,
    # all rules are listed (0 hits) so the output shows what was checked.
    summary = report["summary"]
    display = {rid: s for rid, s in summary.items() if s["count"]} or summary
    for rule_id, s in display.items():
        click.echo(f"{rule_id}: {s['count']} hit(s) — {s['description']}")
    click.echo(
        f"RAPID tables: {len(result.rapid_tables)}; "
        f"hint-flagged tables (HW-DDL-5): {len(result.rapid_hint_tables)}; "
        f"FULLTEXT tables (HW-DDL-6): {len(result.fulltext_tables)}; "
        f"TiFlash statements emitted: {len(result.tiflash_statements)}"
    )
    review_count = sum(1 for f in result.findings if f.risk == "assess")
    if review_count:
        click.echo(f"⚠️  {review_count} finding(s) need manual review (see report).")
    if result.parse_errors:
        click.echo(f"❌ {len(result.parse_errors)} statement(s) failed re-parse after cleanup:")
        for err in result.parse_errors:
            click.echo(f"   {err}")
        raise SystemExit(1)


def _not_implemented(command: str, guide: str) -> None:
    """Stub exit for phases that are documented but not automated yet.

    Exits non-zero so scripts and CI cannot mistake the stub for a completed
    phase."""
    click.echo(f"tishift-heatwave {command} is not implemented yet — follow {guide} manually.")
    raise SystemExit(2)


@main.command()
@click.option("--config", default="tishift-heatwave.yaml", help="Path to config file.")
@click.option(
    "--strategy",
    default="auto",
    help="Load strategy: auto, direct, ticloud, lightning.",
)
def load(config: str, strategy: str) -> None:
    """Load data from HeatWave to TiDB — intentionally disabled.

    Data loading is deliberately excluded from this tool: it is a high-stakes
    step that must be performed independently by the user. docs/load-guide.md
    covers the manual path (Dumpling export, then tier-appropriate import).
    """
    click.echo(
        "tishift-heatwave load is intentionally disabled — data loading is a "
        "high-stakes step this tool does not handle. Complete it independently "
        "by following docs/load-guide.md."
    )
    raise SystemExit(2)


@main.command()
@click.option("--config", default="tishift-heatwave.yaml", help="Path to config file.")
@click.option("--output", default="cli,json", help="Output format(s).")
@click.option("--checksum", is_flag=True, help="Enable checksum validation.")
def check(config: str, output: str, checksum: bool) -> None:
    """Validate data integrity between source and target.

    Not implemented yet — docs/check-guide.md covers the manual path (row
    counts, structure diff, checksums, TiFlash replica availability).
    """
    _not_implemented("check", "docs/check-guide.md")


@main.command()
@click.option("--config", default="tishift-heatwave.yaml", help="Path to config file.")
def sync(config: str) -> None:
    """Run continue-replication prechecks for a HeatWave -> TiDB DM migration (Essential/Dedicated only).

    This command only verifies preconditions (source/target grants, binlog
    settings, PK/unique-index coverage). The DM migration task itself is
    created, started, monitored, and stopped in the TiDB Cloud console, not
    here — see docs/sync-guide.md.

    Not implemented yet — docs/sync-guide.md covers the manual prechecks.
    """
    _not_implemented("sync", "docs/sync-guide.md")


if __name__ == "__main__":
    main()
