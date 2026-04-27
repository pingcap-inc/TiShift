"""Top-level Click command group for `tishift-supabase`.

Subcommands (scan, convert, load, check, sync) are thin wrappers over the
core library. Business logic lives in tishift_supabase.core.*.
"""

from __future__ import annotations

from pathlib import Path

import click


@click.group()
@click.version_option()
def main() -> None:
    """Supabase → TiDB migration toolkit."""


@main.command()
@click.option("--config", "config_path", type=click.Path(path_type=Path, exists=True), required=True)
@click.option("--format", "formats", multiple=True,
              type=click.Choice(["cli", "json", "html", "pdf"]),
              default=("cli", "json"))
@click.option("--ai/--no-ai", default=False,
              help="Send PL/pgSQL and RLS expressions to AI for semantic classification.")
def scan(config_path: Path, formats: tuple[str, ...], ai: bool) -> None:
    """Read-only assessment: schema inventory, RLS findings, platform signals, score."""
    from ..core.scan import run_scan
    run_scan(config_path, formats=list(formats), ai=ai)


@main.command()
@click.option("--scan-report", type=click.Path(path_type=Path, exists=True), required=True)
@click.option("--output-dir", type=click.Path(path_type=Path), default=Path("./migration-output"))
@click.option("--dry-run/--apply", default=True)
@click.option("--uuid-type", type=click.Choice(["varchar", "binary"]), default="varchar")
def convert(scan_report: Path, output_dir: Path, dry_run: bool, uuid_type: str) -> None:
    """Generate TiDB DDL plus RLS rewrite checklist and external-work plan."""
    from ..core.convert import run_convert
    run_convert(scan_report, output_dir=output_dir, dry_run=dry_run, uuid_type=uuid_type)


@main.command()
@click.option("--config", "config_path", type=click.Path(path_type=Path, exists=True), required=True)
@click.option("--strategy", type=click.Choice(["auto", "direct", "dms", "ticloud", "lightning"]),
              default="auto")
@click.option("--fresh", is_flag=True, help="Ignore the continuation log and restart from scratch.")
def load(config_path: Path, strategy: str, fresh: bool) -> None:
    """Bulk data load. Strategy selected by tier + volume when 'auto'."""
    from ..core.load import run_load
    run_load(config_path, strategy=strategy, fresh=fresh)


@main.command()
@click.option("--config", "config_path", type=click.Path(path_type=Path, exists=True), required=True)
@click.option("--mode", type=click.Choice(["once", "live", "deep"]), default="once")
@click.option("--checksum", is_flag=True)
@click.option("--output", default="cli,json",
              help="Comma-separated output formats (cli, json, html).")
@click.option("--live-tolerance-pct", type=float, default=1.0)
def check(config_path: Path, mode: str, checksum: bool, output: str, live_tolerance_pct: float) -> None:
    """Validate source/target consistency."""
    from ..core.check import run_check
    run_check(
        config_path,
        mode=mode,
        checksum=checksum,
        outputs=[o.strip() for o in output.split(",")],
        live_tolerance_pct=live_tolerance_pct,
    )


@main.command()
@click.option("--config", "config_path", type=click.Path(path_type=Path, exists=True), required=True)
@click.option("--start", "action", flag_value="start")
@click.option("--stop", "action", flag_value="stop")
@click.option("--status", "action", flag_value="status", default=True)
def sync(config_path: Path, action: str) -> None:
    """Start, stop, or inspect the CDC bridge (Essential/Dedicated only)."""
    from ..core.sync import run_sync
    run_sync(config_path, action=action)


if __name__ == "__main__":
    main()
