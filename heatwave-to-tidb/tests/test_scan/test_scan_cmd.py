"""Tests for the tishift-heatwave scan CLI command."""

import json

import pymysql
import pytest
from click.testing import CliRunner

from tests.test_scan.fake_connection import ScriptedConnection
from tests.test_scan.test_orchestrator import ALL_RESPONSES

from tishift_heatwave.cli import main


@pytest.fixture
def fake_source(monkeypatch):
    """Patch connect_source so scan runs against a scripted fake connection
    instead of a real pymysql connection."""

    def _connect_source(_config, read_only=True):
        return ScriptedConnection(ALL_RESPONSES)

    monkeypatch.setattr("tishift_heatwave.connection.connect_source", _connect_source)


def test_scan_prints_cli_summary_and_writes_json(fake_source, sample_config_path, tmp_path):
    out_dir = tmp_path / "out"
    runner = CliRunner()

    result = runner.invoke(
        main,
        ["scan", "--config", str(sample_config_path), "--format", "cli", "--format", "json",
         "--output-dir", str(out_dir)],
    )

    assert result.exit_code == 0, result.output
    assert "HeatWave Scan Report" in result.output
    assert "Readiness Score" in result.output

    report_path = out_dir / "tishift-heatwave-report.json"
    assert report_path.exists()
    report = json.loads(report_path.read_text())
    assert report["schema"] == "testdb"
    assert report["summary"]["table_count"] == 2


def test_scan_quiet_suppresses_cli_summary(fake_source, sample_config_path, tmp_path):
    out_dir = tmp_path / "out"
    runner = CliRunner()

    result = runner.invoke(
        main,
        ["scan", "--config", str(sample_config_path), "--quiet", "--output-dir", str(out_dir)],
    )

    assert result.exit_code == 0, result.output
    assert "HeatWave Scan Report" not in result.output


def test_scan_continue_replication_flag_runs_valid_index_precheck(fake_source, sample_config_path, tmp_path):
    out_dir = tmp_path / "out"
    runner = CliRunner()

    result = runner.invoke(
        main,
        ["scan", "--config", str(sample_config_path), "--continue-replication", "--format", "json",
         "--output-dir", str(out_dir)],
    )

    assert result.exit_code == 0, result.output
    report = json.loads((out_dir / "tishift-heatwave-report.json").read_text())
    assert report["continue_replication_planned"] is True
    assert report["summary"]["tables_without_valid_index_count"] == 1


def test_scan_legacy_cdc_alias_still_works(fake_source, sample_config_path, tmp_path):
    out_dir = tmp_path / "out"
    runner = CliRunner()

    result = runner.invoke(
        main,
        ["scan", "--config", str(sample_config_path), "--cdc", "--format", "json",
         "--output-dir", str(out_dir)],
    )

    assert result.exit_code == 0, result.output
    report = json.loads((out_dir / "tishift-heatwave-report.json").read_text())
    assert report["continue_replication_planned"] is True


def test_scan_database_override(fake_source, sample_config_path, tmp_path):
    out_dir = tmp_path / "out"
    runner = CliRunner()

    result = runner.invoke(
        main,
        ["scan", "--config", str(sample_config_path), "--database", "otherdb",
         "--format", "json", "--output-dir", str(out_dir)],
    )

    assert result.exit_code == 0, result.output
    report = json.loads((out_dir / "tishift-heatwave-report.json").read_text())
    assert report["schema"] == "otherdb"


def test_scan_connection_error_reported_cleanly(monkeypatch, sample_config_path, tmp_path):
    def _raise_connect(_config, read_only=True):
        raise pymysql.err.OperationalError("Can't connect to MySQL server")

    monkeypatch.setattr("tishift_heatwave.connection.connect_source", _raise_connect)

    runner = CliRunner()
    result = runner.invoke(
        main, ["scan", "--config", str(sample_config_path), "--output-dir", str(tmp_path / "out")]
    )

    assert result.exit_code != 0
    assert "Could not connect to source" in result.output
