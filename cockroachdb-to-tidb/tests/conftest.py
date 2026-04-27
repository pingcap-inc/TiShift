"""Shared fixtures for TiShift CockroachDB tests."""

import pytest


@pytest.fixture
def sample_checklist():
    """A representative checklist for testing the scoring engine."""
    return {
        "table_count": 20,
        "stored_procedure_count": 0,
        "trigger_count": 0,
        "view_count": 3,
        "sequence_count": 1,
        "foreign_key_count": 4,
        "enum_type_count": 1,
        "array_column_count": 2,
        "jsonb_column_count": 3,
        "uuid_pk_count": 4,
        "serial_column_count": 1,
        "hash_sharded_index_count": 1,
        "inverted_index_count": 1,
        "has_multi_region": False,
        "has_row_level_ttl": True,
        "has_spatial_geography": False,
        "has_interleaved_tables": False,
        "has_returning_clause": False,
        "has_writable_ctes": False,
        "has_full_text_search": False,
        "has_jsonb_operators": True,
        "has_as_of_system_time": False,
        "total_data_mb": 8000,
        "largest_table_mb": 3000,
        "crdb_version": "24.1",
    }


@pytest.fixture
def sample_config_dict():
    """A minimal config dictionary for testing."""
    return {
        "source": {
            "host": "localhost",
            "port": 26257,
            "user": "root",
            "password": "test_pass",
            "database": "myapp",
            "sslmode": "disable",
        },
        "target": {
            "host": "localhost",
            "port": 4000,
            "user": "root",
            "password": "test_pass",
            "database": "myapp",
            "tls": False,
            "tier": "starter",
        },
    }
