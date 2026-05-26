"""SQL identifier validation and quoting.

MongoDB collection and field names CAN contain characters that are unsafe
in MySQL/TiDB identifiers (dots, dollar signs, NUL bytes). This module
provides:

- `is_safe_ident(name)` — fast check for allowlist [A-Za-z_][A-Za-z0-9_]*
- `quote_ident(name)` — backtick-quoted identifier with embedded-backtick escaping
- `safe_table_name(namespace_or_collection)` — Mongo namespace → TiDB table name
- `safe_column_name(field_path)` — Mongo field path (with dots) → TiDB column name

Use `quote_ident` everywhere a non-literal identifier flows into SQL DDL or
DML. Parameterized %s covers VALUES; identifiers can't be parameterized in
PyMySQL and must be quoted manually.

Reference: https://dev.mysql.com/doc/refman/8.0/en/identifiers.html
"""

from __future__ import annotations

import re


_SAFE_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


class UnsafeIdentifierError(ValueError):
    """Raised when an identifier cannot be safely represented as a TiDB identifier."""


def is_safe_ident(name: str) -> bool:
    """True iff `name` is an unquoted-safe MySQL identifier (alphanumeric + underscore, ≤64)."""
    return bool(_SAFE_IDENT_RE.fullmatch(name))


def quote_ident(name: str) -> str:
    """Return `name` as a backtick-quoted MySQL identifier.

    Escapes embedded backticks per MySQL (double them up). Rejects NUL bytes,
    control characters, or identifiers > 64 bytes.
    """
    if not isinstance(name, str) or not name:
        raise UnsafeIdentifierError("identifier must be a non-empty string")
    if "\x00" in name:
        raise UnsafeIdentifierError("identifier contains NUL byte")
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in name):
        raise UnsafeIdentifierError(f"identifier contains control characters: {name!r}")
    if len(name.encode("utf-8")) > 64:
        raise UnsafeIdentifierError(f"identifier > 64 bytes (MySQL limit): {name!r}")
    return "`" + name.replace("`", "``") + "`"


def safe_table_name(collection: str) -> str:
    """Map a MongoDB collection name to a TiDB table identifier.

    Mongo collection names can contain dots (system collections) and dollar
    signs (internal). We allowlist [A-Za-z_][A-Za-z0-9_]*. Anything else
    raises UnsafeIdentifierError — the user can rename or skip the collection.
    """
    if not isinstance(collection, str) or not collection:
        raise UnsafeIdentifierError("collection name must be non-empty string")
    if not _SAFE_IDENT_RE.fullmatch(collection):
        raise UnsafeIdentifierError(
            f"collection name {collection!r} contains characters outside "
            "[A-Za-z_][A-Za-z0-9_]; rename the collection or set "
            "convert.per_collection.<name>.table_name in config"
        )
    if len(collection) > 64:
        raise UnsafeIdentifierError(f"collection name > 64 bytes: {collection!r}")
    return collection


def safe_column_name(field_path: str) -> str:
    """Map a Mongo field path (which may include dots from nested subdocs) to a column name."""
    if not isinstance(field_path, str) or not field_path:
        raise UnsafeIdentifierError("field path must be non-empty string")
    col = field_path.replace(".", "_").replace("$", "_")
    if not _SAFE_IDENT_RE.fullmatch(col):
        raise UnsafeIdentifierError(
            f"field path {field_path!r} produces unsafe column name {col!r}"
        )
    return col
