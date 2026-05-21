"""Document-count parity check."""

from __future__ import annotations

from dataclasses import dataclass

from tishift_firestore.config import TiShiftConfig
from tishift_firestore.core.convert.ddl_emitter import _table_name
from tishift_firestore.rules.identifiers import quote_ident


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


def source_count(cfg: TiShiftConfig, collection_path: str) -> int:
    """Firestore aggregate count() — exact, server-computed."""
    from tishift_firestore.connection import firestore_client

    client = firestore_client(cfg.source)
    coll = client.collection(collection_path)
    agg = coll.count()
    result = agg.get()
    return int(result[0][0].value)


def target_count(cfg: TiShiftConfig, collection_path: str) -> int:
    """SELECT COUNT(*) against TiDB."""
    from tishift_firestore.connection import tidb_connection

    table = _table_name(collection_path)
    with tidb_connection(cfg.target, read_only=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS n FROM {quote_ident(table)}")
            row = cur.fetchone()
            return int(row["n"] if row else 0)


def compare_counts(cfg: TiShiftConfig, collection_paths: list[str]) -> list[CountResult]:
    """Compare source and target counts for every collection path."""
    import pymysql

    out = []
    for path in collection_paths:
        src = source_count(cfg, path)
        try:
            tgt = target_count(cfg, path)
        except pymysql.err.Error:
            tgt = -1
        out.append(CountResult(collection=path, source_count=src, target_count=tgt))
    return out
