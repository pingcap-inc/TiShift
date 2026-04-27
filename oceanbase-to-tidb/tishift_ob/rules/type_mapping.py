"""OceanBase → TiDB type mapping rules.

MySQL mode: near-1:1 (trivial).
Oracle mode: full Oracle-style mapping.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MappedType:
    tidb_type: str
    comment: str = ""
    lossy: bool = False


def map_mysql_mode_type(data_type: str, column_type: str = "") -> MappedType:
    """Map OceanBase MySQL-mode type. Near-1:1 with TiDB MySQL types."""
    # MySQL-mode types are essentially MySQL types — pass through.
    dt = data_type.upper().strip()

    # Standard MySQL types that map directly
    direct = {
        "INT", "BIGINT", "SMALLINT", "TINYINT", "MEDIUMINT",
        "FLOAT", "DOUBLE", "DECIMAL", "NUMERIC",
        "VARCHAR", "CHAR", "TEXT", "TINYTEXT", "MEDIUMTEXT", "LONGTEXT",
        "BLOB", "TINYBLOB", "MEDIUMBLOB", "LONGBLOB",
        "DATE", "DATETIME", "TIMESTAMP", "TIME", "YEAR",
        "JSON", "ENUM", "SET", "BIT", "BOOLEAN", "BOOL",
        "BINARY", "VARBINARY",
    }

    if dt in direct:
        return MappedType(column_type or dt)

    # Fallback
    return MappedType(column_type or dt, comment=f"OB MySQL type, verify compatibility")


def map_oracle_mode_type(
    data_type: str,
    data_precision: int | None = None,
    data_scale: int | None = None,
    data_length: int | None = None,
    char_used: str | None = None,
) -> MappedType:
    """Map OceanBase Oracle-mode type to TiDB. Same logic as Oracle variant."""
    dt = data_type.upper().strip()

    # NUMBER
    if dt == "NUMBER":
        if data_precision is None and data_scale is None:
            return MappedType("DECIMAL(38,10)", comment="was: NUMBER (no precision)", lossy=True)
        p = data_precision or 38
        s = data_scale or 0
        if s == 0:
            if p <= 2: return MappedType("TINYINT")
            if p <= 4: return MappedType("SMALLINT")
            if p <= 9: return MappedType("INT")
            if p <= 18: return MappedType("BIGINT")
        return MappedType(f"DECIMAL({min(p, 65)},{min(s, 30)})")

    # Strings
    if dt == "VARCHAR2":
        length = data_length or 1
        if char_used == "C":
            return MappedType(f"VARCHAR({length * 4})")
        return MappedType(f"VARCHAR({length})")
    if dt == "NVARCHAR2":
        return MappedType(f"VARCHAR({(data_length or 1) * 4})")
    if dt == "CHAR":
        return MappedType(f"CHAR({data_length or 1})")
    if dt == "NCHAR":
        return MappedType(f"CHAR({(data_length or 1) * 4})")
    if dt in ("CLOB", "NCLOB"):
        return MappedType("LONGTEXT")
    if dt == "LONG":
        return MappedType("LONGTEXT", comment="deprecated")

    # Binary
    if dt == "BLOB":
        return MappedType("LONGBLOB")
    if dt == "RAW":
        return MappedType(f"VARBINARY({data_length or 2000})")
    if dt == "LONG RAW":
        return MappedType("LONGBLOB", comment="deprecated")

    # Date/Time — CRITICAL: Oracle-mode DATE includes time
    if dt == "DATE":
        return MappedType("DATETIME", comment="OB Oracle DATE includes time")
    if dt.startswith("TIMESTAMP"):
        frac = data_scale if data_scale is not None else 6
        capped = min(frac, 6)
        if "WITH TIME ZONE" in dt:
            return MappedType("VARCHAR(40)", comment=f"was: {dt}")
        if "WITH LOCAL TIME ZONE" in dt:
            return MappedType(f"DATETIME({capped})", comment="convert to UTC")
        if frac > 6:
            return MappedType(f"DATETIME({capped})", comment=f"precision capped at 6", lossy=True)
        return MappedType(f"DATETIME({capped})")

    # Float
    if dt in ("FLOAT", "BINARY_DOUBLE"):
        return MappedType("DOUBLE")
    if dt == "BINARY_FLOAT":
        return MappedType("FLOAT")

    # Special
    if dt in ("ROWID", "UROWID"):
        return MappedType("VARCHAR(18)", comment=f"was: {dt}")
    if dt == "XMLTYPE":
        return MappedType("LONGTEXT", comment="was: XMLType")
    if dt == "BOOLEAN":
        return MappedType("TINYINT(1)")

    return MappedType("LONGTEXT", comment=f"unmapped OB Oracle type: {dt}", lossy=True)
