# TiShift

AI-assisted database migration toolkit for [TiDB Cloud](https://www.pingcap.com/tidb-cloud/).

TiShift automates the heavy lifting of migrating from legacy databases to TiDB Cloud — scanning source schemas, assessing compatibility, converting DDL, loading data, and validating results.

## Supported Migration Paths

| Source | Target | Status |
|---|---|---|
| **SQL Server / MSSQL** | TiDB Cloud (Starter, Essential, Dedicated) | Active |
| **Aurora MySQL** | TiDB Cloud (Starter, Essential, Dedicated) | Active |

## How It Works

TiShift follows a phased migration workflow:

```
 ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
 │  1.Scan  │───▶│ 2.Assess │───▶│3.Convert │───▶│ 4. Load  │───▶│5.Validate│
 │          │    │ & Score  │    │  Schema  │    │   Data   │    │          │
 └──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘
```

1. **Scan** — Collect schema inventory, data profile, and feature usage from the source database
2. **Assess & Score** — Identify blockers, warnings, and compute a 0-100 readiness score with per-category breakdowns
3. **Convert** — Generate TiDB-compatible DDL, rewrite queries, and produce code stubs for stored procedures/triggers
4. **Load** — Transfer data using the optimal strategy for your tier (ticloud import, direct load, DMS, or Lightning)
5. **Validate** — Compare row counts, column structures, and data integrity between source and target

## Getting Started

TiShift ships as a set of AI coding assistant skills that guide you interactively through every migration phase. Each skill connects to your source and target databases, runs the scan, scores readiness, converts schemas, loads data, and validates results — step by step.

### Prerequisites

- An AI coding assistant that supports skills / slash commands
- Network access to your source database (SQL Server or Aurora MySQL)
- A TiDB Cloud cluster (a free [Starter](https://tidbcloud.com/) tier works)

### 1. Clone and open the project

```bash
git clone https://github.com/pingcap-inc/TiShift.git
cd TiShift
# Open the project in your AI coding assistant
```

### 2. Run the skill for your source database

#### Aurora MySQL to TiDB Cloud

```
/aurora-to-tidb
```

#### SQL Server to TiDB Cloud

```
/sqlserver-to-tidb
```

The skill will walk you through each phase — connecting to your databases, scanning the source schema, assessing compatibility, converting DDL, loading data, and validating the result. Follow the prompts; no additional setup is required.

## TiDB Cloud Tier Awareness

TiShift is Cloud-first and defaults to **TiDB Cloud Starter** (free tier). It automatically adjusts recommendations based on your target tier:

| Feature | Starter | Essential | Dedicated |
|---|---|---|---|
| Import method | `ticloud serverless import start` | Direct / DMS | Direct / DMS / Lightning |
| CDC sync | Not available (cutover only) | Changefeeds | Changefeeds / DM |
| Storage | 25 GiB free | Auto-scaled | Configurable |
| Cost | Free to start | ~$20/day | From $1,376/mo |

## Optional: CLI Toolkit

For environments where AI-assisted migration is not available, TiShift also provides deterministic Python CLI scripts that cover the same workflow.

### SQL Server to TiDB Cloud

```bash
cd sqlserver-to-tidb
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'

cp config/tishift-mssql.example.yaml tishift-mssql.yaml
# Edit tishift-mssql.yaml with your source and target credentials

# Scan and assess
tishift-mssql scan --config tishift-mssql.yaml --format cli --format json --cost

# Convert schema
tishift-mssql convert --scan-report ./tishift-reports/tishift-mssql-report.json --dry-run

# Load data
tishift-mssql load --config tishift-mssql.yaml --strategy auto

# Validate
tishift-mssql check --config tishift-mssql.yaml
```

### Aurora MySQL to TiDB Cloud

```bash
cd aurora-to-tidb
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'

# Scan and assess
python -m tishift.cli scan --config tishift.yaml

# Convert schema
python -m tishift.cli convert --config tishift.yaml --scan-report ./tishift-reports/tishift-report.json

# Load and validate
python -m tishift.cli load --config tishift.yaml --scan-report ./tishift-reports/tishift-report.json
python -m tishift.cli check --config tishift.yaml --schema mydb
```

### Configuration

The CLI uses YAML config files with environment variable support for credentials:

```yaml
source:
  host: sqlserver.example.com
  user: sa
  password: ${TISHIFT_SOURCE_PASSWORD}
  database: myapp

target:
  host: gateway01.us-east-1.prod.aws.tidbcloud.com
  port: 4000
  user: root
  password: ${TISHIFT_TARGET_PASSWORD}
  database: myapp
  tls: true
  tier: starter    # starter | essential | dedicated | self-hosted
```

See `config/tishift-mssql.example.yaml` for the full configuration reference.

### Tests

```bash
# SQL Server toolkit
cd sqlserver-to-tidb && pytest tests -q

# Aurora toolkit
cd aurora-to-tidb && pytest tests -q
```

## Project Structure

```
TiShift/
├── sqlserver-to-tidb/          SQL Server → TiDB Cloud migration
│   ├── SKILL.md                AI skill (interactive migration guide)
│   ├── references/             Type mappings, compatibility rules, scoring
│   ├── tishift_mssql/          Python CLI toolkit
│   │   ├── scan/               Schema collectors, analyzers, reporters
│   │   ├── convert/            DDL generation, query rewriting, code stubs
│   │   ├── load/               Direct, DMS, Lightning, ticloud import
│   │   ├── check/              Row count, column, checksum validation
│   │   ├── sync/               CDC via DM, DMS, Changefeeds
│   │   └── rules/              Type mapping, compatibility, T-SQL patterns
│   └── tests/                  Unit and integration tests
│
├── aurora-to-tidb/             Aurora MySQL → TiDB Cloud migration
│   ├── SKILL.md                AI skill (interactive migration guide)
│   ├── references/             Compatibility rules, load strategies, scoring
│   ├── tishift/                Python CLI toolkit
│   │   ├── scan/               Schema collectors, analyzers, reporters
│   │   ├── convert/            DDL generation, query rewriting, code stubs
│   │   ├── load/               Direct, DMS, Cloud Import, Lightning
│   │   ├── check/              Row count, column, checksum validation
│   │   ├── sync/               CDC via DM, DMS, Changefeeds
│   │   └── rules/              Compatibility rules, type mapping
│   └── tests/                  Unit and integration tests
│
└── LICENSE                     MIT
```

## License

[MIT](LICENSE)
