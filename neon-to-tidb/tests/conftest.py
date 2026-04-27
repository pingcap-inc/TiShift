"""Shared test fixtures for TiShift Neon."""

import pytest


@pytest.fixture
def sample_config_path(tmp_path):
    """Create a temporary config file for testing."""
    config_content = """\
source:
  host: ep-test-123.us-east-2.aws.neon.tech
  port: 5432
  user: test_user
  password: test_pass
  database: testdb
  sslmode: require

target:
  host: gateway01.us-east-1.prod.aws.tidbcloud.com
  port: 4000
  user: root
  password: target_pass
  database: testdb
  tls: true
  tier: starter

ai:
  provider: none
"""
    config_file = tmp_path / "tishift-neon.yaml"
    config_file.write_text(config_content)
    return config_file
