"""Composite index enumeration via the Firestore Admin API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tishift_firestore.config import SourceConfig


@dataclass(frozen=True)
class IndexField:
    name: str
    order: str  # ASC | DESC | ARRAY_CONTAINS


@dataclass(frozen=True)
class CompositeIndex:
    collection_or_group: str
    scope: str  # COLLECTION | COLLECTION_GROUP
    fields: list[IndexField]

    def field_names(self) -> list[str]:
        return [f.name for f in self.fields]


def list_composite_indexes(source: SourceConfig) -> list[CompositeIndex]:
    """Enumerate all composite indexes in the configured database.

    Walking collection-group "*" returns every composite index across the
    database in one paginated stream.
    """
    from tishift_firestore.connection import firestore_admin_client

    admin = firestore_admin_client(source)

    db_name = (
        f"projects/{source.project_id}/databases/{source.database_id}"
    )
    parent = f"{db_name}/collectionGroups/-"

    out: list[CompositeIndex] = []
    for index in admin.list_indexes(parent=parent):
        fields = []
        for fld in index.fields:
            # Skip the implicit __name__ field that Firestore adds to every index.
            if fld.field_path == "__name__":
                continue
            order = _decode_order(fld)
            fields.append(IndexField(name=fld.field_path, order=order))

        scope = type(index).QueryScope(index.query_scope).name
        # Extract the collection / group ID from the index resource name.
        # Format: .../collectionGroups/{ID}/indexes/{INDEX_ID}
        collection_or_group = index.name.split("/collectionGroups/")[-1].split("/indexes/")[0]

        out.append(
            CompositeIndex(
                collection_or_group=collection_or_group,
                scope=scope,
                fields=fields,
            )
        )

    return out


def _decode_order(fld: Any) -> str:
    """Best-effort decode of the Firestore index-field order enum."""
    if getattr(fld, "array_config", 0):
        return "ARRAY_CONTAINS"
    order = getattr(fld, "order", 0)
    if order:
        return type(fld).Order(order).name  # ASCENDING / DESCENDING
    return "UNSPECIFIED"


def fields_in_any_index(
    indexes: list[CompositeIndex], *, collection_or_group: str
) -> set[str]:
    """All field paths that appear in any composite index for the given collection."""
    out: set[str] = set()
    for idx in indexes:
        if idx.collection_or_group == collection_or_group:
            out.update(f.name for f in idx.fields)
    return out
