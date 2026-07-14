# heatwave-to-tidb

MySQL HeatWave → TiDB Cloud migration module for [TiShift](../README.md).

HeatWave is MySQL 8.0/8.4/9.x under the hood, so core compatibility with TiDB is high.
This module focuses on the HeatWave-specific surface:

- **RAPID analytics offload** (`SECONDARY_ENGINE=RAPID`) → mapped to **TiFlash replicas**
- **Lakehouse external tables** → blocker; data lives in Object Storage, must be materialized
- **AutoML / GenAI** (`ML_SCHEMA_*`, `sys.ML_*` routines) → blocker; re-host models externally
- **VECTOR columns** (MySQL 9) → TiDB Cloud `VECTOR` with index-syntax rework
- **JavaScript (MLE) stored programs** → application-code stubs
- Standard MySQL gaps (stored procedures, triggers, events, spatial, FULLTEXT, 0900 collations)

## Implementation status

`scan` and `convert` are implemented and unit-tested. `load`, `check`, and
`sync` are documented but not yet automated — each prints a pointer to its
guide (`docs/load-guide.md`, `docs/check-guide.md`, `docs/sync-guide.md`)
and exits non-zero; follow those guides manually, or use the AI skill, which
walks through the same steps interactively.

## AI skill

Open this project in an AI coding assistant and run:

```
/heatwave-to-tidb
```

The skill (`SKILL.md`) walks through Connect → Scan → Assess & Score → Convert →
Load → Validate → optional continue-replication sync, one command at a time.

See [`docs/checklist.md`](docs/checklist.md) for every compatibility rule,
DDL cleanup rule, and precheck/attention tip across all phases in one place.

## CLI toolkit

```bash
cd heatwave-to-tidb
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'

cp config/tishift-heatwave.example.yaml tishift-heatwave.yaml
# Edit with your HeatWave and TiDB credentials.
# HeatWave DB Systems are VCN-private — connect through an SSH tunnel or
# OCI Bastion session (see config comments).

# Scan and assess
tishift-heatwave scan --config tishift-heatwave.yaml --format cli --format json

# Convert schema — HeatWave-only clauses become TISHIFT-REMOVED comments
# (auditable, nothing deleted); each RAPID table gets an inline
# ALTER TABLE ... SET TIFLASH REPLICA right after its CREATE TABLE
tishift-heatwave convert --ddl-file schema.sql --tier dedicated --dry-run

# Load and check are not automated yet — both print a pointer to the
# manual runbook and exit non-zero; follow docs/load-guide.md and
# docs/check-guide.md (or the AI skill) by hand until they land.
tishift-heatwave load --config tishift-heatwave.yaml --strategy auto
tishift-heatwave check --config tishift-heatwave.yaml
```

## Layout

```
heatwave-to-tidb/
├── SKILL.md                    AI skill (interactive migration guide)
├── references/                 Type mappings, compatibility rules, load strategies, scoring
├── config/                     Example YAML configuration
├── docs/                       Getting started + per-phase guides
├── sql/                        Sample schema exercising HeatWave features
├── tishift_heatwave/           Python CLI toolkit
│   ├── core/scan/              Schema collectors, HeatWave detection, analyzers, reporters
│   ├── core/convert/           DDL transform, TiFlash emission, code stubs
│   ├── core/load/              Dumpling, ticloud import, direct, Lightning
│   ├── core/check/             Row count, column, checksum validation
│   ├── core/sync/              Continue replication via TiDB DM (binlog replication)
│   └── rules/                  Type mapping, compatibility rules, scoring
└── tests/                      Unit tests (offline, fixture-driven)
```

## Tests

```bash
pytest tests -q
```
