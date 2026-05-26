"""Tests for the schema policy decision engine."""

from __future__ import annotations

from collections import Counter

from tishift_firestore.config import ConvertConfig
from tishift_firestore.core.convert.policy import decide_policy_for_collection
from tishift_firestore.core.scan.indexes import CompositeIndex, IndexField
from tishift_firestore.core.scan.type_inferrer import FieldHistogram


def _hist(name: str, *type_counts) -> FieldHistogram:
    h = FieldHistogram(field_path=name)
    h.sample_size = 100
    h.seen_count = sum(c for t, c in type_counts if t != "null")
    for t, c in type_counts:
        h.type_counts[t] = c
    return h


def test_json_mostly_when_no_indexes_and_sparse():
    histograms = {
        "field_a": _hist("field_a", ("string", 30), ("null", 70)),  # sparse
        "field_b": _hist("field_b", ("string", 25), ("number", 25), ("null", 50)),  # poly + sparse
    }
    plan = decide_policy_for_collection(
        collection_name="audit_logs",
        histograms=histograms,
        indexes=[],
        convert_cfg=ConvertConfig(),
    )
    assert plan.policy == "json-mostly"


def test_json_mostly_when_no_indexes():
    histograms = {
        "name": _hist("name", ("string", 100)),
        "count": _hist("count", ("number", 100)),
    }
    plan = decide_policy_for_collection(
        collection_name="simple",
        histograms=histograms,
        indexes=[],
        convert_cfg=ConvertConfig(),
    )
    assert plan.policy == "json-mostly"


def test_hybrid_when_indexes_present():
    histograms = {
        "name": _hist("name", ("string", 100)),
        "category_ref": _hist("category_ref", ("reference", 100)),
        "price": _hist("price", ("number", 100)),
        "extra_data": _hist("extra_data", ("map", 100)),
    }
    indexes = [
        CompositeIndex(
            collection_or_group="products",
            scope="COLLECTION",
            fields=[IndexField(name="category_ref", order="ASC"),
                    IndexField(name="price", order="ASC")],
        ),
    ]
    plan = decide_policy_for_collection(
        collection_name="products",
        histograms=histograms,
        indexes=indexes,
        convert_cfg=ConvertConfig(),
    )
    assert plan.policy == "hybrid"
    # Indexed fields are typed
    assert "category_ref" in plan.typed_columns
    assert "price" in plan.typed_columns
    # Non-indexed fields collapse into the merged `doc JSON` column,
    # NOT into individual JSON columns per field. (json_columns is for
    # user-override-forced individual JSON columns only.)
    assert plan.merged_json_column is True
    assert "name" not in plan.json_columns
    assert "extra_data" not in plan.json_columns
    assert "name" not in plan.typed_columns
    assert "extra_data" not in plan.typed_columns


def test_polymorphic_in_indexed_path_flagged():
    histograms = {
        "price": _hist("price", ("number", 70), ("map", 30)),  # polymorphic
    }
    indexes = [
        CompositeIndex(
            collection_or_group="products",
            scope="COLLECTION",
            fields=[IndexField(name="price", order="ASC")],
        ),
    ]
    plan = decide_policy_for_collection(
        collection_name="products",
        histograms=histograms,
        indexes=indexes,
        convert_cfg=ConvertConfig(),
    )
    assert plan.policy == "hybrid"
    assert any("BLOCKER-4" in flag for flag in plan.flagged_for_review)


def test_forced_normalized_via_override():
    from tishift_firestore.config import PerCollectionConvertOverride

    histograms = {
        "name": _hist("name", ("string", 100)),
    }
    cfg = ConvertConfig(per_collection={
        "users": PerCollectionConvertOverride(policy="normalized")
    })
    plan = decide_policy_for_collection(
        collection_name="users",
        histograms=histograms,
        indexes=[],
        convert_cfg=cfg,
    )
    assert plan.policy == "normalized"


def test_default_to_hybrid_when_no_polymorphism():
    histograms = {
        "name": _hist("name", ("string", 100)),
        "category_ref": _hist("category_ref", ("reference", 100)),
    }
    indexes = [
        CompositeIndex(
            collection_or_group="x",
            scope="COLLECTION",
            fields=[IndexField(name="category_ref", order="ASC")],
        ),
    ]
    plan = decide_policy_for_collection(
        collection_name="x",
        histograms=histograms,
        indexes=indexes,
        convert_cfg=ConvertConfig(),
    )
    assert plan.policy == "hybrid"
    assert plan.flagged_for_review == []
