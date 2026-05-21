"""Aggregation Pipeline → SQL rewrite advisor.

Provider-agnostic. The caller injects a `complete` callable.

Privacy contract: prompts contain pipeline JSON, field names, and inferred
types from the scan. They do NOT contain document data or sample values.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from tishift_mongodb.core.scan.aggregation_inventory import Pipeline


log = logging.getLogger(__name__)


@dataclass
class AggregationRewrite:
    pipeline_id: str
    collection: str
    complexity: int
    original_pipeline_json: str
    suggested_sql: str
    rationale: str
    review_warnings: list[str]


CompletionFn = Callable[[str], str]


def suggest_rewrite(
    pipeline: Pipeline,
    *,
    schema_context: dict,
    complete: CompletionFn | None = None,
) -> AggregationRewrite | None:
    """Produce a SQL rewrite suggestion for one aggregation pipeline.

    `schema_context` carries field names + types from the scan for the
    pipeline's collection — used to ground the suggestion. Document values are
    NOT included.

    Returns None if no completion function provided. Never raises.
    """
    if complete is None:
        return None

    pipeline_json = json.dumps(pipeline.raw, indent=2)
    context_json = json.dumps(schema_context, indent=2)

    prompt = (
        "You are a database engineer translating a MongoDB aggregation pipeline "
        "into TiDB-compatible SQL.\n\n"
        f"Collection: {pipeline.collection}\n"
        f"Stages: {' → '.join(pipeline.stages)}\n"
        f"Complexity score: {pipeline.complexity}\n\n"
        "Schema context (typed columns + JSON paths from TiShift convert):\n"
        f"{context_json}\n\n"
        "Pipeline JSON:\n"
        f"{pipeline_json}\n\n"
        "Produce:\n"
        "1. A TiDB-compatible SQL query equivalent to the pipeline (use "
        "JSON_EXTRACT for fields stored in the merged `doc` JSON column).\n"
        "2. A short rationale (stage-by-stage mapping).\n"
        "3. A list of REVIEW warnings (timezone handling, index implications, "
        "semantics that differ between Mongo and SQL).\n\n"
        'Respond as JSON: {"sql": "...", "rationale": "...", "warnings": [...]}'
    )

    try:
        response_text = complete(prompt)
        parsed = json.loads(response_text)
        return AggregationRewrite(
            pipeline_id=pipeline.id,
            collection=pipeline.collection,
            complexity=pipeline.complexity,
            original_pipeline_json=pipeline_json,
            suggested_sql=parsed.get("sql", ""),
            rationale=parsed.get("rationale", ""),
            review_warnings=parsed.get("warnings", []),
        )
    except Exception as e:  # noqa: BLE001
        log.warning("Aggregation advisor failed for %s: %s", pipeline.id, e)
        return None


def write_rewrites(
    rewrites: list[AggregationRewrite],
    output_path: str | Path,
) -> Path:
    """Render rewrites as a Markdown document."""
    lines = ["# Aggregation Pipeline Rewrite Suggestions", ""]
    lines.append("**These are SUGGESTIONS, not guarantees.** Every rewrite must")
    lines.append("be reviewed by the application team before production use.")
    lines.append("")
    for r in rewrites:
        lines.append(f"## Pipeline: `{r.pipeline_id}` (collection: `{r.collection}`)")
        lines.append("")
        lines.append(f"Complexity: {r.complexity}")
        lines.append("")
        lines.append("### Original (Mongo)")
        lines.append("```json")
        lines.append(r.original_pipeline_json)
        lines.append("```")
        lines.append("")
        lines.append("### Suggested SQL (TiDB)")
        lines.append("```sql")
        lines.append(r.suggested_sql)
        lines.append("```")
        lines.append("")
        if r.rationale:
            lines.append("### Rationale")
            lines.append(r.rationale)
            lines.append("")
        if r.review_warnings:
            lines.append("### ⚠ Review required")
            for w in r.review_warnings:
                lines.append(f"- {w}")
            lines.append("")
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
