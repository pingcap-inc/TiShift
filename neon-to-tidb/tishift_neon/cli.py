"""TiShift Neon CLI — entry point for the tishift-neon command."""

import click

from tishift_neon import __version__


@click.group()
@click.version_option(version=__version__, prog_name="tishift-neon")
def main() -> None:
    """Neon/Postgres to TiDB migration toolkit."""


@main.command()
@click.option("--config", default="tishift-neon.yaml", help="Path to config file.")
@click.option("--database", default=None, help="Specific database to scan.")
@click.option("--ai", is_flag=True, help="Enable AI-powered PL/pgSQL analysis.")
@click.option("--format", "formats", multiple=True, default=("cli",), help="Output format(s).")
@click.option("--output-dir", default="./tishift-reports", help="Report output directory.")
@click.option("--quiet", is_flag=True, help="Suppress CLI output.")
def scan(
    config: str,
    database: str | None,
    ai: bool,
    formats: tuple[str, ...],
    output_dir: str,
    quiet: bool,
) -> None:
    """Scan a Neon/Postgres database and produce a readiness report."""
    click.echo("tishift-neon scan: not yet implemented")


@main.command()
@click.option("--scan-report", required=True, help="Path to scan report JSON.")
@click.option("--dry-run", is_flag=True, help="Preview without writing files.")
@click.option("--ai", is_flag=True, help="Enable AI-assisted PL/pgSQL conversion.")
@click.option("--output-dir", default="./tishift-reports", help="DDL output directory.")
def convert(scan_report: str, dry_run: bool, ai: bool, output_dir: str) -> None:
    """Convert Postgres schema to TiDB-compatible DDL."""
    click.echo("tishift-neon convert: not yet implemented")


@main.command()
@click.option("--config", default="tishift-neon.yaml", help="Path to config file.")
@click.option("--strategy", default="auto", help="Load strategy: auto, direct, dms, lightning.")
def load(config: str, strategy: str) -> None:
    """Load data from Neon/Postgres to TiDB."""
    click.echo("tishift-neon load: not yet implemented")


@main.command()
@click.option("--config", default="tishift-neon.yaml", help="Path to config file.")
@click.option("--output", default="cli,json", help="Output format(s).")
@click.option("--checksum", is_flag=True, help="Enable checksum validation.")
def check(config: str, output: str, checksum: bool) -> None:
    """Validate data integrity between source and target."""
    click.echo("tishift-neon check: not yet implemented")


@main.command()
@click.option("--config", default="tishift-neon.yaml", help="Path to config file.")
@click.option("--start", is_flag=True, help="Start CDC sync.")
@click.option("--stop", is_flag=True, help="Stop CDC sync.")
@click.option("--status", is_flag=True, help="Show sync status.")
def sync(config: str, start: bool, stop: bool, status: bool) -> None:
    """Manage CDC sync lifecycle."""
    click.echo("tishift-neon sync: not yet implemented")


if __name__ == "__main__":
    main()
