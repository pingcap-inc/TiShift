"""Tests for the tishift-heatwave convert CLI command."""

import json

from click.testing import CliRunner

from tishift_heatwave.cli import main

DDL = (
    "CREATE TABLE orders (id BIGINT PRIMARY KEY) "
    "ENGINE=InnoDB SECONDARY_ENGINE=RAPID CLUSTERING BY (id);\n"
)


def test_convert_writes_outputs(tmp_path):
    ddl_file = tmp_path / "schema.sql"
    ddl_file.write_text(DDL)
    out_dir = tmp_path / "out"

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["convert", "--ddl-file", str(ddl_file), "--tier", "dedicated", "--output-dir", str(out_dir)],
    )

    assert result.exit_code == 0, result.output
    converted = (out_dir / "converted-schema.sql").read_text()
    assert "TISHIFT-REMOVED [HW-DDL-1]" in converted
    assert "ALTER TABLE orders SET TIFLASH REPLICA 2;" in converted

    report = json.loads((out_dir / "ddl-cleanup-report.json").read_text())
    assert report["summary"]["HW-DDL-1"]["count"] == 1
    assert report["summary"]["HW-DDL-3"]["count"] == 1
    assert report["rapid_tables"] == ["orders"]

    md = (out_dir / "ddl-cleanup-report.md").read_text()
    assert "Manual review" in md
    assert "1 finding(s) need manual review" in result.output

    # Zero-hit rules are omitted from the markdown table and CLI summary
    # (HW-DDL-2 and HW-DDL-4 have no hits in DDL); JSON keeps every rule.
    assert "| HW-DDL-1 |" in md
    assert "HW-DDL-2" not in md
    assert "HW-DDL-4" not in md
    assert "HW-DDL-2" not in result.output
    assert report["summary"]["HW-DDL-2"]["count"] == 0


def test_convert_with_no_hits_shows_all_rules(tmp_path):
    ddl_file = tmp_path / "schema.sql"
    ddl_file.write_text("CREATE TABLE plain (id BIGINT PRIMARY KEY) ENGINE=InnoDB;\n")
    out_dir = tmp_path / "out"

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["convert", "--ddl-file", str(ddl_file), "--tier", "dedicated", "--output-dir", str(out_dir)],
    )

    assert result.exit_code == 0, result.output
    md = (out_dir / "ddl-cleanup-report.md").read_text()
    # Nothing matched — the whole rule set is shown with 0 hits, in both outputs
    for rule_id in ("HW-DDL-1", "HW-DDL-2", "HW-DDL-3", "HW-DDL-4"):
        assert f"| {rule_id} |" in md
        assert f"{rule_id}: 0 hit(s)" in result.output


def test_convert_dry_run_writes_nothing(tmp_path):
    ddl_file = tmp_path / "schema.sql"
    ddl_file.write_text(DDL)
    out_dir = tmp_path / "out"

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["convert", "--ddl-file", str(ddl_file), "--tier", "dedicated",
         "--output-dir", str(out_dir), "--dry-run"],
    )

    assert result.exit_code == 0, result.output
    assert "+ALTER TABLE orders SET TIFLASH REPLICA 2;" in result.output
    assert not out_dir.exists()


def test_convert_requires_ddl_file():
    runner = CliRunner()
    result = runner.invoke(main, ["convert"])
    assert result.exit_code != 0
    assert "--ddl-file is required" in result.output


def test_convert_tier_defaults_from_config(tmp_path):
    ddl_file = tmp_path / "schema.sql"
    ddl_file.write_text(DDL)
    out_dir = tmp_path / "out"
    config_file = tmp_path / "tishift-heatwave.yaml"
    config_file.write_text(
        """\
source:
  host: 10.0.1.15
  user: admin
  database: testdb

target:
  host: tidb.example.com
  user: root
  database: testdb
  tier: dedicated
"""
    )

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "convert",
            "--ddl-file", str(ddl_file),
            "--config", str(config_file),
            "--output-dir", str(out_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    report = json.loads((out_dir / "ddl-cleanup-report.json").read_text())
    assert report["tier"] == "dedicated"


def test_convert_tier_flag_overrides_config(tmp_path):
    ddl_file = tmp_path / "schema.sql"
    ddl_file.write_text(DDL)
    out_dir = tmp_path / "out"
    config_file = tmp_path / "tishift-heatwave.yaml"
    config_file.write_text(
        """\
source:
  host: 10.0.1.15
  user: admin
  database: testdb

target:
  host: tidb.example.com
  user: root
  database: testdb
  tier: dedicated
"""
    )

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "convert",
            "--ddl-file", str(ddl_file),
            "--config", str(config_file),
            "--tier", "essential",
            "--output-dir", str(out_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    report = json.loads((out_dir / "ddl-cleanup-report.json").read_text())
    assert report["tier"] == "essential"


def test_convert_without_tier_or_config_fails(tmp_path, monkeypatch):
    ddl_file = tmp_path / "schema.sql"
    ddl_file.write_text(DDL)
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(main, ["convert", "--ddl-file", str(ddl_file)])

    assert result.exit_code != 0
    assert "Config file not found" in result.output
