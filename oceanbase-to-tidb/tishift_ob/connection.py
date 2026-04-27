"""Connection manager for OceanBase source and TiDB target."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pymysql

if TYPE_CHECKING:
    from tishift_ob.config import SourceConfig, TargetConfig


def connect_source(cfg: SourceConfig) -> pymysql.Connection:
    """Connect to OceanBase in read-only mode.

    OceanBase speaks MySQL protocol in both MySQL and Oracle modes.
    Default port is 2881 (OBProxy), not 3306.
    Tenant-qualified username: user@tenant_name.
    """
    conn = pymysql.connect(
        host=cfg.host,
        port=cfg.port,
        user=cfg.effective_user,
        password=cfg.password,
        database=cfg.database,
        charset="utf8mb4",
        autocommit=True,
    )

    # Enforce read-only at session level
    with conn.cursor() as cur:
        cur.execute("SET SESSION TRANSACTION READ ONLY")

    return conn


def detect_ob_mode(conn: pymysql.Connection) -> str:
    """Detect OceanBase compatibility mode (MYSQL or ORACLE).

    Returns 'mysql' or 'oracle' (lowercase).
    """
    with conn.cursor() as cur:
        cur.execute("SHOW VARIABLES LIKE 'ob_compatibility_mode'")
        row = cur.fetchone()
        if row:
            return str(row[1]).lower()
    return "mysql"  # default if variable not found


def get_ob_version(conn: pymysql.Connection) -> str:
    """Get OceanBase version string."""
    with conn.cursor() as cur:
        cur.execute("SELECT ob_version()")
        row = cur.fetchone()
        if row:
            return str(row[0])
    return "unknown"


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
