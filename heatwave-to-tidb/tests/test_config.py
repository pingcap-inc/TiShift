"""Tests for configuration loading."""

from tishift_heatwave.config import load_config


def test_load_config(sample_config_path):
    config = load_config(sample_config_path)

    assert config.source.host == "10.0.1.15"
    assert config.source.port == 3306
    assert config.source.tls is True
    assert config.source.bastion_host == "bastion.example.com"

    assert config.target.port == 4000
    assert config.target.tier == "starter"

    # Defaults for omitted sections
    assert config.output.dir == "./tishift-reports"


def test_env_var_resolution(tmp_path, monkeypatch):
    monkeypatch.setenv("TISHIFT_SOURCE_PASSWORD", "s3cret")
    config_file = tmp_path / "cfg.yaml"
    config_file.write_text(
        """\
source:
  host: 10.0.1.15
  user: admin
  password: ${TISHIFT_SOURCE_PASSWORD}
  database: testdb

target:
  host: tidb.example.com
  user: root
  database: testdb
"""
    )

    config = load_config(config_file)
    assert config.source.password == "s3cret"


def test_env_var_resolution_embedded(tmp_path, monkeypatch):
    monkeypatch.setenv("TISHIFT_REGION", "us-east-1")
    config_file = tmp_path / "cfg.yaml"
    config_file.write_text(
        """\
source:
  host: db.${TISHIFT_REGION}.example.com
  user: admin
  database: testdb

target:
  host: tidb.example.com
  user: root
  database: testdb
"""
    )

    config = load_config(config_file)
    assert config.source.host == "db.us-east-1.example.com"


def test_unset_env_var_left_as_placeholder(tmp_path):
    config_file = tmp_path / "cfg.yaml"
    config_file.write_text(
        """\
source:
  host: 10.0.1.15
  user: admin
  password: ${TISHIFT_UNSET_PASSWORD_XYZ}
  database: testdb

target:
  host: tidb.example.com
  user: root
  database: testdb
"""
    )

    config = load_config(config_file)
    assert config.source.password == "${TISHIFT_UNSET_PASSWORD_XYZ}"


def test_tier_is_normalized_and_validated(tmp_path):
    import pytest
    from pydantic import ValidationError

    base = """\
source:
  host: 10.0.1.15
  user: admin
  database: testdb

target:
  host: tidb.example.com
  user: root
  database: testdb
  tier: {tier}
"""
    config_file = tmp_path / "cfg.yaml"

    config_file.write_text(base.format(tier="Starter"))
    assert load_config(config_file).target.tier == "starter"

    config_file.write_text(base.format(tier="enterprise"))
    with pytest.raises(ValidationError, match="tier must be one of"):
        load_config(config_file)
