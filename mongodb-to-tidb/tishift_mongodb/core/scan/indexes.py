"""MongoDB index inventory.

Captures every index type: single, compound, multikey, 2dsphere, 2d,
geoHaystack, text, hashed, wildcard, partial, sparse, TTL.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class IndexField:
    name: str
    direction: Any  # 1 / -1 / "2dsphere" / "2d" / "text" / "hashed"


@dataclass
class IndexInfo:
    name: str
    collection: str
    fields: list[IndexField] = field(default_factory=list)
    unique: bool = False
    sparse: bool = False
    ttl_seconds: int | None = None
    partial_filter: dict | None = None
    wildcard_projection: dict | None = None

    # Derived classifications
    is_geospatial: bool = False
    is_text: bool = False
    is_wildcard: bool = False
    is_multikey: bool = False  # determined at runtime, not from getIndexes()

    def field_names(self) -> list[str]:
        return [f.name for f in self.fields]


def parse_index_info(collection: str, raw: dict) -> IndexInfo:
    """Parse a single getIndexes() document into an IndexInfo."""
    name = raw.get("name", "")
    key = raw.get("key", {})
    fields: list[IndexField] = []
    is_geo = False
    is_text = False
    is_wildcard = False

    for fname, direction in key.items():
        fields.append(IndexField(name=fname, direction=direction))
        if direction in ("2dsphere", "2d", "geoHaystack"):
            is_geo = True
        if direction == "text":
            is_text = True
        if "$**" in fname:
            is_wildcard = True

    return IndexInfo(
        name=name,
        collection=collection,
        fields=fields,
        unique=bool(raw.get("unique", False)),
        sparse=bool(raw.get("sparse", False)),
        ttl_seconds=raw.get("expireAfterSeconds"),
        partial_filter=raw.get("partialFilterExpression"),
        wildcard_projection=raw.get("wildcardProjection"),
        is_geospatial=is_geo,
        is_text=is_text,
        is_wildcard=is_wildcard,
    )


def list_indexes_for_collection(collection_obj) -> list[IndexInfo]:
    """Pull indexes for a single PyMongo collection."""
    name = collection_obj.name
    return [parse_index_info(name, raw) for raw in collection_obj.list_indexes()]


def fields_in_any_composite_index(indexes: list[IndexInfo], *, collection: str) -> set[str]:
    """All field paths appearing in any *composite* (≥2 fields) index for the collection."""
    out: set[str] = set()
    for idx in indexes:
        if idx.collection != collection:
            continue
        if len(idx.fields) < 2:
            continue
        out.update(f.name for f in idx.fields)
    return out
