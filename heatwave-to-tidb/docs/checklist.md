# Checklist — Rules, Prechecks & Attention Tips

Single consolidated reference for everything that can block or silently break
a HeatWave → TiDB migration: compatibility rules, DDL cleanup rules, and every
precheck/attention tip from the scan/convert/load/check/sync phases. Each item
links back to its source of truth (`references/*.md`, `SKILL.md`, the other
`docs/*-guide.md` files) — this doc is the index, not a replacement for them.

---

## 1. Connectivity & environment

- [ ] **Network path confirmed.** HeatWave DB Systems have no public endpoint —
  reach them via SSH tunnel through an OCI Bastion session, a compute jump
  host in the same VCN, or site-to-site VPN/FastConnect.
  ```bash
  ssh -f -N -L 3306:<db-system-private-ip>:3306 opc@<bastion-host>
  ```
- [ ] **TLS is mandatory on both ends, not optional.**
  - Source: HeatWave requires TLS on every client connection (scan, convert,
    load, and the DM replication link). Needs the HeatWave instance CA
    certificate (OCI Console → DB System → Connect); pass with `--ssl-ca=<path>`.
  - Target: TiDB Cloud Starter/Essential requires `--ssl-mode=VERIFY_IDENTITY`
    (ISRG Root X1 CA).
- [ ] **Credentials via environment variables**, not the command line
  (`SRC_PWD`, `MYSQL_PWD`) — command-line passwords leak into shell history
  and process listings.
- [ ] **Target tier decided upfront** (Starter / Essential / Dedicated) — it
  gates load strategy, continue-replication availability, and TiFlash replica emission
  throughout every later phase.

---

## 2. Compatibility rules — BLOCKERS (TiDB cannot do these)

| ID | Condition | Feature | Action |
|----|-----------|---------|--------|
| BLOCKER-1 | `stored_procedure_count > 0` | Stored procedures — parsed but cannot execute | Convert to application code (Python/Go/Java/JS) |
| BLOCKER-2 | `trigger_count > 0` | Triggers — parsed but cannot execute | Move logic to application middleware |
| BLOCKER-3 | `event_count > 0` | Scheduled events — not supported | Use cron, Kubernetes CronJob, or OCI Functions + scheduler |
| BLOCKER-4 | `has_spatial_columns = TRUE` | Spatial/GIS columns — data type, functions, and indexes all unsupported | Convert columns to JSON with `COMMENT 'was: <original_type>'` |
| BLOCKER-5 | XA transactions detected | XA distributed transactions — not supported | Refactor to single-shard transactions or saga pattern |
| BLOCKER-6 | UDFs detected | User-defined functions — not supported | Convert to application-layer functions |
| BLOCKER-7 | XML functions detected | XML functions (ExtractValue, UpdateXML) — not supported | Process XML in application layer |
| BLOCKER-8 | Charset outside ascii/latin1/binary/utf8/utf8mb4/gbk | TiDB rejects the column outright | Convert to a supported charset (utf8mb4 by default) before export |
| BLOCKER-9 | Case-colliding table names AND source `lower_case_table_names != 2` | TiDB Cloud only supports `lower_case_table_names=2` | Rename one of each colliding pair before migrating |
| HW-BLOCKER-1 | `lakehouse_table_count > 0` | Lakehouse external tables — data lives in Object Storage, not InnoDB | Materialize to InnoDB before export, or re-point the analytics pipeline; no TiDB equivalent |
| HW-BLOCKER-2 | `automl_schema_count > 0` (`ML_SCHEMA_%`) | HeatWave AutoML / GenAI (`sys.ML_TRAIN`, `ML_PREDICT_*`, `ML_EMBED_*`) — no TiDB equivalent | Re-host models externally (OCI Data Science, SageMaker, vLLM); exclude `ML_SCHEMA_%` schemas from migration |
| HW-BLOCKER-3 | `js_routine_count > 0` | JavaScript (MLE) stored programs — not supported | Convert to application code; convert phase emits JS stubs |

Full detail: `references/compatibility-rules.md`.

## 3. Compatibility rules — WARNINGS (works differently in TiDB)

| ID | Condition | Feature | Action |
|----|-----------|---------|--------|
| WARNING-2 | `has_fulltext_indexes = TRUE` AND target tier != starter | FULLTEXT — real index support is Starter-only (region-limited); Essential/Dedicated/self-hosted only parse the syntax | Starter: confirm region support. Others: use Elasticsearch/Meilisearch or TiDB's native full-text/vector search |
| WARNING-3 | `auto_increment_table_count > 0` | AUTO_INCREMENT — unique but NOT sequential | Consider AUTO_RANDOM for high-insert tables, or MySQL Compatibility Mode for strict sequential IDs |
| WARNING-4 | `unsupported_collation_count > 0` | `utf8mb4_0900_*` collations (MySQL 8 default) | Maps 1:1 — supported natively on TiDB ≥ v7.4 (target TiDB Cloud is v8.5). Informational only; no readiness-score impact. **Foreign keys likewise no longer warn** — enforced natively since v6.6, though TiDB Cloud DM's precheck still reports FK warnings even when the migration is safe (see §10.5) |
| WARNING-5 | GET_LOCK usage detected | Limited implementation | Test advisory locking; consider Redis-based locks |
| WARNING-6 | SQL_CALC_FOUND_ROWS detected | Works but full table scan | Replace with separate COUNT(*) |
| WARNING-7 | SAVEPOINT usage detected | Pessimistic mode only | Ensure pessimistic transaction mode (TiDB default) |
| WARNING-8 | `lower_case_table_names != 2` | TiDB Cloud only supports value 2 | Verify no app code depends on case-sensitive table-name matching. Escalates to BLOCKER-9 on an actual name collision |
| WARNING-9 | `updatable_view_count > 0` | TiDB views are always read-only | Redirect writes through the view to the underlying table(s) |
| HW-WARNING-1 | `rapid_table_count > 0` | RAPID analytics offload (`SECONDARY_ENGINE=RAPID`) | Maps to **TiFlash replicas** — not a loss of function (Essential/Dedicated) |
| HW-WARNING-2 | `vector_column_count > 0` | MySQL 9 `VECTOR` columns | TiDB Cloud supports `VECTOR`; re-create indexes, re-verify distance functions; GenAI embeddings must be regenerated externally |
| HW-WARNING-3 | Enterprise features detected (TDE, data masking, audit plugin, firewall) | MySQL Enterprise add-ons | Map to TiDB Cloud equivalents (encryption at rest by default, Dedicated audit logging, app-layer masking) |
| HW-WARNING-4 | `binlog_expire_logs_seconds < 86400` (fail) / `< 604800` (warn) and continue replication planned | Short retention risks DM losing position during initial load | Raise retention to ≥ 86400 (1 day, hard minimum), 604800 (7 days) recommended |
| HW-WARNING-5 | `binlog_row_value_options = 'PARTIAL_JSON'` and continue replication planned | DM cannot parse partial-JSON binlog rows | `SET GLOBAL binlog_row_value_options = '';` before starting sync |
| HW-WARNING-6 | `log_bin != 'ON'` and continue replication planned | Binary logging disabled — nothing for DM to replicate from | Enable `log_bin` (requires restart) before starting sync |
| HW-WARNING-7 | `binlog_format != 'ROW'` and continue replication planned | Misses edge cases in data changes | Set `binlog_format = ROW` before starting sync |
| HW-WARNING-8 | `binlog_row_image != 'FULL'` and continue replication planned | Partial row images unsafe for conflict resolution | Set `binlog_row_image = FULL` before starting sync |
| HW-WARNING-9 | `binlog_transaction_compression != 'OFF'` and continue replication planned | DM does not support transaction compression | `SET GLOBAL binlog_transaction_compression = 'OFF';` before starting sync |

HW-WARNING-4/6..9 are checked together by one `SHOW VARIABLES` query — see §10.1.
Full detail: `references/compatibility-rules.md`.

## 4. DDL cleanup rules (convert phase — HW-DDL-*)

Applied by `tishift-heatwave convert`. **Comment-preserving**: cleaned clauses
become `/* TISHIFT-REMOVED [rule-id]: <original> */` (or a `--` line comment
for whole statements) — nothing is deleted. Only plain comments are used,
never `/*! */` / `/*T! */`. Idempotent; every modified statement is re-parsed
with sqlglot to confirm the cleanup left valid syntax.

| ID | Syntax | Risk | Handling | Auto-cleanable |
|----|--------|------|----------|----------------|
| HW-DDL-1 | `SECONDARY_ENGINE=RAPID` | 🔴 blocker | Comment out; emit `ALTER TABLE ... SET TIFLASH REPLICA n` right after the `CREATE TABLE` | ✅ yes |
| HW-DDL-2 | `SECONDARY_LOAD=...` option / `ALTER ... SECONDARY_LOAD`/`SECONDARY_UNLOAD` statements | 🔴 blocker | Comment out (statements → `--` line comments) | ✅ yes |
| HW-DDL-3 | `CLUSTERING BY (...)` | 🟠 needs assessment | Comment out + `TISHIFT-REVIEW` suggestion (secondary index, or clustered PK if columns are a PK prefix); goes on the manual-review checklist | ⚠️ partial |
| HW-DDL-4 | `COMMENT 'RAPID_COLUMN=...'` | 🟢 harmless | Keep as-is; reported only | ❌ not needed |

**Attention:** if a removed clause itself contains `*/`, the engine degrades
to a `--` line comment so the wrapping comment can't close early.

Full detail: `references/compatibility-rules.md` § DDL cleanup rules, `docs/convert-guide.md`.

## 5. Type mapping exceptions

| HeatWave / MySQL | TiDB | Rule |
|---|---|---|
| `VECTOR(n)` (MySQL 9) | `VECTOR(n)` on TiDB Cloud | Index syntax differs (`VECTOR INDEX ... USING HNSW`); re-verify distance functions. Self-hosted TiDB < v8.4: convert to JSON |
| Spatial types | `JSON` + `COMMENT 'was: <type>'` | BLOCKER-4 |
| `utf8mb4_0900_*` collation | Same collation, unchanged (native on TiDB ≥ v7.4; target is v8.5) | WARNING-4 |
| Charset outside ascii/latin1/binary/utf8/utf8mb4/gbk | Convert to a supported charset | BLOCKER-8 |
| `AUTO_INCREMENT` | Same (non-sequential) or `AUTO_RANDOM` | WARNING-3 |
| Updatable view (`IS_UPDATABLE='YES'`) | View stays, becomes read-only | WARNING-9 |
| Case-colliding table names, source `lower_case_table_names != 2` | Rename to remove the collision | BLOCKER-9 / WARNING-8 |
| `NOT SECONDARY` (column) | Stripped — TiFlash replicates whole tables | Note excluded columns in the report |
| `ENGINE_ATTRIBUTE`/`SECONDARY_ENGINE_ATTRIBUTE` (Lakehouse) | — | HW-BLOCKER-1 |
| `ENCRYPTION='Y'` | Stripped — TiDB Cloud encrypts at rest by default | — |

Full detail: `references/type-mapping.md`.

---

## 6. Scan phase — what to check

- **Binlog / continue-replication readiness precheck** (implemented + tested, §10.1): `log_bin`,
  `binlog_format`, `binlog_row_image`, `binlog_expire_logs_seconds`,
  `binlog_transaction_compression`, plus informational `server_id`/`expire_logs_days`
- Other server config: `binlog_row_value_options`, `gtid_mode`, charset/collation,
  `sql_mode`, `lower_case_table_names` — TiDB Cloud only supports value `2` (WARNING-8 /
  BLOCKER-9 on an actual name collision)
- RAPID cluster attached? (`performance_schema.rpd_nodes`); which tables are offloaded
  (`CREATE_OPTIONS LIKE '%SECONDARY_ENGINE%'`)
- Lakehouse external tables (`ENGINE = 'Lakehouse'`) and AutoML schemas (`ML_SCHEMA_%`)
- Programmable objects: stored procedures/triggers/events, `EXTERNAL_LANGUAGE = 'JAVASCRIPT'` (MLE)
- VECTOR/spatial columns, FULLTEXT/SPATIAL indexes, `utf8mb4_0900_*` collations, FK count
- Column character sets outside ascii/latin1/binary/utf8/utf8mb4/gbk (BLOCKER-8)
- Views and `information_schema.VIEWS.IS_UPDATABLE` (WARNING-9 — TiDB views are read-only)
- Total size vs. tier capacity (25 GiB free on Starter)

The scan is read-only — source session is `TRANSACTION READ ONLY`. Full detail: `docs/scan-guide.md`, `SKILL.md` Phase 2.

## 7. Convert phase — attention tips

- Nothing is silently dropped — see §4 (DDL cleanup rules)
- **TiFlash replica trade-off**: the `ALTER TABLE ... SET TIFLASH REPLICA n`
  is placed immediately after each RAPID table's `CREATE TABLE`, so the
  replica exists *before* data load — TiFlash replicates during the import,
  which slows large loads. Move the ALTERs to after the load window if import
  speed matters.
- Replica statements are emitted on every tier (Starter/Serverless included,
  default 2 replicas); only `--tiflash-replicas 0` downgrades the ALTER to an
  informational comment.
- Code stubs for stored procedures/triggers/events/JS routines are generated
  but require manual porting — not a drop-in replacement.

Full detail: `docs/convert-guide.md`, `SKILL.md` Phase 4.

## 8. Load phase — attention tips

- AWS DMS does not apply (OCI-hosted source) — export always runs Dumpling
  over the MySQL protocol through the tunnel/bastion.
- `FLUSH TABLES WITH READ LOCK` is **restricted on HeatWave** — Dumpling falls
  back to per-table locking. Schedule the export during low traffic, or rely
  on continue replication (§10) to catch up changes made during export.
- Always **exclude `ML_SCHEMA_%` schemas and Lakehouse tables** from the export filter.
- MySQL Shell (`util.dumpSchemas()`/`util.exportTable()`) is a valid
  alternative export path to Object Storage, but Lightning cannot read the
  MySQL Shell dump format directly — prefer Dumpling if Lightning is the import path.

Full detail: `references/load-strategies.md`, `docs/load-guide.md`, `SKILL.md` Phase 5.

## 9. Check phase — what's validated

1. Row counts per table, both sides
2. Column structure diff (deliberate conversions from §4/§5 are expected, not flagged)
3. Sample checksums (`BIT_XOR(CRC32(CONCAT_WS('#', ...)))`) for numeric-PK tables
4. TiFlash replicas report `AVAILABLE = 1` in `information_schema.tiflash_replica`

Full detail: `docs/check-guide.md`, `SKILL.md` Phase 6.

---

## 10. Continue Replication Sync (TiDB DM) — prechecks & attention tips

Essential/Dedicated only; Starter is cutover-only. HeatWave supports outbound
replication, so TiDB DM attaches through the same network path as scan/load.

**This tool only runs the prechecks below.** The DM migration task itself —
creation, scoping, precheck run, lag monitoring, start/stop — is configured
and executed as a task in the **TiDB Cloud console**, not by this CLI. Treat
§10.2–10.4 as values to verify/enter there, not steps this tool performs for you.

### 10.1 Preflight

**Binlog / continue-replication readiness precheck** — one `SHOW VARIABLES` query, implemented
and tested (`core/scan/analyzers/binlog_check.py`, `tests/test_scan/`):

```sql
SHOW VARIABLES WHERE Variable_name IN
('log_bin','server_id','binlog_format','binlog_row_image',
'binlog_expire_logs_seconds','expire_logs_days','binlog_transaction_compression');
```

| Configuration | Required value | Why |
|---|---|---|
| `log_bin` | ON | Enables binary logging, which DM uses to replicate changes to TiDB |
| `binlog_format` | ROW | Captures all data changes accurately (other formats miss edge cases) |
| `binlog_row_image` | FULL | Includes all column values in events for safe conflict resolution |
| `binlog_expire_logs_seconds` | ≥ 86400 (1 day, hard minimum), 604800 (7 days, recommended) | Ensures DM can access consecutive logs during migration |
| `binlog_transaction_compression` | OFF | DM does not support transaction compression |

`server_id` and `expire_logs_days` are collected by the same query but are
informational only — `server_id = 0` disables binary logging entirely
(silent failure, not a clean error); `expire_logs_days` is the legacy
pre-8.0 setting superseded by `binlog_expire_logs_seconds`.

- [ ] `gtid_mode = ON`
- [ ] `binlog_row_value_options` is **empty** — HeatWave can default this to
  `PARTIAL_JSON`, which DM cannot parse. Leaving it set causes **silent
  replication corruption on JSON columns**, not a clean failure:
  ```sql
  SET GLOBAL binlog_row_value_options = '';
  SELECT @@binlog_row_value_options;  -- must return empty
  ```
  Clearing it invalidates any binlog position captured before the change —
  run this before creating the DM task.
- [ ] Source TLS configured with the HeatWave CA certificate

### 10.2 Migration user privileges

DM's precheck validates replication access, source schema read access, and
target DDL/DML access independently — any one being wrong fails the precheck.

**Source (HeatWave)** — replication grants are instance-wide (binlog access
is not schema-scoped); `SELECT` is granted per business schema and must be
repeated for every schema in scope:
```sql
GRANT REPLICATION SLAVE, REPLICATION CLIENT ON *.* TO '$DM_USER'@'%';
GRANT SELECT ON `$DB`.* TO '$DM_USER'@'%';
-- repeat the SELECT grant for every additional business schema in scope
```
Missing `SELECT` on a business schema is a common cause of precheck failures
that look unrelated to permissions.

**Target (TiDB)** — DM needs both DDL and DML privileges to create/alter
tables and apply changes:
```sql
GRANT CREATE, SELECT, INSERT, UPDATE, DELETE, ALTER, DROP, INDEX ON *.* TO 'dm_target_user'@'%';
```

### 10.3 Valid indexes precheck

Implemented as code: `core/scan/collectors/valid_indexes.py`.

DM needs a primary key or unique index on every table to apply row changes
deterministically. Tables without one can replicate incorrectly or fail outright:

```sql
SELECT
    t.table_name,
    t.table_schema
FROM
    information_schema.tables AS t
WHERE
    (t.table_schema, t.table_name) NOT IN (
        SELECT
            s.table_schema,
            s.table_name
        FROM
            information_schema.statistics AS s
        WHERE
            s.NON_UNIQUE = 0
        GROUP BY
            s.table_schema,
            s.table_name
    )
    AND t.table_schema NOT IN (
        'mysql', 'performance_schema', 'information_schema', 'sys',
        'mysql_autopilot', 'mysql_audit', 'mysql_tasks'
    )
    AND t.table_schema NOT LIKE 'ML\_SCHEMA\_%'
    AND t.table_type = 'BASE TABLE';
```

**Attention:** the schema exclusion list must cover **every non-business
database on the actual HeatWave instance being migrated** — the values above
(`mysql_autopilot`, `mysql_audit`, `mysql_tasks`, `ML_SCHEMA_%`) are the ones
this module already knows about, not an exhaustive list for every
environment. Extend both the `NOT IN` list and the `NOT LIKE` pattern before
relying on the result. Any row returned is a business table missing a
PK/UNIQUE index — add one, or explicitly exclude the table and document why
that's safe.

### 10.4 Scope the DM task to business schemas only

Do **not** select "All Objects." Use an explicit `block-allow-list`:

```yaml
block-allow-list:
  instance:
    do-dbs: ["$DB"]
    ignore-dbs: ["mysql_autopilot", "mysql_audit", "mysql_tasks"]
```

- `do-dbs` — the business schema(s) being migrated
- `ignore-dbs` — HeatWave-managed schemas that must never replicate:
  `mysql_autopilot`, `mysql_audit`, `mysql_tasks`, plus standard MySQL system
  schemas (`mysql`, `sys`, `information_schema`, `performance_schema`) and any
  `ML_SCHEMA_%` AutoML schema (HW-BLOCKER-2)

Selecting "All Objects" either fails the task outright on these schemas or
pulls in objects with no place on the target.

### 10.5 FK precheck warnings are expected, not blocking

TiDB Cloud DM's precheck reports FK-related warnings against HeatWave
sources. Migrations proceed and replicate successfully with these warnings
present — the warning itself is not the risk. Before dismissing it, confirm
every item on the:

**FK Pre-upgrade Checklist**
- [ ] All FK-related parent and child tables are included in the task
- [ ] Any tables excluded from the task are confirmed not part of a required FK relationship
- [ ] Target TiDB schemas, tables, FK constraints, charset, and collation are already prepared and match source
- [ ] No PK/UK updates are expected on the source during replication
- [ ] No DDL or FK constraint changes are expected on the source during replication

If any item is unchecked, resolve it first — an unmet checklist item, not the
FK warning, is what causes replication problems.

### 10.6 Notify PingCAP

Notify PingCAP in advance of the planned cutover window so the relevant team
is aligned and available if support or rollback assistance is needed.

Full detail: `docs/sync-guide.md`, `SKILL.md` Phase 7.

---

## 11. Cutover checklist (all tiers)

- [ ] Application connection strings updated
- [ ] Stored-procedure/trigger/event/MLE replacements deployed
- [ ] Analytics queries verified against TiFlash (if RAPID tables were migrated)
- [ ] Every business table has a valid index (§10.3)
- [ ] FK Pre-upgrade Checklist items all checked (§10.5)
- [ ] PingCAP notified of the cutover window (§10.6)
- [ ] Rollback window agreed; HeatWave kept read-only for that window

---

## 12. Readiness scoring — quick reference

Implemented as code (`rules/scoring.py` + `core/scan/analyzers/scoring.py`,
reusing the compatibility analyzer's rule checks so the two never disagree).

0-100 score computed from the scan inventory; five categories
(Schema compatibility 30, Programmable objects 25, HeatWave surface 20,
Data & load feasibility 15, Cutover & continue replication 10). Rating bands: 85-100 READY,
65-84 READY WITH WORK, 40-64 SIGNIFICANT REWORK, 0-39 NOT RECOMMENDED YET.

Full detail (deduction formulas per category): `references/scoring.md`.
