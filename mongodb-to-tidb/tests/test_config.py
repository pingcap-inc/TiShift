"""Tests for config loading + env-var interpolation + SecretStr."""

from __future__ import annotations

import textwrap

import pytest

from tishift_mongodb.config import EnvVarMissingError, load_config


def test_load_minimal_config(tmp_path, monkeypatch):
    monkeypatch.setenv("TISHIFT_TARGET_PASSWORD", "secret123")
    monkeypatch.setenv("TISHIFT_SOURCE_PASS", "mongo-pass")

    cfg_path = tmp_path / "tishift-mongodb.yaml"
    cfg_path.write_text(textwrap.dedent("""
        source:
          uri: mongodb://user:${TISHIFT_SOURCE_PASS}@host:27017/db?authSource=admin
          database: myapp
        target:
          host: h
          port: 4000
          user: root
          password: ${TISHIFT_TARGET_PASSWORD}
          database: d
          tls: true
          tier: dedicated
    """))

    cfg = load_config(cfg_path)
    assert cfg.source.database == "myapp"
    assert "mongo-pass" in cfg.source.uri
    # SecretStr hides the value in repr/str
    assert cfg.target.password.get_secret_value() == "secret123"
    assert str(cfg.target.password) == "**********"


def test_env_var_missing_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("NOT_SET_VAR", raising=False)
    cfg_path = tmp_path / "tishift-mongodb.yaml"
    cfg_path.write_text(textwrap.dedent("""
        source:
          uri: mongodb://${NOT_SET_VAR}@h:27017/d
          database: d
        target:
          host: h
          port: 4000
          user: u
          password: pw
          database: d
          tier: dedicated
    """))
    with pytest.raises(EnvVarMissingError, match="NOT_SET_VAR"):
        load_config(cfg_path)


def test_invalid_uri_rejected(tmp_path):
    cfg_path = tmp_path / "tishift-mongodb.yaml"
    cfg_path.write_text(textwrap.dedent("""
        source:
          uri: http://invalid
          database: d
        target:
          host: h
          port: 4000
          user: u
          password: pw
          database: d
          tier: dedicated
    """))
    with pytest.raises(Exception):  # pydantic ValidationError
        load_config(cfg_path)


def test_invalid_staging_url_rejected(tmp_path):
    cfg_path = tmp_path / "tishift-mongodb.yaml"
    cfg_path.write_text(textwrap.dedent("""
        source:
          uri: mongodb://h/d
          database: d
        target:
          host: h
          port: 4000
          user: u
          password: pw
          database: d
          tier: dedicated
        load:
          staging:
            backend: s3
            base_url: http://not-a-storage-url/
    """))
    with pytest.raises(Exception):
        load_config(cfg_path)
