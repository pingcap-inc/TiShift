"""Shared test fixtures for TiShift HeatWave."""

import pytest


@pytest.fixture
def sample_config_path(tmp_path):
    """Create a temporary config file for testing."""
    config_content = """\
source:
  host: 10.0.1.15
  port: 3306
  user: admin
  password: test_pass
  database: testdb
  tls: true
  bastion_host: bastion.example.com
  bastion_user: opc

target:
  host: gateway01.us-east-1.prod.aws.tidbcloud.com
  port: 4000
  user: root
  password: target_pass
  database: testdb
  tls: true
  tier: starter
"""
    config_file = tmp_path / "tishift-heatwave.yaml"
    config_file.write_text(config_content)
    return config_file
