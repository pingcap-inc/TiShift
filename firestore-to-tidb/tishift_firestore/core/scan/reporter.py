"""Scan report builder. Combines traversal output + indexes + mode detection."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tishift_firestore.config import TiShiftConfig
from tishift_firestore.core.scan.indexes import CompositeIndex, list_composite_indexes
from tishift_firestore.core.scan.mode_detect import detect_mode
from tishift_firestore.core.scan.traverser import (
    CollectionScanResult,
    traverse_root_collections,
)


@dataclass
class ScanReport:
    scan_started_at: str
    scan_completed_at: str
    project_id: str
    database_id: str
    mode: str
    edition: str
    location: str
    multiple_databases: bool
    collections: list[CollectionScanResult] = field(default_factory=list)
    composite_indexes: list[CompositeIndex] = field(default_factory=list)
    data_profile: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scan_started_at": self.scan_started_at,
            "scan_completed_at": self.scan_completed_at,
            "project_id": self.project_id,
            "database_id": self.database_id,
            "mode": self.mode,
            "edition": self.edition,
            "location": self.location,
            "multiple_databases": self.multiple_databases,
            "collections": [c.to_dict() for c in self.collections],
            "composite_indexes": [
                {
                    "collection_or_group": idx.collection_or_group,
                    "scope": idx.scope,
                    "fields": [{"name": f.name, "order": f.order} for f in idx.fields],
                }
                for idx in self.composite_indexes
            ],
            "data_profile": self.data_profile,
        }

    def write_json(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, default=str)


def run_scan(cfg: TiShiftConfig) -> ScanReport:
    """Top-level scan entry point. Returns a populated ScanReport."""
    started = datetime.now(timezone.utc).isoformat()

    mode_result = detect_mode(cfg.source)
    if mode_result.redirect_required:
        raise SystemExit(
            "Firestore Enterprise / MongoDB-compatibility detected. "
            "Use the mongo-to-tidb skill — this skill targets the Native API."
        )

    from tishift_firestore.connection import firestore_client

    client = firestore_client(cfg.source)
    collections = traverse_root_collections(client, cfg=cfg.scan)
    indexes = list_composite_indexes(cfg.source)

    completed = datetime.now(timezone.utc).isoformat()
    return ScanReport(
        scan_started_at=started,
        scan_completed_at=completed,
        project_id=cfg.source.project_id,
        database_id=cfg.source.database_id,
        mode=mode_result.mode,
        edition=mode_result.edition,
        location=mode_result.location,
        multiple_databases=mode_result.multiple_databases,
        collections=collections,
        composite_indexes=indexes,
        data_profile={},  # Cloud Monitoring fill-in lives in a separate module
    )
