"""Shared test fixtures for TiShift Spanner."""

import pytest


@pytest.fixture
def sample_config_path(tmp_path):
    """Create a temporary config file for testing."""
    config_content = """\
source:
  project_id: test-project
  instance_id: test-instance
  database_id: testdb
  credentials_file: ""

target:
  host: gateway01.us-east-1.prod.aws.tidbcloud.com
  port: 4000
  user: root
  password: target_pass
  database: testdb
  tls: true
  tier: starter

gcs:
  bucket: test-bucket
  prefix: spanner-export/

ai:
  provider: none
"""
    config_file = tmp_path / "tishift-spanner.yaml"
    config_file.write_text(config_content)
    return config_file
