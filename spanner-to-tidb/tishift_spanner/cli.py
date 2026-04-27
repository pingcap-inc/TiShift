"""TiShift Spanner CLI — entry point for the tishift-spanner command."""

import click

from tishift_spanner import __version__


@click.group()
@click.version_option(version=__version__, prog_name="tishift-spanner")
def main() -> None:
    """Cloud Spanner to TiDB migration toolkit."""


@main.command()
@click.option("--config", default="tishift-spanner.yaml", help="Path to config file.")
@click.option("--format", "formats", multiple=True, default=("cli",), help="Output format(s).")
@click.option("--output-dir", default="./tishift-reports", help="Report output directory.")
@click.option("--quiet", is_flag=True, help="Suppress CLI output.")
def scan(config: str, formats: tuple[str, ...], output_dir: str, quiet: bool) -> None:
    """Scan a Cloud Spanner database and produce a readiness report."""
    click.echo("tishift-spanner scan: not yet implemented")


@main.command()
@click.option("--scan-report", required=True, help="Path to scan report JSON.")
@click.option("--dry-run", is_flag=True, help="Preview without writing files.")
@click.option("--output-dir", default="./tishift-reports", help="DDL output directory.")
def convert(scan_report: str, dry_run: bool, output_dir: str) -> None:
    """Convert Spanner schema to TiDB-compatible DDL."""
    click.echo("tishift-spanner convert: not yet implemented")


@main.command()
@click.option("--config", default="tishift-spanner.yaml", help="Path to config file.")
@click.option("--strategy", default="auto", help="Load strategy: auto, direct, dataflow, lightning.")
def load(config: str, strategy: str) -> None:
    """Load data from Cloud Spanner to TiDB via Dataflow/GCS."""
    click.echo("tishift-spanner load: not yet implemented")


@main.command()
@click.option("--config", default="tishift-spanner.yaml", help="Path to config file.")
@click.option("--output", default="cli,json", help="Output format(s).")
@click.option("--checksum", is_flag=True, help="Enable checksum validation.")
def check(config: str, output: str, checksum: bool) -> None:
    """Validate data integrity between source and target."""
    click.echo("tishift-spanner check: not yet implemented")


@main.command()
@click.option("--config", default="tishift-spanner.yaml", help="Path to config file.")
@click.option("--start", is_flag=True, help="Start CDC sync via change streams.")
@click.option("--stop", is_flag=True, help="Stop CDC sync.")
@click.option("--status", is_flag=True, help="Show sync status.")
def sync(config: str, start: bool, stop: bool, status: bool) -> None:
    """Manage CDC sync lifecycle via Spanner Change Streams."""
    click.echo("tishift-spanner sync: not yet implemented")


if __name__ == "__main__":
    main()
