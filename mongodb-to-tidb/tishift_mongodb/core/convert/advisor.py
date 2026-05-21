"""Provider-agnostic LLM advisor for relationship inference.

Submits only field names + type histograms — never document data. The caller
injects a `complete` callable; the operator chooses the LLM provider.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Callable

from tishift_mongodb.core.scan.type_inferrer import FieldHistogram


log = logging.getLogger(__name__)


@dataclass
class RelationshipHint:
    field_path: str
    candidate_target_collection: str
    confidence: float
    rationale: str


CompletionFn = Callable[[str], str]


def suggest_relationships(
    *,
    collection_name: str,
    histograms: dict[str, FieldHistogram],
    known_collections: list[str],
    complete: CompletionFn | None = None,
) -> list[RelationshipHint]:
    """Infer string-typed FK candidates from field-name conventions using an LLM.

    Returns empty list if `complete` is None or fails. Never raises.
    """
    if complete is None:
        log.info("No completion function provided; skipping relationship advisor")
        return []

    field_summary = []
    for path, hist in sorted(histograms.items()):
        if hist.dominant_type() in ("String", "ObjectId"):
            field_summary.append({
                "path": path,
                "type": hist.dominant_type(),
                "presence_ratio": round(hist.presence_ratio(), 2),
            })

    if not field_summary:
        return []

    prompt = (
        f"You are a database schema analyst. Given the following string-typed or "
        f"ObjectId fields from collection '{collection_name}', identify which "
        f"likely encode a foreign-key reference to another collection by naming "
        f"convention.\n"
        f"Available target collections: {known_collections}.\n\n"
        f"Fields:\n{json.dumps(field_summary, indent=2)}\n\n"
        f'Return a JSON array. Each entry: {{"field_path": str, '
        f'"candidate_target_collection": str, "confidence": 0.0-1.0, '
        f'"rationale": str}}. Return only fields where confidence >= 0.6.'
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
        log.warning("Relationship advisor failed: %s", e)
        return []
