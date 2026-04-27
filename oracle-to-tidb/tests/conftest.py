"""Shared fixtures for TiShift Oracle tests."""

import pytest


@pytest.fixture
def sample_checklist():
    """A representative checklist for testing the scoring engine."""
    return {
        "table_count": 15,
        "stored_procedure_count": 3,
        "function_count": 1,
        "package_count": 1,
        "package_body_count": 1,
        "type_count": 0,
        "trigger_count": 2,
        "view_count": 4,
        "sequence_count": 3,
        "synonym_count": 1,
        "dblink_count": 0,
        "mview_count": 1,
        "foreign_key_count": 5,
        "partition_count": 1,
        "has_xmltype_columns": False,
        "has_sdo_geometry": False,
        "has_long_columns": False,
        "has_bfile_columns": False,
        "lob_column_count": 2,
        "has_connect_by": True,
        "has_autonomous_transactions": False,
        "has_bulk_collect": False,
        "has_pipelined_functions": False,
        "has_dbms_packages": True,
        "has_utl_packages": False,
        "has_dynamic_sql": False,
        "has_rownum_usage": True,
        "total_data_mb": 5000,
        "largest_table_mb": 2000,
        "oracle_version": "19.0.0.0.0",
        "nls_characterset": "AL32UTF8",
        "supplemental_logging_min": "NO",
        "has_composite_partitions": False,
        "has_global_temp_tables": False,
        "has_object_types": False,
    }


@pytest.fixture
def sample_config_dict():
    """A minimal config dictionary for testing."""
    return {
        "source": {
            "host": "localhost",
            "port": 1521,
            "service_name": "ORCL",
            "user": "test_user",
            "password": "test_pass",
            "schema": "HR",
            "mode": "thin",
        },
        "target": {
            "host": "localhost",
            "port": 4000,
            "user": "root",
            "password": "test_pass",
            "database": "hr",
            "tls": False,
            "tier": "starter",
        },
    }
