"""Detect Firestore database mode and edition."""

from __future__ import annotations

from dataclasses import dataclass

from tishift_firestore.config import SourceConfig


@dataclass(frozen=True)
class ModeDetectResult:
    mode: str  # native | datastore | mongo-api
    edition: str  # standard | enterprise
    location: str
    multiple_databases: bool
    redirect_required: bool


def detect_mode(source: SourceConfig) -> ModeDetectResult:
    """Call the Admin API to determine database mode and edition.

    Lives in its own module because Phase 1 of the SKILL flow gates everything
    else on this result. Returns a redirect signal if the database is on the
    MongoDB-API surface.
    """
    from tishift_firestore.connection import firestore_admin_client

    admin = firestore_admin_client(source)

    # List databases in project to determine multi-DB presence.
    parent = f"projects/{source.project_id}"
    databases = list(admin.list_databases(parent=parent).databases)
    multiple = len(databases) > 1

    target_db_name = (
        f"{parent}/databases/{source.database_id}"
        if source.database_id != "(default)"
        else f"{parent}/databases/(default)"
    )

    target_db = next((d for d in databases if d.name == target_db_name), None)
    if target_db is None:
        raise RuntimeError(
            f"Database {source.database_id} not found in project {source.project_id}"
        )

    # Database.type is an enum: FIRESTORE_NATIVE | DATASTORE_MODE
    type_name = type(target_db).Type(target_db.type_).name
    if type_name == "FIRESTORE_NATIVE":
        mode = "native"
    elif type_name == "DATASTORE_MODE":
        mode = "datastore"
    else:
        mode = "unknown"

    # The Admin protos expose edition via the `database_edition` field in newer versions.
    # Older versions: assume STANDARD.
    edition = "standard"
    if hasattr(target_db, "database_edition"):
        ed_name = type(target_db).DatabaseEdition(target_db.database_edition).name
        edition = "enterprise" if ed_name == "ENTERPRISE" else "standard"

    # MongoDB-compatibility detection: Enterprise edition + an api_scope or
    # similar marker. Conservative default: treat Enterprise as needing redirect
    # unless explicitly confirmed Native-API.
    redirect_required = edition == "enterprise"

    return ModeDetectResult(
        mode="mongo-api" if redirect_required else mode,
        edition=edition,
        location=target_db.location_id,
        multiple_databases=multiple,
        redirect_required=redirect_required,
    )
