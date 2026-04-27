"""Unit tests for endpoint classification."""

from __future__ import annotations

import pytest

from tishift_supabase.config import SourceConfig
from tishift_supabase.connection import (
    ConnectionMode,
    analyze_endpoint,
)


def _src(host: str, port: int, user: str) -> SourceConfig:
    return SourceConfig(
        host=host,
        port=port,
        user=user,
        password="x",
        database="postgres",
    )


def test_direct_endpoint() -> None:
    analysis = analyze_endpoint(_src("db.abcdef.supabase.co", 5432, "postgres"))
    assert analysis.mode == ConnectionMode.DIRECT
    assert analysis.project_ref == "abcdef"
    assert analysis.warnings == ()


def test_direct_endpoint_with_pooler_username_warns() -> None:
    analysis = analyze_endpoint(_src("db.abcdef.supabase.co", 5432, "postgres.abcdef"))
    assert analysis.mode == ConnectionMode.DIRECT
    assert any("direct endpoint uses username 'postgres'" in w for w in analysis.warnings)


def test_session_pooler() -> None:
    analysis = analyze_endpoint(
        _src("aws-0-us-east-1.pooler.supabase.com", 5432, "postgres.abcdef")
    )
    assert analysis.mode == ConnectionMode.SESSION_POOLER
    assert analysis.project_ref == "abcdef"
    assert analysis.region == "us-east-1"
    assert analysis.warnings == ()


def test_session_pooler_wrong_username_warns() -> None:
    analysis = analyze_endpoint(
        _src("aws-0-us-east-1.pooler.supabase.com", 5432, "postgres")
    )
    assert analysis.mode == ConnectionMode.SESSION_POOLER
    assert any("pooler endpoint requires" in w for w in analysis.warnings)


def test_unknown_endpoint() -> None:
    analysis = analyze_endpoint(_src("custom.example.com", 5432, "postgres"))
    assert analysis.mode == ConnectionMode.UNKNOWN
    assert analysis.warnings
