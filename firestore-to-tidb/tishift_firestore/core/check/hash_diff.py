"""Deterministic canonicalization + SHA-256 hashing of Firestore documents.

Used by the check phase to compare a sample of source documents against their
target rows. The canonicalization rules are documented in docs/check-guide.md
and must change in lockstep with any consumer of the resulting hashes.
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone
from typing import Any


CANONICALIZATION_VERSION = 1


def canonicalize(value: Any) -> Any:
    """Recursive canonical form. Stable across SDK versions and Python versions.

    Rules:
      - dicts → sorted by key
      - lists → unchanged order (Firestore arrays preserve order)
      - timestamps → ISO 8601 UTC with microsecond precision
      - bytes → base64 string with marker
      - DocumentReference → {"$ref": "<path>"}
      - GeoPoint → {"$geo": [lat, lng]} rounded to 6dp
      - floats → repr() (round-trip exact)
    """
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
        return {"$bytes": base64.b64encode(value).decode("ascii")}
    if isinstance(value, list):
        return [canonicalize(v) for v in value]
    if isinstance(value, dict):
        # Synthetic test-fixture forms.
        if value.get("_type") == "timestamp" and "iso" in value:
            return value["iso"]
        if value.get("_type") == "bytes" and "base64" in value:
            return {"$bytes": value["base64"]}
        if value.get("_type") == "geopoint" and "lat" in value:
            return {"$geo": [round(value["lat"], 6), round(value["lng"], 6)]}
        if value.get("_type") == "reference" and "path" in value:
            return {"$ref": value["path"]}
        return {k: canonicalize(v) for k, v in sorted(value.items())}
    # Live-SDK objects: detect via attribute conventions.
    if hasattr(value, "latitude") and hasattr(value, "longitude"):
        return {"$geo": [round(value.latitude, 6), round(value.longitude, 6)]}
    if hasattr(value, "path"):
        return {"$ref": value.path}
    return canonicalize(str(value))


def hash_document(doc: dict[str, Any]) -> str:
    """SHA-256 hex digest of the canonicalized document."""
    canonical = canonicalize(doc)
    raw = json.dumps(canonical, separators=(",", ":"), sort_keys=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
