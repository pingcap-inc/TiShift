---
name: heatwave-to-tidb-migration
description: Migrate MySQL HeatWave databases to TiDB — assess readiness, convert schema, load data, and validate. Use this skill whenever someone mentions migrating from MySQL HeatWave, Oracle MySQL Database Service, or OCI MySQL to TiDB, wants to assess HeatWave compatibility with TiDB, needs to map HeatWave analytics (RAPID) to TiFlash, or is planning any HeatWave to TiDB migration project, even if they don't use the word "migration" explicitly.
metadata:
  version: 0.1.0
---

# MySQL HeatWave to TiDB Migration

This skill walks you through a complete MySQL HeatWave to TiDB migration, one command at a time. The user runs each command and pastes the output back; you interpret the results and move to the next step. The reason for this call-and-response pattern is that database migrations are high-stakes — each step needs human verification before proceeding.

HeatWave is MySQL 8.0/8.4/9.x under the hood, so core compatibility with TiDB is high. The migration-specific work concentrates in the HeatWave surface: RAPID analytics offload (maps to TiFlash), Lakehouse external tables (blocker), AutoML/GenAI schemas (blocker), VECTOR columns, and JavaScript stored programs.

`docs/checklist.md` collects every compatibility rule, DDL cleanup rule, and precheck/attention tip from every phase below into one reference — consult it directly if you need the full picture without walking the phases in order.

## How to use this skill

**Config-file mode (preferred):** if a filled-in config exists (`config/tishift-heatwave.yaml` or `tishift-heatwave.yaml`, gitignored), read connection details from it and drive the phases directly — run `tishift-heatwave scan/convert --config <file>` and execute the per-phase queries yourself over TLS — instead of asking the user to run commands and paste output. When Phase 7 continue replication is planned (or the tier is Essential/Dedicated and the user hasn't ruled it out), pass `--continue-replication` to `scan` so the binlog rules count against the score and the valid-indexes precheck (Step 7.1) runs. Confirm the config file is gitignored before proceeding, and never echo its passwords into commands or chat. The call-and-response flow below is the fallback when no config file exists.

When the user provides database credentials, start Phase 1 immediately. Output one command, say "Run this and paste the output," and wait. Don't summarize all phases upfront or explain what you'll do — just execute.

**Security note:** Passwords on the command line are visible in shell history and process listings. Before starting, ask the user to set environment variables for credentials so passwords never appear in commands:
```
export SRC_PWD="<source password>"
export MYSQL_PWD="<target password>"
```
Both endpoints speak MySQL protocol. For source commands, use `--password="$SRC_PWD"`; for target commands `MYSQL_PWD` is picked up natively by the mysql client (no `-p` flag needed).

When pasting output back, remind the user to paste only the query results, not the command itself — this avoids credentials appearing in conversation history.

**IMPORTANT — network path:** Before Phase 1, confirm how the user reaches the DB System:
- Public endpoint (DB Systems with public accessibility enabled, e.g. `*.dbsystem.<region>.aws.cloud.mysql.com` or OCI "Networking Accessibility: Public"): connect directly over TLS; the client IP must be within the allowed public IP ranges
- SSH tunnel through an OCI Bastion session or a compute jump host (VCN-private DB Systems): `ssh -f -N -L 3306:<db-system-private-ip>:3306 opc@<bastion>` then connect to `127.0.0.1:3306`
- Site-to-site VPN / FastConnect: connect to the private IP directly

**Command format for HeatWave (source):**
```
mysql -h $SRC_HOST -P 3306 -u $SRC_USER --password="$SRC_PWD" -e "SQL"
```

**Command format for TiDB (target):**
```
mysql --ssl-mode=VERIFY_IDENTITY -h $TARGET_HOST -P 4000 -u $TARGET_USER -e "SQL"
```

Substitute the user's actual values for `$SRC_HOST`, `$SRC_USER`, etc. Output one command per step — never combine queries. `$DB` below is the database (schema) the user wants to migrate.

**Always display the full generated report.** Phase 3 (scan) and Phase 4 (convert) each produce a report — either written to disk (`tishift-reports/tishift-heatwave-report.md`, `tishift-reports/ddl-cleanup-report.md`) if you ran the `tishift-heatwave` CLI directly, or assembled by you from the manual query results if the user is pasting output back per the step-by-step flow above. Either way, once that phase's report is complete, print its full contents in the chat as your last message for that phase — read the file back and echo it (or write out the complete assembled report) rather than a bullet-point paraphrase. The user should have the whole report sitting in the conversation, not just your summary of it.

**When asked for a consolidated/final report, list every check item, not just the ones that fired.** The CLI's `.md`/CLI-text output omits zero-hit rules to stay short (the JSON report keeps the full set — see `tishift-reports/*-report.json`). If the user asks to review the full process, don't just re-paste the summary: enumerate every rule in `references/compatibility-rules.md` (all BLOCKER-\*/WARNING-\*/HW-\*/HW-DDL-\* IDs) against what actually fired, and call out explicitly which ones are backed by a real collector (schema/inventory-based) versus which rely on query-log analysis this tool doesn't implement yet (BLOCKER-5/6/7, WARNING-5/6/7, HW-WARNING-3 — these default to "not detected," which is not the same as "confirmed clear"). Presenting "0 blockers" without that distinction overstates how much was actually verified.

---

## Phase 1: Connect

Before connecting, ask the user which TiDB Cloud tier they're targeting:
- **Starter** (default) — free up to 25 GiB, ideal for assessment and small migrations; cutover only, no continue replication
- **Essential** — production workloads, autoscaling, DM-based continue replication from the HeatWave binlog
- **Dedicated** — enterprise, full HTAP with TiFlash, Lightning, DM, PCI-DSS/SOC 2

This choice affects load strategy, continue-replication options, and how RAPID analytics offload is handled throughout.

**Step 1.1 — Test source:**
```
mysql --ssl-mode=VERIFY_IDENTITY -h $SRC_HOST -P 3306 -u $SRC_USER --password="$SRC_PWD" -e "SELECT VERSION(), @@version_comment"
```

Verify: version string is 8.0+, and `@@version_comment` contains "MySQL Enterprise - Cloud" (confirms an OCI-managed HeatWave DB System). If it shows a community build, the source is plain MySQL — the skill still works, skip HeatWave-specific steps.

**Source TLS is mandatory, not optional** — HeatWave DB Systems require TLS on every client connection, including scan/convert/load and the DM replication link in Phase 7. If `--ssl-mode=VERIFY_IDENTITY` fails, the user needs the HeatWave instance CA certificate (downloadable from the OCI Console → DB System → Connect); pass it with `--ssl-ca=<path>`.

**Step 1.2 — Detect an attached HeatWave (RAPID) cluster:**
```
mysql -h $SRC_HOST -P 3306 -u $SRC_USER --password="$SRC_PWD" -e "SELECT COUNT(*) AS rapid_nodes FROM performance_schema.rpd_nodes"
```

If `rapid_nodes > 0`, a HeatWave cluster is attached and tables may be offloaded to RAPID — Phase 2 must inventory them. If the table doesn't exist, no cluster is attached.

**Step 1.3 — Test target:**

For TiDB Cloud Starter/Essential (TLS required):
```
mysql --ssl-mode=VERIFY_IDENTITY -h $TARGET_HOST -P 4000 -u $TARGET_USER -e "SELECT VERSION()"
```
For self-hosted TiDB:
```
mysql -h $TARGET_HOST -P $TARGET_PORT -u $TARGET_USER -e "SELECT VERSION()"
```

**Gate:** Both must return version strings. Source shows MySQL 8.0+, target shows TiDB. If the target is TiDB Cloud and TLS fails, ensure the user has the correct CA certificate (ISRG Root X1 for Starter/Essential).

---

## Phase 2: Scan

Collect schema inventory and HeatWave feature usage. Run all steps — each as a single command.

**Step 2.1a — Binlog / continue-replication readiness precheck:**
```
mysql -h $SRC_HOST -P 3306 -u $SRC_USER --password="$SRC_PWD" -e "
SHOW VARIABLES WHERE Variable_name IN
('log_bin','server_id','binlog_format','binlog_row_image',
'binlog_expire_logs_seconds','expire_logs_days','binlog_transaction_compression',
'binlog_row_value_options')"
```

Only matters if continue replication (Phase 7) is planned — a cutover-only migration can ignore this. Evaluate each row against:

| Configuration | Required value | Why |
|---|---|---|
| `log_bin` | ON | Enables binary logging, which DM uses to replicate changes to TiDB |
| `binlog_format` | ROW | Captures all data changes accurately (other formats miss edge cases) |
| `binlog_row_image` | FULL | Includes all column values in events for safe conflict resolution |
| `binlog_expire_logs_seconds` | ≥ 86400 (1 day, hard minimum), 604800 (7 days, recommended) | Ensures DM can access consecutive logs during migration |
| `binlog_transaction_compression` | OFF | DM does not support transaction compression |
| `binlog_row_value_options` | `''` (empty, not PARTIAL_JSON) | DM cannot parse partial-JSON binlog rows — PARTIAL_JSON causes silent replication corruption on JSON columns. Clear with `SET GLOBAL binlog_row_value_options = '';` (this invalidates any binlog position captured before the change) |

`server_id` and `expire_logs_days` are returned by the same query but have no required value — just check `server_id` is non-zero (0 disables binary logging entirely, a silent failure mode) and note `expire_logs_days` is a legacy pre-8.0 setting normally showing 0 on HeatWave (superseded by `binlog_expire_logs_seconds`). This whole check is implemented and unit-tested: `tishift_heatwave/core/scan/analyzers/binlog_check.py` (rule IDs HW-WARNING-4..9).

**Step 2.1b — Other server settings:**
```
mysql -h $SRC_HOST -P 3306 -u $SRC_USER --password="$SRC_PWD" -e "
SELECT @@gtid_mode, @@character_set_server,
       @@collation_server, @@sql_mode, @@lower_case_table_names, @@transaction_isolation"
```

Record for the assessment: TiDB Cloud only supports `lower_case_table_names = 2`; if the source is 0 or 1, flag WARNING-8 (and check the table list from Step 2.2 for any names that only differ by case — that's BLOCKER-9, not just a warning, since TiDB can't represent both). Note the default collation. (`binlog_row_value_options` is gated by the Step 2.1a precheck — rule HW-WARNING-5.)

**Step 2.2 — Tables and sizes:**
```
mysql -h $SRC_HOST -P 3306 -u $SRC_USER --password="$SRC_PWD" -e "
SELECT TABLE_NAME, ENGINE, TABLE_ROWS, DATA_LENGTH, INDEX_LENGTH,
       TABLE_COLLATION, CREATE_OPTIONS
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = '$DB' AND TABLE_TYPE = 'BASE TABLE'
ORDER BY DATA_LENGTH DESC"
```

Watch `CREATE_OPTIONS` for `SECONDARY_ENGINE="RAPID"` (RAPID-offloaded) and `ENGINE` values other than InnoDB (Lakehouse external tables). Sum DATA_LENGTH + INDEX_LENGTH against tier capacity (25 GiB on Starter).

**Step 2.3 — RAPID-offloaded tables (only if Step 1.2 found a cluster):**
```
mysql -h $SRC_HOST -P 3306 -u $SRC_USER --password="$SRC_PWD" -e "
SELECT TABLE_SCHEMA, TABLE_NAME
FROM information_schema.TABLES
WHERE CREATE_OPTIONS LIKE '%SECONDARY_ENGINE%' AND TABLE_SCHEMA = '$DB'"
```

These tables serve analytics from the HeatWave cluster today. They map to TiFlash replicas on every tier (emitted in Phase 4) — TiDB Cloud Starter/Serverless supports TiFlash replicas too.

**Step 2.4 — Lakehouse external tables and AutoML schemas:**
```
mysql -h $SRC_HOST -P 3306 -u $SRC_USER --password="$SRC_PWD" -e "
SELECT TABLE_SCHEMA, TABLE_NAME, ENGINE FROM information_schema.TABLES WHERE ENGINE = 'Lakehouse';
SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME LIKE 'ML\\_SCHEMA\\_%'"
```

Both are blockers if present (HW-BLOCKER-1, HW-BLOCKER-2): Lakehouse table data lives in Object Storage, and AutoML schemas hold model catalogs with no TiDB equivalent. They must be excluded from migration scope and handled externally.

**Step 2.5 — Programmable objects:**
```
mysql -h $SRC_HOST -P 3306 -u $SRC_USER --password="$SRC_PWD" -e "
SELECT ROUTINE_TYPE, EXTERNAL_LANGUAGE, COUNT(*) AS n
FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA = '$DB'
GROUP BY ROUTINE_TYPE, EXTERNAL_LANGUAGE;
SELECT COUNT(*) AS trigger_count FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA = '$DB';
SELECT COUNT(*) AS event_count FROM information_schema.EVENTS WHERE EVENT_SCHEMA = '$DB'"
```

`EXTERNAL_LANGUAGE = 'JAVASCRIPT'` rows are MLE stored programs (HW-BLOCKER-3). All stored procedures, triggers, and events need application-code conversion (BLOCKER-1/2/3).

**Step 2.6 — Type and index hotspots:**
```
mysql -h $SRC_HOST -P 3306 -u $SRC_USER --password="$SRC_PWD" -e "
SELECT DATA_TYPE, COUNT(*) AS n FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = '$DB' AND DATA_TYPE IN
  ('vector','geometry','point','linestring','polygon','multipoint','multilinestring','multipolygon','geometrycollection')
GROUP BY DATA_TYPE;
SELECT INDEX_TYPE, COUNT(DISTINCT TABLE_NAME, INDEX_NAME) AS n
FROM information_schema.STATISTICS
WHERE TABLE_SCHEMA = '$DB' AND INDEX_TYPE IN ('FULLTEXT','SPATIAL') GROUP BY INDEX_TYPE;
SELECT COLLATION_NAME, COUNT(*) AS n FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = '$DB' AND COLLATION_NAME LIKE 'utf8mb4\\_0900%' GROUP BY COLLATION_NAME;
SELECT COUNT(*) AS fk_count FROM information_schema.REFERENTIAL_CONSTRAINTS WHERE CONSTRAINT_SCHEMA = '$DB'"
```

**Step 2.7 — Character sets and views:**
```
mysql -h $SRC_HOST -P 3306 -u $SRC_USER --password="$SRC_PWD" -e "
SELECT CHARACTER_SET_NAME, COUNT(*) AS n FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = '$DB' AND CHARACTER_SET_NAME IS NOT NULL
  AND CHARACTER_SET_NAME NOT IN ('ascii','latin1','binary','utf8','utf8mb4','gbk')
GROUP BY CHARACTER_SET_NAME;
SELECT TABLE_NAME, IS_UPDATABLE FROM information_schema.VIEWS WHERE TABLE_SCHEMA = '$DB'"
```
Any charset row returned is BLOCKER-8 — TiDB rejects those columns outright (docs.pingcap.com/tidbcloud/mysql-compatibility lists `ascii`/`latin1`/`binary`/`utf8`/`utf8mb4`/`gbk` as the complete supported set). Views with `IS_UPDATABLE = 'YES'` are WARNING-9 — TiDB views are always read-only, so any write path through the view needs to move to the underlying table(s).

**Gate:** You now have the full checklist — table count/size, RAPID tables, Lakehouse tables, AutoML schemas, routines by language, triggers, events, VECTOR/spatial columns, FULLTEXT indexes, 0900 collations, unsupported character sets, views/updatable views, FK count, `lower_case_table_names`, binlog config.

---

## Phase 3: Assess & Score

Load `references/compatibility-rules.md` and apply every rule against the Phase 2 checklist. Then load `references/scoring.md` and compute the 0-100 readiness score with per-category breakdowns.

Present to the user:
1. Blockers table (rule ID, feature, count, required action)
2. Warnings table
3. Readiness score with category breakdown and rating band
4. The RAPID → TiFlash story explicitly: analytics offload is not lost, it moves to TiFlash replicas (Essential/Dedicated)

If you ran `tishift-heatwave scan` directly rather than walking Step 2.1-2.6 manually, don't stop at the four points above — read back `tishift-reports/tishift-heatwave-report.md` (or the `--format cli` output already in the terminal) and display the complete report in the chat as your final message for this phase.

**Gate:** The user acknowledges the blockers and decides to proceed (possibly with reduced scope — e.g., excluding Lakehouse tables).

---

## Phase 4: Convert Schema

Generate TiDB-compatible DDL. Consult `references/type-mapping.md` for every table.

**Step 4.1 — Extract DDL:** For each table:
```
mysql -h $SRC_HOST -P 3306 -u $SRC_USER --password="$SRC_PWD" --raw -e "SHOW CREATE TABLE $DB.<table>\G"
```

**Step 4.2 — Transform.** Apply in order:
1. Comment out HeatWave-only clauses instead of deleting them, so the original text stays auditable: `SECONDARY_ENGINE=RAPID`, `SECONDARY_LOAD=...`, and `CLUSTERING BY (...)` each become `/* TISHIFT-REMOVED [rule-id]: <original clause> */`; standalone `ALTER TABLE ... SECONDARY_LOAD/SECONDARY_UNLOAD` statements become `-- TISHIFT-REMOVED [HW-DDL-2]: ...` line comments. `CLUSTERING BY` additionally gets a `/* TISHIFT-REVIEW ... */` comment with the suggested TiDB alternative (secondary index, or clustered PK when the columns are a PK prefix) — this one needs human sign-off. Column comments like `COMMENT 'RAPID_COLUMN=...'` are harmless and kept as-is. Use only plain `/* */` / `--` comments, never `/*! */` or `/*T! */`. The CLI automates this step: `tishift-heatwave convert --ddl-file schema.sql --tier <tier>` (see `references/compatibility-rules.md` § DDL cleanup rules).
2. Strip `ENCRYPTION='Y'` and other OCI-managed options
3. Keep `utf8mb4_0900_*` collations unchanged — supported natively on the target (TiDB Cloud v8.5; native since v7.4)
4. Convert spatial columns to JSON with `COMMENT 'was: <type>'`; drop SPATIAL indexes
5. Keep VECTOR columns for TiDB Cloud targets; rewrite vector index syntax
6. Review AUTO_INCREMENT PKs — suggest AUTO_RANDOM for high-insert tables
7. Convert any column flagged by Step 2.7 (BLOCKER-8) to a supported charset — `utf8mb4` by default
8. Rename any table flagged by Step 2.7/2.2 for case collision (BLOCKER-9) before applying the DDL — TiDB cannot hold both

**Step 4.3 — TiFlash replicas inline** (all tiers): for each RAPID table from Step 2.3, place the replica statement in the converted schema SQL **immediately after that table's `CREATE TABLE`**:
```sql
ALTER TABLE $DB.<table> SET TIFLASH REPLICA 2;
```
Trade-off to tell the user: because the replica exists before data load, TiFlash replicates during the import, which slows large loads — if import speed matters, they can remove the ALTERs from the schema file and run them after the load instead.

**Step 4.4 — Code stubs:** For each stored procedure, trigger, event, and JS routine, generate an application-code stub in the user's preferred language and list them as post-migration work.

**Step 4.5 — Apply DDL to target** and verify with `SHOW TABLES` / `SHOW CREATE TABLE` on TiDB. Extracting each table's DDL independently (Step 4.1) does not preserve FK dependency order — applying the concatenated file straight through can fail partway with `ERROR 1824: Failed to open the referenced table '<parent>'` if a child table's `CREATE TABLE` lands before its parent's. Wrap the apply in `SET FOREIGN_KEY_CHECKS=0; ... SET FOREIGN_KEY_CHECKS=1;` rather than hand-reordering the file. If an earlier attempt partially applied before failing, drop the tables it did create before re-applying — don't leave a half-created schema.

If you ran `tishift-heatwave convert` to do Step 4.2.1, read back `tishift-reports/ddl-cleanup-report.md` and display its complete contents in the chat before moving on — the rule-summary table, findings, manual-review items, and any parse errors, not just a count of hits.

**Gate:** All tables exist on the target with expected column counts.

---

## Phase 5: Load Data — NOT handled by this skill

**This phase is deliberately disabled.** Data loading is too high-stakes to delegate to this tool — the user must perform it independently, outside this skill. Do not generate, run, or walk the user through export/import commands, and do not invoke `tishift-heatwave load` (it exits with an error by design).

When you reach this phase, tell the user:

> Data loading is intentionally not handled by this skill. Please complete the export and import yourself, following your organization's change-control process. `docs/load-guide.md` and `references/load-strategies.md` document the recommended manual path (Dumpling export through the SSH tunnel, then tier-appropriate import: `ticloud serverless import` for Starter, direct load for Essential, Lightning for Dedicated). Remember to exclude `ML_SCHEMA_%` schemas and Lakehouse tables from the export filter. Let me know once the load has completed so we can continue with validation.

**Gate:** The user confirms they have completed the data load independently and the import finished without errors. Only then proceed to Phase 6.

---

## Phase 6: Validate

**Step 6.1 — Row counts:** For each table, compare:
```
mysql -h $SRC_HOST ... -e "SELECT COUNT(*) FROM $DB.<table>"
mysql -h $TARGET_HOST ... -e "SELECT COUNT(*) FROM $DB.<table>"
```

**Step 6.2 — Column structure:** Compare `information_schema.COLUMNS` (name, type, nullability) per table on both sides; expected diffs are the ones introduced deliberately in Phase 4 (collations, spatial→JSON).

**Step 6.3 — Sample checksums:** For tables with a numeric PK, compare `BIT_XOR(CRC32(CONCAT_WS('#', col1, col2, ...)))` over matching PK ranges on both sides.

**Step 6.4 — TiFlash replicas** (if Step 4.3 emitted replica statements):
```
mysql -h $TARGET_HOST ... -e "SELECT TABLE_NAME, AVAILABLE, PROGRESS FROM information_schema.tiflash_replica WHERE TABLE_SCHEMA = '$DB'"
```

**Gate:** Counts match, structures match modulo deliberate conversions, checksums agree, TiFlash replicas report AVAILABLE=1.

---

## Phase 7: Continue Replication Sync & Cutover (optional; Essential/Dedicated only)

Starter is cutover-only — skip to the cutover checklist.

**Preflight** (from Step 2.1a/2.1b — re-run Step 2.1a now if anything below fails):
- `log_bin=ON`, `binlog_format=ROW`, `binlog_row_image=FULL`, `binlog_transaction_compression=OFF`, `gtid_mode=ON`
- `binlog_expire_logs_seconds ≥ 86400` (1 day, hard minimum) — `≥ 604800` (7 days) recommended
- Migration user holds the grants below
- `binlog_row_value_options` must be empty (HW-WARNING-5, gated by the Step 2.1a precheck). If it showed `PARTIAL_JSON`, disable it now:
  ```
  mysql -h $SRC_HOST -P 3306 -u $SRC_USER --password="$SRC_PWD" -e "SET GLOBAL binlog_row_value_options = '';"
  ```
  DM cannot parse binlog rows written under partial-JSON mode; leaving it set causes silent replication corruption on JSON columns, not a clean failure. Run this before creating the DM task, and re-run Step 2.1a to confirm it took effect.

  **This `SET GLOBAL` frequently fails on OCI-managed HeatWave DB Systems** — even accounts with broad DDL/DML grants typically lack `SUPER`/`SYSTEM_VARIABLES_ADMIN`, so both this and the `binlog_expire_logs_seconds` fix return `ERROR 1227 (42000): Access denied; you need (at least one of) the SUPER or SYSTEM_VARIABLES_ADMIN privilege(s)`. When that happens, these are DB System configuration parameters, not SQL-settable — the user needs to change them via **OCI Console → DB System → Configuration**, not `SET GLOBAL`. Re-run Step 2.1a (or `scan --continue-replication`) afterward to confirm the change took effect.
- Source TLS is mandatory — DM's source connection needs the HeatWave CA certificate, same as scan/load (Step 1.1)

HeatWave supports outbound replication, so TiDB DM can attach as a replica through the same network path used for scan/load.

**Step 7.0 — Grant the DM migration users (source + target).** Source replication grants are instance-wide (binlog access is not schema-scoped); `SELECT` is granted per business schema and must be repeated for every schema in scope — missing it on any one schema is a common cause of precheck failures that look unrelated to permissions. The target user needs DDL + DML privileges on TiDB so DM can create/alter tables and apply changes:
```
mysql -h $SRC_HOST -P 3306 -u $SRC_USER --password="$SRC_PWD" -e "
GRANT REPLICATION SLAVE, REPLICATION CLIENT ON *.* TO '$DM_USER'@'%';
GRANT SELECT ON $DB.* TO '$DM_USER'@'%';"
```
```
mysql --ssl-mode=VERIFY_IDENTITY -h $TARGET_HOST -P 4000 -u $TARGET_USER -e "
GRANT CREATE, SELECT, INSERT, UPDATE, DELETE, ALTER, DROP, INDEX ON *.* TO '$DM_TARGET_USER'@'%';"
```

**Step 7.1 — Check every table has a valid (unique) index.** DM needs a primary key or unique index on each table to apply row changes deterministically; tables without one can replicate incorrectly or fail. Run against the source, replacing the schema exclusion list with every non-business schema on this HeatWave instance (system schemas, `mysql_autopilot`/`mysql_audit`/`mysql_tasks`, and any `ML_SCHEMA_%` AutoML schemas):
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
Any row returned is a business table with no PK/UNIQUE index — add one before starting sync, or exclude the table and document why it's safe to skip. (Automated: `tishift-heatwave scan --continue-replication` runs this same query during Phase 2 and reports "Tables without a valid index" — registry `tishift_heatwave/rules/valid_indexes.py`.)

**Step 7.2 — Scope the DM task to business schemas only.** When creating the task in the TiDB Cloud console, do **not** select "All Objects" — use an explicit `block-allow-list` naming the business schema(s) being migrated (the `$DB` used throughout this skill) and excluding HeatWave/MySQL system and management schemas:
```yaml
block-allow-list:
  instance:
    do-dbs: ["$DB"]
    ignore-dbs: ["mysql_autopilot", "mysql_audit", "mysql_tasks"]
```
Also exclude standard MySQL system schemas (`mysql`, `sys`, `performance_schema`, `information_schema`) and any `ML_SCHEMA_%` AutoML schemas (HW-BLOCKER-2) from `do-dbs`. Selecting "All Objects" instead of an explicit list either fails outright on these schemas or pulls in objects with no place on the target.

**This scoping is database-level only** — `do-dbs`/`ignore-dbs` can't exclude a single table within an in-scope database. If Phase 4's schema-convert deliberately left a table out of migration scope (e.g. a smoke-test table), DM will still replicate it alongside everything else in that database once the task starts, auto-creating it on the target with TiDB-native DDL. This is usually harmless if the table is empty or irrelevant, but it's schema drift the tool didn't originate and Phase 6's validation won't catch it unless you diff the *full* table list on both sides (not just the tables you converted) — do that once after the DM task is running. If it matters, ask about a dedicated migration schema instead, or budget for a manual `DROP TABLE` on the target after sync stabilizes.

DM task creation itself is TiDB Cloud **Console-only** for Essential/Dedicated tiers — the `ticloud` CLI only manages Serverless clusters (`ticloud serverless ...`), it has no Essential/Dedicated DM task commands. Give the user the block-allow-list above and the grants from Step 7.0 to paste into the Console form; don't expect to script this step.

**Optional — validate the DM task before trusting it for cutover.** Once the task is running, insert a small batch of clearly-tagged synthetic rows into the source in FK-safe order (parents before children — e.g. categories/customers/products before orders before order_items) using a prefix like `TISHIFT_TEST_` on name columns and `TT-*` on unique codes, so they're trivially identifiable. Re-run the Phase 6 row-count and checksum checks to confirm the DM task actually replicated them correctly — matching row counts alone isn't sufficient proof, checksums confirm content, not just totals. Delete the tagged rows from both sides once satisfied; never leave synthetic data in place through a real cutover.

**Step 7.3 — FK precheck warnings are expected, not blocking.** TiDB Cloud DM's precheck reports foreign-key warnings for this source; migrations proceed and replicate successfully with these warnings present. Before dismissing them, work through the **FK Pre-upgrade Checklist**:
- [ ] All FK-related parent and child tables are included in the task
- [ ] Any tables excluded from the task are confirmed not part of a required FK relationship
- [ ] Target TiDB schemas, tables, FK constraints, charset, and collation are already created and match source
- [ ] No PK/UK changes are expected on the source during replication
- [ ] No DDL or FK constraint changes are expected on the source during replication

If any item is unchecked, resolve it before proceeding — the FK warning itself is not the risk, an unmet checklist item is.

**Step 7.4 — Notify PingCAP in advance of the cutover window**, so the relevant team is aligned and available for support or rollback assistance if needed.

Set up a DM task with the HeatWave endpoint as source (users from Step 7.0, scoped per Step 7.2), monitor lag until it approaches zero, then cut over: stop writes on HeatWave, wait for lag = 0, repoint the application to TiDB, keep HeatWave read-only for the rollback window.

**Cutover checklist (all tiers):** application connection strings updated; stored-procedure/trigger/event replacements deployed; analytics queries verified against TiFlash; every business table has a valid index (Step 7.1); FK Pre-upgrade Checklist items all checked; PingCAP notified of the window; rollback window agreed.

**Executing cutover is the user's call, not this skill's.** This skill's job ends at a created, verified, healthy DM task (grants confirmed, valid-indexes precheck passed, FK checklist confirmed, sync spot-checked). Present the cutover checklist above as reference, but don't offer to run the stop-writes/repoint/monitor sequence yourself — that decision and its execution belong to the user or their TiDB account team, same as Phase 5's load is deliberately left to the user rather than automated.

### Non-destructive re-verification

If the user asks to "rerun" or independently re-confirm the migration after a DM task already exists, do **not** drop or recreate the target schema to do it — that would very likely break the running DM task, which can only be recreated via the Console (Step 7.2), not by this skill. Instead, re-run the read-only/idempotent parts against current live state: Phase 1 connectivity, `scan --continue-replication` (Phase 2/3), `convert --dry-run` (Phase 4, to confirm the applied DDL hasn't drifted from what the current source DDL would produce), Phase 6's validation queries, and Phase 7's grants/valid-indexes/checksum re-checks. Only fall back to a destructive rebuild if the user explicitly confirms they understand it will likely require recreating the DM task afterward.
