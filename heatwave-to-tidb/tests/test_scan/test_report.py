"""Tests for scan report building/rendering."""

from tests.test_scan.fake_connection import ScriptedConnection
from tests.test_scan.test_orchestrator import ALL_RESPONSES

from tishift_heatwave.core.scan.orchestrator import run_scan
from tishift_heatwave.core.scan.report import _human_bytes, build_report, render_cli, render_markdown, write_reports


def scan_result():
    return run_scan(ScriptedConnection(ALL_RESPONSES), "myapp", tier="essential", continue_replication_planned=True)


class TestHumanBytes:
    def test_bytes(self):
        assert _human_bytes(500) == "500 B"

    def test_gib(self):
        assert _human_bytes(3 * 1024**3) == "3.0 GiB"

    def test_zero(self):
        assert _human_bytes(0) == "0 B"


class TestBuildReport:
    def test_matches_scan_result(self):
        report = build_report(scan_result())
        assert report["schema"] == "myapp"
        assert report["summary"]["table_count"] == 2
        assert report["summary"]["rapid_table_count"] == 1
        assert report["summary"]["view_count"] == 2
        assert report["summary"]["updatable_view_count"] == 1
        assert report["topology"]["connected_replica_count"] == 2
        assert report["topology"]["lower_case_table_names"] == 0
        assert report["score"]["overall"] == report["score"]["overall"]  # just present
        assert 0 <= report["score"]["overall"] <= 100


class TestRenderCli:
    def test_contains_key_sections(self):
        text = render_cli(build_report(scan_result()))
        assert "HeatWave Scan Report" in text
        assert "Binlog / continue-replication readiness" in text
        assert "Readiness Score" in text
        assert "Tables without a valid index" in text  # continue_replication_planned=True in fixture


class TestRenderMarkdown:
    def test_contains_tables(self):
        text = render_markdown(build_report(scan_result()))
        assert text.startswith("# HeatWave Scan Report")
        assert "| Metric | Value |" in text
        assert "## Readiness Score" in text

    def test_no_findings_renders_none_detected(self):
        # a clean report (no blockers/warnings) should say so explicitly, not
        # render an empty table
        report = build_report(scan_result())
        report["assessment"]["blockers"] = []
        text = render_markdown(report)
        assert "None detected." in text


class TestWriteReports:
    def test_writes_only_requested_formats(self, tmp_path):
        report = build_report(scan_result())

        written = write_reports(report, tmp_path, ("json",))
        assert set(written) == {"json"}
        assert (tmp_path / "tishift-heatwave-report.json").exists()
        assert not (tmp_path / "tishift-heatwave-report.md").exists()

    def test_writes_markdown_when_requested(self, tmp_path):
        report = build_report(scan_result())
        written = write_reports(report, tmp_path, ("md",))
        assert set(written) == {"md"}
        assert (tmp_path / "tishift-heatwave-report.md").exists()

    def test_cli_only_writes_nothing(self, tmp_path):
        report = build_report(scan_result())
        written = write_reports(report, tmp_path, ("cli",))
        assert written == {}
        assert not tmp_path.exists() or list(tmp_path.iterdir()) == []
