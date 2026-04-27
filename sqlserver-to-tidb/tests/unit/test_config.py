"""Tests for config loading, env var expansion, auth modes."""

from __future__ import annotations

from pathlib import Path

import pytest

from tishift_mssql.config import load_config


class TestLoadConfig:
    def test_expands_env_vars(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SRC_PASS", "secret")
        cfg_file = tmp_path / "cfg.yaml"
        cfg_file.write_text(
            "source:\n  host: localhost\n  user: sa\n  password: ${SRC_PASS}\n"
        )
        cfg = load_config(cfg_file)
        assert cfg.source.password == "secret"

    def test_missing_file_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            load_config(Path("/does-not-exist.yaml"))

    def test_invalid_yaml_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text("- just a list\n")
        with pytest.raises(ValueError, match="YAML mapping"):
            load_config(bad)

    def test_missing_env_var_raises(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "cfg.yaml"
        cfg_file.write_text(
            "source:\n  host: localhost\n  user: sa\n  password: ${UNDEFINED_VAR_XYZ}\n"
        )
        with pytest.raises(ValueError, match="UNDEFINED_VAR_XYZ"):
            load_config(cfg_file)

    def test_default_values(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "cfg.yaml"
        cfg_file.write_text("source:\n  host: localhost\n  user: sa\n")
        cfg = load_config(cfg_file)
        assert cfg.source.port == 1433
        assert cfg.source.auth == "sql"
        assert cfg.source.encrypt is True
        assert cfg.target.port == 4000
        assert cfg.output.dir == "./tishift-reports"
        assert cfg.metrics.enabled is False

    def test_windows_auth(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "cfg.yaml"
        cfg_file.write_text(
            "source:\n  host: srv\n  user: sa\n  auth: windows\n  domain: CORP\n"
        )
        cfg = load_config(cfg_file)
        assert cfg.source.auth == "windows"
        assert cfg.source.domain == "CORP"

    def test_full_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TGT_PW", "tidb123")
        cfg_file = tmp_path / "full.yaml"
        cfg_file.write_text(
            """
source:
  host: sqlserver.example.com
  port: 1433
  instance: MSSQLSERVER
  user: sa
  password: test
  database: myapp
  auth: sql
target:
  host: tidb.example.com
  port: 4000
  user: root
  password: ${TGT_PW}
  database: myapp
  tls: true
aws:
  region: us-west-2
ai:
  provider: openai
  api_key: sk-test
output:
  dir: ./reports
  formats: [json, html]
logging:
  level: debug
metrics:
  enabled: true
  port: 9091
"""
        )
        cfg = load_config(cfg_file)
        assert cfg.source.instance == "MSSQLSERVER"
        assert cfg.target.password == "tidb123"
        assert cfg.aws.region == "us-west-2"
        assert cfg.ai.provider == "openai"
        assert cfg.output.formats == ["json", "html"]
        assert cfg.logging.level == "debug"
        assert cfg.metrics.port == 9091
