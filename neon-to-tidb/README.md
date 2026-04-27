# TiShift Neon

TiShift Neon is a Python toolkit for Neon/Postgres to TiDB migration workflows.

## Commands

- `tishift-neon scan`: Assess source readiness and generate reports.
- `tishift-neon convert`: Convert scan output to TiDB DDL and code stubs.
- `tishift-neon load`: Run initial bulk-load strategy orchestration.
- `tishift-neon sync`: Start/stop/check CDC sync lifecycle.
- `tishift-neon check`: Validate source/target consistency.

## Quick Start

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'

cp config/tishift-neon.example.yaml tishift-neon.yaml

# Scan
tishift-neon scan --config tishift-neon.yaml --format cli --format json

# Convert from scan report
tishift-neon convert --scan-report ./tishift-reports/tishift-neon-report.json --dry-run

# Load / Check / Sync
tishift-neon load --config tishift-neon.yaml --strategy auto
tishift-neon check --config tishift-neon.yaml --output cli,json
tishift-neon sync --config tishift-neon.yaml --status
```

## AI-Assisted Migration

For an interactive, guided migration experience, use the TiShift skill:

```
/neon-to-tidb
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
