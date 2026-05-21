"""Schema policy decision engine.

Reference: references/schema-policy.md. Same auto algorithm as Firestore, with
the Hybrid-merge bug fix applied from day one (non-indexed fields collapse
into a single `doc JSON` column).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from tishift_mongodb.config import (
    ConvertConfig,
    PerCollectionConvertOverride,
    SchemaPolicy,
)
from tishift_mongodb.core.scan.indexes import IndexInfo, fields_in_any_composite_index
from tishift_mongodb.core.scan.type_inferrer import FieldHistogram


PolicyChoice = Literal["json-mostly", "hybrid", "normalized"]


@dataclass
class CollectionPolicy:
    collection_name: str
    policy: PolicyChoice
    rationale: str
    typed_columns: list[str] = field(default_factory=list)
    # For Hybrid: single 'doc' JSON column holds the non-indexed fields.
    # For json-mostly: the full document body lands in 'doc'.
    merged_json_column: bool = False
    json_columns: list[str] = field(default_factory=list)  # user-forced individual JSON columns
    flagged_for_review: list[str] = field(default_factory=list)
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
    indexes: list[IndexInfo],
    convert_cfg: ConvertConfig,
) -> CollectionPolicy:
    """Decide JSON-mostly / Hybrid / Normalized for one collection.

    Hybrid policy correctness: non-indexed fields collapse into ONE merged
    `doc JSON` column, not into individual JSON columns per field.
    """
    override: PerCollectionConvertOverride | None = convert_cfg.per_collection.get(collection_name)
    indexed_fields = fields_in_any_composite_index(indexes, collection=collection_name)
    polymorphic = _polymorphic_field_paths(histograms)
    poly_ratio = _polymorphic_field_ratio(histograms)

    # Explicit override wins
    forced: SchemaPolicy | None = override.policy if override else None
    if forced and forced != "auto":
        policy_choice: PolicyChoice = forced  # type: ignore[assignment]
        rationale = f"Forced by per_collection.{collection_name}.policy"
    elif convert_cfg.schema_policy_default != "auto":
        policy_choice = convert_cfg.schema_policy_default  # type: ignore[assignment]
        rationale = f"Forced by schema_policy_default = {convert_cfg.schema_policy_default}"
    elif not indexed_fields and poly_ratio > 0.30:
        policy_choice = "json-mostly"
        rationale = f"No composite indexes; {poly_ratio:.0%} polymorphic fields → json-mostly"
    elif not indexed_fields:
        policy_choice = "json-mostly"
        rationale = "No composite indexes; no query parity needed → json-mostly"
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
    merged_json = False

    if policy_choice == "json-mostly":
        typed_cols = ["id"]
        merged_json = True
        # Surface polymorphic-in-indexed warnings if any
        for f in indexed_fields & polymorphic:
            flagged.append(f"{f} (BLOCKER-5) — polymorphic in indexed path")

    elif policy_choice == "normalized":
        for path, hist in sorted(histograms.items()):
            if "." in path:
                continue  # nested handled by ddl_emitter
            if hist.is_polymorphic():
                flagged.append(f"{path} (BLOCKER-5) — polymorphic; normalized requires typed col")
                json_cols.append(path)
            else:
                typed_cols.append(path)

    else:  # hybrid (the corrected behavior — single merged doc JSON)
        typed_set: set[str] = set()
        if override:
            typed_set.update(override.flatten_columns)
        for f in indexed_fields:
            if override and f in override.json_columns:
                json_cols.append(f)
            else:
                typed_set.add(f)
        for path in sorted(histograms.keys()):
            if "." in path:
                continue
            if path in typed_set:
                typed_cols.append(path)
                if path in indexed_fields and histograms[path].is_polymorphic():
                    flagged.append(f"{path} (BLOCKER-5) — polymorphic in indexed path")
            # else: lands in the single merged doc JSON (not individual JSON cols)
        merged_json = True

    return CollectionPolicy(
        collection_name=collection_name,
        policy=policy_choice,
        rationale=rationale,
        typed_columns=sorted(set(typed_cols)),
        merged_json_column=merged_json,
        json_columns=sorted(set(json_cols)),
        flagged_for_review=sorted(flagged),
        indexed_field_paths=set(indexed_fields),
    )


def decide_policy(
    *,
    histograms_by_collection: dict[str, dict[str, FieldHistogram]],
    indexes: list[IndexInfo],
    convert_cfg: ConvertConfig,
) -> SchemaPolicyPlan:
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
