"""DDL emission: turns a SchemaPolicyPlan into 4 TiDB SQL files.

Reference: references/type-mapping.md, references/schema-policy.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tishift_firestore.config import ConvertConfig
from tishift_firestore.core.convert.policy import CollectionPolicy, SchemaPolicyPlan
from tishift_firestore.core.scan.indexes import CompositeIndex
from tishift_firestore.core.scan.type_inferrer import FieldHistogram
from tishift_firestore.rules.identifiers import (
    quote_ident,
    safe_column_name,
    safe_table_name,
)
from tishift_firestore.rules.type_map import (
    ColumnSpec,
    integer_shaped,
    map_bytes,
    map_document_id,
    map_document_reference,
    map_geopoint,
    map_map_as_json,
    map_array_as_json,
    map_parent_doc_id,
    map_scalar_boolean,
    map_scalar_number,
    map_scalar_string,
    map_timestamp,
    varchar_size_for,
)


@dataclass
class DDLArtifact:
    create_tables: str
    create_indexes: str
    foreign_keys: str
    multi_valued_indexes: str
    advisor_markdown: str

    def write_all(self, out_dir: str | Path) -> None:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "01-create-tables.sql").write_text(self.create_tables, encoding="utf-8")
        (out / "02-create-indexes.sql").write_text(self.create_indexes, encoding="utf-8")
        (out / "03-foreign-keys.sql").write_text(self.foreign_keys, encoding="utf-8")
        (out / "04-multi-valued-indexes.sql").write_text(
            self.multi_valued_indexes, encoding="utf-8"
        )
        (out / "convert-advisor.md").write_text(self.advisor_markdown, encoding="utf-8")


_TABLE_SUFFIX = " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin"


def _table_name(collection_path: str) -> str:
    """Map a Firestore collection path to a TiDB table name.

    Raises UnsafeIdentifierError if the collection path produces an identifier
    that cannot safely be used in DDL. Caller should override via config.
    """
    return safe_table_name(collection_path)


def _columns_for_field(
    field_path: str, hist: FieldHistogram, policy: CollectionPolicy
) -> list[ColumnSpec]:
    """Map a field histogram to one or more column specs."""
    dominant = hist.dominant_type()
    nullable = hist.is_nullable()
    col_name = field_path.replace(".", "_")

    if hist.is_polymorphic() and col_name in policy.json_columns:
        return [ColumnSpec(name=col_name, sql_type="JSON", nullable=nullable)]

    if dominant == "string":
        return [
            map_scalar_string(
                max_observed_len=max(hist.max_observed_string_len, 32),
                name=col_name,
                nullable=nullable,
            )
        ]
    if dominant == "number":
        return [
            map_scalar_number(
                integer_shaped=integer_shaped(hist.numeric_values),
                name=col_name,
                nullable=nullable,
            )
        ]
    if dominant == "boolean":
        return [map_scalar_boolean(name=col_name, nullable=nullable)]
    if dominant == "timestamp":
        return [
            map_timestamp(
                name=col_name,
                nullable=nullable,
                with_server_sentinel=hist.server_timestamp_sentinels_seen > 0,
            )
        ]
    if dominant == "geopoint":
        mode = policy.geopoint_mapping.get(col_name, "lat_lng_columns")
        return map_geopoint(name=col_name, nullable=nullable, mode=mode)
    if dominant == "reference":
        return [map_document_reference(name=col_name, nullable=nullable)]
    if dominant == "bytes":
        return map_bytes(
            max_observed_size_mb=int(hist.max_observed_bytes_mb),
            name=col_name,
            nullable=nullable,
        )
    if dominant == "map":
        return [map_map_as_json(name=col_name, nullable=nullable)]
    if dominant == "array":
        return [map_array_as_json(name=col_name, nullable=nullable)]

    # null-only field
    return [ColumnSpec(name=col_name, sql_type="VARCHAR(255)", nullable=True)]


def _emit_create_table(
    policy: CollectionPolicy,
    histograms: dict[str, FieldHistogram],
    *,
    convert_cfg: ConvertConfig,
    is_subcollection: bool,
) -> str:
    """Emit a single CREATE TABLE statement for one collection."""
    table = _table_name(policy.collection_name)
    columns: list[ColumnSpec] = []

    # PK column
    pk_col = map_document_id(name="id")
    columns.append(pk_col)

    # Subcollections get a parent_doc_id FK column
    if is_subcollection:
        columns.append(map_parent_doc_id())

    if policy.policy == "json-mostly":
        columns.append(ColumnSpec(name="doc", sql_type="JSON", nullable=True))
    else:
        for col_name in policy.typed_columns:
            if col_name in ("id", "parent_doc_id"):
                continue
            hist = histograms.get(col_name)
            if not hist:
                continue
            columns.extend(_columns_for_field(col_name, hist, policy))
        # User-forced individual JSON columns (override.json_columns)
        for col_name in policy.json_columns:
            if col_name == "doc":
                continue
            hist = histograms.get(col_name)
            nullable = hist.is_nullable() if hist else True
            columns.append(ColumnSpec(name=col_name, sql_type="JSON", nullable=nullable))
        # The Hybrid-merge fix: non-indexed/non-flattened fields collapse into
        # a single merged `doc JSON` column instead of one JSON column per
        # field. Driven by policy.merged_json_column set in the policy engine.
        if policy.merged_json_column and policy.policy == "hybrid":
            columns.append(ColumnSpec(name="doc", sql_type="JSON", nullable=True))

    lines = [c.to_ddl() for c in columns]
    lines.append(f"PRIMARY KEY ({quote_ident('id')})")
    if is_subcollection:
        lines.append(f"KEY {quote_ident('idx_parent')} ({quote_ident('parent_doc_id')})")

    cols_sql = ",\n    ".join(lines)
    return f"CREATE TABLE {quote_ident(table)} (\n    {cols_sql}\n){_TABLE_SUFFIX};"


def _emit_secondary_indexes(
    policy: CollectionPolicy, indexes: list[CompositeIndex]
) -> list[str]:
    """Emit CREATE INDEX statements for composite indexes on this collection."""
    out: list[str] = []
    table = _table_name(policy.collection_name)
    for idx in indexes:
        if idx.collection_or_group != policy.collection_name:
            continue
        # Skip ARRAY_CONTAINS — those become multi-valued indexes, separately.
        if any(f.order == "ARRAY_CONTAINS" for f in idx.fields):
            continue
        cols = []
        for f in idx.fields:
            col_name = safe_column_name(f.name)
            order = "ASC" if f.order in ("ASCENDING", "ASC") else "DESC"
            cols.append(f"{quote_ident(col_name)} {order}")
        idx_name_raw = f"idx_{'_'.join(safe_column_name(f.name) for f in idx.fields)}"[:60]
        out.append(
            f"CREATE INDEX {quote_ident(idx_name_raw)} ON {quote_ident(table)} "
            f"({', '.join(cols)});"
        )
    return out


def _emit_multi_valued_indexes(
    policy: CollectionPolicy,
    histograms: dict[str, FieldHistogram],
    indexes: list[CompositeIndex],
) -> list[str]:
    """Multi-valued indexes via generated columns for ARRAY_CONTAINS query patterns."""
    out: list[str] = []
    table = _table_name(policy.collection_name)
    for idx in indexes:
        if idx.collection_or_group != policy.collection_name:
            continue
        for f in idx.fields:
            if f.order != "ARRAY_CONTAINS":
                continue
            col = safe_column_name(f.name)
            idx_name = f"idx_mv_{col}"
            # JSON multi-valued index using CAST AS UNSIGNED ARRAY isn't quite right
            # for string arrays; emit a CHAR(N) array form for safety.
            out.append(
                f"ALTER TABLE {quote_ident(table)} ADD INDEX {quote_ident(idx_name)} "
                f"((CAST(JSON_EXTRACT({quote_ident(col)}, '$') AS CHAR(64) ARRAY)));"
            )
    return out


def _emit_foreign_keys(
    plan: SchemaPolicyPlan,
    histograms_by_collection: dict[str, dict[str, FieldHistogram]],
    *,
    emit_fks: bool,
) -> list[str]:
    """Emit ALTER TABLE ... ADD FOREIGN KEY statements for in-scope DocumentReferences."""
    if not emit_fks:
        return []

    out: list[str] = []
    in_scope_collections = {p.collection_name for p in plan.collections}

    for policy in plan.collections:
        table = _table_name(policy.collection_name)
        histograms = histograms_by_collection.get(policy.collection_name, {})

        for col_name, hist in histograms.items():
            if hist.dominant_type() != "reference":
                continue
            if not hist.document_reference_paths:
                continue
            # Infer the target collection from the first reference path
            # Format: projects/p/databases/(default)/documents/<collection>/<docid>
            first = hist.document_reference_paths[0]
            try:
                target_collection = first.split("/documents/")[1].rsplit("/", 1)[0]
            except IndexError:
                continue
            if target_collection not in in_scope_collections:
                continue
            target_table = _table_name(target_collection)
            fk_col = safe_column_name(col_name)
            fk_name = f"fk_{table}_{fk_col}"[:64]
            out.append(
                f"ALTER TABLE {quote_ident(table)} ADD CONSTRAINT {quote_ident(fk_name)} "
                f"FOREIGN KEY ({quote_ident(fk_col)}) REFERENCES "
                f"{quote_ident(target_table)}({quote_ident('id')});"
            )

        # Subcollection parent FK
        if "/" in policy.collection_name:
            parent_path = policy.collection_name.rsplit("/", 2)[0]
            parent_table = _table_name(parent_path)
            fk_name = f"fk_{table}_parent"[:64]
            out.append(
                f"ALTER TABLE {quote_ident(table)} ADD CONSTRAINT {quote_ident(fk_name)} "
                f"FOREIGN KEY ({quote_ident('parent_doc_id')}) REFERENCES "
                f"{quote_ident(parent_table)}({quote_ident('id')});"
            )

    return out


def _emit_advisor(plan: SchemaPolicyPlan) -> str:
    sections = ["# Convert Advisor", ""]
    for policy in plan.collections:
        sections.append(f"## `{policy.collection_name}` (policy: {policy.policy})")
        sections.append("")
        sections.append(f"Rationale: {policy.rationale}")
        sections.append("")
        sections.append(f"Typed columns: {', '.join(policy.typed_columns) or '(none)'}")
        sections.append(f"JSON columns:  {', '.join(policy.json_columns) or '(none)'}")
        if policy.flagged_for_review:
            sections.append("")
            sections.append("**Flagged for review:**")
            for flag in policy.flagged_for_review:
                sections.append(f"  - {flag}")
        sections.append("")
    return "\n".join(sections)


def emit_ddl(
    *,
    plan: SchemaPolicyPlan,
    histograms_by_collection: dict[str, dict[str, FieldHistogram]],
    indexes: list[CompositeIndex],
    convert_cfg: ConvertConfig,
) -> DDLArtifact:
    """Top-level: turn policy + histograms + indexes into a DDLArtifact."""
    create_tables_lines: list[str] = []
    secondary_indexes_lines: list[str] = []
    multi_valued_lines: list[str] = []

    for policy in plan.collections:
        histograms = histograms_by_collection.get(policy.collection_name, {})
        is_subcol = "/" in policy.collection_name

        create_tables_lines.append(
            _emit_create_table(
                policy, histograms, convert_cfg=convert_cfg, is_subcollection=is_subcol
            )
        )

        secondary_indexes_lines.extend(_emit_secondary_indexes(policy, indexes))
        multi_valued_lines.extend(_emit_multi_valued_indexes(policy, histograms, indexes))

    fks = _emit_foreign_keys(
        plan, histograms_by_collection, emit_fks=convert_cfg.emit_foreign_keys
    )

    return DDLArtifact(
        create_tables="\n\n".join(create_tables_lines) + "\n",
        create_indexes="\n".join(secondary_indexes_lines) + ("\n" if secondary_indexes_lines else ""),
        foreign_keys="\n".join(fks) + ("\n" if fks else ""),
        multi_valued_indexes="\n".join(multi_valued_lines) + ("\n" if multi_valued_lines else ""),
        advisor_markdown=_emit_advisor(plan),
    )
