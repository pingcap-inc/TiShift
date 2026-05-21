"""Top-level Click entry point. Wires subcommands to core library functions."""

from __future__ import annotations

import logging
import sys

import click
from rich.console import Console
from rich.logging import RichHandler

from tishift_firestore import __version__
from tishift_firestore.cli.scan_cmd import scan_cmd
from tishift_firestore.cli.score_cmd import score_cmd
from tishift_firestore.cli.convert_cmd import convert_cmd
from tishift_firestore.cli.load_cmd import load_cmd
from tishift_firestore.cli.check_cmd import check_cmd
from tishift_firestore.cli.sync_cmd import sync_cmd
from tishift_firestore.cli.preflight_cmd import preflight_cmd


console = Console()


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True)],
    )


@click.group()
@click.version_option(__version__, prog_name="tishift-firestore")
@click.option("--log-level", default="INFO",
              type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"]))
def cli(log_level: str) -> None:
    """Cloud Firestore → TiDB migration toolkit."""
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
