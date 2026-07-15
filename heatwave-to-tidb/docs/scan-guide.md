# Scan Guide

`tishift-heatwave scan` connects to the source, runs every collector below,
applies the compatibility rules and readiness scoring, and prints/writes the
result. Fully implemented and unit-tested (174 tests across
`core/scan/collectors/`, `core/scan/analyzers/`, `core/scan/orchestrator.py`,
`core/scan/report.py`, and `rules/`).

```bash
tishift-heatwave scan --config tishift-heatwave.yaml
tishift-heatwave scan --config tishift-heatwave.yaml --continue-replication \
    --format cli --format json --output-dir ./tishift-reports
```

- `--continue-replication` — also run the valid-indexes precheck and include continue-replication-specific
  binlog/index deductions in scoring (Cutover & continue replication category); omit for a
  cutover-only assessment
- `--database <schema>` — override `source.database` from the config
- `--no-network-path` — score as if the load phase has no confirmed network path
- `--format cli|json|md` (repeatable) — `cli` prints to stdout, `json`/`md`
  write `tishift-reports/tishift-heatwave-report.{json,md}`; defaults to
  `output.formats` from the config. Unsupported formats are skipped with a note
- `--output-dir` — defaults to `output.dir` from the config
- `--ai` — accepted but not yet implemented (printed as a note)

Orchestration (`core/scan/orchestrator.py`) is deliberately thin: it just
calls the collectors and analyzers below in order over one open connection,
so almost all of its behavior is already covered by their own unit tests —
see `tests/test_scan/test_orchestrator.py` for the end-to-end wiring test and
`tests/test_scan/test_scan_cmd.py` for the CLI-level tests (connection
errors, `--continue-replication`, `--database`, quiet mode).

A handful of compatibility rules (XA transactions, UDFs, XML functions,
GET_LOCK, SQL_CALC_FOUND_ROWS, SAVEPOINT, MySQL Enterprise plugins) need
query-log analysis with no collector yet — they're wired via
`QueryLogSignals` and default to "not detected" rather than being silently
dropped from the rule set.

What it collects:

- **Binlog / continue-replication readiness precheck** — `log_bin`, `binlog_format`,
  `binlog_row_image`, `binlog_expire_logs_seconds`, `binlog_transaction_compression`,
  `binlog_row_value_options` (plus informational `server_id`, `expire_logs_days`)
  via a single `SHOW VARIABLES` query, validated against required values
  (HW-WARNING-4..9). Implemented and tested:
  `core/scan/collectors/binlog.py` (query runner) +
  `core/scan/analyzers/binlog_check.py` (pure validator, `tests/test_scan/`).
  Only gates continue replication (Phase 7) — a cutover-only migration can ignore a failing result.
- **Other server config** (`core/scan/collectors/metadata.py`) — MySQL
  version, `version_comment` (HeatWave detection), RAPID analytics cluster
  node count, `binlog_row_value_options`, GTID mode, charset/collation,
  sql_mode, lower_case_table_names, max_connections
- **Primary/secondary (HA) replication topology** (`core/scan/collectors/metadata.py`)
  — distinct from the RAPID cluster above: `read_only`/`super_read_only`,
  whether this node is itself a replica (`SHOW REPLICA STATUS`) and its
  source host, and the number/hosts of downstream replicas attached to it
  (`SHOW REPLICAS`). Requires `REPLICATION CLIENT`; degrades to "standalone,
  no replicas" without it.
- **Schema inventory** (`core/scan/collectors/schema.py`) — tables (size,
  engine, collation, partitioning), columns (incl. charset), indexes,
  constraints, routines, triggers, events, views (name + `IS_UPDATABLE`) —
  one query per object type, parameterized by schema
- **HeatWave surface** (derived from the schema inventory above):
  - RAPID-offloaded tables (`CREATE_OPTIONS` contains `SECONDARY_ENGINE="RAPID"`,
    cluster presence via `performance_schema.rpd_nodes`)
  - Lakehouse external tables (`ENGINE = 'Lakehouse'`, instance-wide)
  - AutoML/GenAI schemas (`ML_SCHEMA_%`, instance-wide)
  - `VECTOR` columns (`DATA_TYPE = 'vector'`) and JavaScript (MLE) routines
    (`EXTERNAL_LANGUAGE = 'JAVASCRIPT'`)
- **Compatibility hotspots** — `utf8mb4_0900_*` collations (flagged per
  column), unsupported character sets outside ascii/latin1/binary/utf8/
  utf8mb4/gbk (BLOCKER-8), FULLTEXT/SPATIAL indexes (via index type), foreign
  key count (derivable from constraint types), table count / total
  data+index size / index count (all derivable from the tables and indexes
  lists above), AUTO_INCREMENT tables (WARNING-3), updatable views
  (WARNING-9), and case-colliding table names when `lower_case_table_names
  != 2` (WARNING-8 / BLOCKER-9)
- **Valid-indexes precheck** (`core/scan/collectors/valid_indexes.py`) —
  business tables missing a PK/UNIQUE index, needed for continue-replication readiness scoring
  (see `docs/sync-guide.md` § Valid indexes precheck for the same query)

Known gap: `ColumnInfo.excluded_from_rapid` (column-level `NOT SECONDARY`) is
always `False` from this collector — that attribute doesn't surface reliably
in `information_schema.COLUMNS`. The convert-phase DDL cleaner detects it
from `SHOW CREATE TABLE` text directly instead.

The scan is read-only: the source session is set to `TRANSACTION READ ONLY`.

Assessment and scoring apply `references/compatibility-rules.md` and
`references/scoring.md` to the collected inventory.
