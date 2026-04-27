"""Connection management for Supabase (source) and TiDB (target).

Source connections are enforced read-only at the session level. The connection
manager recognizes the three Supabase endpoint shapes and validates that the
username matches the endpoint type:

  Direct        db.{ref}.supabase.co:5432          user: postgres
  Session pool  aws-0-{region}.pooler.supabase.com:5432   user: postgres.{ref}
  Txn pool      aws-0-{region}.pooler.supabase.com:6543   user: postgres.{ref}  [REFUSED]

Mismatched usernames on the pooler endpoints fail silently (Supavisor auth
returns "password authentication failed" with no hint that the username is the
real issue). This module validates up front so that misconfiguration is caught
at config-load time, not at the first query.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

import psycopg
import pymysql

from .config import Config, SourceConfig, TargetConfig


class ConnectionMode(str, Enum):
    DIRECT = "direct"
    SESSION_POOLER = "session_pooler"
    TRANSACTION_POOLER = "transaction_pooler"   # always refused
    UNKNOWN = "unknown"


_DIRECT_HOST_RE = re.compile(r"^db\.([a-z0-9]+)\.supabase\.co$", re.IGNORECASE)
_POOLER_HOST_RE = re.compile(
    r"^aws-\d+-([a-z0-9-]+)\.pooler\.supabase\.com$", re.IGNORECASE
)
_POOLER_USER_RE = re.compile(r"^postgres\.([a-z0-9]+)$", re.IGNORECASE)


@dataclass(frozen=True)
class EndpointAnalysis:
    mode: ConnectionMode
    project_ref: str | None
    region: str | None
    warnings: tuple[str, ...] = ()


def analyze_endpoint(source: SourceConfig) -> EndpointAnalysis:
    """Classify a Supabase endpoint and validate username coherence.

    Returns an EndpointAnalysis with mode and any warnings. Does not raise on
    session-mode sync usage (it's flagged in warnings); does raise on a
    transaction-pooler config that slipped through validation.
    """
    host = source.host.strip().lower()
    port = source.port
    user = source.user

    if direct := _DIRECT_HOST_RE.match(host):
        ref = direct.group(1)
        warnings: list[str] = []
        if user != "postgres":
            warnings.append(
                f"direct endpoint uses username 'postgres', got '{user}'. "
                "Pooler-style usernames (postgres.{ref}) do not work on the direct endpoint."
            )
        return EndpointAnalysis(ConnectionMode.DIRECT, ref, None, tuple(warnings))

    if pooler := _POOLER_HOST_RE.match(host):
        region = pooler.group(1)
        user_match = _POOLER_USER_RE.match(user)
        warnings = []
        ref = user_match.group(1) if user_match else None
        if not user_match:
            warnings.append(
                f"pooler endpoint requires username 'postgres.{{project_ref}}', got '{user}'. "
                "The pooler fails auth silently on username mismatch."
            )
        if port == 6543:
            raise ValueError(
                "transaction-mode pooler (port 6543) is refused at runtime. "
                "This should have been caught by config validation."
            )
        if port != 5432:
            warnings.append(f"unexpected pooler port {port}; expected 5432 (session mode)")
        return EndpointAnalysis(ConnectionMode.SESSION_POOLER, ref, region, tuple(warnings))

    return EndpointAnalysis(
        ConnectionMode.UNKNOWN,
        None,
        None,
        (
            f"host '{host}' does not match a known Supabase endpoint pattern. "
            "Expected db.{ref}.supabase.co or aws-N-{region}.pooler.supabase.com.",
        ),
    )


def open_source_readonly(source: SourceConfig) -> psycopg.Connection:
    """Open a read-only connection to Supabase.

    Enforces read-only at the session level with
    SET default_transaction_read_only = on.
    """
    analysis = analyze_endpoint(source)
    if analysis.mode == ConnectionMode.TRANSACTION_POOLER:
        raise RuntimeError("transaction-mode pooler refused")

    conn = psycopg.connect(
        host=source.host,
        port=source.port,
        user=source.user,
        password=source.password,
        dbname=source.database,
        sslmode=source.sslmode,
        connect_timeout=15,  # Supabase free tier may cold-start the compute
    )
    with conn.cursor() as cur:
        cur.execute("SET default_transaction_read_only = on")
    return conn


def open_target(target: TargetConfig) -> pymysql.Connection:
    """Open a connection to TiDB."""
    kwargs: dict = {
        "host": target.host,
        "port": target.port,
        "user": target.user,
        "password": target.password,
        "database": target.database,
        "charset": "utf8mb4",
        "autocommit": True,
    }
    if target.tls:
        kwargs["ssl"] = {"check_hostname": True}
    return pymysql.connect(**kwargs)


def sync_endpoint_requirements(config: Config) -> None:
    """Validate that the configured source endpoint supports logical replication.

    Logical replication requires the direct endpoint — Supavisor does not proxy
    the replication protocol. Raises RuntimeError if the sync config is
    incompatible with the source endpoint.
    """
    sync_host = config.sync.replication_host or config.source.host
    analysis = analyze_endpoint(
        SourceConfig(
            host=sync_host,
            port=config.sync.replication_port,
            user=config.source.user,
            password=config.source.password,
            database=config.source.database,
            sslmode=config.source.sslmode,
        )
    )
    if analysis.mode != ConnectionMode.DIRECT:
        raise RuntimeError(
            f"sync requires the direct Supabase endpoint (db.{{ref}}.supabase.co:5432); "
            f"got '{sync_host}' which classifies as {analysis.mode.value}. "
            "The Supavisor pooler does not proxy the replication protocol."
        )
