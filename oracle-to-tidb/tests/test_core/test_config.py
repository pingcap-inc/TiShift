"""Tests for TiShift Oracle configuration."""

import os
import tempfile
from pathlib import Path

import pytest
import yaml

from tishift_oracle.config import (
    TiShiftOracleConfig,
    SourceConfig,
    TargetConfig,
    load_config,
)


class TestSourceConfig:
    def test_defaults(self):
        cfg = SourceConfig()
        assert cfg.host == "localhost"
        assert cfg.port == 1521
        assert cfg.mode == "thin"

    def test_explicit_values(self):
        cfg = SourceConfig(host="oracle.example.com", port=1522, service_name="PROD", mode="thick")
        assert cfg.host == "oracle.example.com"
        assert cfg.port == 1522
        assert cfg.service_name == "PROD"
        assert cfg.mode == "thick"

    def test_invalid_mode(self):
        with pytest.raises(Exception):
            SourceConfig(mode="invalid")

    def test_env_var_resolution(self, monkeypatch):
        monkeypatch.setenv("TEST_ORA_PASS", "secret123")
        cfg = SourceConfig(password="${TEST_ORA_PASS}")
        assert cfg.password == "secret123"

    def test_env_var_missing(self, monkeypatch):
        monkeypatch.delenv("NONEXISTENT_VAR", raising=False)
        cfg = SourceConfig(password="${NONEXISTENT_VAR}")
        assert cfg.password == ""

    def test_plain_password_unchanged(self):
        cfg = SourceConfig(password="mypassword")
        assert cfg.password == "mypassword"


class TestTargetConfig:
    def test_defaults(self):
        cfg = TargetConfig()
        assert cfg.host == "localhost"
        assert cfg.port == 4000
        assert cfg.tls is True
        assert cfg.tier == "starter"

    def test_valid_tiers(self):
        for tier in ("starter", "essential", "dedicated", "self-hosted"):
            cfg = TargetConfig(tier=tier)
            assert cfg.tier == tier

    def test_invalid_tier(self):
        with pytest.raises(Exception):
            TargetConfig(tier="enterprise")

    def test_env_var_resolution(self, monkeypatch):
        monkeypatch.setenv("TEST_TIDB_PASS", "tidb_secret")
        cfg = TargetConfig(password="${TEST_TIDB_PASS}")
        assert cfg.password == "tidb_secret"


class TestTiShiftOracleConfig:
    def test_from_dict(self, sample_config_dict):
        cfg = TiShiftOracleConfig.model_validate(sample_config_dict)
        assert cfg.source.host == "localhost"
        assert cfg.source.port == 1521
        assert cfg.source.service_name == "ORCL"
        assert cfg.target.tier == "starter"

    def test_defaults(self):
        cfg = TiShiftOracleConfig()
        assert cfg.ai.provider == "none"
        assert cfg.logging.level == "info"
        assert cfg.metrics.enabled is False
        assert cfg.metrics.port == 9090

    def test_output_formats(self):
        cfg = TiShiftOracleConfig()
        assert "cli" in cfg.output.formats
        assert "json" in cfg.output.formats


class TestLoadConfig:
    def test_load_from_yaml(self, sample_config_dict, tmp_path):
        config_file = tmp_path / "test-config.yaml"
        config_file.write_text(yaml.dump(sample_config_dict))

        cfg = load_config(config_file)
        assert cfg.source.host == "localhost"
        assert cfg.source.service_name == "ORCL"
        assert cfg.target.database == "hr"

    def test_load_empty_yaml(self, tmp_path):
        config_file = tmp_path / "empty.yaml"
        config_file.write_text("")

        cfg = load_config(config_file)
        assert cfg.source.host == "localhost"  # defaults apply

    def test_load_missing_file(self):
        with pytest.raises(FileNotFoundError):
            load_config(Path("/nonexistent/config.yaml"))

    def test_load_with_env_vars(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MY_ORA_PASS", "oracle_secret")
        config = {
            "source": {
                "host": "db.example.com",
                "password": "${MY_ORA_PASS}",
                "service_name": "ORCL",
            }
        }
        config_file = tmp_path / "env-config.yaml"
        config_file.write_text(yaml.dump(config))

        cfg = load_config(config_file)
        assert cfg.source.password == "oracle_secret"
