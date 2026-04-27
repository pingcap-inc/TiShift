"""AI analyzer for stored procedures using OpenAI-compatible API."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict
from typing import Any

import sqlglot

from tishift.config import AIConfig
from tishift.models import RoutineInfo, SPAIAnalysis, SPComplexity, SPDifficulty

logger = logging.getLogger(__name__)


def _count_occurrences(pattern: str, text: str) -> int:
    return len(re.findall(pattern, text, flags=re.IGNORECASE))


def _compute_complexity(definition: str | None) -> SPComplexity:
    if not definition:
        return SPComplexity(
            loc=0,
            cursor_count=0,
            dynamic_sql_count=0,
            temp_table_count=0,
            control_flow_count=0,
            nested_calls=0,
            transaction_statements=0,
        )

    lines = [l.strip() for l in definition.splitlines() if l.strip()]
    text = definition
    return SPComplexity(
        loc=len(lines),
        cursor_count=_count_occurrences(r"\bCURSOR\b", text),
        dynamic_sql_count=(
            _count_occurrences(r"\bPREPARE\b", text)
            + _count_occurrences(r"\bEXECUTE\b", text)
        ),
        temp_table_count=_count_occurrences(r"\bTEMPORARY\b", text),
        control_flow_count=(
            _count_occurrences(r"\bIF\b", text)
            + _count_occurrences(r"\bWHILE\b", text)
            + _count_occurrences(r"\bLOOP\b", text)
            + _count_occurrences(r"\bCASE\b", text)
        ),
        nested_calls=_count_occurrences(r"\bCALL\b", text),
        transaction_statements=(
            _count_occurrences(r"\bSTART\s+TRANSACTION\b", text)
            + _count_occurrences(r"\bCOMMIT\b", text)
            + _count_occurrences(r"\bROLLBACK\b", text)
            + _count_occurrences(r"\bSAVEPOINT\b", text)
        ),
    )


def _local_difficulty(complexity: SPComplexity) -> SPDifficulty:
    if complexity.dynamic_sql_count > 0 or complexity.nested_calls > 0:
        if complexity.loc > 100:
            return SPDifficulty.REQUIRES_REDESIGN
        return SPDifficulty.COMPLEX
    if complexity.loc < 10 and complexity.cursor_count == 0 and complexity.control_flow_count <= 1:
        return SPDifficulty.TRIVIAL
    if complexity.loc < 30 and complexity.cursor_count == 0:
        return SPDifficulty.SIMPLE
    if complexity.cursor_count > 0 or complexity.temp_table_count > 0 or complexity.loc >= 100:
        return SPDifficulty.MODERATE
    return SPDifficulty.SIMPLE


def _parse_ai_json(payload: str) -> dict[str, Any]:
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        # Try to extract a JSON object from a response that includes text.
        start = payload.find("{")
        end = payload.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(payload[start : end + 1])
            except json.JSONDecodeError:
                pass
    raise ValueError("AI response was not valid JSON")


def _build_prompt(proc: RoutineInfo) -> str:
    definition = proc.routine_definition or proc.routine_body or ""
    return (
        "Analyze this MySQL stored procedure for migration to TiDB (which does not support stored procedures).\n\n"
        "Procedure:\n"
        f"{definition}\n\n"
        "Respond in JSON with:\n"
        "- difficulty: \"trivial\" | \"simple\" | \"moderate\" | \"complex\" | \"requires_redesign\"\n"
        "- automation_pct: number (0-100, how much of this the AI can fully generate)\n"
        "- summary: one-line description of what it does\n"
        "- suggested_approach: how to refactor (move to app layer, use TiDB features, etc.)\n"
        "- equivalent_code: { python: \"...\", go: \"...\", javascript: \"...\" }\n"
        "- tidb_compatible_sql: any pure SQL portions that work in TiDB\n"
        "- warnings: list of edge cases or gotchas\n"
    )


def _call_ai(prompt: str, config: AIConfig) -> dict[str, Any]:
    try:
        import openai  # type: ignore
    except ImportError as exc:
        raise RuntimeError("openai dependency not installed; install tishift[ai]") from exc

    client = openai.OpenAI(api_key=config.api_key)
    resp = client.chat.completions.create(
        model=config.model,
        max_tokens=1200,
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )

    content = resp.choices[0].message.content or ""
    if not content:
        raise ValueError("Empty response from AI provider")
    return _parse_ai_json(content)


def analyze_stored_procedures(
    routines: list[RoutineInfo],
    config: AIConfig,
) -> list[SPAIAnalysis]:
    """Analyze stored procedures/functions with optional AI assistance."""
    if config.provider in ("none", ""):
        return []
    if not config.api_key:
        logger.warning("AI provider set but api_key is empty; skipping AI analysis")
        return []

    analyses: list[SPAIAnalysis] = []

    for routine in routines:
        if routine.routine_type not in ("PROCEDURE", "FUNCTION"):
            continue

        definition = routine.routine_definition or routine.routine_body or ""
        complexity = _compute_complexity(definition)
        warnings: list[str] = []

        try:
            sqlglot.parse_one(definition)
        except Exception as exc:  # pragma: no cover - parser errors are expected
            warnings.append(f"sqlglot parse error: {exc}")

        analysis = SPAIAnalysis(
            routine_schema=routine.routine_schema,
            routine_name=routine.routine_name,
            routine_type=routine.routine_type,
            complexity=complexity,
            difficulty=_local_difficulty(complexity),
            warnings=warnings,
            provider=config.provider,
            model=config.model,
        )

        prompt = _build_prompt(routine)
        try:
            data = _call_ai(prompt, config)
        except Exception as exc:
            logger.warning("AI analysis failed for %s.%s: %s", routine.routine_schema, routine.routine_name, exc)
            analyses.append(analysis)
            continue

        difficulty = data.get("difficulty")
        if isinstance(difficulty, str):
            try:
                analysis.difficulty = SPDifficulty(difficulty)
            except ValueError:
                warnings.append(f"Unknown difficulty from AI: {difficulty}")

        automation_pct = data.get("automation_pct")
        if isinstance(automation_pct, (int, float)):
            analysis.automation_pct = int(round(automation_pct))

        analysis.summary = data.get("summary") if isinstance(data.get("summary"), str) else None
        analysis.suggested_approach = (
            data.get("suggested_approach") if isinstance(data.get("suggested_approach"), str) else None
        )

        equivalent = data.get("equivalent_code")
        if isinstance(equivalent, dict):
            analysis.equivalent_code = {
                k: v for k, v in equivalent.items() if isinstance(v, str)
            }

        analysis.tidb_compatible_sql = (
            data.get("tidb_compatible_sql") if isinstance(data.get("tidb_compatible_sql"), str) else None
        )

        warn_list = data.get("warnings")
        if isinstance(warn_list, list):
            analysis.warnings.extend([w for w in warn_list if isinstance(w, str)])

        analyses.append(analysis)

    logger.info("AI analysis complete for %d routine(s)", len(analyses))
    return analyses


def local_complexity_summary(routines: list[RoutineInfo]) -> dict[str, Any]:
    """Return a summary of local complexity metrics (for debugging/tests)."""
    items = []
    for routine in routines:
        complexity = _compute_complexity(routine.routine_definition or routine.routine_body)
        items.append({
            "schema": routine.routine_schema,
            "name": routine.routine_name,
            "complexity": asdict(complexity),
            "difficulty": _local_difficulty(complexity).value,
        })
    return {"routines": items}
