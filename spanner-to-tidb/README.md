# TiShift Spanner

TiShift Spanner is a Python toolkit for Cloud Spanner to TiDB migration workflows.

## Commands

- `tishift-spanner scan`: Assess source readiness and generate reports.
- `tishift-spanner convert`: Convert scan output to TiDB DDL.
- `tishift-spanner load`: Run initial bulk-load strategy orchestration.
- `tishift-spanner sync`: Start/stop/check CDC sync lifecycle.
- `tishift-spanner check`: Validate source/target consistency.

## Quick Start

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'

cp config/tishift-spanner.example.yaml tishift-spanner.yaml

# Scan
tishift-spanner scan --config tishift-spanner.yaml --format cli --format json

# Convert from scan report
tishift-spanner convert --scan-report ./tishift-reports/tishift-spanner-report.json --dry-run

# Load / Check / Sync
tishift-spanner load --config tishift-spanner.yaml --strategy auto
tishift-spanner check --config tishift-spanner.yaml --output cli,json
tishift-spanner sync --config tishift-spanner.yaml --status
```

## AI-Assisted Migration

For an interactive, guided migration experience, use the TiShift skill:

```
/spanner-to-tidb
```

The skill walks you through each phase — connecting to your databases, scanning the source schema, assessing compatibility, converting DDL, loading data, and validating the result. See [SKILL.md](SKILL.md) for details.

## Guides

- [Getting Started](docs/getting-started.md)
- [Scan Guide](docs/scan-guide.md)
- [Convert Guide](docs/convert-guide.md)
- [Load Guide](docs/load-guide.md)
- [Check Guide](docs/check-guide.md)
- [Sync Guide](docs/sync-guide.md)

## Test

```bash
pytest tests -q
```
