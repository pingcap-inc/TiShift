"""Load: bulk data transfer with mandatory schema allow-list.

Strategies:
  direct      CSV via \\COPY + LOAD DATA LOCAL INFILE (< 50 GB)
  dms         AWS Database Migration Service (50-500 GB, Essential/Dedicated)
  ticloud     `ticloud serverless import start` (Starter tier)
  lightning   TiDB Lightning physical import (> 500 GB, Dedicated)
  auto        pick by tier + total_data_gb from the scan report

The export step MUST use source.schema_include — wildcard is refused by config
validation so this is enforced at load time too as defense-in-depth. A naive
pg_dump against a Supabase project would ship auth.users (bcrypt hashes) and
storage.objects (metadata) to the target. Never.

Continuation: writes migration-output/load.continuation.json with per-table
status; rerun to resume. --fresh wipes the log and restarts.
"""

from __future__ import annotations

from pathlib import Path


def run_load(config_path: Path, strategy: str, fresh: bool) -> None:
    """Entry point for `tishift-supabase load`."""
    raise NotImplementedError("load implementation pending — see build spec §Load Strategies")
