"""TiDB-native CDC: PyMongo Change Streams → PyMySQL writer.

Runs in any container runtime. Persists resume tokens for restart safety.
Surfaces lag metrics. Cloud-agnostic by design.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tishift_mongodb.config import TiShiftConfig
from tishift_mongodb.core.check.hash_diff import canonicalize
from tishift_mongodb.core.convert.ddl_emitter import _table_name
from tishift_mongodb.rules.identifiers import quote_ident


log = logging.getLogger(__name__)


@dataclass
class DaemonState:
    resume_token: dict | None
    last_event_at: str
    events_applied: int

    def to_dict(self) -> dict:
        return {
            "resume_token": self.resume_token,
            "last_event_at": self.last_event_at,
            "events_applied": self.events_applied,
        }


def _load_state(path: Path) -> DaemonState:
    if not path.exists():
        return DaemonState(resume_token=None, last_event_at="", events_applied=0)
    raw = json.loads(path.read_text())
    return DaemonState(
        resume_token=raw.get("resume_token"),
        last_event_at=raw.get("last_event_at", ""),
        events_applied=int(raw.get("events_applied", 0)),
    )


def _save_state(path: Path, state: DaemonState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state.to_dict(), indent=2, default=str))
    tmp.replace(path)


def _apply_event_to_tidb(conn, event: dict, cfg: TiShiftConfig) -> None:
    """Apply one Change Stream event to TiDB."""
    operation = event.get("operationType")
    namespace = event.get("ns", {})
    collection = namespace.get("coll", "")
    table = _table_name(collection)
    doc_id = str(event.get("documentKey", {}).get("_id", ""))

    if operation == "insert":
        full_doc = event.get("fullDocument", {})
        canonical = canonicalize({k: v for k, v in full_doc.items() if k != "_id"})
        with conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO {quote_ident(table)} "
                f"({quote_ident('id')}, {quote_ident('doc')}) VALUES (%s, %s) "
                f"ON DUPLICATE KEY UPDATE {quote_ident('doc')} = VALUES({quote_ident('doc')})",
                (doc_id, json.dumps(canonical, separators=(",", ":"))),
            )
    elif operation == "update":
        full_doc = event.get("fullDocument")
        if full_doc:
            canonical = canonicalize({k: v for k, v in full_doc.items() if k != "_id"})
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE {quote_ident(table)} SET {quote_ident('doc')} = %s "
                    f"WHERE {quote_ident('id')} = %s",
                    (json.dumps(canonical, separators=(",", ":")), doc_id),
                )
    elif operation == "replace":
        full_doc = event.get("fullDocument", {})
        canonical = canonicalize({k: v for k, v in full_doc.items() if k != "_id"})
        with conn.cursor() as cur:
            cur.execute(
                f"REPLACE INTO {quote_ident(table)} "
                f"({quote_ident('id')}, {quote_ident('doc')}) VALUES (%s, %s)",
                (doc_id, json.dumps(canonical, separators=(",", ":"))),
            )
    elif operation == "delete":
        with conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM {quote_ident(table)} WHERE {quote_ident('id')} = %s",
                (doc_id,),
            )
    elif operation in ("drop", "rename", "dropDatabase", "invalidate"):
        log.warning("DDL-shaped event %s ignored: %s", operation, event)
    else:
        log.warning("Unknown operationType %r: %s", operation, event)


def run_daemon(
    cfg: TiShiftConfig,
    *,
    state_path: str | Path = "tishift-output/.cdc-state.json",
    since: str | None = None,
    max_events: int | None = None,
) -> DaemonState:
    """Run the Change Streams daemon. Blocks until interrupted or max_events reached.

    `since` is an ISO timestamp — used only on first start when no resume token exists.
    Subsequent restarts use the persisted resume token.
    """
    from tishift_mongodb.connection import mongo_client, tidb_connection

    state_p = Path(state_path)
    state = _load_state(state_p)

    fs = mongo_client(cfg.source)
    db = fs[cfg.source.database]

    options: dict[str, Any] = {"full_document": "updateLookup"}
    if state.resume_token:
        options["resume_after"] = state.resume_token
    elif since:
        # Mongo accepts a BSON Timestamp for start_at_operation_time; for the
        # CLI/external use the ISO string is parsed by the caller.
        from datetime import datetime as _dt
        try:
            start_at = _dt.fromisoformat(since.replace("Z", "+00:00"))
            from bson.timestamp import Timestamp  # type: ignore[import-not-found]
            options["start_at_operation_time"] = Timestamp(int(start_at.timestamp()), 0)
        except Exception as e:  # noqa: BLE001
            log.warning("could not parse --since %r: %s", since, e)

    with tidb_connection(cfg.target) as conn:
        with db.watch(**options) as stream:
            for event in stream:
                _apply_event_to_tidb(conn, event, cfg)
                conn.commit()
                state.resume_token = event.get("_id")
                state.last_event_at = datetime.now(timezone.utc).isoformat()
                state.events_applied += 1
                _save_state(state_p, state)

                if state.events_applied % 100 == 0:
                    log.info("Applied %d events; lag %ds",
                             state.events_applied,
                             _compute_lag_seconds(event))

                if max_events and state.events_applied >= max_events:
                    break

    return state


def _compute_lag_seconds(event: dict) -> int:
    cluster_time = event.get("clusterTime")
    if cluster_time is None:
        return 0
    try:
        event_time = cluster_time.time if hasattr(cluster_time, "time") else int(cluster_time)
        return int(time.time() - event_time)
    except Exception:  # noqa: BLE001
        return 0
