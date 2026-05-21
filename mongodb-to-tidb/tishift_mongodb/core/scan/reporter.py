"""Scan report builder. Combines traversal + indexes + topology + aggregation inventory."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tishift_mongodb.config import TiShiftConfig
from tishift_mongodb.core.scan.aggregation_inventory import Pipeline
from tishift_mongodb.core.scan.indexes import IndexInfo
from tishift_mongodb.core.scan.topology_detect import TopologyResult
from tishift_mongodb.core.scan.traverser import CollectionScanResult


@dataclass
class ScanReport:
    scan_started_at: str
    scan_completed_at: str
    database: str
    topology: TopologyResult
    collections: list[CollectionScanResult] = field(default_factory=list)
    indexes: list[IndexInfo] = field(default_factory=list)
    aggregations: list[Pipeline] = field(default_factory=list)
    data_profile: dict[str, Any] = field(default_factory=dict)
    has_gridfs: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "scan_started_at": self.scan_started_at,
            "scan_completed_at": self.scan_completed_at,
            "database": self.database,
            "topology": self.topology.topology,
            "mongo_version": self.topology.mongo_version,
            "replica_set_name": self.topology.replica_set_name,
            "shards": self.topology.shards,
            "has_gridfs": self.has_gridfs,
            "collections": [c.to_dict() for c in self.collections],
            "indexes": [
                {
                    "name": idx.name,
                    "collection": idx.collection,
                    "fields": [{"name": f.name, "direction": f.direction} for f in idx.fields],
                    "unique": idx.unique,
                    "sparse": idx.sparse,
                    "ttl_seconds": idx.ttl_seconds,
                    "partial_filter": idx.partial_filter,
                    "is_geospatial": idx.is_geospatial,
                    "is_text": idx.is_text,
                    "is_wildcard": idx.is_wildcard,
                }
                for idx in self.indexes
            ],
            "aggregations": [
                {
                    "id": p.id,
                    "collection": p.collection,
                    "stages": p.stages,
                    "complexity": p.complexity,
                    "source": p.source,
                }
                for p in self.aggregations
            ],
            "data_profile": self.data_profile,
        }

    def write_json(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, default=str)


def run_scan(cfg: TiShiftConfig) -> ScanReport:
    """Top-level scan entry point. Lazy-imports PyMongo to keep tests deps-light."""
    from tishift_mongodb.connection import mongo_client
    from tishift_mongodb.core.scan.aggregation_inventory import inventory_from_system_profile
    from tishift_mongodb.core.scan.indexes import list_indexes_for_collection
    from tishift_mongodb.core.scan.topology_detect import detect_topology
    from tishift_mongodb.core.scan.traverser import list_collection_names, scan_collection

    started = datetime.now(timezone.utc).isoformat()
    client = mongo_client(cfg.source)

    topology = detect_topology(client)
    db = client[cfg.source.database]

    # Detect GridFS by collection presence
    coll_names = list_collection_names(client, cfg.source.database)
    has_gridfs = "fs.files" in db.list_collection_names() and "fs.chunks" in db.list_collection_names()

    collections: list[CollectionScanResult] = []
    indexes: list[IndexInfo] = []
    for name in coll_names:
        collections.append(scan_collection(client, database=cfg.source.database, collection=name, cfg=cfg.scan))
        indexes.extend(list_indexes_for_collection(db[name]))

    # Aggregation inventory: try system.profile if present
    aggregations: list[Pipeline] = []
    if cfg.scan.inventory_aggregations:
        try:
            profile_coll = db["system.profile"]
            profile_docs = list(profile_coll.find({"op": "command"}).limit(500))
            aggregations.extend(inventory_from_system_profile(profile_docs))
        except Exception:  # noqa: BLE001
            pass

    # Data profile
    try:
        db_stats = db.command("dbStats")
        data_profile = {
            "total_storage_gb": db_stats.get("storageSize", 0) / (1024**3),
            "total_index_storage_gb": db_stats.get("indexSize", 0) / (1024**3),
            "data_size_gb": db_stats.get("dataSize", 0) / (1024**3),
        }
    except Exception:  # noqa: BLE001
        data_profile = {}

    completed = datetime.now(timezone.utc).isoformat()
    return ScanReport(
        scan_started_at=started,
        scan_completed_at=completed,
        database=cfg.source.database,
        topology=topology,
        collections=collections,
        indexes=indexes,
        aggregations=aggregations,
        data_profile=data_profile,
        has_gridfs=has_gridfs,
    )
