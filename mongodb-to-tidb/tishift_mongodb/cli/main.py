"""Top-level Click entry point. Wires subcommands to the core library."""

from __future__ import annotations

import logging
import sys

import click
from rich.console import Console
from rich.logging import RichHandler

from tishift_mongodb import __version__
from tishift_mongodb.cli.preflight_cmd import preflight_cmd
from tishift_mongodb.cli.scan_cmd import scan_cmd
from tishift_mongodb.cli.score_cmd import score_cmd
from tishift_mongodb.cli.convert_cmd import convert_cmd
from tishift_mongodb.cli.load_cmd import load_cmd
from tishift_mongodb.cli.check_cmd import check_cmd
from tishift_mongodb.cli.sync_cmd import sync_cmd


console = Console()


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True)],
    )


@click.group()
@click.version_option(__version__, prog_name="tishift-mongodb")
@click.option("--log-level", default="INFO",
              type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"]))
def cli(log_level: str) -> None:
    """MongoDB → TiDB migration toolkit."""
    _configure_logging(log_level)


cli.add_command(preflight_cmd, name="preflight")
cli.add_command(scan_cmd, name="scan")
cli.add_command(score_cmd, name="score")
cli.add_command(convert_cmd, name="convert")
cli.add_command(load_cmd, name="load")
cli.add_command(check_cmd, name="check")
cli.add_command(sync_cmd, name="sync")


if __name__ == "__main__":
    sys.exit(cli())
