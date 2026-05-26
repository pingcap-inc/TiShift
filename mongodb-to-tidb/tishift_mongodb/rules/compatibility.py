"""BLOCKER and WARNING rule evaluation against the Phase 2.5 checklist.

Reference: references/compatibility-rules.md — keep IDs and conditions in sync.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable

from pydantic import BaseModel, ConfigDict


class Severity(str, Enum):
    BLOCKER = "BLOCKER"
    WARNING = "WARNING"


class Checklist(BaseModel):
    """Phase 2.5 structured output. Populated from scan report + user answers."""

    model_config = ConfigDict(extra="forbid")

    # Topology + version
    topology: str = "replica_set"
    mongo_version: str = "7.0"

    # Inventory
    collection_count: int = 0
    total_document_count_estimate: int = 0
    total_data_gb_estimate: float = 0.0
    composite_index_count: int = 0
    geospatial_index_count: int = 0
    text_index_count: int = 0
    wildcard_index_count: int = 0
    partial_index_count: int = 0
    ttl_index_count: int = 0
    dbref_field_count: int = 0
    objectid_field_count: int = 0
    decimal128_field_count: int = 0
    binary_field_count: int = 0
    csfle_field_count: int = 0
    date_field_count: int = 0
    has_polymorphic_id: bool = False
    polymorphic_field_count: int = 0
    polymorphic_field_in_indexed_path: bool = False
    sparse_field_ratio: float = 0.0
    subdocument_max_depth: int = 0
    largest_collection_doc_count: int = 0
    has_capped_collections: bool = False
    has_gridfs: bool = False
    binary_field_max_size_mb: float = 0.0
    binary_field_total_gb: float = 0.0

    # Aggregation inventory
    aggregation_pipeline_count: int = 0
    aggregation_complexity_total: int = 0
    aggregation_advisor_enabled: bool = True
    transaction_block_count: int = 0

    # User-supplied (from SKILL Phase 2.2)
    cutover_tolerance: str = "weekend"  # minutes | hours | weekend | longer

    # Operational
    target_tier: str = "dedicated"
    storage_backend: str = "local"
    load_strategy: str = "auto"


@dataclass(frozen=True)
class Finding:
    rule_id: str
    severity: Severity
    feature: str
    action: str


Rule = Callable[[Checklist], "Finding | None"]


# --- BLOCKERs ---

def _b1_standalone_cdc(cl: Checklist) -> Finding | None:
    if cl.topology == "standalone" and cl.cutover_tolerance in ("minutes", "hours"):
        return Finding(
            "BLOCKER-1", Severity.BLOCKER,
            "Standalone topology cannot support Change Streams",
            "Convert source to single-node replica set before cutover, "
            "OR accept a longer read-only window.",
        )
    return None


def _b2_polymorphic_id(cl: Checklist) -> Finding | None:
    if cl.has_polymorphic_id:
        return Finding(
            "BLOCKER-2", Severity.BLOCKER,
            "Polymorphic _id field across docs in a collection",
            "TiDB PK requires one type. Choose per collection: coerce to "
            "string, split into per-type child tables, or skip.",
        )
    return None


def _b3_csfle(cl: Checklist) -> Finding | None:
    if cl.csfle_field_count > 0:
        return Finding(
            "BLOCKER-3", Severity.BLOCKER,
            "Client-Side Field-Level Encryption (Binary subtype 6)",
            "Encrypted fields are opaque without client keys. Exclude them or "
            "update the application to not depend on them.",
        )
    return None


def _b4_heavy_aggregation_no_advisor(cl: Checklist) -> Finding | None:
    if cl.aggregation_complexity_total > 100 and not cl.aggregation_advisor_enabled:
        return Finding(
            "BLOCKER-4", Severity.BLOCKER,
            "Heavy aggregation usage without rewrite guidance",
            "Enable convert.aggregation_advisor.enabled, or commit to manual "
            "rewrite for every pipeline before proceeding.",
        )
    return None


def _b5_poly_in_indexed(cl: Checklist) -> Finding | None:
    if cl.polymorphic_field_in_indexed_path:
        return Finding(
            "BLOCKER-5", Severity.BLOCKER,
            "Polymorphic field in composite-indexed path",
            "Per field: coerce in application, accept JSON column with "
            "degraded index parity, or skip.",
        )
    return None


def _b6_gridfs(cl: Checklist) -> Finding | None:
    if cl.has_gridfs:
        return Finding(
            "BLOCKER-6", Severity.BLOCKER,
            "GridFS file storage",
            "TiDB has no GridFS equivalent. Offload files to object storage "
            "before running TiShift; update application to read from there.",
        )
    return None


def _b7_pretransactions(cl: Checklist) -> Finding | None:
    if cl.mongo_version < "4.2" and cl.transaction_block_count > 0:
        return Finding(
            "BLOCKER-7", Severity.BLOCKER,
            "Pre-4.2 Mongo with multi-doc transactions",
            "Upgrade Mongo to 4.2+ before migration, or accept that some "
            "atomic-multi-doc sequences may not behave identically.",
        )
    return None


# --- WARNINGs ---

def _w1_geo(cl: Checklist) -> Finding | None:
    if cl.geospatial_index_count > 0:
        return Finding(
            "WARNING-1", Severity.WARNING,
            "Geospatial indexes",
            f"{cl.geospatial_index_count} geospatial index(es). TiDB has "
            "limited spatial support — app-side math, external geo service, "
            "or drop the queries.",
        )
    return None


def _w2_text(cl: Checklist) -> Finding | None:
    if cl.text_index_count > 0 and cl.target_tier in ("starter", "essential", "dedicated"):
        return Finding(
            "WARNING-2", Severity.WARNING,
            "Text indexes",
            "TiDB Cloud FTS available on some tiers; self-hosted lacks parity. "
            "Move to a tier with FTS or integrate Elasticsearch/OpenSearch.",
        )
    return None


def _w3_wildcard(cl: Checklist) -> Finding | None:
    if cl.wildcard_index_count > 0:
        return Finding(
            "WARNING-3", Severity.WARNING,
            "Wildcard indexes",
            "No TiDB equivalent. JSON-mostly policy + functional indexes on "
            "known JSON paths.",
        )
    return None


def _w4_partial(cl: Checklist) -> Finding | None:
    if cl.partial_index_count > 0:
        return Finding(
            "WARNING-4", Severity.WARNING,
            "Partial indexes",
            "Approximate via generated columns + WHERE-filter. Native partial "
            "indexes arrive in TiDB v8.x.",
        )
    return None


def _w5_ttl(cl: Checklist) -> Finding | None:
    if cl.ttl_index_count > 0:
        return Finding(
            "WARNING-5", Severity.WARNING,
            "TTL indexes",
            "Direct map to TiDB TTL clause (v6.5+). Convert phase will emit.",
        )
    return None


def _w6_capped(cl: Checklist) -> Finding | None:
    if cl.has_capped_collections:
        return Finding(
            "WARNING-6", Severity.WARNING,
            "Capped collections",
            "No direct equivalent. Approximate with TTL + size-bounded delete; "
            "insertion-order guarantees weaker.",
        )
    return None


def _w7_aggregation_present(cl: Checklist) -> Finding | None:
    if cl.aggregation_pipeline_count > 0 and cl.aggregation_advisor_enabled:
        return Finding(
            "WARNING-7", Severity.WARNING,
            "Aggregation pipelines with advisor",
            f"{cl.aggregation_pipeline_count} pipelines. Advisor produces "
            "SUGGESTIONS — every rewrite needs human review.",
        )
    return None


def _w8_poly_non_indexed(cl: Checklist) -> Finding | None:
    if cl.polymorphic_field_count > 0 and not cl.polymorphic_field_in_indexed_path:
        return Finding(
            "WARNING-8", Severity.WARNING,
            "Polymorphic fields outside indexed paths",
            f"{cl.polymorphic_field_count} polymorphic fields. Default to JSON.",
        )
    return None


def _w9_sharded(cl: Checklist) -> Finding | None:
    if cl.topology == "sharded":
        return Finding(
            "WARNING-9", Severity.WARNING,
            "Sharded cluster",
            "TiShift uses per-shard mongodump parallelism for faster bulk load.",
        )
    return None


def _w10_dbref(cl: Checklist) -> Finding | None:
    if cl.dbref_field_count > 0:
        return Finding(
            "WARNING-10", Severity.WARNING,
            "DBRef-style references",
            f"{cl.dbref_field_count} DBRef field(s). Map to VARCHAR FK; emit "
            "FK constraint when target collection in scope.",
        )
    return None


def _w11_decimal128(cl: Checklist) -> Finding | None:
    if cl.decimal128_field_count > 0:
        return Finding(
            "WARNING-11", Severity.WARNING,
            "Decimal128 fields",
            "Map to DECIMAL(38,11). Verify no values exceed 34-digit significand.",
        )
    return None


def _w12_bulk_size(cl: Checklist) -> Finding | None:
    if cl.total_data_gb_estimate > 1000:
        return Finding(
            "WARNING-12", Severity.WARNING,
            "Bulk size > 1 TB",
            "direct strategy not viable. Use mongodump-lightning or adapter. "
            "Multi-day load expected.",
        )
    return None


def _w13_sparse(cl: Checklist) -> Finding | None:
    if cl.sparse_field_ratio > 0.30:
        return Finding(
            "WARNING-13", Severity.WARNING,
            "Many sparse fields",
            f"{cl.sparse_field_ratio:.0%} of fields are sparse. Consider "
            "json-mostly policy.",
        )
    return None


def _w14_large_binary(cl: Checklist) -> Finding | None:
    if cl.binary_field_max_size_mb > 5:
        return Finding(
            "WARNING-14", Severity.WARNING,
            "Large Binary fields",
            f"Max observed: {cl.binary_field_max_size_mb} MB. Recommend "
            "offloading >5 MB Binary values to object storage.",
        )
    return None


def _w15_old_mongo(cl: Checklist) -> Finding | None:
    if cl.mongo_version < "4.0":
        return Finding(
            "WARNING-15", Severity.WARNING,
            "Pre-4.0 Mongo",
            "No Change Streams; multi-doc transactions limited. Upgrade recommended.",
        )
    return None


def _w16_standalone_weekend(cl: Checklist) -> Finding | None:
    if cl.topology == "standalone" and cl.cutover_tolerance == "weekend":
        return Finding(
            "WARNING-16", Severity.WARNING,
            "Standalone with weekend cutover (acceptable)",
            "No CDC needed; bulk load during read-only window. Informational.",
        )
    return None


ALL_RULES: list[Rule] = [
    _b1_standalone_cdc, _b2_polymorphic_id, _b3_csfle, _b4_heavy_aggregation_no_advisor,
    _b5_poly_in_indexed, _b6_gridfs, _b7_pretransactions,
    _w1_geo, _w2_text, _w3_wildcard, _w4_partial, _w5_ttl, _w6_capped,
    _w7_aggregation_present, _w8_poly_non_indexed, _w9_sharded, _w10_dbref,
    _w11_decimal128, _w12_bulk_size, _w13_sparse, _w14_large_binary,
    _w15_old_mongo, _w16_standalone_weekend,
]


def evaluate(checklist: Checklist) -> list[Finding]:
    """Evaluate every rule. Returns findings in rule-order."""
    out: list[Finding] = []
    for rule in ALL_RULES:
        finding = rule(checklist)
        if finding is not None:
            out.append(finding)
    return out
