"""SQL identifier validation and quoting.

Firestore collection and field names CAN contain characters that are unsafe
in MySQL/TiDB identifiers (backticks, control chars, etc.). This module
provides:

  - `is_safe_ident(name)` — fast check for the allowlist of characters that
    are safe to use unquoted in TiDB DDL: [A-Za-z0-9_]+.
  - `quote_ident(name)` — emit a properly backtick-quoted identifier with
    any embedded backticks escaped per MySQL rules (double them up).
  - `safe_table_name(collection_path)` — map a Firestore collection path
    to a TiDB table identifier, rejecting paths that produce unsafe names.

Use `quote_ident` everywhere a non-literal identifier flows into SQL DDL or
DML, regardless of whether the source seems trusted. Parameterized %s in
DML covers VALUES; identifiers can't be parameterized in PyMySQL and must
be quoted manually.

Reference for the MySQL identifier-quoting rule:
https://dev.mysql.com/doc/refman/8.0/en/identifiers.html
"""

from __future__ import annotations

import re


_SAFE_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


class UnsafeIdentifierError(ValueError):
    """Raised when an identifier cannot be safely represented as a TiDB column or table name."""


def is_safe_ident(name: str) -> bool:
    """True iff `name` is an unquoted-safe MySQL identifier (alphanumeric + underscore, ≤64)."""
    return bool(_SAFE_IDENT_RE.fullmatch(name))


def quote_ident(name: str) -> str:
    """Return `name` as a backtick-quoted MySQL identifier.

    Escapes embedded backticks per MySQL rules (double them up). Rejects
    identifiers containing characters that are never legal in MySQL even
    when quoted: NUL bytes, characters outside the printable ASCII range,
    or longer than 64 bytes (MySQL identifier limit).
    """
    if not isinstance(name, str) or not name:
        raise UnsafeIdentifierError("identifier must be a non-empty string")
    if "\x00" in name:
        raise UnsafeIdentifierError("identifier contains NUL byte")
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in name):
        raise UnsafeIdentifierError(
            f"identifier contains control characters: {name!r}"
        )
    if len(name.encode("utf-8")) > 64:
        raise UnsafeIdentifierError(
            f"identifier > 64 bytes (MySQL limit): {name!r}"
        )
    return "`" + name.replace("`", "``") + "`"


def safe_table_name(collection_path: str) -> str:
    """Map a Firestore collection path to a TiDB table identifier.

    Strategy:
    - Drop the document-ID segments (every odd-indexed piece of a path):
      'users/{uid}/orders' → ['users', 'orders']
    - Concatenate with underscore.
    - Validate against the safe-ident regex; if any piece contains characters
      outside [A-Za-z0-9_], raise UnsafeIdentifierError. The caller decides
      whether to remap the offending collection (config override) or abort.
    """
    if not isinstance(collection_path, str) or not collection_path:
        raise UnsafeIdentifierError("collection path must be a non-empty string")

    parts = collection_path.split("/")
    cleaned = [p for i, p in enumerate(parts) if i % 2 == 0]
    if not cleaned:
        raise UnsafeIdentifierError(f"could not derive table name from {collection_path!r}")

    for piece in cleaned:
        if not _SAFE_IDENT_RE.fullmatch(piece):
            raise UnsafeIdentifierError(
                f"collection name {piece!r} from path {collection_path!r} contains "
                "characters outside [A-Za-z_][A-Za-z0-9_]; "
                "rename the collection or set convert.per_collection.<name>.table_name in config"
            )

    name = "_".join(cleaned)
    if len(name) > 64:
        raise UnsafeIdentifierError(f"derived table name >64 bytes: {name!r}")
    return name


def safe_column_name(field_path: str) -> str:
    """Map a Firestore field path (which may include dots from nested maps) to a column name."""
    if not isinstance(field_path, str) or not field_path:
        raise UnsafeIdentifierError("field path must be a non-empty string")
    col = field_path.replace(".", "_")
    if not _SAFE_IDENT_RE.fullmatch(col):
        raise UnsafeIdentifierError(
            f"field path {field_path!r} produces unsafe column name {col!r}; "
            "rename the field or set convert.per_collection.<name>.field_renames in config"
        )
    return col
