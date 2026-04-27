"""Check: source/target validation.

Modes:
  once  (default)  snapshot comparison after load
  live             tolerate small deltas during active sync
  deep             full COUNT(*) + per-PK-range MD5 checksum in a maintenance window

Cross-protocol: psycopg against Supabase, PyMySQL against TiDB. Type normalization
before hashing (TRUE ↔ 1, UUID ↔ VARCHAR(36)/BINARY(16), etc.).

Only validates user-schema data. auth.*, storage.*, realtime.* are out of scope
— those are verified by their respective migration tracks.
"""

from __future__ import annotations

from pathlib import Path


def run_check(
    config_path: Path,
    mode: str,
    checksum: bool,
    outputs: list[str],
    live_tolerance_pct: float,
) -> None:
    """Entry point for `tishift-supabase check`."""
    raise NotImplementedError("check implementation pending — see build spec §Check")
