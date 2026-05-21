"""Firestore type → TiDB column type mapping.

Reference: references/type-mapping.md (which is generated from the same rules
this module encodes — keep the two in sync if you change one).
"""

from __future__ import annotations

from dataclasses import dataclass

from tishift_firestore.rules.identifiers import quote_ident


JS_SAFE_INT_BOUND = 2**53


@dataclass(frozen=True)
class ColumnSpec:
    """The DDL pieces for one TiDB column derived from a Firestore field."""

    name: str
    sql_type: str
    nullable: bool
    default_clause: str = ""
    comment: str = ""

    def to_ddl(self) -> str:
        nn = "" if self.nullable else " NOT NULL"
        default = f" {self.default_clause}" if self.default_clause else ""
        # Escape any single quotes in COMMENT (the only user-controlled string-literal we emit).
        comment = (
            f" COMMENT '{self.comment.replace(chr(39), chr(39) * 2)}'"
            if self.comment
            else ""
        )
        return f"{quote_ident(self.name)} {self.sql_type}{nn}{default}{comment}"


def varchar_size_for(max_observed_len: int) -> str:
    """Round up to the next power of 2; ≥10k chars becomes TEXT."""
    if max_observed_len >= 10_000:
        return "TEXT"
    size = 1
    while size < max(max_observed_len, 32):
        size *= 2
    return f"VARCHAR({size})"


def map_scalar_string(*, max_observed_len: int, name: str, nullable: bool) -> ColumnSpec:
    return ColumnSpec(name=name, sql_type=varchar_size_for(max_observed_len), nullable=nullable)


def map_scalar_number(*, integer_shaped: bool, name: str, nullable: bool) -> ColumnSpec:
    sql_type = "BIGINT" if integer_shaped else "DOUBLE"
    return ColumnSpec(name=name, sql_type=sql_type, nullable=nullable)


def map_scalar_boolean(*, name: str, nullable: bool) -> ColumnSpec:
    return ColumnSpec(name=name, sql_type="TINYINT(1)", nullable=nullable)


def map_timestamp(*, name: str, nullable: bool, with_server_sentinel: bool) -> ColumnSpec:
    default = "DEFAULT CURRENT_TIMESTAMP(6)" if with_server_sentinel else ""
    return ColumnSpec(name=name, sql_type="DATETIME(6)", nullable=nullable, default_clause=default)


def map_bytes(*, max_observed_size_mb: int, name: str, nullable: bool) -> list[ColumnSpec]:
    """Bytes >5 MB → GCS-path column (single VARCHAR), else inline LONGBLOB."""
    if max_observed_size_mb > 5:
        return [
            ColumnSpec(
                name=name,
                sql_type="VARCHAR(2048)",
                nullable=nullable,
                comment=f"GCS object path; original bytes ~{max_observed_size_mb}MB",
            )
        ]
    return [ColumnSpec(name=name, sql_type="LONGBLOB", nullable=nullable)]


def map_geopoint(*, name: str, nullable: bool, mode: str) -> list[ColumnSpec]:
    """GeoPoint default = two DECIMAL(9,6) columns. 'json' mode = one JSON column."""
    if mode == "json":
        return [ColumnSpec(name=name, sql_type="JSON", nullable=nullable)]
    return [
        ColumnSpec(name=f"{name}_lat", sql_type="DECIMAL(9,6)", nullable=nullable),
        ColumnSpec(name=f"{name}_lng", sql_type="DECIMAL(9,6)", nullable=nullable),
    ]


def map_document_reference(*, name: str, nullable: bool) -> ColumnSpec:
    return ColumnSpec(name=name, sql_type="VARCHAR(1500)", nullable=nullable)


def map_map_as_flattened(*, prefix: str, keys: dict[str, "ColumnSpec"]) -> list[ColumnSpec]:
    """Flatten a stable-shape map into prefix_<key> columns. Caller decides per key type."""
    out: list[ColumnSpec] = []
    for k, spec in keys.items():
        out.append(
            ColumnSpec(
                name=f"{prefix}_{k}",
                sql_type=spec.sql_type,
                nullable=spec.nullable,
                default_clause=spec.default_clause,
                comment=spec.comment,
            )
        )
    return out


def map_map_as_json(*, name: str, nullable: bool) -> ColumnSpec:
    return ColumnSpec(name=name, sql_type="JSON", nullable=nullable)


def map_array_as_json(*, name: str, nullable: bool) -> ColumnSpec:
    return ColumnSpec(name=name, sql_type="JSON", nullable=nullable)


def map_document_id(*, name: str = "id", id_shape: str = "auto") -> ColumnSpec:
    """Document ID column. Default = auto-generated 20-char Firestore IDs preserved as VARCHAR(20).

    id_shape values: 'auto' (default, VARCHAR(20)), 'integer' (BIGINT).
    """
    if id_shape == "integer":
        return ColumnSpec(name=name, sql_type="BIGINT", nullable=False)
    return ColumnSpec(name=name, sql_type="VARCHAR(20)", nullable=False)


def map_parent_doc_id(*, name: str = "parent_doc_id") -> ColumnSpec:
    """FK column on subcollection child tables pointing back to the parent document."""
    return ColumnSpec(name=name, sql_type="VARCHAR(20)", nullable=False)


def integer_shaped(numbers_seen: list[float]) -> bool:
    """A field is integer-shaped if every sampled value is integral and within safe-int bounds."""
    if not numbers_seen:
        return True  # vacuously
    return all(
        v == int(v) and -JS_SAFE_INT_BOUND < v < JS_SAFE_INT_BOUND
        for v in numbers_seen
    )
