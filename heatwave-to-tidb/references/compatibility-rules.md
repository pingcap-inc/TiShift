# TiDB Compatibility Rules — MySQL HeatWave

This reference is loaded by the SKILL.md during Phase 3 (Assess Compatibility).
Apply every rule in order against the checklist from Phase 2.

**Implemented as code:** every rule below (except the query-log-dependent
ones noted inline) is codified in `tishift_heatwave/rules/compatibility.py`
and evaluated by `tishift_heatwave/core/scan/analyzers/compatibility.py`
(unit-tested in `tests/test_scan/test_compatibility_analyzer.py`). This
Markdown table is the human-facing description; the Python module is the
executable source of truth — keep both in sync when a rule changes.

HeatWave is MySQL 8.0/8.4/9.x under the hood, so the standard MySQL rules apply,
plus HeatWave-specific rules (HW-*) for the analytics/ML/Lakehouse surface.
The non-HW rules are sourced from
[docs.pingcap.com/tidbcloud/mysql-compatibility](https://docs.pingcap.com/tidbcloud/mysql-compatibility/)
— re-check that page when TiDB Cloud's compatibility surface changes.

## BLOCKERS — TiDB cannot do these

| ID | Condition | Feature | Action |
|----|-----------|---------|--------|
| BLOCKER-1 | `stored_procedure_count > 0` | Stored procedures — parsed but cannot execute | Convert to application code (Python/Go/Java/JS) |
| BLOCKER-2 | `trigger_count > 0` | Triggers — parsed but cannot execute | Move logic to application middleware |
| BLOCKER-3 | `event_count > 0` | Scheduled events — not supported | Use cron, Kubernetes CronJob, or OCI Functions + scheduler |
| BLOCKER-4 | `has_spatial_columns = TRUE` | Spatial/GIS columns — data type, functions, and indexes all unsupported | Convert columns to JSON with `COMMENT 'was: <original_type>'` |
| BLOCKER-5 | XA transactions detected | XA distributed transactions — not supported (TiDB uses 2PC internally but doesn't expose it via SQL) | Refactor to single-shard transactions or saga pattern |
| BLOCKER-6 | UDFs detected | User-defined functions — not supported | Convert to application-layer functions |
| BLOCKER-7 | XML functions detected | XML functions (ExtractValue, UpdateXML) — not supported | Process XML in application layer |
| BLOCKER-8 | `unsupported_charset_table_count > 0` | Character set outside ascii/latin1/binary/utf8/utf8mb4/gbk — TiDB rejects the column outright | Convert affected columns to a supported charset (utf8mb4 by default) before export |
| BLOCKER-9 | Case-colliding table names AND source `lower_case_table_names != 2` | Table names that only differ by case (e.g. `Users`/`users`) — TiDB Cloud only supports `lower_case_table_names=2` (case-insensitive) | Rename one of each colliding pair before migrating — TiDB cannot represent both. Only fires on an actual collision; a mismatched setting with no collision is WARNING-8 instead |
| HW-BLOCKER-1 | `lakehouse_table_count > 0` | Lakehouse external tables — data lives in Object Storage, not InnoDB | Materialize to InnoDB before export, or re-point the analytics pipeline; no TiDB equivalent for external tables |
| HW-BLOCKER-2 | `automl_schema_count > 0` (schemas matching `ML_SCHEMA_%`) | HeatWave AutoML / GenAI (`sys.ML_TRAIN`, `ML_PREDICT_*`, `ML_EMBED_*`) — no TiDB equivalent | Re-host models on external ML serving (OCI Data Science, SageMaker, vLLM); exclude `ML_SCHEMA_*` schemas from migration |
| HW-BLOCKER-3 | `js_routine_count > 0` | JavaScript (MLE) stored programs — not supported | Convert to application code; the convert phase emits JS stubs |

## WARNINGS — works differently in TiDB

| ID | Condition | Feature | Action |
|----|-----------|---------|--------|
| WARNING-2 | `has_fulltext_indexes = TRUE` AND target tier != starter | FULLTEXT indexes — real index support is Starter-only (and region-limited); Essential, Dedicated, and self-hosted only parse the syntax, they don't index | Starter: confirm your region supports FULLTEXT indexes. Essential/Dedicated/self-hosted: use Elasticsearch/Meilisearch, or TiDB's native full-text/vector search as a replacement, not a drop-in index |
| WARNING-3 | `auto_increment_table_count > 0` | AUTO_INCREMENT — unique but NOT sequential | Each TiDB node allocates ID ranges independently; consider AUTO_RANDOM for high-insert tables, or MySQL Compatibility Mode if the application truly needs sequential IDs (throughput cost) |
| WARNING-4 | `unsupported_collation_count > 0` | utf8mb4_0900_* collations (MySQL 8 default) | Maps 1:1 — utf8mb4_0900_* supported natively since TiDB v7.4 (target TiDB Cloud is v8.5). Informational only; no readiness-score impact |
| WARNING-5 | GET_LOCK usage detected | GET_LOCK/RELEASE_LOCK — limited implementation | Test advisory locking behavior; consider Redis-based locks |
| WARNING-6 | SQL_CALC_FOUND_ROWS detected | Works but triggers full table scan | Replace with separate COUNT(*) query |
| WARNING-7 | SAVEPOINT usage detected | SAVEPOINT — pessimistic mode only | Ensure pessimistic transaction mode is enabled (default in TiDB) |
| WARNING-8 | `lower_case_table_names != 2` | lower_case_table_names mismatch — TiDB Cloud only supports value 2 | Verify no application code depends on case-sensitive table-name matching; TiDB always compares names case-insensitively regardless of the source's setting. Escalates to BLOCKER-9 if the source actually holds colliding names |
| WARNING-9 | `updatable_view_count > 0` (`information_schema.VIEWS.IS_UPDATABLE = 'YES'`) | Updatable views — TiDB views are always read-only, no UPDATE/INSERT/DELETE through a view | Redirect writes that currently go through the view to the underlying table(s) directly |
| HW-WARNING-1 | `rapid_table_count > 0` | RAPID analytics offload (`SECONDARY_ENGINE=RAPID`) | Map to **TiFlash replicas** — convert emits `ALTER TABLE ... SET TIFLASH REPLICA n` for each RAPID table (Essential/Dedicated). This is the natural HTAP equivalent, not a loss of function |
| HW-WARNING-2 | `vector_column_count > 0` | MySQL 9 `VECTOR` columns | TiDB Cloud supports `VECTOR`; re-create vector indexes with TiDB syntax and re-verify distance functions. Embeddings generated by HeatWave GenAI must be re-generated externally |
| HW-WARNING-3 | Enterprise features detected (TDE, data masking, audit plugin, firewall) | MySQL Enterprise add-ons | Map to TiDB Cloud equivalents: encryption at rest (default), audit logging (Dedicated), data masking in application layer |
| HW-WARNING-4 | `binlog_expire_logs_seconds < 86400` (fail) or `< 604800` (warn) and continue replication planned | Short binlog retention risks DM losing its position during initial load | Raise retention to at least 86400 (1 day, hard minimum), 604800 (7 days) recommended, before starting sync |
| HW-WARNING-5 | `binlog_row_value_options = 'PARTIAL_JSON'` and continue replication planned | DM cannot parse binlog rows that use partial JSON updates | `SET GLOBAL binlog_row_value_options = '';` on the source before starting sync (see HW-DDL note in `docs/sync-guide.md`) |
| HW-WARNING-6 | `log_bin != 'ON'` and continue replication planned | Binary logging disabled — DM has nothing to replicate from | Enable `log_bin` on the DB System (requires a restart) before starting sync |
| HW-WARNING-7 | `binlog_format != 'ROW'` and continue replication planned | Non-ROW binlog format misses edge cases in data changes | Set `binlog_format = ROW` before starting sync |
| HW-WARNING-8 | `binlog_row_image != 'FULL'` and continue replication planned | Partial row images are unsafe for conflict resolution | Set `binlog_row_image = FULL` before starting sync |
| HW-WARNING-9 | `binlog_transaction_compression != 'OFF'` and continue replication planned | DM does not support transaction compression | `SET GLOBAL binlog_transaction_compression = 'OFF';` before starting sync |

Checked together via one `SHOW VARIABLES` query (`tishift_heatwave/rules/binlog_check.py`); `server_id` and `expire_logs_days` are collected by the same query but reported informationally only (no hard required value) — `server_id = 0` disables binary logging entirely, and `expire_logs_days` is the legacy pre-8.0 retention setting superseded by `binlog_expire_logs_seconds`.

## DDL cleanup rules (convert phase)

Applied automatically by `tishift-heatwave convert` (engine:
`tishift_heatwave/core/convert/ddl_cleaner.py`, registry:
`tishift_heatwave/rules/ddl_cleanup.py`). Removal is comment-preserving —
cleaned clauses become `/* TISHIFT-REMOVED [rule-id]: <original> */` comments
(plain comments only, never `/*! */` / `/*T! */`), so nothing is lost.

| ID | Syntax | Risk | Handling | Auto-cleanable |
|----|--------|------|----------|----------------|
| HW-DDL-1 | `SECONDARY_ENGINE=RAPID` | 🔴 blocker | Comment out; emit `ALTER TABLE ... SET TIFLASH REPLICA n` right after the CREATE TABLE (HW-WARNING-1 mapping) | ✅ yes |
| HW-DDL-2 | `SECONDARY_LOAD=...` option, `ALTER ... SECONDARY_LOAD/UNLOAD` statements | 🔴 blocker | Comment out (statements become `--` line comments) | ✅ yes |
| HW-DDL-3 | `CLUSTERING BY (...)` | 🟠 needs assessment | Comment out + `TISHIFT-REVIEW` alternative suggestion; goes on the manual-review checklist | ⚠️ partial |
| HW-DDL-4 | `COMMENT 'RAPID_COLUMN=...'` | 🟢 harmless | Keep as-is; reported as informational | ❌ not needed |

## COMPATIBLE — no changes needed

- InnoDB engine (TiDB's only engine — always compatible)
- Foreign keys — enforced natively (TiDB v6.6+; target TiDB Cloud is v8.5). TiDB Cloud DM's precheck still reports FK warnings even when the migration is safe — see the FK Pre-upgrade Checklist in `docs/sync-guide.md` before dismissing them
- JSON columns (full JSON path support)
- ENUM/SET types
- ascii/latin1/binary/utf8/utf8mb4/gbk charsets (see BLOCKER-8 for everything else)
- Window functions and CTEs
- Prepared statements
- Pessimistic transactions (default mode)
- RANGE/LIST/HASH/KEY partitioning (SUBPARTITION and most partition-maintenance operations are not — see the note below)
- Online DDL (distributed implementation)
- Generated columns (VIRTUAL and STORED)
- Views (standard SQL views — read-only; see WARNING-9 for updatable-view usage)
- Analytic queries previously offloaded to RAPID — run on TiFlash instead

## Known gaps not yet detected by scan (query-log or DDL-parse dependent)

These are real TiDB incompatibilities per
[docs.pingcap.com/tidbcloud/mysql-compatibility](https://docs.pingcap.com/tidbcloud/mysql-compatibility/)
that `scan` cannot currently see — they show up only in application SQL or
DDL details the collectors don't parse yet, unlike the `QueryLogSignals`-gated
BLOCKER-5/6/7 rules above which already have the plumbing, just no live
collector. Ask the user about these directly when relevant; there's no
automated check to fall back on:

- `CREATE TABLE ... AS SELECT` (CTAS)
- `CHECK TABLE`, `CHECKSUM TABLE`, `REPAIR TABLE`, `OPTIMIZE TABLE`
- `HANDLER` statements, `CREATE TABLESPACE`
- Descending indexes (`... (col DESC)`)
- `SKIP LOCKED`
- Lateral derived tables, `JOIN ON` subqueries
- SUBPARTITION and most partition-maintenance operations (HASH/KEY partitions only allow ADD/COALESCE/TRUNCATE; RANGE/LIST allow ADD/DROP/TRUNCATE/REORGANIZE)

## Output Format

```json
{
  "blockers": [{"id": "HW-BLOCKER-1", "feature": "...", "count": N, "action": "..."}],
  "warnings": [{"id": "HW-WARNING-1", "feature": "...", "count": N, "action": "..."}],
  "compatible": ["InnoDB", "JSON columns", "..."]
}
```
