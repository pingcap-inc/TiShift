"""Connection manager for Oracle source and TiDB target."""

from __future__ import annotations

from typing import TYPE_CHECKING

import oracledb
import pymysql

if TYPE_CHECKING:
    from tishift_oracle.config import SourceConfig, TargetConfig


def connect_source(cfg: SourceConfig) -> oracledb.Connection:
    """Connect to Oracle in read-only mode.

    Uses thin mode by default (no Oracle Client required).
    Falls back to thick mode if cfg.mode == "thick".
    """
    if cfg.mode == "thick":
        oracledb.init_oracle_client()

    if cfg.connection_string:
        conn = oracledb.connect(
            user=cfg.user,
            password=cfg.password,
            dsn=cfg.connection_string,
        )
    else:
        conn = oracledb.connect(
            user=cfg.user,
            password=cfg.password,
            dsn=f"{cfg.host}:{cfg.port}/{cfg.service_name}",
        )

    # Enforce read-only at session level
    with conn.cursor() as cur:
        cur.execute("SET TRANSACTION READ ONLY")

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
