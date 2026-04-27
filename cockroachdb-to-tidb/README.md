# CockroachDB to TiDB Migration

AI-assisted migration toolkit for moving CockroachDB databases to [TiDB Cloud](https://www.pingcap.com/tidb-cloud/).

## What It Does

TiShift CRDB scans your CockroachDB cluster, assesses TiDB compatibility, scores migration readiness, converts schema (stripping CRDB-specific extensions and mapping Postgres types to MySQL), loads data via EXPORT INTO CSV, and validates results.

CockroachDB and TiDB are both distributed SQL databases — many features have near-equivalents (scatter, CDC, TTL, placement rules), making this the most architecturally aligned migration path TiShift offers.

## Getting Started

### Prerequisites

- `cockroach sql` CLI or any Postgres client (`psql`)
- Network access to your CockroachDB cluster (default port: 26257)
- A TiDB Cloud cluster (a free [Starter](https://tidbcloud.com/) tier works)

### Run the skill

```
/cockroachdb-to-tidb
```

The skill walks you through each phase interactively. See [SKILL.md](SKILL.md) for the full guide.

## Migration Phases

```
 ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
 │  1.Scan  │───>│ 2.Assess │───>│3.Convert │───>│ 4. Load  │───>│5.Validate│
 │          │    │ & Score  │    │  Schema  │    │   Data   │    │          │
 └──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘
```

1. **Scan** — Collect schema inventory, CRDB-specific features (hash-sharded indexes, multi-region, inverted indexes, TTL), and data profile
2. **Assess & Score** — Classify as blockers/warnings, compute 0–100 readiness score (5 categories)
3. **Convert** — Strip CRDB extensions, map types (INT→BIGINT, UUID, STRING, JSONB→JSON), transpile PG→MySQL
4. **Load** — Extract data via `EXPORT INTO CSV`, load via TiDB Lightning / LOAD DATA
5. **Validate** — Compare row counts, column structures, and JSON data between source and target

## Key Type Mappings

| CockroachDB | TiDB | Why |
|---|---|---|
| `INT` / `INT8` | `BIGINT` | CRDB INT is 64-bit (not 32-bit like Postgres) |
| `SERIAL` | `BIGINT AUTO_RANDOM` | Both produce non-sequential distributed IDs |
| `UUID` | `CHAR(36)` | With `DEFAULT (UUID())` |
| `STRING` | `TEXT` | Unbounded string |
| `BYTES` | `BLOB` | Binary data |
| `JSONB` | `JSON` | Operators need rewrite (`@>` → `JSON_CONTAINS`) |

## Optional: CLI Toolkit

```bash
cd cockroachdb-to-tidb
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'

cp config/tishift-crdb.example.yaml tishift-crdb.yaml
# Edit with your credentials

tishift-crdb scan --config tishift-crdb.yaml --format cli --format json
tishift-crdb convert --scan-report ./tishift-reports/report.json --dry-run
tishift-crdb load --config tishift-crdb.yaml --strategy auto
tishift-crdb check --config tishift-crdb.yaml
```

## Reference Documentation

- [Compatibility Rules](references/compatibility-rules.md) — 7 blockers, 14 warnings
- [Scoring Engine](references/scoring.md) — 5-category model (25/25/15/20/15)
- [Type Mapping](references/type-mapping.md) — CockroachDB → TiDB type conversion
- [Function Mapping](references/function-mapping.md) — PG/CRDB → MySQL translations + JSONB operator rewrites

## Guides

- [Getting Started](docs/getting-started.md)
- [Scan Guide](docs/scan-guide.md)
- [Convert Guide](docs/convert-guide.md)
- [Load Guide](docs/load-guide.md)
- [Check Guide](docs/check-guide.md)
- [Sync Guide](docs/sync-guide.md)

## License

[Apache 2.0](../LICENSE)
