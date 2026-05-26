"""Shared pytest fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


SAMPLE_SCHEMA_PATH = Path(__file__).parent.parent / "sql" / "sample-schema.json"


@pytest.fixture
def sample_schema() -> dict:
    return json.loads(SAMPLE_SCHEMA_PATH.read_text())


@pytest.fixture
def sample_collections(sample_schema: dict) -> dict[str, list[dict]]:
    return sample_schema["collections"]


@pytest.fixture
def sample_indexes(sample_schema: dict) -> dict[str, list[dict]]:
    return sample_schema.get("indexes", {})


@pytest.fixture
def sample_aggregations(sample_schema: dict) -> list[dict]:
    return sample_schema.get("aggregations", [])
