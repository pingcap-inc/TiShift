"""Direct (small-DB) load: Admin SDK read → in-process INSERT batches.

Use only for <10 GB sources or development / CI. The bulk path is Dataflow.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import pymysql

from tishift_firestore.config import TiShiftConfig
from tishift_firestore.connection import firestore_client, tidb_connection
from tishift_firestore.core.convert.ddl_emitter import _table_name
from tishift_firestore.rules.identifiers import quote_ident


log = logging.getLogger(__name__)
BATCH_SIZE = 1000


def _serialize_for_tidb(doc: dict[str, Any], doc_id: str) -> tuple[str, str]:
    """Default JSON-mostly serialization: id + JSON-encoded body."""
    return (doc_id, json.dumps(_jsonable(doc), separators=(",", ":")))


def _jsonable(value: Any) -> Any:
    """Strip Firestore-SDK types to JSON-serializable forms."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "latitude"):
        return {"lat": value.latitude, "lng": value.longitude}
    if hasattr(value, "path"):
        return {"$ref": value.path}
    if isinstance(value, bytes):
        import base64
        return {"$bytes": base64.b64encode(value).decode("ascii")}
    return str(value)


def load_collection_direct(
    cfg: TiShiftConfig,
    *,
    collection_path: str,
    json_mostly: bool = True,
) -> int:
    """Load one Firestore collection into TiDB via Admin SDK reads + batched INSERTs.

    Returns the number of rows inserted.
    """
    fs = firestore_client(cfg.source)
    coll = fs.collection(collection_path)
    table = _table_name(collection_path)

    if not json_mostly:
        raise NotImplementedError(
            "direct load currently supports json-mostly target schema only. "
            "Use dataflow-lightning for normalized/hybrid policies."
        )

    inserted = 0
    batch: list[tuple[str, str]] = []

    with tidb_connection(cfg.target) as conn:
        with conn.cursor() as cur:
            # Quote identifiers once up front. `table` came from safe_table_name
            # (called via _table_name), so it's already on the allowlist; quote_ident
            # belt-and-braces against any future refactor of _table_name.
            insert_sql = (
                f"INSERT INTO {quote_ident(table)} "
                f"({quote_ident('id')}, {quote_ident('doc')}) VALUES (%s, %s)"
            )
            for doc in coll.stream():
                batch.append(_serialize_for_tidb(doc.to_dict() or {}, doc.id))
                if len(batch) >= BATCH_SIZE:
                    cur.executemany(insert_sql, batch)
                    conn.commit()
                    inserted += len(batch)
                    batch.clear()
                    log.info("Loaded %d rows into %s", inserted, table)
            if batch:
                cur.executemany(insert_sql, batch)
                conn.commit()
                inserted += len(batch)

    return inserted


def load_direct(cfg: TiShiftConfig, collection_paths: list[str]) -> dict[str, int]:
    """Direct-strategy entry point."""
    results: dict[str, int] = {}
    for path in collection_paths:
        log.info("Direct loading %s", path)
        results[path] = load_collection_direct(cfg, collection_path=path)
    return results
