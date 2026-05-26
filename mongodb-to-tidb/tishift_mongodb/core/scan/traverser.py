"""Live MongoDB traversal with sampling.

Live-Mongo code. Tested via mongomock fixture; not unit-tested without a Mongo
instance (live or mocked).
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import Iterable

from tishift_mongodb.config import ScanConfig
from tishift_mongodb.core.scan.sampler import plan_sample
from tishift_mongodb.core.scan.type_inferrer import (
    FieldHistogram,
    classify,
    walk_document,
)


log = logging.getLogger(__name__)


@dataclass
class CollectionScanResult:
    name: str
    estimated_count: int
    sampled_count: int
    id_type: str = "unknown"
    has_polymorphic_id: bool = False
    field_histograms: dict[str, FieldHistogram] = field(default_factory=dict)
    capped: bool = False

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "estimated_count": self.estimated_count,
            "sampled_count": self.sampled_count,
            "id_type": self.id_type,
            "has_polymorphic_id": self.has_polymorphic_id,
            "capped": self.capped,
            "fields": {p: h.to_dict() for p, h in sorted(self.field_histograms.items())},
        }


def estimate_count(coll) -> int:
    """Fast estimated count; falls back to 0 if the collection is empty."""
    try:
        return coll.estimated_document_count()
    except Exception as e:  # noqa: BLE001
        log.warning("estimated_document_count failed for %s: %s", coll.name, e)
        return 0


def sample_documents(coll, *, target_size: int, full_scan: bool):
    """Yield up to target_size documents via PyMongo aggregation $sample stage
    (server-side random) when supported, else reservoir-sample client-side.
    """
    if full_scan:
        yield from coll.find({})
        return
    try:
        # $sample is the canonical Mongo random-sample primitive
        yield from coll.aggregate([{"$sample": {"size": target_size}}])
    except Exception:  # noqa: BLE001
        # Reservoir fallback
        reservoir = []
        seen = 0
        for doc in coll.find({}):
            seen += 1
            if len(reservoir) < target_size:
                reservoir.append(doc)
            else:
                j = random.randint(0, seen - 1)
                if j < target_size:
                    reservoir[j] = doc
        yield from reservoir


def scan_collection(client, *, database: str, collection: str, cfg: ScanConfig) -> CollectionScanResult:
    db = client[database]
    coll = db[collection]
    estimated = estimate_count(coll)
    plan = plan_sample(collection, estimated_count=estimated, cfg=cfg)

    result = CollectionScanResult(
        name=collection,
        estimated_count=plan.estimated_count,
        sampled_count=0,
    )

    # Detect capped via collstats
    try:
        stats = db.command("collStats", collection)
        result.capped = bool(stats.get("capped", False))
    except Exception:  # noqa: BLE001
        pass

    id_types_seen: set[str] = set()

    for doc in sample_documents(coll, target_size=plan.target_sample_size, full_scan=plan.full_scan):
        result.sampled_count += 1
        if "_id" in doc:
            id_types_seen.add(classify(doc["_id"]))
        walk_document(doc, histograms=result.field_histograms)

    if len(id_types_seen) == 1:
        result.id_type = next(iter(id_types_seen))
        result.has_polymorphic_id = False
    elif len(id_types_seen) > 1:
        result.id_type = "polymorphic"
        result.has_polymorphic_id = True
    else:
        result.id_type = "unknown"

    return result


def list_collection_names(client, database: str) -> list[str]:
    """List collection names in the in-scope database, excluding system + GridFS."""
    raw = client[database].list_collection_names()
    out = []
    for name in sorted(raw):
        if name.startswith("system."):
            continue
        # GridFS collections handled separately in scoring
        out.append(name)
    return out
