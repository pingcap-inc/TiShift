# Oracle to TiDB Migration

AI-assisted migration toolkit for moving Oracle databases to [TiDB Cloud](https://www.pingcap.com/tidb-cloud/).

## What It Does

TiShift Oracle scans your Oracle database, assesses TiDB compatibility, scores migration readiness, converts schema and PL/SQL to TiDB-compatible DDL and application code stubs, loads data, and validates results.

## Getting Started

### Prerequisites

- An AI coding assistant that supports skills / slash commands
- Network access to your Oracle database (`sqlplus` or Oracle SQLcl installed)
- A TiDB Cloud cluster (a free [Starter](https://tidbcloud.com/) tier works)

### Run the skill

```
/oracle-to-tidb
```

The skill walks you through each phase — connecting to your databases, scanning the source schema, assessing compatibility, converting DDL, loading data, and validating the result. Follow the prompts; no additional setup is required.

See [SKILL.md](SKILL.md) for the full interactive migration guide.

## Migration Phases

```
 ┌──────────┐    ┌──────────┐    ┌───────���──┐    ┌──────────┐    ┌──────────┐
 │  1.Scan  │───>│ 2.Assess │───>│3.Convert │───>│ 4. Load  │───>│5.Validate│
 │          │    │ & Score  │    │  Schema  │    │   Data   │    │          │
 └──────────┘    └─────���────┘    └──────────┘    └──────────��    └──────────┘
```

1. **Scan** — Collect schema inventory, data profile, PL/SQL complexity, and feature usage
2. **Assess & Score** — Identify blockers/warnings, compute 0–100 readiness score (5 categories, Oracle-tuned weights)
3. **Convert** — Generate TiDB DDL, rewrite Oracle SQL (CONNECT BY → CTE, ROWNUM → LIMIT), produce code stubs for PL/SQL
4. **Load** — Transfer data via CSV extraction (SQLcl) → TiDB Lightning / LOAD DATA / DMS
5. **Validate** — Compare row counts, column structures, NULL semantics, and sequence state

## TiDB Cloud Tier Awareness

| Feature | Starter | Essential | Dedicated |
|---|---|---|---|
| Import method | `ticloud serverless import start` | Direct / DMS | Direct / DMS / Lightning |
| CDC sync | Not available (cutover only) | Changefeeds | Changefeeds / DM |
| Storage | 25 GiB free | Auto-scaled | Configurable |

## Optional: CLI Toolkit

```bash
cd oracle-to-tidb
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'

cp config/tishift-oracle.example.yaml tishift-oracle.yaml
# Edit tishift-oracle.yaml with your source and target credentials

# Scan and assess
tishift-oracle scan --config tishift-oracle.yaml --format cli --format json

# Convert schema
tishift-oracle convert --scan-report ./tishift-reports/report.json --dry-run

# Load data
tishift-oracle load --config tishift-oracle.yaml --strategy auto

# Validate
tishift-oracle check --config tishift-oracle.yaml
```

## Reference Documentation

- [Compatibility Rules](references/compatibility-rules.md) — 12 blockers, 14 warnings
- [Scoring Engine](references/scoring.md) — 5-category weighted model (20/30/20/20/10)
- [Type Mapping](references/type-mapping.md) — Oracle → TiDB type conversion table
- [Function Mapping](references/function-mapping.md) — Oracle → MySQL function translations

## Guides

- [Getting Started](docs/getting-started.md)
- [Scan Guide](docs/scan-guide.md)
- [Convert Guide](docs/convert-guide.md)
- [Load Guide](docs/load-guide.md)
- [Check Guide](docs/check-guide.md)
- [Sync Guide](docs/sync-guide.md)

## License

[Apache 2.0](../LICENSE)
