"""LLM-assisted mapping suggestions for polymorphic fields and naming-based FKs.

Provider-agnostic. The caller injects a `complete` callable that maps
prompt → response text; this module assembles the prompt, parses the
response, and returns structured hints.

By design, this module submits only field names and aggregate type
histograms — never document data. The caller is responsible for ensuring
the injected `complete` callable honors that contract.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Callable

from tishift_firestore.core.scan.type_inferrer import FieldHistogram


log = logging.getLogger(__name__)


@dataclass
class RelationshipHint:
    field_path: str
    candidate_target_collection: str
    confidence: float
    rationale: str


CompletionFn = Callable[[str], str]
"""A callable that takes a prompt and returns a model response. The caller
chooses the LLM provider, the model, and the credential handling."""


def suggest_relationships(
    *,
    collection_name: str,
    histograms: dict[str, FieldHistogram],
    known_collections: list[str],
    complete: CompletionFn | None = None,
) -> list[RelationshipHint]:
    """Infer string-typed FK candidates from field-name conventions using an LLM.

    Returns an empty list if `complete` is None or the call fails.
    Never raises — relationship inference is best-effort.
    """
    if complete is None:
        log.info("No completion function provided; skipping relationship-inference advisor")
        return []

    # Build a privacy-safe payload: only field names + dominant type, no values.
    field_summary = []
    for path, hist in sorted(histograms.items()):
        if hist.dominant_type() == "string":
            field_summary.append({"path": path, "presence_ratio": round(hist.presence_ratio(), 2)})

    if not field_summary:
        return []

    prompt = (
        f"You are a database schema analyst. Given the following string-typed "
        f"fields from collection '{collection_name}', identify which fields likely "
        f"encode a foreign-key reference to another collection by naming convention.\n"
        f"Available target collections: {known_collections}.\n\n"
        f"Fields:\n{json.dumps(field_summary, indent=2)}\n\n"
        f"Return a JSON array. Each entry must have: "
        f'{{"field_path": str, "candidate_target_collection": str, '
        f'"confidence": 0.0-1.0, "rationale": str}}. '
        f"Return only fields where confidence >= 0.6. Empty array if none."
    )

    try:
        response_text = complete(prompt)
        parsed = json.loads(response_text)
        return [
            RelationshipHint(
                field_path=h["field_path"],
                candidate_target_collection=h["candidate_target_collection"],
                confidence=float(h["confidence"]),
                rationale=h.get("rationale", ""),
            )
            for h in parsed
        ]
    except Exception as e:  # noqa: BLE001
        log.warning("Relationship-inference advisor failed: %s", e)
        return []
