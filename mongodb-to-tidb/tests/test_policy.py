"""Tests for the schema policy decision engine."""

from __future__ import annotations

from collections import Counter

from tishift_mongodb.config import ConvertConfig
from tishift_mongodb.core.convert.policy import decide_policy_for_collection
from tishift_mongodb.core.scan.indexes import IndexField, IndexInfo
from tishift_mongodb.core.scan.type_inferrer import FieldHistogram


def _hist(name: str, *type_counts) -> FieldHistogram:
    h = FieldHistogram(field_path=name)
    h.sample_size = 100
    h.seen_count = sum(c for t, c in type_counts if t != "null")
    h.type_counts = Counter()
    for t, c in type_counts:
        h.type_counts[t] = c
    return h


def test_json_mostly_no_indexes_high_polymorphism():
    histograms = {
        "f1": _hist("f1", ("String", 30), ("Int32", 30), ("null", 40)),  # polymorphic + sparse
        "f2": _hist("f2", ("String", 20), ("Object", 20), ("null", 60)),
    }
    plan = decide_policy_for_collection(
        collection_name="audit_logs",
        histograms=histograms,
        indexes=[],
        convert_cfg=ConvertConfig(),
    )
    assert plan.policy == "json-mostly"


def test_json_mostly_no_indexes():
    histograms = {"name": _hist("name", ("String", 100))}
    plan = decide_policy_for_collection(
        collection_name="simple",
        histograms=histograms,
        indexes=[],
        convert_cfg=ConvertConfig(),
    )
    assert plan.policy == "json-mostly"


def test_hybrid_with_composite_indexes():
    histograms = {
        "name": _hist("name", ("String", 100)),
        "country": _hist("country", ("String", 100)),
        "tier": _hist("tier", ("String", 100)),
        "extra": _hist("extra", ("Object", 100)),
    }
    indexes = [
        IndexInfo(
            name="ct",
            collection="users",
            fields=[IndexField("country", 1), IndexField("tier", 1)],
        ),
    ]
    plan = decide_policy_for_collection(
        collection_name="users",
        histograms=histograms,
        indexes=indexes,
        convert_cfg=ConvertConfig(),
    )
    assert plan.policy == "hybrid"
    assert "country" in plan.typed_columns
    assert "tier" in plan.typed_columns
    assert plan.merged_json_column   # non-indexed fields collapse into doc JSON
    # Critical correctness check: 'name' and 'extra' should NOT appear as
    # individual JSON columns (Hybrid-merge fix from Firestore)
    assert "name" not in plan.json_columns
    assert "extra" not in plan.json_columns


def test_polymorphic_in_indexed_flags_blocker():
    histograms = {
        "price": _hist("price", ("Int32", 70), ("Object", 30)),
    }
    indexes = [
        IndexInfo(
            name="catprice",
            collection="products",
            fields=[IndexField("category_ref", 1), IndexField("price", 1)],
        ),
    ]
    plan = decide_policy_for_collection(
        collection_name="products",
        histograms=histograms,
        indexes=indexes,
        convert_cfg=ConvertConfig(),
    )
    assert any("BLOCKER-5" in flag for flag in plan.flagged_for_review)


def test_forced_normalized_via_override():
    from tishift_mongodb.config import PerCollectionConvertOverride
    histograms = {"name": _hist("name", ("String", 100))}
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
