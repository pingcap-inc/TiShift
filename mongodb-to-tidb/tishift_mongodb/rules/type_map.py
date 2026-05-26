"""MongoDB BSON → TiDB column type mapping.

Reference: references/type-mapping.md — keep IDs and rules in sync.
"""

from __future__ import annotations

from dataclasses import dataclass

from tishift_mongodb.rules.identifiers import quote_ident


JS_SAFE_INT_BOUND = 2**53


@dataclass(frozen=True)
class ColumnSpec:
    """DDL pieces for one TiDB column derived from a Mongo field."""

    name: str
    sql_type: str
    nullable: bool
    default_clause: str = ""
    comment: str = ""

    def to_ddl(self) -> str:
        nn = "" if self.nullable else " NOT NULL"
        default = f" {self.default_clause}" if self.default_clause else ""
        # Escape single quotes in COMMENT (user-controlled string literal).
        comment = (
            f" COMMENT '{self.comment.replace(chr(39), chr(39) * 2)}'"
            if self.comment
            else ""
        )
        return f"{quote_ident(self.name)} {self.sql_type}{nn}{default}{comment}"


def varchar_size_for(max_observed_len: int) -> str:
    """Round up to the next power of 2; ≥10k chars → TEXT."""
    if max_observed_len >= 10_000:
        return "TEXT"
    size = 1
    while size < max(max_observed_len, 32):
        size *= 2
    return f"VARCHAR({size})"


def map_scalar_string(*, max_observed_len: int, name: str, nullable: bool) -> ColumnSpec:
    return ColumnSpec(name=name, sql_type=varchar_size_for(max_observed_len), nullable=nullable)


def map_int32(*, name: str, nullable: bool) -> ColumnSpec:
    return ColumnSpec(name=name, sql_type="INT", nullable=nullable)


def map_int64(*, name: str, nullable: bool) -> ColumnSpec:
    return ColumnSpec(name=name, sql_type="BIGINT", nullable=nullable)


def map_double(*, name: str, nullable: bool) -> ColumnSpec:
    return ColumnSpec(name=name, sql_type="DOUBLE", nullable=nullable)


def map_decimal128(*, name: str, nullable: bool) -> ColumnSpec:
    # Mongo Decimal128 supports 34-digit significand. DECIMAL(38,11) covers
    # with safety margin within TiDB's 65-total-digit limit.
    return ColumnSpec(name=name, sql_type="DECIMAL(38,11)", nullable=nullable)


def map_boolean(*, name: str, nullable: bool) -> ColumnSpec:
    return ColumnSpec(name=name, sql_type="TINYINT(1)", nullable=nullable)


def map_date(*, name: str, nullable: bool) -> ColumnSpec:
    return ColumnSpec(name=name, sql_type="DATETIME(6)", nullable=nullable)


def map_bson_timestamp(*, name: str, nullable: bool) -> ColumnSpec:
    return ColumnSpec(
        name=name, sql_type="DATETIME(6)", nullable=nullable,
        comment="BSON Timestamp (lossy): (seconds, increment) packed",
    )


def map_objectid(*, name: str = "id", as_binary: bool = False) -> ColumnSpec:
    """Mongo `_id` ObjectId as hex string (default) or BINARY(12)."""
    if as_binary:
        return ColumnSpec(name=name, sql_type="BINARY(12)", nullable=False)
    return ColumnSpec(name=name, sql_type="VARCHAR(24)", nullable=False)


def map_uuid(*, name: str, nullable: bool) -> ColumnSpec:
    return ColumnSpec(name=name, sql_type="BINARY(16)", nullable=nullable)


def map_binary(
    *, max_observed_size_mb: float, name: str, nullable: bool, subtype: int = 0
) -> list[ColumnSpec]:
    """BSON Binary mapping.

    - subtype 6 (CSFLE-encrypted): LONGBLOB opaque, surface BLOCKER-3
    - >5 MB observed: recommend external-storage offload
    - otherwise: inline LONGBLOB
    """
    if subtype == 6:
        return [
            ColumnSpec(
                name=name, sql_type="LONGBLOB", nullable=nullable,
                comment="CSFLE-encrypted; queryable only with client keys",
            )
        ]
    if max_observed_size_mb > 5:
        return [
            ColumnSpec(
                name=name, sql_type="VARCHAR(2048)", nullable=nullable,
                comment=f"Object-storage path; original ~{int(max_observed_size_mb)}MB",
            )
        ]
    return [ColumnSpec(name=name, sql_type="LONGBLOB", nullable=nullable)]


def map_dbref(*, name: str, nullable: bool) -> ColumnSpec:
    return ColumnSpec(name=name, sql_type="VARCHAR(1500)", nullable=nullable)


def map_regex(*, name: str, nullable: bool) -> ColumnSpec:
    return ColumnSpec(name=name, sql_type="VARCHAR(2048)", nullable=nullable,
                      comment="BSON Regex source pattern; lossy")


def map_code(*, name: str, nullable: bool) -> ColumnSpec:
    return ColumnSpec(name=name, sql_type="VARCHAR(8000)", nullable=nullable,
                      comment="BSON JavaScript Code; NEVER EXECUTE")


def map_subdocument_as_json(*, name: str, nullable: bool) -> ColumnSpec:
    return ColumnSpec(name=name, sql_type="JSON", nullable=nullable)


def map_array_as_json(*, name: str, nullable: bool) -> ColumnSpec:
    return ColumnSpec(name=name, sql_type="JSON", nullable=nullable)


def map_parent_doc_id(*, name: str = "parent_doc_id") -> ColumnSpec:
    """FK column on child tables (from Array<Subdoc> expansion)."""
    return ColumnSpec(name=name, sql_type="VARCHAR(24)", nullable=False)


def integer_shaped(numbers_seen: list[float]) -> bool:
    """A field is integer-shaped if every sampled value is integral within safe-int bounds."""
    if not numbers_seen:
        return True
    return all(
        v == int(v) and -JS_SAFE_INT_BOUND < v < JS_SAFE_INT_BOUND
        for v in numbers_seen
    )
