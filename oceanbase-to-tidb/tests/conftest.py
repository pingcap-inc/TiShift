"""Shared fixtures for TiShift OceanBase tests."""

import pytest


@pytest.fixture
def mysql_mode_checklist():
    return {
        "ob_mode": "mysql",
        "ob_version": "4.2.1",
        "table_count": 20,
        "stored_procedure_count": 1,
        "trigger_count": 1,
        "view_count": 2,
        "has_tablegroups": True,
        "has_primary_zone": True,
        "has_locality": True,
        "has_resource_units": False,
        "has_global_indexes": False,
        "has_spatial": False,
        "composite_partition_count": 0,
        "total_data_mb": 5000,
        "largest_table_mb": 2000,
        "lob_column_count": 0,
        "cdc_not_available": True,
        "collation_mismatch": False,
    }


@pytest.fixture
def oracle_mode_checklist():
    return {
        "ob_mode": "oracle",
        "ob_version": "4.2.1",
        "table_count": 15,
        "stored_procedure_count": 3,
        "function_count": 1,
        "package_count": 1,
        "trigger_count": 2,
        "has_tablegroups": True,
        "has_primary_zone": True,
        "has_locality": False,
        "has_oracle_types": True,
        "has_object_types": False,
        "has_xmltype": False,
        "total_data_mb": 8000,
        "largest_table_mb": 3000,
        "lob_column_count": 2,
        "cdc_not_available": True,
    }


@pytest.fixture
def sample_config_dict():
    return {
        "source": {
            "host": "localhost",
            "port": 2881,
            "user": "admin",
            "tenant": "sys",
            "password": "test_pass",
            "database": "myapp",
            "mode": "auto",
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
