"""DDL emission: SchemaPolicyPlan → 4 TiDB SQL files + advisor markdown.

Reference: references/type-mapping.md, references/schema-policy.md.
Hybrid-merge fix: non-indexed fields collapse into ONE merged `doc JSON` column.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tishift_mongodb.config import ConvertConfig
from tishift_mongodb.core.convert.policy import CollectionPolicy, SchemaPolicyPlan
from tishift_mongodb.core.scan.indexes import IndexInfo
from tishift_mongodb.core.scan.type_inferrer import FieldHistogram
from tishift_mongodb.rules.identifiers import (
    quote_ident,
    safe_column_name,
    safe_table_name,
)
from tishift_mongodb.rules.type_map import (
    ColumnSpec,
    integer_shaped,
    map_array_as_json,
    map_binary,
    map_boolean,
    map_date,
    map_dbref,
    map_decimal128,
    map_double,
    map_int32,
    map_int64,
    map_objectid,
    map_regex,
    map_scalar_string,
    map_subdocument_as_json,
    map_uuid,
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


def _table_name(collection: str) -> str:
    """Mongo collection → TiDB table name (safe identifier)."""
    return safe_table_name(collection)


def _column_spec_for_field(
    field_path: str, hist: FieldHistogram, policy: CollectionPolicy
) -> list[ColumnSpec]:
    """Map a single field's histogram to one or more column specs."""
    col_name = safe_column_name(field_path)
    dominant = hist.dominant_type()
    nullable = hist.is_nullable()

    if hist.is_polymorphic():
        return [ColumnSpec(name=col_name, sql_type="JSON", nullable=nullable)]

    if dominant == "String":
        return [
            map_scalar_string(
                max_observed_len=max(hist.max_observed_string_len, 32),
                name=col_name,
                nullable=nullable,
            )
        ]
    if dominant == "Int32":
        return [map_int32(name=col_name, nullable=nullable)]
    if dominant == "Int64":
        return [map_int64(name=col_name, nullable=nullable)]
    if dominant == "Double":
        # If samples are all integer-shaped, demote to Int64
        if integer_shaped(hist.numeric_values):
            return [map_int64(name=col_name, nullable=nullable)]
        return [map_double(name=col_name, nullable=nullable)]
    if dominant == "Decimal128":
        return [map_decimal128(name=col_name, nullable=nullable)]
    if dominant == "Boolean":
        return [map_boolean(name=col_name, nullable=nullable)]
    if dominant == "Date":
        return [map_date(name=col_name, nullable=nullable)]
    if dominant == "ObjectId":
        # Non-_id ObjectId field — keep as hex
        return [ColumnSpec(name=col_name, sql_type="VARCHAR(24)", nullable=nullable)]
    if dominant == "UUID":
        return [map_uuid(name=col_name, nullable=nullable)]
    if dominant == "Binary":
        # Use most-common subtype for mapping (CSFLE = 6 trips BLOCKER-3 separately)
        subtypes = hist.binary_subtypes_seen
        main_subtype = max(subtypes.items(), key=lambda kv: kv[1])[0] if subtypes else 0
        return map_binary(
            max_observed_size_mb=hist.max_observed_binary_size_mb,
            name=col_name,
            nullable=nullable,
            subtype=int(main_subtype),
        )
    if dominant == "DBRef":
        return [map_dbref(name=col_name, nullable=nullable)]
    if dominant == "Regex":
        return [map_regex(name=col_name, nullable=nullable)]
    if dominant == "Object":
        return [map_subdocument_as_json(name=col_name, nullable=nullable)]
    if dominant == "Array":
        return [map_array_as_json(name=col_name, nullable=nullable)]

    # Fallback (null-only or unknown)
    return [ColumnSpec(name=col_name, sql_type="VARCHAR(255)", nullable=True)]


def _emit_create_table(
    policy: CollectionPolicy,
    histograms: dict[str, FieldHistogram],
    id_type: str = "ObjectId",
) -> str:
    """Emit a single CREATE TABLE statement.

    Hybrid + JSON-mostly: non-indexed/non-typed fields collapse into ONE `doc JSON` column.
    """
    table = _table_name(policy.collection_name)
    columns: list[ColumnSpec] = []

    # PK column based on observed _id type
    if id_type == "ObjectId":
        columns.append(map_objectid(name="id"))
    elif id_type == "Int64":
        columns.append(map_int64(name="id", nullable=False))
    elif id_type == "Int32":
        columns.append(map_int32(name="id", nullable=False))
    elif id_type == "String":
        columns.append(ColumnSpec(name="id", sql_type="VARCHAR(255)", nullable=False))
    else:
        columns.append(map_objectid(name="id"))

    if policy.policy == "json-mostly":
        columns.append(ColumnSpec(name="doc", sql_type="JSON", nullable=True))
    else:
        for col_name in policy.typed_columns:
            if col_name == "id":
                continue
            hist = histograms.get(col_name)
            if not hist:
                continue
            columns.extend(_column_spec_for_field(col_name, hist, policy))
        for col_name in policy.json_columns:
            hist = histograms.get(col_name)
            nullable = hist.is_nullable() if hist else True
            columns.append(
                ColumnSpec(
                    name=safe_column_name(col_name),
                    sql_type="JSON",
                    nullable=nullable,
                )
            )
        # The Hybrid-merge fix: single merged `doc JSON` for non-indexed/non-typed
        if policy.merged_json_column and policy.policy == "hybrid":
            columns.append(ColumnSpec(name="doc", sql_type="JSON", nullable=True))

    lines = [c.to_ddl() for c in columns]
    lines.append(f"PRIMARY KEY ({quote_ident('id')})")

    cols_sql = ",\n    ".join(lines)
    return f"CREATE TABLE {quote_ident(table)} (\n    {cols_sql}\n){_TABLE_SUFFIX};"


def _emit_secondary_indexes(policy: CollectionPolicy, indexes: list[IndexInfo]) -> list[str]:
    out: list[str] = []
    table = _table_name(policy.collection_name)
    for idx in indexes:
        if idx.collection != policy.collection_name:
            continue
        if idx.is_geospatial or idx.is_text or idx.is_wildcard:
            continue
        if len(idx.fields) < 2 and not idx.unique:
            continue  # single-field non-unique = noise
        cols = []
        for f in idx.fields:
            col_name = safe_column_name(f.name)
            direction = "ASC" if f.direction == 1 else "DESC" if f.direction == -1 else "ASC"
            cols.append(f"{quote_ident(col_name)} {direction}")
        idx_name_raw = f"idx_{'_'.join(safe_column_name(f.name) for f in idx.fields)}"[:60]
        unique = "UNIQUE " if idx.unique else ""
        out.append(
            f"CREATE {unique}INDEX {quote_ident(idx_name_raw)} ON {quote_ident(table)} "
            f"({', '.join(cols)});"
        )
    return out


def _emit_multi_valued_indexes(policy: CollectionPolicy, indexes: list[IndexInfo]) -> list[str]:
    """Emit multi-valued indexes for multikey-array indexes (single-field array indexes)."""
    out: list[str] = []
    table = _table_name(policy.collection_name)
    for idx in indexes:
        if idx.collection != policy.collection_name:
            continue
        if len(idx.fields) != 1:
            continue
        f = idx.fields[0]
        if not (isinstance(f.direction, int) and f.direction in (1, -1)):
            continue
        # Multikey detection is a runtime property; we emit candidate multi-valued
        # indexes for fields whose histogram suggested Array dominant type.
        # The convert phase passes histograms via the policy.indexed_field_paths set
        # but we keep this generic: emit ALTER TABLE ADD INDEX with CAST AS ARRAY.
        col_name = safe_column_name(f.name)
        idx_name = f"idx_mv_{col_name}"
        out.append(
            f"-- Multi-valued candidate (verify field is array-typed before applying):\n"
            f"-- ALTER TABLE {quote_ident(table)} ADD INDEX {quote_ident(idx_name)} "
            f"((CAST(JSON_EXTRACT({quote_ident(col_name)}, '$') AS CHAR(64) ARRAY)));"
        )
    return out


def _emit_foreign_keys(
    plan: SchemaPolicyPlan,
    histograms_by_collection: dict[str, dict[str, FieldHistogram]],
    *,
    emit_fks: bool,
) -> list[str]:
    """Emit ALTER TABLE ... ADD FOREIGN KEY statements for in-scope DBRefs."""
    if not emit_fks:
        return []
    out: list[str] = []
    in_scope = {p.collection_name for p in plan.collections}
    for policy in plan.collections:
        table = _table_name(policy.collection_name)
        histograms = histograms_by_collection.get(policy.collection_name, {})
        for col_name, hist in histograms.items():
            if hist.dominant_type() != "DBRef":
                continue
            if not hist.dbref_targets:
                continue
            target_collection = hist.dbref_targets[0]
            if target_collection not in in_scope:
                continue
            target_table = _table_name(target_collection)
            fk_col = safe_column_name(col_name)
            fk_name = f"fk_{table}_{fk_col}"[:64]
            out.append(
                f"ALTER TABLE {quote_ident(table)} ADD CONSTRAINT {quote_ident(fk_name)} "
                f"FOREIGN KEY ({quote_ident(fk_col)}) REFERENCES "
                f"{quote_ident(target_table)}({quote_ident('id')});"
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
        if policy.merged_json_column and policy.policy in ("hybrid", "json-mostly"):
            label = "doc (merged JSON)" if policy.policy == "hybrid" else "doc (full document JSON)"
            sections.append(f"JSON column:   {label}")
        if policy.json_columns:
            sections.append(f"Forced individual JSON columns: {', '.join(policy.json_columns)}")
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
    indexes: list[IndexInfo],
    convert_cfg: ConvertConfig,
    id_types: dict[str, str] | None = None,
) -> DDLArtifact:
    """Top-level: turn policy + histograms + indexes into a DDLArtifact."""
    id_types = id_types or {}

    create_lines: list[str] = []
    sec_idx_lines: list[str] = []
    mv_idx_lines: list[str] = []

    for policy in plan.collections:
        histograms = histograms_by_collection.get(policy.collection_name, {})
        id_type = id_types.get(policy.collection_name, "ObjectId")
        create_lines.append(_emit_create_table(policy, histograms, id_type=id_type))
        sec_idx_lines.extend(_emit_secondary_indexes(policy, indexes))
        mv_idx_lines.extend(_emit_multi_valued_indexes(policy, indexes))

    fks = _emit_foreign_keys(
        plan, histograms_by_collection, emit_fks=convert_cfg.emit_foreign_keys
    )

    return DDLArtifact(
        create_tables="\n\n".join(create_lines) + "\n",
        create_indexes="\n".join(sec_idx_lines) + ("\n" if sec_idx_lines else ""),
        foreign_keys="\n".join(fks) + ("\n" if fks else ""),
        multi_valued_indexes="\n".join(mv_idx_lines) + ("\n" if mv_idx_lines else ""),
        advisor_markdown=_emit_advisor(plan),
    )
