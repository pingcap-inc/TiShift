"""Sync: logical-replication CDC bridge.

psycopg logical-replication client → pgoutput decoder → type mapping → PyMySQL
against TiDB. LSN tracking for resumability.

Supabase-specific hygiene (enforced):
  - Direct endpoint only (Supavisor does not proxy replication) — validated by
    connection.sync_endpoint_requirements
  - Slot name is NOT 'supabase_realtime' — validated by config.SyncConfig
  - Publication is NEVER created FOR ALL TABLES — the publication table list
    is built from the scan inventory's user tables only
  - The Realtime slot/publication ('supabase_realtime') is left untouched

Not available on TiDB Cloud Starter (no Changefeeds / DM).
"""

from __future__ import annotations

from pathlib import Path


def run_sync(config_path: Path, action: str) -> None:
    """Entry point for `tishift-supabase sync`."""
    raise NotImplementedError("sync implementation pending — see build spec §Sync (CDC)")
