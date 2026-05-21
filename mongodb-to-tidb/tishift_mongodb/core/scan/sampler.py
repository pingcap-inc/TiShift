"""Sample size policy for the scan phase."""

from __future__ import annotations

from dataclasses import dataclass

from tishift_mongodb.config import ScanConfig


@dataclass(frozen=True)
class SamplePlan:
    collection_name: str
    target_sample_size: int
    estimated_count: int
    full_scan: bool


def plan_sample(
    collection_name: str,
    *,
    estimated_count: int,
    cfg: ScanConfig,
) -> SamplePlan:
    """Decide how many documents to sample from one collection."""
    if estimated_count <= cfg.full_scan_threshold_docs:
        return SamplePlan(
            collection_name=collection_name,
            target_sample_size=estimated_count,
            estimated_count=estimated_count,
            full_scan=True,
        )
    one_pct = max(1, estimated_count // 100)
    target = max(cfg.sample_size_per_collection, one_pct)
    target = min(target, 5000)
    return SamplePlan(
        collection_name=collection_name,
        target_sample_size=target,
        estimated_count=estimated_count,
        full_scan=False,
    )
