"""sync: CDC orchestration."""

from __future__ import annotations

import logging

import click
from rich.console import Console

from tishift_mongodb.config import load_config
from tishift_mongodb.core.sync.cutover import generate_cutover_plan, write_cutover_plan


log = logging.getLogger(__name__)
console = Console()


@click.group()
def sync_cmd() -> None:
    """CDC sync: direct-changestream (default) or adapter."""


@sync_cmd.command("start")
@click.option("--config", "-c", required=True, type=click.Path(exists=True))
@click.option("--provider",
              type=click.Choice(["direct-changestream", "aws-dms", "datastream", "debezium"]),
              default=None,
              help="Override provider from config.")
@click.option("--since", default=None,
              help="ISO8601 timestamp of the bulk-load completion (first start only).")
@click.option("--task-arn", default="", help="DMS task ARN (aws-dms only).")
@click.option("--stream-id", default="", help="Datastream stream ID (datastream only).")
@click.option("--emit-connector-config", is_flag=True,
              help="(debezium) Emit connector configs to tishift-output/; do not run.")
def start_cmd(config: str, provider: str | None, since: str,
              task_arn: str, stream_id: str, emit_connector_config: bool) -> None:
    """Start CDC."""
    cfg = load_config(config)
    chosen = provider or cfg.sync.provider

    if chosen == "direct-changestream":
        from tishift_mongodb.core.sync.direct_changestream import run_daemon
        console.print("[blue]Starting direct-changestream daemon (Ctrl+C to stop)...[/blue]")
        state = run_daemon(cfg, since=since)
        console.print(f"[green]Daemon stopped. Applied {state.events_applied} events.[/green]")
        return

    if chosen == "aws-dms":
        if not task_arn:
            raise click.UsageError("--task-arn is required for aws-dms")
        from tishift_mongodb.core.sync.dms_bridge import poll_dms_sync
        status = poll_dms_sync(task_arn, region=cfg.load.aws_dms.replication_instance_arn.split(":")[3] if ":" in cfg.load.aws_dms.replication_instance_arn else "us-east-1")
        console.print(f"[blue]DMS status: {status.status}, lag {status.lag_seconds}s[/blue]")
        return

    if chosen == "datastream":
        from tishift_mongodb.core.sync.datastream_bridge import emit_dataflow_job_spec
        path = emit_dataflow_job_spec(cfg, since_timestamp_iso=since or "")
        console.print(f"[blue]Wrote Dataflow job spec to {path}[/blue]")
        console.print("[yellow]Submit via gcloud dataflow flex-template run[/yellow]")
        return

    if chosen == "debezium":
        from tishift_mongodb.core.sync.debezium_bridge import emit_both
        src, sink = emit_both(cfg)
        console.print(f"[blue]Source connector: {src}[/blue]")
        console.print(f"[blue]JDBC sink: {sink}[/blue]")
        console.print(
            "[yellow]Apply via:\n"
            "  curl -X POST http://kafka-connect:8083/connectors -d @"
            f"{src.name}\n"
            "  curl -X POST http://kafka-connect:8083/connectors -d @"
            f"{sink.name}[/yellow]"
        )


@sync_cmd.command("plan")
@click.option("--config", "-c", required=True, type=click.Path(exists=True))
@click.option("--tolerance",
              type=click.Choice(["minutes", "hours", "weekend", "longer"]),
              required=True)
@click.option("--output", "-o", default="tishift-output/cutover-plan.md")
def plan_cmd(config: str, tolerance: str, output: str) -> None:
    """Generate a cutover plan tailored to the tolerance + configured provider."""
    cfg = load_config(config)
    plan = generate_cutover_plan(cfg, tolerance)  # type: ignore[arg-type]
    path = write_cutover_plan(plan, output)
    console.print(f"[green]Wrote cutover plan to {path}[/green]")


@sync_cmd.command("stop")
@click.option("--config", "-c", required=True, type=click.Path(exists=True))
def stop_cmd(config: str) -> None:
    """Stop CDC. For direct-changestream, interrupts the daemon process."""
    console.print(
        "[yellow]direct-changestream daemon: send SIGTERM/SIGINT to the daemon process.\n"
        "Adapter-based providers: stop via the customer's tooling "
        "(AWS Console / gcloud / Kafka Connect REST).[/yellow]"
    )
