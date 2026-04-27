"""Oracle → TiDB type mapping rules.

Implements the mapping table from references/type-mapping.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class MappedType:
    tidb_type: str
    comment: str = ""
    lossy: bool = False


def map_oracle_type(
    data_type: str,
    data_precision: int | None = None,
    data_scale: int | None = None,
    data_length: int | None = None,
    char_used: str | None = None,
) -> MappedType:
    """Map an Oracle column type to its TiDB equivalent.

    Args:
        data_type: Oracle data type name (e.g., 'NUMBER', 'VARCHAR2', 'DATE').
        data_precision: Precision for numeric types.
        data_scale: Scale for numeric types.
        data_length: Length for string/binary types.
        char_used: 'C' for CHAR semantics, 'B' for BYTE semantics (from ALL_TAB_COLUMNS.CHAR_USED).

    Returns:
        MappedType with the TiDB type, optional comment, and lossy flag.
    """
    dt = data_type.upper().strip()

    # --- Numeric types ---
    if dt == "NUMBER":
        return _map_number(data_precision, data_scale)
    if dt in ("FLOAT", "BINARY_FLOAT", "BINARY_DOUBLE"):
        return _map_float(dt)
    if dt == "INTEGER":
        return MappedType("INT")
    if dt == "SMALLINT":
        return MappedType("SMALLINT")

    # --- String types ---
    if dt in ("VARCHAR2", "VARCHAR"):
        return _map_varchar2(data_length, char_used)
    if dt == "NVARCHAR2":
        length = (data_length or 1) * 4
        return MappedType(f"VARCHAR({length})")
    if dt == "CHAR":
        return MappedType(f"CHAR({data_length or 1})")
    if dt == "NCHAR":
        length = (data_length or 1) * 4
        return MappedType(f"CHAR({length})")
    if dt == "CLOB":
        return MappedType("LONGTEXT")
    if dt == "NCLOB":
        return MappedType("LONGTEXT")
    if dt == "LONG":
        return MappedType("LONGTEXT", comment="was: LONG (deprecated)")

    # --- Binary types ---
    if dt == "BLOB":
        return MappedType("LONGBLOB")
    if dt == "RAW":
        return MappedType(f"VARBINARY({data_length or 2000})")
    if dt == "LONG RAW":
        return MappedType("LONGBLOB", comment="was: LONG RAW (deprecated). DMS limit: 64 KB.")

    # --- Date/Time types ---
    if dt == "DATE":
        return MappedType("DATETIME", comment="Oracle DATE includes time")
    if dt.startswith("TIMESTAMP"):
        return _map_timestamp(dt, data_scale)
    if dt.startswith("INTERVAL"):
        if "YEAR" in dt:
            return MappedType("VARCHAR(20)", comment=f"was: {dt}")
        return MappedType("VARCHAR(30)", comment=f"was: {dt}")

    # --- Special types ---
    if dt in ("ROWID", "UROWID"):
        return MappedType("VARCHAR(18)", comment=f"was: {dt}")
    if dt == "XMLTYPE":
        return MappedType("LONGTEXT", comment="was: XMLType — process XML in app layer")
    if dt == "SDO_GEOMETRY":
        return MappedType("LONGTEXT", comment="was: SDO_GEOMETRY")
    if dt == "BFILE":
        return MappedType("VARCHAR(255)", comment="was: BFILE — store file path")
    if dt == "BOOLEAN":
        return MappedType("TINYINT(1)")

    # Fallback
    return MappedType("LONGTEXT", comment=f"unmapped Oracle type: {dt}", lossy=True)


def _map_number(precision: int | None, scale: int | None) -> MappedType:
    """Map Oracle NUMBER(p,s) to appropriate TiDB numeric type."""
    if precision is None and scale is None:
        return MappedType(
            "DECIMAL(38,10)",
            comment="was: NUMBER (no precision) — scan data for better fit",
            lossy=True,
        )

    p = precision or 38
    s = scale or 0

    if s == 0:
        if p <= 2:
            return MappedType("TINYINT")
        if p <= 4:
            return MappedType("SMALLINT")
        if p <= 9:
            return MappedType("INT")
        if p <= 18:
            return MappedType("BIGINT")

    if p > 65:
        return MappedType(
            "DECIMAL(65,30)",
            comment=f"was: NUMBER({p},{s}) — TiDB max precision",
            lossy=True,
        )

    capped_scale = min(s, 30)
    return MappedType(f"DECIMAL({p},{capped_scale})")


def _map_float(dt: str) -> MappedType:
    if dt == "BINARY_FLOAT":
        return MappedType("FLOAT")
    if dt == "BINARY_DOUBLE":
        return MappedType("DOUBLE")
    # FLOAT / FLOAT(p) — Oracle FLOAT is binary precision
    return MappedType("DOUBLE")


def _map_varchar2(data_length: int | None, char_used: str | None) -> MappedType:
    length = data_length or 1
    if char_used == "C":
        # CHAR semantics — up to 4 bytes per char in utf8mb4
        return MappedType(f"VARCHAR({length * 4})")
    return MappedType(f"VARCHAR({length})")


def _map_timestamp(dt: str, data_scale: int | None) -> MappedType:
    # Extract precision from TIMESTAMP(N) or default to 6
    m = re.search(r"\((\d+)\)", dt)
    frac = int(m.group(1)) if m else (data_scale if data_scale is not None else 6)

    if "WITH LOCAL TIME ZONE" in dt:
        capped = min(frac, 6)
        return MappedType(f"DATETIME({capped})", comment="converted to UTC at extraction")
    if "WITH TIME ZONE" in dt:
        return MappedType("VARCHAR(40)", comment="was: TIMESTAMP WITH TIME ZONE")

    capped = min(frac, 6)
    if frac > 6:
        return MappedType(
            f"DATETIME({capped})",
            comment=f"was: TIMESTAMP({frac}) — precision capped at 6",
            lossy=True,
        )
    return MappedType(f"DATETIME({capped})")
