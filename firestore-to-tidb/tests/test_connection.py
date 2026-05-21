"""Tests for the TLS-posture logic in connection._build_tidb_ssl_args."""

from __future__ import annotations

import ssl as ssl_mod

import pytest

from tishift_firestore.config import TargetConfig
from tishift_firestore.connection import (
    TLSConfigurationError,
    _build_tidb_ssl_args,
)


def _target(**overrides) -> TargetConfig:
    base = {
        "host": "h",
        "port": 4000,
        "user": "u",
        "password": "pw",
        "database": "d",
        "tls": True,
        "tls_ca": "",
        "tls_insecure_skip_verify": False,
        "tier": "byoc",
    }
    base.update(overrides)
    return TargetConfig(**base)  # type: ignore[arg-type]


def test_tls_disabled_returns_empty_ssl_args():
    args = _build_tidb_ssl_args(_target(tls=False))
    assert args == {}


def test_tls_default_uses_system_trust_with_verify():
    args = _build_tidb_ssl_args(_target(tls=True))
    ctx = args["ssl"]
    assert isinstance(ctx, ssl_mod.SSLContext)
    assert ctx.check_hostname is True
    assert ctx.verify_mode == ssl_mod.CERT_REQUIRED


def test_tls_with_ca_pins_to_bundle(tmp_path):
    """Verify that pointing tls_ca at a valid PEM produces a CERT_REQUIRED context."""
    # Find any valid system CA bundle on this host to use as fixture data.
    candidate_paths = ssl_mod.get_default_verify_paths()
    src = candidate_paths.cafile or candidate_paths.openssl_cafile
    if not src or not __import__("os").path.exists(src):
        import pytest
        pytest.skip("no system CA bundle available to use as test fixture")

    ca_path = tmp_path / "ca.pem"
    ca_path.write_text(open(src).read())

    args = _build_tidb_ssl_args(_target(tls=True, tls_ca=str(ca_path)))
    ctx = args["ssl"]
    assert isinstance(ctx, ssl_mod.SSLContext)
    assert ctx.check_hostname is True
    assert ctx.verify_mode == ssl_mod.CERT_REQUIRED


def test_tls_with_ca_path_missing_raises():
    with pytest.raises(TLSConfigurationError):
        _build_tidb_ssl_args(_target(tls=True, tls_ca="/nonexistent/path/ca.pem"))


def test_tls_insecure_skip_verify_disables_validation():
    args = _build_tidb_ssl_args(_target(tls=True, tls_insecure_skip_verify=True))
    ctx = args["ssl"]
    assert isinstance(ctx, ssl_mod.SSLContext)
    assert ctx.check_hostname is False
    assert ctx.verify_mode == ssl_mod.CERT_NONE


def test_insecure_skip_verify_only_active_when_tls_true():
    # tls=False short-circuits before insecure flag is examined.
    args = _build_tidb_ssl_args(_target(tls=False, tls_insecure_skip_verify=True))
    assert args == {}
