"""Tests for the DDL emitter — especially the Hybrid-merge fix."""

from __future__ import annotations

from collections import Counter

from tishift_mongodb.config import ConvertConfig
from tishift_mongodb.core.convert.ddl_emitter import _table_name, emit_ddl
from tishift_mongodb.core.convert.policy import CollectionPolicy, SchemaPolicyPlan
from tishift_mongodb.core.scan.indexes import IndexField, IndexInfo
from tishift_mongodb.core.scan.type_inferrer import FieldHistogram


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


def test_table_name():
    assert _table_name("users") == "users"


def test_hybrid_emits_single_merged_doc_json(tmp_path):
    """The Hybrid-merge fix: non-indexed fields collapse into ONE 'doc' JSON column."""
    histograms = {
        "country_code": _hist("country_code", ("String", 100), max_observed_string_len=2),
        "tier": _hist("tier", ("String", 100), max_observed_string_len=16),
        "created_at": _hist("created_at", ("Date", 100)),
        "email": _hist("email", ("String", 100)),
        "display_name": _hist("display_name", ("String", 100)),
        "age": _hist("age", ("Int32", 100)),
    }
    plan = SchemaPolicyPlan(collections=[
        CollectionPolicy(
            collection_name="users",
            policy="hybrid",
            rationale="test",
            typed_columns=["country_code", "tier", "created_at"],
            merged_json_column=True,
            indexed_field_paths={"country_code", "tier", "created_at"},
        ),
    ])

    artifact = emit_ddl(
        plan=plan,
        histograms_by_collection={"users": histograms},
        indexes=[],
        convert_cfg=ConvertConfig(),
        id_types={"users": "ObjectId"},
    )
    sql = artifact.create_tables

    # Indexed fields land as typed columns
    assert "`country_code` VARCHAR" in sql
    assert "`tier` VARCHAR" in sql
    assert "`created_at` DATETIME(6)" in sql

    # The single merged doc JSON column
    assert "`doc` JSON" in sql

    # Non-indexed fields do NOT each get their own JSON column
    # (the bug from the Firestore variant)
    assert "`email` JSON" not in sql
    assert "`display_name` JSON" not in sql
    assert "`age` JSON" not in sql


def test_json_mostly_table():
    plan = SchemaPolicyPlan(collections=[
        CollectionPolicy(
            collection_name="audit_logs",
            policy="json-mostly",
            rationale="test",
            typed_columns=["id"],
            merged_json_column=True,
        ),
    ])
    artifact = emit_ddl(
        plan=plan,
        histograms_by_collection={"audit_logs": {}},
        indexes=[],
        convert_cfg=ConvertConfig(),
        id_types={"audit_logs": "ObjectId"},
    )
    sql = artifact.create_tables
    assert "CREATE TABLE `audit_logs`" in sql
    assert "`doc` JSON" in sql
    assert "PRIMARY KEY (`id`)" in sql


def test_emit_unique_secondary_index():
    histograms = {"email": _hist("email", ("String", 100), max_observed_string_len=128)}
    plan = SchemaPolicyPlan(collections=[
        CollectionPolicy(
            collection_name="users",
            policy="hybrid",
            rationale="test",
            typed_columns=["email"],
            merged_json_column=True,
        ),
    ])
    indexes = [
        IndexInfo(
            name="email_unique",
            collection="users",
            fields=[IndexField("email", 1)],
            unique=True,
        ),
    ]
    artifact = emit_ddl(
        plan=plan,
        histograms_by_collection={"users": histograms},
        indexes=indexes,
        convert_cfg=ConvertConfig(),
    )
    assert "UNIQUE INDEX" in artifact.create_indexes
    assert "`email`" in artifact.create_indexes


def test_artifact_writes_files(tmp_path):
    plan = SchemaPolicyPlan(collections=[
        CollectionPolicy(
            collection_name="t",
            policy="json-mostly",
            rationale="test",
            typed_columns=["id"],
            merged_json_column=True,
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
        assert (tmp_path / fname).exists()


def test_objectid_id_column():
    plan = SchemaPolicyPlan(collections=[
        CollectionPolicy(
            collection_name="t", policy="json-mostly", rationale="test",
            typed_columns=["id"], merged_json_column=True,
        ),
    ])
    artifact = emit_ddl(
        plan=plan,
        histograms_by_collection={"t": {}},
        indexes=[],
        convert_cfg=ConvertConfig(),
        id_types={"t": "ObjectId"},
    )
    assert "`id` VARCHAR(24) NOT NULL" in artifact.create_tables


def test_int64_id_column():
    plan = SchemaPolicyPlan(collections=[
        CollectionPolicy(
            collection_name="t", policy="json-mostly", rationale="test",
            typed_columns=["id"], merged_json_column=True,
        ),
    ])
    artifact = emit_ddl(
        plan=plan,
        histograms_by_collection={"t": {}},
        indexes=[],
        convert_cfg=ConvertConfig(),
        id_types={"t": "Int64"},
    )
    assert "`id` BIGINT NOT NULL" in artifact.create_tables
