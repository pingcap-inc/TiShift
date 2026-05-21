"""Tests for config loading + env-var interpolation."""

from __future__ import annotations

import os
import textwrap

from tishift_firestore.config import load_config


def test_load_minimal_config(tmp_path, monkeypatch):
    monkeypatch.setenv("TISHIFT_TARGET_PASSWORD", "secret123")

    cfg_path = tmp_path / "tishift-firestore.yaml"
    cfg_path.write_text(textwrap.dedent("""
        source:
          project_id: p
          database_id: "(default)"
          staging:
            gcs_bucket: b
            gcs_prefix: x/
            region: us-central1
        target:
          host: h
          port: 4000
          user: root
          password: ${TISHIFT_TARGET_PASSWORD}
          database: d
          tls: true
          tier: byoc
    """))

    cfg = load_config(cfg_path)
    assert cfg.source.project_id == "p"
    # SecretStr: the actual secret value is hidden behind .get_secret_value()
    assert cfg.target.password.get_secret_value() == "secret123"
    assert str(cfg.target.password) == "**********"  # repr hides the value
    assert cfg.target.tier == "byoc"


def test_env_var_missing_raises(tmp_path, monkeypatch):
    """Strict-by-default: a missing env var must raise, not silently become empty.

    Silent empty-string substitution is a footgun — an unset
    TISHIFT_TARGET_PASSWORD would produce an empty password and attempt to
    connect unauthenticated. Loud failure at config load is safer.
    """
    import pytest
    from tishift_firestore.config import EnvVarMissingError

    monkeypatch.delenv("NOT_SET_VAR", raising=False)

    cfg_path = tmp_path / "tishift-firestore.yaml"
    cfg_path.write_text(textwrap.dedent("""
        source:
          project_id: ${NOT_SET_VAR}p
          database_id: "(default)"
          staging:
            gcs_bucket: b
            gcs_prefix: x/
            region: us-central1
        target:
          host: h
          port: 4000
          user: u
          password: pw
          database: d
          tier: byoc
    """))

    with pytest.raises(EnvVarMissingError, match="NOT_SET_VAR"):
        load_config(cfg_path)


def test_env_var_present_substitutes_correctly(tmp_path, monkeypatch):
    monkeypatch.setenv("MY_PREFIX", "alpha-")

    cfg_path = tmp_path / "tishift-firestore.yaml"
    cfg_path.write_text(textwrap.dedent("""
        source:
          project_id: ${MY_PREFIX}prod
          database_id: "(default)"
          staging:
            gcs_bucket: b
            gcs_prefix: x/
            region: us-central1
        target:
          host: h
          port: 4000
          user: u
          password: pw
          database: d
          tier: byoc
    """))

    cfg = load_config(cfg_path)
    assert cfg.source.project_id == "alpha-prod"


def test_scan_defaults(tmp_path):
    cfg_path = tmp_path / "tishift-firestore.yaml"
    cfg_path.write_text(textwrap.dedent("""
        source:
          project_id: p
          database_id: "(default)"
          staging:
            gcs_bucket: b
            gcs_prefix: x/
            region: us-central1
        target:
          host: h
          port: 4000
          user: u
          password: pw
          database: d
          tier: byoc
    """))

    cfg = load_config(cfg_path)
    assert cfg.scan.sample_size_per_collection == 200
    assert cfg.scan.full_scan_threshold_docs == 5000
