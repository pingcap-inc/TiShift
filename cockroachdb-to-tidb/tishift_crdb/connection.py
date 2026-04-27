"""Connection manager for CockroachDB source and TiDB target."""

from __future__ import annotations

from typing import TYPE_CHECKING

import psycopg
import pymysql

if TYPE_CHECKING:
    from tishift_crdb.config import SourceConfig, TargetConfig


def connect_source(cfg: SourceConfig) -> psycopg.Connection:
    """Connect to CockroachDB in read-only mode.

    CockroachDB speaks PostgreSQL wire protocol — psycopg3 connects natively.
    Default port is 26257 (not 5432).
    """
    conn = psycopg.connect(cfg.dsn, password=cfg.password, autocommit=False)

    # Enforce read-only at session level
    conn.execute("SET default_transaction_read_only = on")

    return conn


def connect_target(cfg: TargetConfig) -> pymysql.Connection:
    """Connect to TiDB target."""
    ssl: dict | None = None
    if cfg.tls:
        ssl = {"ssl": True}

    return pymysql.connect(
        host=cfg.host,
        port=cfg.port,
        user=cfg.user,
        password=cfg.password,
        database=cfg.database,
        ssl=ssl,
        charset="utf8mb4",
        autocommit=True,
    )
