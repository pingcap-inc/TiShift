"""Connection management for Neon/Postgres (source) and TiDB (target)."""

from __future__ import annotations

import logging
import re
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import psycopg
    import pymysql

from tishift_neon.config import SourceConfig, TargetConfig

logger = logging.getLogger(__name__)

# Pattern to detect Neon pooled connection strings
_POOLER_PATTERN = re.compile(r"-pooler\b|:6543\b")


def is_pooled_connection(host: str, port: int) -> bool:
    """Detect if the connection string points to a PgBouncer pooled endpoint."""
    return bool(_POOLER_PATTERN.search(host)) or port == 6543


def connect_source(config: SourceConfig, read_only: bool = True) -> psycopg.Connection:
    """Connect to a Neon/Postgres source database.

    Enforces read-only at the session level. Handles Neon cold-start
    latency with a longer initial timeout and one retry.
    """
    import psycopg

    if is_pooled_connection(config.host, config.port):
        logger.warning(
            "Detected pooled connection (host=%s, port=%d). "
            "pg_dump, COPY, and logical replication require a direct (unpooled) connection.",
            config.host,
            config.port,
        )

    conninfo = (
        f"host={config.host} port={config.port} "
        f"dbname={config.database} user={config.user} "
        f"password={config.password} sslmode={config.sslmode} "
        f"connect_timeout=15"
    )

    for attempt in range(2):
        try:
            conn = psycopg.connect(conninfo, autocommit=False)
            break
        except psycopg.OperationalError:
            if attempt == 0:
                logger.info("Connection refused — Neon compute may be waking up. Retrying in 3s...")
                time.sleep(3)
            else:
                raise

    if read_only:
        conn.execute("SET default_transaction_read_only = on")
        logger.debug("Source connection set to read-only.")

    return conn


def connect_target(config: TargetConfig) -> pymysql.Connection:
    """Connect to a TiDB target database."""
    import pymysql

    ssl = {"ssl": {"ca": ""}} if config.tls else {}

    conn = pymysql.connect(
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password,
        database=config.database,
        charset="utf8mb4",
        connect_timeout=10,
        **ssl,
    )
    return conn
