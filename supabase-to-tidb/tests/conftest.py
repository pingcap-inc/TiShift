"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent


@pytest.fixture
def sample_schema_sql() -> str:
    """The full fixture schema (all BLOCKERs + WARNINGs exercised)."""
    return (REPO_ROOT / "sql" / "sample-schema.sql").read_text()


@pytest.fixture
def example_config_path() -> Path:
    return REPO_ROOT / "config" / "tishift-supabase.example.yaml"
