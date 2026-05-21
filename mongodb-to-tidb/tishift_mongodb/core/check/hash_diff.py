"""Deterministic BSON-aware canonicalization + SHA-256 hashing.

Extends the Firestore canonicalization rules with BSON-specific types:
ObjectId, Decimal128, UUID, Binary (with subtype), Regex, Code, BSON Timestamp.

Canonicalization version is bumped to 2 to distinguish from the Firestore-era
v1 — any hash produced under one version is not comparable to the other.
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone
from typing import Any


CANONICALIZATION_VERSION = 2


def canonicalize(value: Any) -> Any:
    """Recursive canonical form. Stable across SDK/Python versions."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return float(repr(value))
    if isinstance(value, str):
        return value
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds")
    if isinstance(value, bytes):
        return {"$bin": base64.b64encode(value).decode("ascii"), "$type": 0}
    if isinstance(value, list):
        return [canonicalize(v) for v in value]
    if isinstance(value, dict):
        # Synthetic test-fixture forms
        if value.get("_type") == "ObjectId" and "value" in value:
            return {"$oid": value["value"]}
        if value.get("_type") == "Decimal128" and "value" in value:
            return {"$dec": value["value"]}
        if value.get("_type") == "UUID" and "value" in value:
            return {"$uuid": value["value"]}
        if value.get("_type") == "Binary":
            return {"$bin": value.get("base64", ""), "$type": value.get("subtype", 0)}
        if value.get("_type") == "Date" and "iso" in value:
            return value["iso"]
        if value.get("_type") == "Timestamp":
            return {"$ts": (value.get("time", 0), value.get("inc", 0))}
        if value.get("_type") == "Regex":
            return {"$regex": value.get("pattern", ""), "$opts": value.get("flags", "")}
        if value.get("_type") == "Code":
            return {"$code": value.get("source", "")}
        if value.get("_type") == "GeoPoint":
            return {"$geo": [round(value["lat"], 6), round(value["lng"], 6)]}
        if value.get("_type") == "DBRef" or ("$ref" in value and "$id" in value):
            ref = value.get("$ref", value.get("ref", ""))
            ref_id = value.get("$id", value.get("id", ""))
            return {"$dbref": [ref, str(ref_id)]}
        return {k: canonicalize(v) for k, v in sorted(value.items())}

    # Live PyMongo BSON objects — detect by class name + attributes
    cls = type(value).__name__
    if cls == "ObjectId":
        return {"$oid": str(value)}
    if cls == "Decimal128":
        return {"$dec": str(value)}
    if cls == "UUID":
        return {"$uuid": str(value)}
    if cls == "Binary":
        subtype = getattr(value, "subtype", 0)
        return {"$bin": base64.b64encode(bytes(value)).decode("ascii"), "$type": subtype}
    if cls == "Timestamp":
        return {"$ts": (getattr(value, "time", 0), getattr(value, "inc", 0))}
    if cls == "Regex":
        return {"$regex": getattr(value, "pattern", ""), "$opts": getattr(value, "flags", "")}
    if cls == "Code":
        return {"$code": str(value)}
    if hasattr(value, "collection") and hasattr(value, "id"):
        # DBRef
        return {"$dbref": [value.collection, str(value.id)]}
    return canonicalize(str(value))


def hash_document(doc: dict[str, Any]) -> str:
    """SHA-256 hex digest of the canonicalized document."""
    canonical = canonicalize(doc)
    raw = json.dumps(canonical, separators=(",", ":"), sort_keys=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
