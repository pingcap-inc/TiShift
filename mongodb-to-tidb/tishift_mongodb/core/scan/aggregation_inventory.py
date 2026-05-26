"""Aggregation pipeline inventory and complexity scoring.

Pulls pipelines from one of three sources (in priority order):
1. Atlas Performance Advisor (Atlas only)
2. system.profile collection (if profiling enabled)
3. User-supplied file (always available as fallback)

Then computes a complexity score per pipeline (drives Application Coupling
scoring in the readiness assessment).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


_STAGE_COMPLEXITY = {
    "$match": 1,
    "$sort": 1,
    "$limit": 1,
    "$skip": 1,
    "$project": 1,
    "$addFields": 1,
    "$set": 1,
    "$unset": 1,
    "$count": 1,
    "$group": 3,
    "$lookup": 5,
    "$unwind": 5,
    "$graphLookup": 8,
    "$facet": 8,
    "$bucket": 8,
    "$bucketAuto": 8,
    "$replaceRoot": 2,
    "$replaceWith": 2,
    "$out": 10,
    "$merge": 10,
}


_ARRAY_OP_COMPLEXITY = 4
_ARRAY_OPS = {"$elemMatch", "$slice", "$filter", "$map", "$reduce", "$zip"}


@dataclass
class Pipeline:
    id: str
    collection: str
    stages: list[str]
    raw: list[dict]
    complexity: int = 0
    source: str = "user"  # atlas | system_profile | user


def complexity_of_stage(stage: dict) -> int:
    """Compute complexity points for one aggregation stage."""
    if not isinstance(stage, dict) or not stage:
        return 0
    name = next(iter(stage.keys()))
    base = _STAGE_COMPLEXITY.get(name, 1)
    # Heuristic: count array-operator usage inside the stage
    array_ops_found = 0

    def walk(node: Any) -> None:
        nonlocal array_ops_found
        if isinstance(node, dict):
            for k, v in node.items():
                if k in _ARRAY_OPS:
                    array_ops_found += 1
                walk(v)
        elif isinstance(node, list):
            for x in node:
                walk(x)

    walk(stage)
    return base + (array_ops_found * _ARRAY_OP_COMPLEXITY)


def complexity_of_pipeline(stages: list[dict]) -> int:
    """Sum complexity across all stages."""
    return sum(complexity_of_stage(s) for s in stages)


def stage_names(stages: list[dict]) -> list[str]:
    return [next(iter(s.keys())) for s in stages if isinstance(s, dict) and s]


def inventory_from_user_file(pipelines: list[dict]) -> list[Pipeline]:
    """Build inventory from user-supplied JSON file."""
    out: list[Pipeline] = []
    for entry in pipelines:
        stages_raw = entry.get("pipeline", [])
        out.append(
            Pipeline(
                id=entry.get("id", f"{entry.get('collection', 'unknown')}.{len(out)}"),
                collection=entry.get("collection", ""),
                stages=stage_names(stages_raw),
                raw=stages_raw,
                complexity=complexity_of_pipeline(stages_raw),
                source="user",
            )
        )
    return out


def inventory_from_system_profile(profile_docs: list[dict]) -> list[Pipeline]:
    """Build inventory from system.profile aggregation operations."""
    out: list[Pipeline] = []
    for doc in profile_docs:
        if doc.get("op") != "command":
            continue
        cmd = doc.get("command", {})
        if "aggregate" not in cmd:
            continue
        collection = cmd["aggregate"]
        stages_raw = cmd.get("pipeline", [])
        out.append(
            Pipeline(
                id=f"{collection}.profile-{len(out)}",
                collection=collection,
                stages=stage_names(stages_raw),
                raw=stages_raw,
                complexity=complexity_of_pipeline(stages_raw),
                source="system_profile",
            )
        )
    return out


def aggregate_complexity(pipelines: list[Pipeline]) -> int:
    """Sum complexity across all pipelines."""
    return sum(p.complexity for p in pipelines)
