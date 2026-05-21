"""Document-count parity check between Mongo source and TiDB target."""

from __future__ import annotations

from dataclasses import dataclass

from tishift_mongodb.config import TiShiftConfig
from tishift_mongodb.core.convert.ddl_emitter import _table_name
from tishift_mongodb.rules.identifiers import quote_ident


@dataclass
class CountResult:
    collection: str
    source_count: int
    target_count: int

    @property
    def delta(self) -> int:
        return self.target_count - self.source_count

    @property
    def matches(self) -> bool:
        return self.delta == 0

    def to_dict(self) -> dict:
        return {
            "collection": self.collection,
            "source_count": self.source_count,
            "target_count": self.target_count,
            "delta": self.delta,
            "matches": self.matches,
        }


def source_count(cfg: TiShiftConfig, collection: str) -> int:
    """Mongo count_documents — exact, server-side."""
    from tishift_mongodb.connection import mongo_client

    client = mongo_client(cfg.source)
    coll = client[cfg.source.database][collection]
    return int(coll.count_documents({}))


def target_count(cfg: TiShiftConfig, collection: str) -> int:
    """TiDB SELECT COUNT(*)."""
    from tishift_mongodb.connection import tidb_connection

    table = _table_name(collection)
    with tidb_connection(cfg.target, read_only=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS n FROM {quote_ident(table)}")
            row = cur.fetchone()
            return int(row["n"] if row else 0)


def compare_counts(cfg: TiShiftConfig, collections: list[str]) -> list[CountResult]:
    """Compare source vs target counts for every collection."""
    import pymysql

    out: list[CountResult] = []
    for c in collections:
        src = source_count(cfg, c)
        try:
            tgt = target_count(cfg, c)
        except pymysql.err.Error:
            tgt = -1
        out.append(CountResult(collection=c, source_count=src, target_count=tgt))
    return out
