"""Tests for TiShift OceanBase configuration."""

import pytest
import yaml
from pathlib import Path

from tishift_ob.config import TiShiftObConfig, SourceConfig, TargetConfig, load_config
from tishift_ob.mode import OBEnvironment


class TestSourceConfig:
    def test_defaults(self):
        cfg = SourceConfig()
        assert cfg.port == 2881  # OBProxy, not 3306
        assert cfg.mode == "auto"

    def test_effective_user_with_tenant(self):
        cfg = SourceConfig(user="admin", tenant="sys")
        assert cfg.effective_user == "admin@sys"

    def test_effective_user_no_tenant(self):
        cfg = SourceConfig(user="admin", tenant="")
        assert cfg.effective_user == "admin"

    def test_env_var(self, monkeypatch):
        monkeypatch.setenv("OB_PASS", "secret")
        cfg = SourceConfig(password="${OB_PASS}")
        assert cfg.password == "secret"

    def test_valid_modes(self):
        for m in ("auto", "mysql", "oracle"):
            cfg = SourceConfig(mode=m)
            assert cfg.mode == m


class TestTargetConfig:
    def test_defaults(self):
        cfg = TargetConfig()
        assert cfg.port == 4000
        assert cfg.tier == "starter"

    def test_invalid_tier(self):
        with pytest.raises(Exception):
            TargetConfig(tier="enterprise")


class TestOBEnvironment:
    def test_mysql_mode(self):
        env = OBEnvironment(mode="mysql", version="4.2.1", tenant="sys")
        assert env.is_mysql_mode
        assert not env.is_oracle_mode
        assert env.sqlglot_dialect == "mysql"
        assert env.major_version == 4.2

    def test_oracle_mode(self):
        env = OBEnvironment(mode="oracle", version="4.2.1", tenant="prod")
        assert env.is_oracle_mode
        assert env.sqlglot_dialect == "oracle"

    def test_version_parsing(self):
        env = OBEnvironment(mode="mysql", version="3.2.4", tenant="sys")
        assert env.major_version == 3.2


class TestLoadConfig:
    def test_from_yaml(self, sample_config_dict, tmp_path):
        f = tmp_path / "config.yaml"
        f.write_text(yaml.dump(sample_config_dict))
        cfg = load_config(f)
        assert cfg.source.port == 2881
        assert cfg.source.tenant == "sys"

    def test_empty_yaml(self, tmp_path):
        f = tmp_path / "empty.yaml"
        f.write_text("")
        cfg = load_config(f)
        assert cfg.source.port == 2881

    def test_missing(self):
        with pytest.raises(FileNotFoundError):
            load_config(Path("/nonexistent.yaml"))
