"""Connection management for MySQL HeatWave (source) and TiDB (target).

Both endpoints speak the MySQL protocol, so pymysql is used for both sides.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pymysql

from tishift_heatwave.config import SourceConfig, TargetConfig

logger = logging.getLogger(__name__)


def connect_source(config: SourceConfig, read_only: bool = True) -> pymysql.Connection:
    """Connect to a MySQL HeatWave source DB System.

    DB Systems with public accessibility enabled (HeatWave on AWS, or OCI
    "Networking Accessibility: Public") are reached directly; VCN-private
    ones need an SSH tunnel or jump host. Either way TLS is
    mandatory and the service CA is self-signed, so verification needs the
    CA certificate (config.ssl_ca). Enforces read-only at the session level
    so scan can never mutate the source.
    """
    import pymysql

    ssl = {"ssl": {"ca": config.ssl_ca}} if config.tls else {}

    conn = pymysql.connect(
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password,
        database=config.database,
        charset="utf8mb4",
        connect_timeout=15,
        cursorclass=pymysql.cursors.DictCursor,
        **ssl,
    )

    if read_only:
        with conn.cursor() as cur:
            cur.execute("SET SESSION TRANSACTION READ ONLY")
        logger.debug("Source connection set to read-only.")

    return conn


def connect_target(config: TargetConfig) -> pymysql.Connection:
    """Connect to a TiDB target database."""
    import pymysql

    ssl = {"ssl": {"ca": config.ssl_ca}} if config.tls else {}

    conn = pymysql.connect(
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password,
        database=config.database,
        charset="utf8mb4",
        connect_timeout=10,
        cursorclass=pymysql.cursors.DictCursor,
        **ssl,
    )
    return conn


def has_rapid_cluster(conn: pymysql.Connection) -> bool:
    """Return True when a HeatWave (RAPID) cluster is attached to the DB System.

    ``performance_schema.rpd_nodes`` only has rows while a HeatWave cluster is
    attached; the table is absent entirely on plain MySQL, which we treat as
    "no cluster" so the toolkit still works against vanilla MySQL sources.
    """
    import pymysql

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM performance_schema.rpd_nodes")
            row = cur.fetchone()
            return bool(row and int(list(row.values())[0]) > 0)
    except pymysql.Error:
        return False
