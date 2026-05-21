"""Per-field type inference from sampled MongoDB documents.

Pure logic, no PyMongo dependency at module level — uses synthetic
`{_type: "ObjectId", value: ...}` sentinels for test fixtures, and the real
BSON Python classes when called from the live scanner.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any


BSON_TYPES = {
    "Int32", "Int64", "Double", "Decimal128", "String", "Boolean", "null",
    "Date", "Timestamp", "ObjectId", "UUID", "Binary", "Regex", "Code",
    "Symbol", "MinKey", "MaxKey", "DBRef",
    "Object",  # subdocument
    "Array",
}


@dataclass
class FieldHistogram:
    """Type histogram + presence statistics for one field path within a collection."""

    field_path: str
    type_counts: Counter = field(default_factory=Counter)
    sample_size: int = 0
    seen_count: int = 0
    max_observed_string_len: int = 0
    max_observed_binary_size_mb: float = 0.0
    binary_subtypes_seen: Counter = field(default_factory=Counter)
    numeric_values: list[float] = field(default_factory=list)
    subdocument_keys_union: set[str] = field(default_factory=set)
    array_element_types: Counter = field(default_factory=Counter)
    dbref_targets: list[str] = field(default_factory=list)

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
        return self.type_counts.get("null", 0) > 0 or self.is_sparse()

    def has_csfle(self) -> bool:
        return self.binary_subtypes_seen.get(6, 0) > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "types": dict(self.type_counts),
            "presence_ratio": round(self.presence_ratio(), 4),
            "max_observed_string_len": self.max_observed_string_len,
            "max_observed_binary_size_mb": round(self.max_observed_binary_size_mb, 3),
            "binary_subtypes": dict(self.binary_subtypes_seen),
            "subdocument_keys": sorted(self.subdocument_keys_union),
            "array_element_types": dict(self.array_element_types),
            "is_polymorphic": self.is_polymorphic(),
            "is_sparse": self.is_sparse(),
            "has_csfle": self.has_csfle(),
        }


def classify(value: Any) -> str:
    """Map a Python value (from PyMongo or synthetic fixture) to a BSON-type label."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "Boolean"
    if isinstance(value, int):
        # BSON has Int32 and Int64 — PyMongo decodes per the wire-level type.
        # For Python int values, we can't tell at this point, so the scanner
        # records "Int" and the load phase decides Int32 vs Int64 based on
        # numeric_values stats. For histogram purposes "Int64" is the safe default.
        return "Int64" if abs(value) > 2**31 else "Int32"
    if isinstance(value, float):
        return "Double"
    if isinstance(value, str):
        return "String"
    if isinstance(value, list):
        return "Array"
    if isinstance(value, bytes):
        return "Binary"
    if isinstance(value, dict):
        # Synthetic typed sentinels for tests + sample-schema.json
        t = value.get("_type")
        if t in (
            "ObjectId", "Decimal128", "UUID", "Binary", "Date",
            "Timestamp", "Regex", "Code", "Symbol", "MinKey", "MaxKey",
            "DBRef", "GeoPoint",
        ):
            return t if t != "GeoPoint" else "Object"  # GeoPoint is a sub-shape
        # DBRef detection by structure
        if "$ref" in value and "$id" in value:
            return "DBRef"
        return "Object"
    # PyMongo wire-level BSON classes: detect by class name to avoid
    # importing pymongo at module top.
    cls = type(value).__name__
    if cls == "ObjectId":
        return "ObjectId"
    if cls == "Decimal128":
        return "Decimal128"
    if cls == "UUID":
        return "UUID"
    if cls == "Binary":
        return "Binary"
    if cls == "datetime":
        return "Date"
    if cls == "Timestamp":
        return "Timestamp"
    if cls == "Regex":
        return "Regex"
    if cls == "Code":
        return "Code"
    if cls == "DBRef":
        return "DBRef"
    return "Object"


def update_histogram(
    hist: FieldHistogram, value: Any, *, increment_sample: bool = True
) -> None:
    """Update histogram with one observation of `value`."""
    if increment_sample:
        hist.sample_size += 1

    type_label = classify(value)
    hist.type_counts[type_label] += 1
    if type_label != "null":
        hist.seen_count += 1

    if type_label == "String":
        hist.max_observed_string_len = max(hist.max_observed_string_len, len(value))
    elif type_label in ("Int32", "Int64", "Double"):
        hist.numeric_values.append(float(value))
    elif type_label == "Decimal128":
        # From sentinel: {_type: "Decimal128", value: "49.99"}; from BSON: Decimal128 object
        if isinstance(value, dict) and "value" in value:
            try:
                hist.numeric_values.append(float(value["value"]))
            except (ValueError, TypeError):
                pass
    elif type_label == "Binary":
        if isinstance(value, bytes):
            size_mb = len(value) / (1024 * 1024)
            hist.binary_subtypes_seen[0] += 1
        elif isinstance(value, dict):
            subtype = int(value.get("subtype", 0))
            hist.binary_subtypes_seen[subtype] += 1
            if "base64" in value:
                import base64
                size_mb = len(base64.b64decode(value["base64"])) / (1024 * 1024)
            else:
                size_mb = 0.0
        else:
            # PyMongo Binary
            size_mb = len(bytes(value)) / (1024 * 1024)
            subtype = getattr(value, "subtype", 0)
            hist.binary_subtypes_seen[subtype] += 1
        hist.max_observed_binary_size_mb = max(hist.max_observed_binary_size_mb, size_mb)
    elif type_label == "DBRef":
        if isinstance(value, dict):
            ref = value.get("$ref", "")
            if ref:
                hist.dbref_targets.append(ref)
    elif type_label == "Object":
        if isinstance(value, dict):
            hist.subdocument_keys_union.update(
                k for k in value.keys() if not k.startswith("_") and not k.startswith("$")
            )
    elif type_label == "Array":
        for elem in value:
            hist.array_element_types[classify(elem)] += 1


def infer_field_type(hist: FieldHistogram) -> str:
    """Reduce a histogram to a single inferred type label."""
    non_null = {t: c for t, c in hist.type_counts.items() if t != "null"}
    if not non_null:
        return "null"
    total_non_null = sum(non_null.values())
    if len(non_null) == 1:
        return next(iter(non_null))
    dominant = max(non_null.items(), key=lambda tc: tc[1])
    if dominant[1] / total_non_null >= 0.95:
        return dominant[0]
    return "polymorphic"


def walk_document(
    doc_fields: dict[str, Any],
    *,
    prefix: str = "",
    histograms: dict[str, FieldHistogram] | None = None,
    skip_top_level_id: bool = True,
) -> dict[str, FieldHistogram]:
    """Walk a document body and update histograms for every field path.

    The Mongo `_id` field is handled separately by the scanner (per-collection
    PK inference) and skipped here when at top level.
    """
    if histograms is None:
        histograms = {}

    for key, value in doc_fields.items():
        if prefix == "" and skip_top_level_id and key == "_id":
            continue
        # Skip synthetic test markers
        if key.startswith("_") and prefix == "" and key != "_id":
            continue
        path = f"{prefix}.{key}" if prefix else key
        hist = histograms.setdefault(path, FieldHistogram(field_path=path))
        update_histogram(hist, value)

        # Recurse into plain subdocuments (not typed sentinels, not DBRefs)
        if (
            isinstance(value, dict)
            and "_type" not in value
            and "$ref" not in value
            and not key.startswith("$")
        ):
            walk_document(value, prefix=path, histograms=histograms,
                          skip_top_level_id=False)

    return histograms
