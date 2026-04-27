"""Tests for TiShift CockroachDB configuration."""

import pytest
import yaml

from tishift_crdb.config import (
    TiShiftCrdbConfig, SourceConfig, TargetConfig, load_config,
)
from pathlib import Path


class TestSourceConfig:
    def test_defaults(self):
        cfg = SourceConfig()
        assert cfg.host == "localhost"
        assert cfg.port == 26257  # CRDB default, not 5432
        assert cfg.sslmode == "verify-full"

    def test_dsn(self):
        cfg = SourceConfig(host="crdb.example.com", port=26257, user="root",
                           password="pass", database="myapp", sslmode="disable")
        assert "crdb.example.com:26257/myapp" in cfg.dsn
        assert "sslmode=disable" in cfg.dsn

    def test_dsn_with_cert(self):
        cfg = SourceConfig(sslrootcert="/path/to/ca.crt")
        assert "sslrootcert=/path/to/ca.crt" in cfg.dsn

    def test_env_var(self, monkeypatch):
        monkeypatch.setenv("CRDB_PASS", "secret")
        cfg = SourceConfig(password="${CRDB_PASS}")
        assert cfg.password == "secret"


class TestTargetConfig:
    def test_defaults(self):
        cfg = TargetConfig()
        assert cfg.port == 4000
        assert cfg.tier == "starter"

    def test_valid_tiers(self):
        for tier in ("starter", "essential", "dedicated", "self-hosted"):
            cfg = TargetConfig(tier=tier)
            assert cfg.tier == tier

    def test_invalid_tier(self):
        with pytest.raises(Exception):
            TargetConfig(tier="enterprise")


class TestLoadConfig:
    def test_from_yaml(self, sample_config_dict, tmp_path):
        f = tmp_path / "config.yaml"
        f.write_text(yaml.dump(sample_config_dict))
        cfg = load_config(f)
        assert cfg.source.port == 26257
        assert cfg.target.database == "myapp"

    def test_empty_yaml(self, tmp_path):
        f = tmp_path / "empty.yaml"
        f.write_text("")
        cfg = load_config(f)
        assert cfg.source.port == 26257

    def test_missing_file(self):
        with pytest.raises(FileNotFoundError):
            load_config(Path("/nonexistent.yaml"))

    def test_env_var_resolution(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MY_CRDB_PASS", "crdb_secret")
        config = {"source": {"password": "${MY_CRDB_PASS}", "database": "test"}}
        f = tmp_path / "env.yaml"
        f.write_text(yaml.dump(config))
        cfg = load_config(f)
        assert cfg.source.password == "crdb_secret"
