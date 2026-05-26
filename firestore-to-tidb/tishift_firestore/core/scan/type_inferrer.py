"""Per-field type inference from sampled Firestore documents.

Pure logic, no Firestore client dependency — testable with synthetic input.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any


# Canonical Firestore value type names. Aligned with what the Admin SDK
# would return; tests construct these directly without needing a live SDK.
FIRESTORE_TYPES = {
    "string", "number", "boolean", "null",
    "timestamp", "geopoint", "reference", "bytes",
    "array", "map",
}


@dataclass
class FieldHistogram:
    """Type histogram + presence statistics for one field path within a collection."""

    field_path: str
    type_counts: Counter = field(default_factory=Counter)
    sample_size: int = 0
    seen_count: int = 0
    max_observed_string_len: int = 0
    max_observed_bytes_mb: float = 0.0
    numeric_values: list[float] = field(default_factory=list)
    map_keys_union: set[str] = field(default_factory=set)
    array_element_types: Counter = field(default_factory=Counter)
    server_timestamp_sentinels_seen: int = 0
    document_reference_paths: list[str] = field(default_factory=list)

    def presence_ratio(self) -> float:
        if self.sample_size == 0:
            return 0.0
        return self.seen_count / self.sample_size

    def is_sparse(self) -> bool:
        return self.presence_ratio() < 0.75

    def is_polymorphic(self) -> bool:
        non_null = {t: c for t, c in self.type_counts.items() if t != "null"}
        return len(non_null) > 1

    def dominant_type(self) -> str | None:
        if not self.type_counts:
            return None
        non_null = [(t, c) for t, c in self.type_counts.items() if t != "null"]
        if not non_null:
            return "null"
        non_null.sort(key=lambda tc: tc[1], reverse=True)
        return non_null[0][0]

    def is_nullable(self) -> bool:
        # Nullable if any sample was null OR field is sparse.
        return self.type_counts.get("null", 0) > 0 or self.is_sparse()

    def to_dict(self) -> dict[str, Any]:
        return {
            "types": dict(self.type_counts),
            "presence_ratio": round(self.presence_ratio(), 4),
            "max_observed_string_len": self.max_observed_string_len,
            "max_observed_bytes_mb": round(self.max_observed_bytes_mb, 3),
            "map_keys_union": sorted(self.map_keys_union),
            "array_element_types": dict(self.array_element_types),
            "server_timestamp_sentinels_seen": self.server_timestamp_sentinels_seen,
            "is_polymorphic": self.is_polymorphic(),
            "is_sparse": self.is_sparse(),
        }


def classify(value: Any) -> str:
    """Map a Python value (as deserialized from a Firestore document) to a type label.

    Tests pass synthetic sentinel dicts {"_type": "timestamp", ...} to represent
    Firestore-specific types without depending on the SDK. Real scanner code
    passes actual SDK objects, but the structural detection is the same.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        # Must come before int check — booleans are ints in Python.
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, bytes):
        return "bytes"
    if isinstance(value, dict):
        # Synthetic typed sentinels used in test fixtures and sample-schema.json.
        t = value.get("_type")
        if t in ("timestamp", "geopoint", "reference", "bytes"):
            return t
        return "map"
    return "map"  # default fallback for unknown SDK shapes


def update_histogram(
    hist: FieldHistogram, value: Any, *, increment_sample: bool = True
) -> None:
    """Update a histogram with one observation of `value`.

    increment_sample should be True when this is a top-level field of a sampled
    document (counts toward presence). For nested traversals it's True too —
    each visited path counts independently.
    """
    if increment_sample:
        hist.sample_size += 1

    type_label = classify(value)
    hist.type_counts[type_label] += 1
    if type_label != "null":
        hist.seen_count += 1

    if type_label == "string":
        hist.max_observed_string_len = max(hist.max_observed_string_len, len(value))
    elif type_label == "number":
        hist.numeric_values.append(float(value))
    elif type_label == "bytes":
        if isinstance(value, bytes):
            size_mb = len(value) / (1024 * 1024)
        elif isinstance(value, dict) and "base64" in value:
            import base64
            size_mb = len(base64.b64decode(value["base64"])) / (1024 * 1024)
        else:
            size_mb = 0.0
        hist.max_observed_bytes_mb = max(hist.max_observed_bytes_mb, size_mb)
    elif type_label == "timestamp":
        if isinstance(value, dict) and value.get("_sentinel") == "SERVER_TIMESTAMP":
            hist.server_timestamp_sentinels_seen += 1
    elif type_label == "reference":
        if isinstance(value, dict) and "path" in value:
            hist.document_reference_paths.append(value["path"])
        elif hasattr(value, "path"):
            hist.document_reference_paths.append(value.path)
    elif type_label == "map":
        hist.map_keys_union.update(k for k in value.keys() if not k.startswith("_"))
    elif type_label == "array":
        for elem in value:
            hist.array_element_types[classify(elem)] += 1


def infer_field_type(hist: FieldHistogram) -> str:
    """Reduce a histogram to a single inferred type label.

    Rules (in order):
    - 100% of values are the same type → that type
    - ≥95% are one type with rest null → that type (nullable inferred elsewhere)
    - Multiple non-null types → 'polymorphic'
    - All null → 'null'
    """
    non_null = {t: c for t, c in hist.type_counts.items() if t != "null"}
    if not non_null:
        return "null"

    total_non_null = sum(non_null.values())
    if len(non_null) == 1:
        return next(iter(non_null))

    # Multiple types — check if one dominates ≥95%
    dominant = max(non_null.items(), key=lambda tc: tc[1])
    if dominant[1] / total_non_null >= 0.95:
        return dominant[0]

    return "polymorphic"


def walk_document(
    doc_fields: dict[str, Any],
    *,
    prefix: str = "",
    histograms: dict[str, FieldHistogram] | None = None,
) -> dict[str, FieldHistogram]:
    """Walk a document body and update histograms for every field path.

    For test fixtures, `doc_fields` is the raw dict from sample-schema.json
    (with the synthetic sentinel format). For live scans, it's the
    document.to_dict() output from the Firestore SDK.
    """
    if histograms is None:
        histograms = {}

    for key, value in doc_fields.items():
        if key.startswith("_") and prefix == "":
            # _id, _type, etc. — skip top-level synthetic markers
            continue
        path = f"{prefix}.{key}" if prefix else key
        hist = histograms.setdefault(path, FieldHistogram(field_path=path))
        update_histogram(hist, value)

        # Recurse into maps (but not into the typed-sentinel maps).
        if isinstance(value, dict) and "_type" not in value:
            walk_document(value, prefix=path, histograms=histograms)

    return histograms
