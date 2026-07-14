"""Server metadata collector — SKILL.md Step 1.1/1.2 and Step 2.1b.

Reads version/HeatWave-cluster identity and the server settings not already
covered by the binlog/continue-replication readiness precheck (collectors/binlog.py). Wraps
each read defensively so the collector degrades gracefully against plain
MySQL (no HeatWave cluster, no rpd_nodes table).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pymysql

from tishift_heatwave.models import HeatWaveMetadata

_VAR_PATTERN = re.compile(r"@@[a-zA-Z_][a-zA-Z0-9_.]*")


def _get_var(cursor: Any, expr: str) -> str | None:
    """Execute ``SELECT <expr>`` and return the scalar value, or None.

    Only @@system_variable expressions are allowed — this is the one place
    string interpolation into SQL is acceptable, and only because it's
    restricted to a fixed pattern that can't carry injected SQL.
    """
    if not _VAR_PATTERN.fullmatch(expr):
        raise ValueError(f"Only @@system_variable expressions are allowed, got: {expr!r}")
    import pymysql

    try:
        cursor.execute(f"SELECT {expr}")
        row = cursor.fetchone()
        if row is None:
            return None
        return str(list(row.values())[0]) if row else None
    except pymysql.Error:
        return None


def _get_rapid_node_count(cursor: Any) -> int:
    """Return the number of attached HeatWave (RAPID) cluster nodes, or 0.

    performance_schema.rpd_nodes only exists while a HeatWave cluster is
    attached; the table is absent entirely on plain MySQL.
    """
    import pymysql

    try:
        cursor.execute("SELECT COUNT(*) AS n FROM performance_schema.rpd_nodes")
        row = cursor.fetchone()
        return int(list(row.values())[0]) if row else 0
    except pymysql.Error:
        return 0


def _collect_replication_topology(cursor: Any, meta: HeatWaveMetadata) -> None:
    """Populate the primary/secondary (HA) topology fields on *meta*.

    Distinct from the RAPID analytics cluster (rapid_node_count above) — this
    is MySQL replication topology: is this node a replica, and how many
    replicas are attached downstream of it. Requires REPLICATION CLIENT;
    degrades to defaults (not a replica, 0 downstream replicas) without it or
    on a standalone instance.
    """
    import pymysql

    read_only = _get_var(cursor, "@@read_only")
    meta.read_only = (read_only == "1") if read_only is not None else None

    super_read_only = _get_var(cursor, "@@super_read_only")
    meta.super_read_only = (super_read_only == "1") if super_read_only is not None else None

    try:
        cursor.execute("SHOW REPLICA STATUS")
        row = cursor.fetchone()
        if row:
            meta.is_replica = True
            meta.replica_source_host = row.get("Source_Host") or row.get("Master_Host")
    except pymysql.Error:
        pass

    try:
        cursor.execute("SHOW REPLICAS")
        rows = cursor.fetchall()
        meta.connected_replica_count = len(rows)
        meta.connected_replica_hosts = [r["Host"] for r in rows if r.get("Host")]
    except pymysql.Error:
        pass


def collect_heatwave_metadata(conn: pymysql.Connection) -> HeatWaveMetadata:
    """Collect server-level metadata used throughout scan/assess."""
    meta = HeatWaveMetadata()

    with conn.cursor() as cur:
        meta.mysql_version = _get_var(cur, "@@version")
        meta.version_comment = _get_var(cur, "@@version_comment")

        meta.rapid_node_count = _get_rapid_node_count(cur)
        meta.has_rapid_cluster = meta.rapid_node_count > 0

        meta.binlog_row_value_options = _get_var(cur, "@@binlog_row_value_options")
        meta.gtid_mode = _get_var(cur, "@@gtid_mode")
        meta.character_set_server = _get_var(cur, "@@character_set_server")
        meta.collation_server = _get_var(cur, "@@collation_server")
        meta.transaction_isolation = _get_var(cur, "@@transaction_isolation")
        meta.sql_mode = _get_var(cur, "@@sql_mode")

        lc_names = _get_var(cur, "@@lower_case_table_names")
        meta.lower_case_table_names = int(lc_names) if lc_names is not None else None

        max_conn = _get_var(cur, "@@max_connections")
        meta.max_connections = int(max_conn) if max_conn is not None else None

        _collect_replication_topology(cur, meta)

    return meta
