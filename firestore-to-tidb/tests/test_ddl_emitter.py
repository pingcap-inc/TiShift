"""Tests for the DDL emitter — verifies generated SQL is valid TiDB DDL."""

from __future__ import annotations

from collections import Counter

from tishift_firestore.config import ConvertConfig
from tishift_firestore.core.convert.ddl_emitter import (
    DDLArtifact,
    _table_name,
    emit_ddl,
)
from tishift_firestore.core.convert.policy import (
    CollectionPolicy,
    SchemaPolicyPlan,
    decide_policy,
)
from tishift_firestore.core.scan.indexes import CompositeIndex, IndexField
from tishift_firestore.core.scan.type_inferrer import FieldHistogram


def _hist(name: str, *type_counts, **kwargs) -> FieldHistogram:
    h = FieldHistogram(field_path=name)
    h.sample_size = 100
    h.seen_count = sum(c for t, c in type_counts if t != "null")
    h.type_counts = Counter()
    for t, c in type_counts:
        h.type_counts[t] = c
    for k, v in kwargs.items():
        setattr(h, k, v)
    return h


def test_table_name_subcollection():
    assert _table_name("users") == "users"
    assert _table_name("users/u-123/orders") == "users_orders"


def test_emit_normalized_users_table():
    histograms = {
        "email": _hist("email", ("string", 100), max_observed_string_len=50),
        "age": _hist("age", ("number", 100), numeric_values=[float(i) for i in range(100)]),
        "location": _hist("location", ("geopoint", 100)),
    }
    plan = SchemaPolicyPlan(collections=[
        CollectionPolicy(
            collection_name="users",
            policy="hybrid",
            rationale="test",
            typed_columns=["email", "age", "location"],
        ),
    ])

    artifact = emit_ddl(
        plan=plan,
        histograms_by_collection={"users": histograms},
        indexes=[],
        convert_cfg=ConvertConfig(),
    )
    sql = artifact.create_tables

    assert "CREATE TABLE `users`" in sql
    assert "`email`" in sql
    assert "VARCHAR(" in sql
    assert "`age` BIGINT" in sql
    assert "`location_lat` DECIMAL(9,6)" in sql
    assert "`location_lng` DECIMAL(9,6)" in sql
    assert "PRIMARY KEY (`id`)" in sql
    assert "ENGINE=InnoDB" in sql


def test_emit_json_mostly():
    plan = SchemaPolicyPlan(collections=[
        CollectionPolicy(
            collection_name="audit_logs",
            policy="json-mostly",
            rationale="test",
            typed_columns=["id"],
            json_columns=["doc"],
        ),
    ])

    artifact = emit_ddl(
        plan=plan,
        histograms_by_collection={"audit_logs": {}},
        indexes=[],
        convert_cfg=ConvertConfig(),
    )
    sql = artifact.create_tables

    assert "CREATE TABLE `audit_logs`" in sql
    assert "`doc` JSON" in sql
    assert "PRIMARY KEY (`id`)" in sql


def test_emit_subcollection_has_parent_doc_id():
    histograms = {"total": _hist("total", ("number", 100))}
    plan = SchemaPolicyPlan(collections=[
        CollectionPolicy(
            collection_name="users/u-a/orders",
            policy="hybrid",
            rationale="test",
            typed_columns=["total"],
        ),
    ])

    artifact = emit_ddl(
        plan=plan,
        histograms_by_collection={"users/u-a/orders": histograms},
        indexes=[],
        convert_cfg=ConvertConfig(),
    )
    sql = artifact.create_tables

    assert "`parent_doc_id` VARCHAR(20)" in sql
    assert "KEY `idx_parent`" in sql


def test_emit_composite_index_secondary():
    histograms = {
        "status": _hist("status", ("string", 100)),
        "created_at": _hist("created_at", ("timestamp", 100)),
    }
    indexes = [
        CompositeIndex(
            collection_or_group="orders",
            scope="COLLECTION_GROUP",
            fields=[
                IndexField(name="status", order="ASCENDING"),
                IndexField(name="created_at", order="DESCENDING"),
            ],
        ),
    ]
    plan = SchemaPolicyPlan(collections=[
        CollectionPolicy(
            collection_name="orders",
            policy="hybrid",
            rationale="test",
            typed_columns=["status", "created_at"],
            indexed_field_paths={"status", "created_at"},
        ),
    ])

    artifact = emit_ddl(
        plan=plan,
        histograms_by_collection={"orders": histograms},
        indexes=indexes,
        convert_cfg=ConvertConfig(),
    )

    assert "CREATE INDEX" in artifact.create_indexes
    assert "`status` ASC" in artifact.create_indexes
    assert "`created_at` DESC" in artifact.create_indexes


def test_emit_artifact_writes_four_files(tmp_path):
    plan = SchemaPolicyPlan(collections=[
        CollectionPolicy(
            collection_name="t",
            policy="json-mostly",
            rationale="test",
            typed_columns=["id"],
            json_columns=["doc"],
        ),
    ])
    artifact = emit_ddl(
        plan=plan,
        histograms_by_collection={"t": {}},
        indexes=[],
        convert_cfg=ConvertConfig(),
    )

    artifact.write_all(tmp_path)
    for fname in [
        "01-create-tables.sql",
        "02-create-indexes.sql",
        "03-foreign-keys.sql",
        "04-multi-valued-indexes.sql",
        "convert-advisor.md",
    ]:
        assert (tmp_path / fname).exists(), f"missing {fname}"


def test_emit_advisor_lists_flags():
    plan = SchemaPolicyPlan(collections=[
        CollectionPolicy(
            collection_name="products",
            policy="hybrid",
            rationale="test",
            typed_columns=["sku"],
            json_columns=["attributes"],
            flagged_for_review=["price (BLOCKER-4) — polymorphic in indexed path"],
        ),
    ])
    artifact = emit_ddl(
        plan=plan,
        histograms_by_collection={"products": {}},
        indexes=[],
        convert_cfg=ConvertConfig(),
    )
    assert "BLOCKER-4" in artifact.advisor_markdown
    assert "Flagged for review" in artifact.advisor_markdown
