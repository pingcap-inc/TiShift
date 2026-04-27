"""Unit tests for config validation.

These guard the non-negotiables: transaction-pooler refusal, wildcard schema
filter refusal, Supabase-internal schema in schema_include refusal, Realtime
slot-name collision refusal.
"""

from __future__ import annotations

import os

import pytest
from pydantic import ValidationError

from tishift_supabase.config import (
    SUPABASE_INTERNAL_SCHEMAS,
    SourceConfig,
    SyncConfig,
)


def _source(**overrides) -> dict:
    base = {
        "host": "db.abcdef.supabase.co",
        "port": 5432,
        "user": "postgres",
        "password": "secret",
        "database": "postgres",
    }
    base.update(overrides)
    return base


def test_accepts_direct_endpoint() -> None:
    SourceConfig(**_source())


def test_rejects_transaction_pooler_port() -> None:
    with pytest.raises(ValidationError, match="6543"):
        SourceConfig(**_source(port=6543))


def test_rejects_wildcard_schema_include() -> None:
    with pytest.raises(ValidationError, match="wildcard"):
        SourceConfig(**_source(schema_include=["*"]))


def test_rejects_empty_schema_include() -> None:
    with pytest.raises(ValidationError):
        SourceConfig(**_source(schema_include=[]))


@pytest.mark.parametrize("schema", sorted(SUPABASE_INTERNAL_SCHEMAS))
def test_rejects_supabase_internal_schema_in_include(schema: str) -> None:
    with pytest.raises(ValidationError, match="platform-internal"):
        SourceConfig(**_source(schema_include=["public", schema]))


@pytest.mark.parametrize("slot_name", ["supabase_realtime", "realtime_messages_xyz", "realtime"])
def test_rejects_realtime_slot_name_collision(slot_name: str) -> None:
    with pytest.raises(ValidationError, match="Realtime"):
        SyncConfig(slot_name=slot_name)


def test_accepts_default_slot_name() -> None:
    cfg = SyncConfig()
    assert cfg.slot_name == "tishift_migration"
