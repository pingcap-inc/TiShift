"""Direct load: PyMongo find() → batched INSERT to TiDB.

Use only for < 10 GB sources. Bulk path is mongodump-lightning.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from tishift_mongodb.config import TiShiftConfig
from tishift_mongodb.core.convert.ddl_emitter import _table_name
from tishift_mongodb.core.check.hash_diff import canonicalize
from tishift_mongodb.rules.identifiers import quote_ident


log = logging.getLogger(__name__)
BATCH_SIZE = 1000


def _serialize_for_tidb(doc: dict[str, Any]) -> tuple[str, str]:
    """Convert one Mongo doc to (id, doc_json) for JSON-mostly INSERT."""
    doc_id = str(doc.get("_id", ""))
    # If _id is an ObjectId, str() gives hex
    canonical = canonicalize({k: v for k, v in doc.items() if k != "_id"})
    return (doc_id, json.dumps(canonical, separators=(",", ":")))


def load_collection_direct(cfg: TiShiftConfig, collection: str) -> int:
    """Load one collection via PyMongo → batched INSERT (JSON-mostly target)."""
    from tishift_mongodb.connection import mongo_client, tidb_connection

    fs = mongo_client(cfg.source)
    coll = fs[cfg.source.database][collection]
    table = _table_name(collection)

    inserted = 0
    batch: list[tuple[str, str]] = []

    with tidb_connection(cfg.target) as conn:
        with conn.cursor() as cur:
            insert_sql = (
                f"INSERT INTO {quote_ident(table)} "
                f"({quote_ident('id')}, {quote_ident('doc')}) VALUES (%s, %s)"
            )
            for doc in coll.find({}):
                batch.append(_serialize_for_tidb(doc))
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


def load_direct(cfg: TiShiftConfig, collections: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for c in collections:
        log.info("Direct loading %s", c)
        out[c] = load_collection_direct(cfg, c)
    return out
