"""Schema policy decision engine.

Reference: references/schema-policy.md — the auto algorithm encoded here
should match what's documented there.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from tishift_firestore.config import (
    ConvertConfig,
    PerCollectionConvertOverride,
    SchemaPolicy,
)
from tishift_firestore.core.scan.indexes import CompositeIndex, fields_in_any_index
from tishift_firestore.core.scan.type_inferrer import FieldHistogram


PolicyChoice = Literal["json-mostly", "hybrid", "normalized"]


@dataclass
class CollectionPolicy:
    collection_name: str
    policy: PolicyChoice
    rationale: str
    typed_columns: list[str] = field(default_factory=list)
    # For Hybrid: non-indexed/non-flattened fields collapse into a single
    # `doc JSON` column (set via merged_json_column=True), NOT into individual
    # JSON columns per field. The latter is the worst of both worlds — JSON
    # storage cost per field without the indexability benefit of typed cols.
    # For JSON-mostly: the full document body lands in `doc`.
    # `json_columns` here is for the user-override case only (operator
    # explicitly asked for these specific fields to be their own JSON cols).
    merged_json_column: bool = False
    json_columns: list[str] = field(default_factory=list)
    flagged_for_review: list[str] = field(default_factory=list)
    geopoint_mapping: dict[str, str] = field(default_factory=dict)
    indexed_field_paths: set[str] = field(default_factory=set)


@dataclass
class SchemaPolicyPlan:
    collections: list[CollectionPolicy]

    def by_name(self, name: str) -> CollectionPolicy | None:
        for c in self.collections:
            if c.collection_name == name:
                return c
        return None


def _polymorphic_field_ratio(histograms: dict[str, FieldHistogram]) -> float:
    if not histograms:
        return 0.0
    poly = sum(1 for h in histograms.values() if h.is_polymorphic())
    return poly / len(histograms)


def _polymorphic_field_paths(histograms: dict[str, FieldHistogram]) -> set[str]:
    return {h.field_path for h in histograms.values() if h.is_polymorphic()}


def decide_policy_for_collection(
    *,
    collection_name: str,
    histograms: dict[str, FieldHistogram],
    indexes: list[CompositeIndex],
    convert_cfg: ConvertConfig,
) -> CollectionPolicy:
    """Decide JSON-mostly / Hybrid / Normalized for a single collection."""
    override: PerCollectionConvertOverride | None = convert_cfg.per_collection.get(collection_name)
    indexed_fields = fields_in_any_index(indexes, collection_or_group=collection_name)
    polymorphic = _polymorphic_field_paths(histograms)
    poly_ratio = _polymorphic_field_ratio(histograms)

    # Explicit per-collection override wins.
    forced: SchemaPolicy | None = override.policy if override else None
    if forced and forced != "auto":
        # Validate that forced normalized doesn't have polymorphism in indexed paths
        # unless the user has explicitly mapped each poly field.
        policy_choice: PolicyChoice = forced  # type: ignore[assignment]
        rationale = f"Forced by config (schema_policy_default or per_collection.{collection_name})"
    else:
        # Auto algorithm.
        if convert_cfg.schema_policy_default != "auto":
            forced = convert_cfg.schema_policy_default
            policy_choice = forced  # type: ignore[assignment]
            rationale = f"Forced by config default ({forced})"
        elif not indexed_fields and poly_ratio > 0.30:
            policy_choice = "json-mostly"
            rationale = (
                f"No composite indexes; {poly_ratio:.0%} polymorphic fields → JSON-mostly"
            )
        elif not indexed_fields:
            policy_choice = "json-mostly"
            rationale = "No composite indexes; no query parity needed → JSON-mostly"
        elif indexed_fields & polymorphic:
            policy_choice = "hybrid"
            rationale = (
                f"Composite indexes present; {len(indexed_fields & polymorphic)} "
                "polymorphic field(s) in indexed path"
            )
        else:
            policy_choice = "hybrid"
            rationale = "Composite indexes present; non-polymorphic indexed fields → hybrid"

    typed_cols: list[str] = []
    json_cols: list[str] = []
    flagged: list[str] = []
    geo_mapping: dict[str, str] = {}
    merged_json = False

    if policy_choice == "json-mostly":
        # Only the document ID is a typed col; the rest collapses into one
        # merged `doc JSON` column emitted by the DDL emitter.
        typed_cols = ["id"]
        merged_json = True
        # Still surface polymorphic-in-indexed warnings if any (rare for JSON-mostly).
        for f in indexed_fields & polymorphic:
            flagged.append(f"{f} (BLOCKER-4) — polymorphic in indexed path")

    elif policy_choice == "normalized":
        # Every observed top-level field becomes typed.
        for path, hist in sorted(histograms.items()):
            if "." in path:
                continue  # nested handled separately by the DDL emitter
            if hist.is_polymorphic():
                flagged.append(f"{path} (BLOCKER-4) — polymorphic; normalized requires typed col")
                # Polymorphic fields under "normalized" stay as individual named
                # JSON cols so they can be addressed by the application; the
                # user explicitly chose normalized despite the polymorphism.
                json_cols.append(path)
            else:
                typed_cols.append(path)

    else:  # hybrid (the corrected behavior — single merged doc JSON)
        typed_set: set[str] = set()
        # User-specified flatten_columns always go typed
        if override:
            typed_set.update(override.flatten_columns)

        # All composite-indexed fields go typed (unless explicitly overridden
        # to be their own named JSON column).
        for f in indexed_fields:
            if override and f in override.json_columns:
                json_cols.append(f)
            else:
                typed_set.add(f)

        # Non-indexed, non-flattened fields collapse into the merged `doc JSON`
        # column. We do NOT append them to json_cols (that would produce one
        # JSON column per field — the worst of both worlds).
        for path, hist in sorted(histograms.items()):
            if "." in path:
                continue
            if path in typed_set:
                typed_cols.append(path)
                if hist.is_polymorphic() and path in indexed_fields:
                    flagged.append(f"{path} (BLOCKER-4) — polymorphic in indexed path")
            # else: lands in the single merged doc JSON via merged_json=True

        merged_json = True

    # GeoPoint mapping
    if override:
        geo_mapping = dict(override.geopoint_mapping)

    return CollectionPolicy(
        collection_name=collection_name,
        policy=policy_choice,
        rationale=rationale,
        typed_columns=sorted(set(typed_cols)),
        merged_json_column=merged_json,
        json_columns=sorted(set(json_cols)),
        flagged_for_review=sorted(flagged),
        geopoint_mapping=geo_mapping,
        indexed_field_paths=set(indexed_fields),
    )


def decide_policy(
    *,
    histograms_by_collection: dict[str, dict[str, FieldHistogram]],
    indexes: list[CompositeIndex],
    convert_cfg: ConvertConfig,
) -> SchemaPolicyPlan:
    """Top-level entry point: decide policy for every collection."""
    out: list[CollectionPolicy] = []
    for name, histograms in sorted(histograms_by_collection.items()):
        out.append(
            decide_policy_for_collection(
                collection_name=name,
                histograms=histograms,
                indexes=indexes,
                convert_cfg=convert_cfg,
            )
        )
    return SchemaPolicyPlan(collections=out)
