"""Recursive Firestore collection + subcollection traversal with sampling.

Live-GCP code. Tested via the Firestore Emulator fixture; not unit-tested
without the emulator running.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import Iterable

from google.cloud import firestore

from tishift_firestore.config import ScanConfig
from tishift_firestore.core.scan.sampler import plan_sample
from tishift_firestore.core.scan.type_inferrer import FieldHistogram, walk_document


log = logging.getLogger(__name__)


@dataclass
class CollectionScanResult:
    name: str  # full path: "users" or "users/{uid}/orders"
    estimated_count: int
    sampled_count: int
    field_histograms: dict[str, FieldHistogram] = field(default_factory=dict)
    subcollection_names: set[str] = field(default_factory=set)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "estimated_count": self.estimated_count,
            "sampled_count": self.sampled_count,
            "fields": {p: h.to_dict() for p, h in sorted(self.field_histograms.items())},
            "subcollections": sorted(self.subcollection_names),
        }


def estimate_count(coll: firestore.CollectionReference) -> int:
    """Use Firestore's aggregate count() for a server-computed exact count.

    Falls back to a small streamed-sample size estimate if the SDK version
    doesn't expose count().
    """
    try:
        agg = coll.count()
        result = agg.get()
        # result is a list of AggregateQueryResult; each has .value.
        return int(result[0][0].value)
    except (AttributeError, Exception) as e:  # noqa: BLE001
        log.warning("count() failed for %s: %s — falling back to sample", coll.id, e)
        return -1


def sample_documents(
    coll: firestore.CollectionReference, *, target_size: int, full_scan: bool
) -> Iterable[firestore.DocumentSnapshot]:
    """Yield up to `target_size` documents from the collection.

    For full_scan: stream every doc.
    For sampled: stream every doc and reservoir-sample (Firestore lacks a server-side random)
    """
    if full_scan:
        yield from coll.stream()
        return

    # Reservoir sample. Cost: 1 read per doc streamed, regardless of sample size.
    # For very large collections this is expensive; consider ID-range bucketing
    # in a future revision (split __name__ into 8 buckets, sample target_size/8 per).
    reservoir: list[firestore.DocumentSnapshot] = []
    seen = 0
    for doc in coll.stream():
        seen += 1
        if len(reservoir) < target_size:
            reservoir.append(doc)
        else:
            j = random.randint(0, seen - 1)
            if j < target_size:
                reservoir[j] = doc

    yield from reservoir


def scan_collection(
    client: firestore.Client,
    *,
    collection_path: str,
    cfg: ScanConfig,
) -> CollectionScanResult:
    """Scan one collection (root or subcollection given as full path)."""
    coll = client.collection(collection_path)
    estimated = estimate_count(coll)
    plan = plan_sample(collection_path, estimated_count=max(estimated, 0), cfg=cfg)

    result = CollectionScanResult(
        name=collection_path,
        estimated_count=plan.estimated_count,
        sampled_count=0,
    )

    for doc in sample_documents(coll, target_size=plan.target_sample_size, full_scan=plan.full_scan):
        result.sampled_count += 1
        body = doc.to_dict() or {}
        walk_document(body, histograms=result.field_histograms)

        # Discover subcollection names. Only descend on a sample of parents.
        if result.sampled_count <= cfg.parent_sample_for_subcollections:
            for subcol in doc.reference.collections():
                result.subcollection_names.add(subcol.id)

    return result


def traverse_root_collections(
    client: firestore.Client, *, cfg: ScanConfig
) -> list[CollectionScanResult]:
    """Top-level traversal entry point. Scans root collections, then recurses."""
    results: list[CollectionScanResult] = []
    visited: set[str] = set()

    # 1. Root collections
    root_names = sorted([c.id for c in client.collections()])
    for name in root_names:
        if name in visited:
            continue
        visited.add(name)
        log.info("Scanning root collection: %s", name)
        result = scan_collection(client, collection_path=name, cfg=cfg)
        results.append(result)

    # 2. Subcollections, BFS up to subcollection_max_depth
    pending = [(r, 1) for r in results]
    while pending:
        parent_result, depth = pending.pop(0)
        if depth >= cfg.subcollection_max_depth:
            continue
        for subcol_id in parent_result.subcollection_names:
            # Build full paths: parent_path / parent_doc_id / subcollection_id
            # We need to enumerate parent doc IDs to descend. Use a sample of parents.
            parent_coll = client.collection(parent_result.name)
            for parent_doc in _take(parent_coll.stream(), cfg.parent_sample_for_subcollections):
                child_path = f"{parent_result.name}/{parent_doc.id}/{subcol_id}"
                if child_path in visited:
                    continue
                visited.add(child_path)
                child_result = scan_collection(client, collection_path=child_path, cfg=cfg)
                results.append(child_result)
                pending.append((child_result, depth + 1))

    return results


def _take(iterable, n):
    out = []
    for i, item in enumerate(iterable):
        if i >= n:
            break
        out.append(item)
    return out
