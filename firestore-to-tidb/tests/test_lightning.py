"""Tests for Lightning config emission — specifically that the password is NOT inlined."""

from __future__ import annotations

import os
import stat

import pytest

from tishift_firestore.config import (
    DataflowConfig,
    LightningConfig,
    LoadConfig,
    SourceConfig,
    StagingConfig,
    TargetConfig,
    TiShiftConfig,
)
from tishift_firestore.core.load.dataflow_runner import JobState, LoadState
from tishift_firestore.core.load.lightning import (
    _PASSWORD_PLACEHOLDER,
    build_lightning_config,
    run_lightning,
)


def _cfg(**overrides) -> TiShiftConfig:
    source = SourceConfig(
        project_id="p", database_id="(default)",
        staging=StagingConfig(gcs_bucket="b", gcs_prefix="x/", region="us-central1"),
    )
    target = TargetConfig(
        host="h", port=4000, user="root",
        password="SUPER_SECRET_PASSWORD",  # type: ignore[arg-type]
        database="d", tls=True, tier="byoc",
    )
    return TiShiftConfig(
        source=source, target=target,
        load=LoadConfig(
            strategy="dataflow-lightning",
            dataflow=DataflowConfig(),
            lightning=LightningConfig(backend="local", sorted_kv_dir="/data/lightning"),
        ),
    )


def _state() -> LoadState:
    return LoadState(
        load_id="test",
        read_time="2026-05-15T00:00:00Z",
        jobs={"users": JobState(
            collection="users", status="complete",
            job_id="j", gcs_path="gs://b/x/users/part",
        )},
    )


def test_password_not_inlined(tmp_path):
    cfg = _cfg()
    path = build_lightning_config(cfg, state=_state(), output_path=tmp_path / "lightning.toml")
    contents = path.read_text()
    assert "SUPER_SECRET_PASSWORD" not in contents
    assert _PASSWORD_PLACEHOLDER in contents


def test_lightning_toml_is_mode_600(tmp_path):
    cfg = _cfg()
    path = build_lightning_config(cfg, state=_state(), output_path=tmp_path / "lightning.toml")
    mode = path.stat().st_mode & 0o777
    assert mode == stat.S_IRUSR | stat.S_IWUSR


def test_run_lightning_requires_password_env_or_arg(monkeypatch, tmp_path):
    monkeypatch.delenv("TIDB_LIGHTNING_TIDB_PASSWORD", raising=False)
    config = tmp_path / "lightning.toml"
    config.write_text("[mydumper]\n")
    with pytest.raises(RuntimeError, match="TIDB_LIGHTNING_TIDB_PASSWORD"):
        run_lightning(config)


def test_run_lightning_does_not_log_password(monkeypatch, tmp_path, caplog):
    monkeypatch.setenv("TIDB_LIGHTNING_TIDB_PASSWORD", "SUPER_SECRET_PASSWORD")
    config = tmp_path / "lightning.toml"
    config.write_text("[mydumper]\n")

    # Stub subprocess.run so we don't try to actually invoke tidb-lightning.
    import subprocess as sp
    monkeypatch.setattr(sp, "run", lambda *a, **kw: type("R", (), {"returncode": 0})())

    with caplog.at_level("INFO"):
        rc = run_lightning(config)
    assert rc == 0
    assert "SUPER_SECRET_PASSWORD" not in caplog.text


def test_no_completed_jobs_raises(tmp_path):
    cfg = _cfg()
    empty_state = LoadState(load_id="t", read_time="2026-05-15T00:00:00Z", jobs={})
    with pytest.raises(RuntimeError, match="No completed"):
        build_lightning_config(cfg, state=empty_state, output_path=tmp_path / "x.toml")
