"""CockroachDB → TiDB type mapping rules.

Implements the mapping table from references/type-mapping.md.
Critical: CockroachDB INT is 64-bit — always maps to BIGINT.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MappedType:
    tidb_type: str
    comment: str = ""
    lossy: bool = False


def map_crdb_type(
    data_type: str,
    character_maximum_length: int | None = None,
    numeric_precision: int | None = None,
    numeric_scale: int | None = None,
    column_default: str | None = None,
) -> MappedType:
    """Map a CockroachDB column type to its TiDB equivalent."""
    dt = data_type.upper().strip()

    # --- Integer types (CRDB INT = 64-bit!) ---
    if dt in ("INT8", "INT64", "INTEGER", "INT"):
        return MappedType("BIGINT", comment="CRDB INT is 64-bit")
    if dt in ("INT4", "INT32"):
        return MappedType("INT")
    if dt in ("INT2", "INT16", "SMALLINT"):
        return MappedType("SMALLINT")
    if dt in ("BOOL", "BOOLEAN"):
        return MappedType("TINYINT(1)")

    # --- Float types ---
    if dt in ("FLOAT4", "REAL"):
        return MappedType("FLOAT")
    if dt in ("FLOAT8", "DOUBLE PRECISION", "FLOAT"):
        return MappedType("DOUBLE")

    # --- Decimal ---
    if dt in ("DECIMAL", "NUMERIC"):
        p = numeric_precision or 10
        s = numeric_scale or 0
        return MappedType(f"DECIMAL({p},{s})")

    # --- Serial (unique_rowid) ---
    if dt == "SERIAL":
        return MappedType("BIGINT", comment="was: SERIAL (unique_rowid). Use AUTO_RANDOM or AUTO_INCREMENT.")

    # --- UUID ---
    if dt == "UUID":
        if column_default and "gen_random_uuid" in (column_default or ""):
            return MappedType("CHAR(36)", comment="DEFAULT (UUID())")
        return MappedType("CHAR(36)")

    # --- String types ---
    if dt in ("STRING", "TEXT"):
        if character_maximum_length:
            return MappedType(f"VARCHAR({character_maximum_length})")
        return MappedType("TEXT")
    if dt in ("VARCHAR", "CHARACTER VARYING"):
        length = character_maximum_length or 255
        return MappedType(f"VARCHAR({length})")
    if dt in ("CHAR", "CHARACTER"):
        length = character_maximum_length or 1
        return MappedType(f"CHAR({length})")
    if dt == "NAME":
        return MappedType("VARCHAR(64)")

    # --- Binary types ---
    if dt in ("BYTES", "BYTEA"):
        if character_maximum_length:
            return MappedType(f"VARBINARY({character_maximum_length})")
        return MappedType("LONGBLOB")

    # --- Date/Time ---
    if dt == "DATE":
        return MappedType("DATE")
    if dt == "TIME":
        return MappedType("TIME")
    if dt in ("TIMESTAMP", "TIMESTAMP WITHOUT TIME ZONE"):
        return MappedType("DATETIME(6)")
    if dt in ("TIMESTAMPTZ", "TIMESTAMP WITH TIME ZONE"):
        return MappedType("DATETIME(6)", comment="extract as UTC")
    if dt == "INTERVAL":
        return MappedType("VARCHAR(40)", comment="was: INTERVAL")

    # --- JSON ---
    if dt == "JSONB":
        return MappedType("JSON", comment="JSONB operators need rewrite")
    if dt == "JSON":
        return MappedType("JSON")

    # --- Array ---
    if dt == "ARRAY" or "[]" in data_type:
        return MappedType("JSON", comment=f"was: {data_type} — serialize as JSON array", lossy=True)

    # --- Spatial ---
    if dt == "GEOMETRY":
        return MappedType("GEOMETRY")
    if dt == "GEOGRAPHY":
        return MappedType("GEOMETRY", comment="was: GEOGRAPHY — geodesic to planar conversion needed", lossy=True)

    # --- Network/Bit ---
    if dt == "INET":
        return MappedType("VARCHAR(45)")
    if dt.startswith("BIT"):
        length = character_maximum_length or 1
        return MappedType(f"BIT({length})")

    # --- Enum (named type — handled at DDL level, not here) ---
    if dt == "USER-DEFINED":
        return MappedType("ENUM(...)", comment="inline enum values from CREATE TYPE", lossy=True)

    # --- OID ---
    if dt == "OID":
        return MappedType("INT UNSIGNED")

    # Fallback
    return MappedType("TEXT", comment=f"unmapped CRDB type: {dt}", lossy=True)
