"""BLOCKER and WARNING rule evaluation against the Phase 2.5 checklist.

Reference: references/compatibility-rules.md — keep IDs and conditions in
sync with that file.
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
    """Phase 2.5 structured output. Populated from the scan report + user answers."""

    model_config = ConfigDict(extra="forbid")

    # Mode and edition
    mode: str = "native"
    edition: str = "standard"

    # Inventory
    collection_count: int = 0
    subcollection_count: int = 0
    total_document_count_estimate: int = 0
    total_data_gb_estimate: float = 0.0
    composite_index_count: int = 0
    document_reference_field_count: int = 0
    geopoint_field_count: int = 0
    bytes_field_count: int = 0
    bytes_field_max_size_mb: float = 0.0
    timestamp_field_count: int = 0
    server_timestamp_sentinel_detected: bool = False
    array_union_remove_sentinel_detected: bool = False
    polymorphic_field_count: int = 0
    polymorphic_field_in_indexed_path: bool = False
    sparse_field_ratio: float = 0.0
    subcollection_max_depth: int = 0
    largest_collection_doc_count: int = 0
    multiple_databases_in_project: bool = False
    cross_database_references: bool = False
    transaction_block_count: int = 0
    auto_id_generation_in_use: bool = True

    # User-supplied (from SKILL Phase 2.2 questions)
    has_realtime_listeners: bool = False
    security_rules_complexity: str = "none"  # none | simple | moderate | complex
    cutover_tolerance: str = "weekend"  # minutes | hours | weekend | longer
    firestore_bigquery_export_present: bool = False

    # Operational
    target_tier: str = "byoc"
    byoc_in_same_gcp_project: bool = True
    byoc_in_different_gcp_project: bool = False
    target_not_gcp: bool = False
    workload_identity_unavailable: bool = False


@dataclass(frozen=True)
class Finding:
    rule_id: str
    severity: Severity
    feature: str
    action: str


# Rule signature: (checklist) -> Optional finding
Rule = Callable[[Checklist], "Finding | None"]


# --- BLOCKERs ---

def _b1_mongo_api(cl: Checklist) -> Finding | None:
    if cl.mode == "mongo-api" or cl.edition == "enterprise":
        return Finding(
            "BLOCKER-1", Severity.BLOCKER,
            "Firestore Enterprise with MongoDB-compatibility API",
            "Abort this skill. Use the mongo-to-tidb skill instead.",
        )
    return None


def _b2_listeners(cl: Checklist) -> Finding | None:
    if cl.has_realtime_listeners:
        return Finding(
            "BLOCKER-2", Severity.BLOCKER,
            "Application uses onSnapshot listeners",
            "Application rewrite required: poll TiDB, use TiCDC→Kafka, or keep "
            "Firestore as a realtime tier alongside TiDB.",
        )
    return None


def _b3_complex_rules(cl: Checklist) -> Finding | None:
    if cl.security_rules_complexity == "complex":
        return Finding(
            "BLOCKER-3", Severity.BLOCKER,
            "Complex multi-doc / function-call security rules",
            "Cannot auto-translate. Manually rewrite to application-layer authorization.",
        )
    return None


def _b4_poly_in_indexed(cl: Checklist) -> Finding | None:
    if cl.polymorphic_field_in_indexed_path:
        return Finding(
            "BLOCKER-4", Severity.BLOCKER,
            "Polymorphic field in composite-indexed path",
            "Per field, choose: coerce in application, accept JSON column with "
            "degraded index parity, or skip the field.",
        )
    return None


def _b5_cross_db_refs(cl: Checklist) -> Finding | None:
    if cl.multiple_databases_in_project and cl.cross_database_references:
        return Finding(
            "BLOCKER-5", Severity.BLOCKER,
            "Cross-database DocumentReference",
            "v1 migrates one Firestore database per run. Plan multi-pass migration.",
        )
    return None


def _b6_datastore_mode(cl: Checklist) -> Finding | None:
    if cl.mode == "datastore":
        return Finding(
            "BLOCKER-6", Severity.BLOCKER,
            "Firestore in Datastore mode",
            "Limited fidelity support in v1; confirm whether your workload fits the "
            "Datastore-mode subset or wait for full Datastore-mode support.",
        )
    return None


# --- WARNINGs ---

def _w1_geopoints(cl: Checklist) -> Finding | None:
    if cl.geopoint_field_count > 0:
        return Finding(
            "WARNING-1", Severity.WARNING,
            "GeoPoint columns",
            f"Default mapping: split each into lat/lng DECIMAL(9,6) columns "
            f"({cl.geopoint_field_count} fields). Alt: JSON. Spatial indexing is limited in TiDB.",
        )
    return None


def _w2_large_bytes(cl: Checklist) -> Finding | None:
    if cl.bytes_field_max_size_mb > 5:
        return Finding(
            "WARNING-2", Severity.WARNING,
            "Large binary documents",
            f"Bytes field observed at {cl.bytes_field_max_size_mb} MB. "
            "Recommend offloading values >5 MB to GCS with a path column.",
        )
    return None


def _w3_many_subcols(cl: Checklist) -> Finding | None:
    if cl.subcollection_count > 50:
        return Finding(
            "WARNING-3", Severity.WARNING,
            "Many subcollections",
            f"{cl.subcollection_count} subcollections detected; each becomes a child table.",
        )
    return None


def _w4_timestamps(cl: Checklist) -> Finding | None:
    if cl.timestamp_field_count > 0:
        return Finding(
            "WARNING-4", Severity.WARNING,
            "Nanosecond Timestamp precision",
            "TiDB DATETIME(6) is microsecond. Three digits of precision lost.",
        )
    return None


def _w5_server_ts(cl: Checklist) -> Finding | None:
    if cl.server_timestamp_sentinel_detected:
        return Finding(
            "WARNING-5", Severity.WARNING,
            "serverTimestamp() sentinel writes",
            "Application writes must drop the sentinel; column gets "
            "DEFAULT CURRENT_TIMESTAMP(6) server-side.",
        )
    return None


def _w6_many_indexes(cl: Checklist) -> Finding | None:
    if cl.composite_index_count > 100:
        return Finding(
            "WARNING-6", Severity.WARNING,
            "Heavy query workload",
            f"{cl.composite_index_count} composite indexes. Plan the index-build order "
            "post-load; each can take hours at multi-TB scale.",
        )
    return None


def _w7_poly_non_indexed(cl: Checklist) -> Finding | None:
    if cl.polymorphic_field_count > 0 and not cl.polymorphic_field_in_indexed_path:
        return Finding(
            "WARNING-7", Severity.WARNING,
            "Polymorphic fields outside indexed paths",
            f"{cl.polymorphic_field_count} polymorphic fields. Default mapping = JSON column.",
        )
    return None


def _w8_bulk_size(cl: Checklist) -> Finding | None:
    if cl.total_data_gb_estimate > 5000:
        return Finding(
            "WARNING-8", Severity.WARNING,
            "Bulk size > 5 TB",
            "Direct strategy not viable; Dataflow + Lightning is mandatory. Multi-day jobs expected.",
        )
    return None


def _w9_dangling_refs(cl: Checklist) -> Finding | None:
    # Heuristic — we surface this if refs exist but cross-database refs are flagged
    if cl.document_reference_field_count > 0 and cl.cross_database_references:
        return Finding(
            "WARNING-9", Severity.WARNING,
            "Dangling DocumentReference",
            "Some references point outside the scoped database; FK cannot be created. "
            "Either expand scan scope or leave as unindexed VARCHAR.",
        )
    return None


def _w10_auto_ids(cl: Checklist) -> Finding | None:
    if cl.auto_id_generation_in_use:
        return Finding(
            "WARNING-10", Severity.WARNING,
            "Firestore auto-generated 20-char IDs",
            "Default: preserve as VARCHAR(20) PRIMARY KEY. AUTO_RANDOM switch is opt-in.",
        )
    return None


def _w11_cdc_extension(cl: Checklist) -> Finding | None:
    if cl.cutover_tolerance == "minutes" and not cl.firestore_bigquery_export_present:
        return Finding(
            "WARNING-11", Severity.WARNING,
            "CDC required, extension not installed",
            "Install firestore-bigquery-export ≥7 days before cutover so change "
            "history accumulates.",
        )
    return None


def _w12_multi_db(cl: Checklist) -> Finding | None:
    if cl.multiple_databases_in_project and not cl.cross_database_references:
        return Finding(
            "WARNING-12", Severity.WARNING,
            "Multi-database project, no cross-DB refs",
            "Plan separate migration runs for sibling databases.",
        )
    return None


def _w13_sparse(cl: Checklist) -> Finding | None:
    if cl.sparse_field_ratio > 0.30:
        return Finding(
            "WARNING-13", Severity.WARNING,
            "Many sparse fields",
            f"{cl.sparse_field_ratio:.0%} of fields are sparse. Consider JSON-mostly policy.",
        )
    return None


ALL_RULES: list[Rule] = [
    _b1_mongo_api, _b2_listeners, _b3_complex_rules, _b4_poly_in_indexed,
    _b5_cross_db_refs, _b6_datastore_mode,
    _w1_geopoints, _w2_large_bytes, _w3_many_subcols, _w4_timestamps,
    _w5_server_ts, _w6_many_indexes, _w7_poly_non_indexed, _w8_bulk_size,
    _w9_dangling_refs, _w10_auto_ids, _w11_cdc_extension, _w12_multi_db,
    _w13_sparse,
]


def evaluate(checklist: Checklist) -> list[Finding]:
    """Evaluate every rule against the checklist. Returns findings in rule-order."""
    out: list[Finding] = []
    for rule in ALL_RULES:
        finding = rule(checklist)
        if finding is not None:
            out.append(finding)
    return out
