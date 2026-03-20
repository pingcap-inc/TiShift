---
name: sqlserver-to-tidb-migration
description: Migrate SQL Server databases to TiDB — assess readiness, convert schema, load data, and validate. Use this skill whenever someone mentions migrating from SQL Server or MSSQL to TiDB, wants to assess SQL Server compatibility with TiDB, needs to convert T-SQL schema to MySQL/TiDB DDL, or is planning any SQL Server to TiDB migration project, even if they don't use the word "migration" explicitly.
metadata:
  version: 0.3.0
---

# SQL Server to TiDB Migration

This skill walks you through a complete SQL Server → TiDB migration, one command at a time. The user runs each command and pastes the output back; you interpret the results and move to the next step. The reason for this call-and-response pattern is that database migrations are high-stakes — each step needs human verification before proceeding.

## How to use this skill

When the user provides database credentials, start Phase 1 immediately. Output one command, say "Run this and paste the output," and wait. Don't summarize all phases upfront or explain what you'll do — just execute.

**Security note:** Passwords on the command line are visible in shell history and process listings. Before starting, ask the user to set environment variables for credentials so passwords never appear in commands:
```
export SQLCMD_PASSWORD="<source password>"
export MYSQL_PWD="<target password>"
```
`SQLCMD_PASSWORD` is natively supported by sqlcmd (no `-P` flag needed). `MYSQL_PWD` is natively supported by the mysql client (no `-p` flag needed). If the user prefers not to use environment variables, they can use `-P` / `-p` flags, but warn them about shell history exposure.

When pasting output back, remind the user to paste only the query results, not the command itself — this avoids credentials appearing in conversation history.

**Command format for SQL Server:**
```
sqlcmd -S $HOST -U $USER -d $DB -Q "SQL"
```
For Windows Authentication, replace `-U $USER` with `-E` (no password needed).
For named instances, use `-S $HOST\$INSTANCE`.

**Command format for TiDB (MySQL protocol):**
```
mysql -h $HOST -P $PORT -u $USER -e "SQL"
```

Substitute the user's actual values for `$HOST`, `$USER`, etc. Output one command per step — never combine queries.

---

## Phase 1: Connect

Verify connectivity to both source (SQL Server) and target (TiDB Cloud).

Before connecting, ask the user which TiDB Cloud tier they're targeting:
- **Starter** (default) — free up to 25 GiB, ideal for assessment and small migrations
- **Essential** — production workloads, autoscaling, Changefeeds for CDC
- **Dedicated** — enterprise, full HTAP, Lightning, DM, PCI-DSS/SOC 2

This choice affects load strategy, CDC options, and constraint warnings throughout.

**Step 1.1 — Test source:**
```
sqlcmd -S $SOURCE_HOST -U $SOURCE_USER -Q "SELECT @@VERSION"
```

**Step 1.2 — Test target:**

For TiDB Cloud Starter/Essential (TLS required):
```
mysql --ssl-mode=VERIFY_IDENTITY -h $TARGET_HOST -P 4000 -u $TARGET_USER -e "SELECT VERSION()"
```
For self-hosted TiDB:
```
mysql -h $TARGET_HOST -P $TARGET_PORT -u $TARGET_USER -e "SELECT VERSION()"
```

**Gate:** Both must return version strings. Source should show "Microsoft SQL Server", target should show TiDB. If the target is TiDB Cloud and TLS fails, ensure the user has the correct CA certificate (ISRG Root X1 for Starter/Essential).

---

## Phase 2: Scan

Collect schema inventory from the SQL Server source. Run all 15 steps — each as a single command. `$DB` is the database name the user wants to migrate.

Read `references/scan-queries.md` for the exact SQL for each step. The step numbers below are logical identifiers, not a strict execution order — start with Step 2.13 (server metadata) to determine the SQL Server version before running the other steps, since the version controls whether `STRING_AGG` is available (2017+) or needs the `FOR XML PATH` fallback. After that, run the remaining steps in any order.

| Step | What |
|---|---|
| 2.13 | Server metadata (version, edition, auth mode) — **run this first** |
| 2.1 | Tables (name, rows, size, memory-optimized, temporal, heap) |
| 2.2 | Columns (type, length, precision, identity, computed, filestream, collation) |
| 2.3 | Indexes (type, unique, PK, filtered, columns) |
| 2.4 | Foreign keys (references, cascade actions) |
| 2.5 | Stored procedures and functions (definition, CLR flag) |
| 2.6 | Triggers (table, instead-of flag, definition) |
| 2.7 | Views (definition, indexed flag) |
| 2.8 | CLR assemblies |
| 2.9 | Linked servers |
| 2.10 | SQL Agent jobs |
| 2.11 | Collation usage |
| 2.12 | Data profile (per-table row count + size in MB) |
| 2.14 | CDC status |
| 2.15 | SSIS presence |

See `references/scan-queries.md` for version fallbacks and catalog view compatibility notes.

**Gate:** All 15 steps must succeed. Step 2.1 must return at least 1 table.

**Error recovery:** If a scan step fails:
- **Permission denied on sys.\* views:** The user needs `VIEW SERVER STATE` or `VIEW DEFINITION` permissions. Output the specific `GRANT` command needed and ask them to have a DBA run it.
- **Invalid column name (e.g., `is_memory_optimized`, `temporal_type`):** The SQL Server version predates this feature. Drop the column from the query, set the corresponding checklist field to `false`/`0`, and continue.
- **msdb access denied (Step 2.10):** SQL Agent job scan is non-critical. Record `agent_job_count = 0`, note the skip, and continue.
- **Timeout on large catalogs:** Suggest the user add `-t 120` to `sqlcmd` for a 2-minute timeout. If it still times out, split the query to scan one schema at a time.
- For any other error, show the user the error message and ask them to investigate before retrying the step. Don't skip steps silently.

---

## Phase 2.5: Build the Checklist

Extract structured counts from the scan output. Fill in every field — no "unknown" or "N/A" allowed.

```
table_count, stored_procedure_count, function_count, clr_routine_count
trigger_count, instead_of_trigger_count, view_count, indexed_view_count
assembly_count, linked_server_count, agent_job_count, foreign_key_count
identity_column_count, computed_column_count, filestream_column_count
has_spatial_columns, has_hierarchyid_columns, has_xml_columns
has_sql_variant_columns, has_image_columns, has_ntext_columns
has_filtered_indexes, has_columnstore_indexes
has_memory_optimized, has_temporal_tables, has_heap_tables
non_standard_collation_count, total_data_mb, largest_table_mb
sql_version, edition, is_cdc_enabled, has_ssis, windows_auth_only
```

**Gate:** Every field has a concrete value. `table_count > 0`.

---

## Phase 3: Assess Compatibility

Classify findings as BLOCKER, WARNING, or COMPATIBLE using the checklist. Read `references/compatibility-rules.md` for the complete rule set with IDs, descriptions, and recommended actions.

The key distinction: **blockers** are features TiDB fundamentally cannot do (stored procedures, triggers, CLR, spatial types, XML, MERGE, cursors, Service Broker). **Warnings** are features that work differently and need review (IDENTITY → AUTO_INCREMENT is non-sequential, computed columns, filtered indexes, temporal tables, Agent jobs).

IDENTITY columns are a warning, never a blocker — TiDB's AUTO_INCREMENT works, it just produces non-sequential values across cluster nodes.

Also scan routine/trigger/view definitions for T-SQL patterns (MERGE, FOR XML, OPENQUERY, DECLARE CURSOR, etc.) — see the detection patterns in `references/compatibility-rules.md`.

**Tier-specific constraints** — apply these on top of the base TiDB rules:

| Constraint | Starter | Essential | Dedicated |
|---|---|---|---|
| Storage limit | 25 GiB free (metered beyond) | No cap | No cap |
| Max connections | 400 (5,000 with spend limit) | Auto-scaled | Configurable |
| Changefeeds (CDC sync) | Not available | Available | Available |
| Data Migration (DM) | Not available | Not available | Available |
| TiDB Lightning | Not available | Not available | Available |
| Transaction timeout | 30 minutes | No limit | No limit |
| Import method | `ticloud serverless import start` | Direct / DMS | Direct / DMS / Lightning |

If `total_data_mb > 25600` (25 GiB) and the target is Starter, flag it as a blocker and recommend Essential or Dedicated.

Output a JSON assessment:
```json
{
  "blockers": [{"id": "BLOCKER-1", "feature": "...", "count": N, "action": "..."}],
  "warnings": [{"id": "WARNING-1", "feature": "...", "count": N, "action": "..."}],
  "compatible": ["INT/BIGINT types", "Views", "Window functions", "..."]
}
```

---

## Phase 4: Score

Calculate a readiness score from 0-100 using 5 weighted categories. Read `references/scoring.md` for the exact pseudocode and deduction rules.

| Category | Max | What It Measures |
|---|---|---|
| Schema Compatibility | 25 | Unsupported types (spatial, hierarchyid, xml, sql_variant), temporal tables, memory-optimized, computed columns, non-dbo schemas |
| Procedural Code | 25 | Stored procedure complexity (line count + features), triggers, CLR assemblies, Agent jobs, SSIS |
| Query Compatibility | 20 | T-SQL patterns in definitions (MERGE, FOR XML, cursors, dynamic SQL). Default 16/20 if no definitions available |
| Data Complexity | 20 | Total data volume, largest table size, table count, collation diversity |
| Operational Readiness | 10 | CDC enabled, authentication mode |

**Rating:** >= 85 excellent, 70-84 good, 50-69 moderate, 25-49 challenging, < 25 difficult.

Output a JSON score with per-category breakdowns and deduction explanations.

---

## Phase 5: Convert Schema

Generate TiDB-compatible DDL. Read `references/type-mapping.md` for the complete SQL Server → TiDB type mapping table, and `references/function-mapping.md` for T-SQL → MySQL function translations and collation mapping.

**Key conversion rules:**
- `tinyint` → `TINYINT UNSIGNED` (SQL Server tinyint is 0-255)
- `money` → `DECIMAL(19,4)`, `datetime2(p)` → `DATETIME(MIN(p,6))`
- `uniqueidentifier` → `CHAR(36)`, `xml` → `LONGTEXT`, `hierarchyid` → `VARCHAR(255)`
- `IDENTITY` → `AUTO_INCREMENT` with a comment about non-sequential behavior
- All tables: `ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci`

**Schema mapping** — if the scan found non-dbo schemas, present these 3 options and ask the user to choose before generating DDL:

1. **Flatten** (recommended for most cases): `dbo.Users` → `Users`, `sales.Orders` → `sales_Orders`. Simple, everything in one TiDB database. Best when schemas are just organizational and don't have conflicting table names.
2. **Prefix**: all non-dbo tables get their schema as a prefix (`sales_Orders`, `hr_Employees`). Same as flatten but also prefixes dbo tables if there are name collisions.
3. **Separate databases**: each SQL Server schema becomes its own TiDB database (`sales` → `sales.Orders`, `hr` → `hr.Employees`). Best when schemas represent isolated domains with their own access controls, but adds cross-database query complexity.

If only `dbo` exists, skip this question and proceed with direct mapping (no prefix needed).

**Output files:**
- `01-create-tables.sql` — CREATE TABLE with type mappings
- `02-create-indexes.sql` — secondary indexes (drop before load, recreate after for 3-5x speed)
- `03-create-views.sql` — views with function translations
- `04-foreign-keys.sql` — ALTER TABLE ADD FOREIGN KEY
- `05-conversion-notes.md` — SPs, triggers, CLR requiring manual conversion

**Gate:** No SQL Server types remain in output. Every IDENTITY → AUTO_INCREMENT. Special types annotated with COMMENTs.

---

## Phase 6: Load Data

Transfer data using the strategy matched to the target tier and data volume:

| Tier | Data Size | Strategy | Method |
|---|---|---|---|
| **Starter** | Any (≤ 25 GiB) | ticloud import | BCP export → CSV → `ticloud serverless import start` |
| **Essential** | < 50 GB | Direct | BCP export → CSV → `LOAD DATA LOCAL INFILE` |
| **Essential** | 50-500 GB | DMS | AWS Database Migration Service (full load) |
| **Dedicated** | < 50 GB | Direct | BCP export → CSV → `LOAD DATA LOCAL INFILE` |
| **Dedicated** | 50-500 GB | DMS | AWS Database Migration Service (full load) |
| **Dedicated** | > 500 GB | Lightning | BCP → S3 → TiDB Lightning physical import |

**Starter loading steps (ticloud import):**
1. Apply schema: `mysql --ssl-mode=VERIFY_IDENTITY -h $HOST -P 4000 -u $USER $DB < 01-create-tables.sql`
2. Export per table: `bcp "$DB.$SCHEMA.$TABLE" out "$TABLE.csv" -S $HOST -U $USER -c -t "," -r "\n" -C 65001`
3. Split CSVs larger than 250 MiB: `split -b 250m "$TABLE.csv" "$TABLE.part."`
4. Import per file: `ticloud serverless import start --cluster-id $CLUSTER_ID --project-id $PROJECT_ID --source-type LOCAL --local.file-path "$FILE" --local.target-database $DB --local.target-table $TABLE`
5. Recreate indexes: `mysql ... $DB < 02-create-indexes.sql`
6. Apply foreign keys: `mysql ... $DB < 04-foreign-keys.sql`

For files under 250 MiB, users can alternatively upload via the TiDB Cloud console Import page.

**Direct loading steps (Essential/Dedicated):**
1. Apply schema: `mysql ... $DB < 01-create-tables.sql`
2. Export per table: `bcp "$DB.$SCHEMA.$TABLE" out "$TABLE.csv" -S $HOST -U $USER -c -t "," -r "\n" -C 65001`
3. Load per table: `mysql ... -e "LOAD DATA LOCAL INFILE '$TABLE.csv' INTO TABLE ..."`
4. Recreate indexes: `mysql ... $DB < 02-create-indexes.sql`
5. Apply foreign keys: `mysql ... $DB < 04-foreign-keys.sql`

**Gate:** Get user confirmation before loading. Schema must apply cleanly. All tables loaded without errors.

**Error recovery:**
- **Schema apply fails:** Show the exact error. Common causes: reserved word as column name (wrap in backticks), type mapping missed (check `references/type-mapping.md`), duplicate key name. Fix the DDL file and re-apply — don't ask the user to edit SQL manually.
- **BCP export fails:** Usually permissions or path issues. Verify the output directory exists and the SQL Server service account can write to it. For large tables, add `-b 100000` to set batch size.
- **LOAD DATA fails partway:** Note which tables succeeded and which failed. For the failed table, check if rows were partially loaded (`SELECT COUNT(*) FROM table`). If so, `TRUNCATE TABLE` and retry. Don't re-load tables that already succeeded.
- **Foreign key apply fails:** Usually a missing referenced table or data integrity issue. Show which FK failed, check that the referenced table was loaded, and verify referential integrity with a query before retrying.

---

## Phase 7: Validate

Compare source and target to confirm data integrity.

**Step 7.1-7.2:** Row counts — `sys.partitions` on source vs `information_schema.tables` on target. Flag any difference > 1%.

**Step 7.3-7.4:** Column structure — compare column names, types, and nullability between source (`sys.columns + sys.types`) and target (`information_schema.columns`).

Report: matching tables, mismatched tables (with details), missing tables in either direction.

**Gate:** Zero mismatches = migration verified.

**Error recovery:**
- **Row count difference 1-5%:** Likely caused by concurrent writes during export. Re-export and re-load only the affected tables. If the source is still active, consider enabling CDC or a maintenance window for the final cutover.
- **Row count difference > 5%:** Something went wrong during load. Check for LOAD DATA errors in the mysql client output, verify the CSV file has the expected row count (`wc -l $TABLE.csv`), and look for encoding issues (BCP's `-C 65001` flag ensures UTF-8). Truncate and re-load the table.
- **Column type mismatch:** Usually a type mapping gap — compare the source type from Step 2.2 against `references/type-mapping.md` and fix `01-create-tables.sql`. If the table already has data, use `ALTER TABLE ... MODIFY COLUMN` rather than recreating.
- **Missing tables on target:** Check if the table was excluded from `01-create-tables.sql` (filtered views or system tables sometimes get mixed in) or if the CREATE TABLE failed silently. Re-apply the missing table's DDL and re-load its data.
- **Missing tables on source:** Tables that exist on target but not source indicate the scan is stale — a table may have been dropped after the scan. Drop the orphaned table from TiDB.

---

## Decision Points

After all phases, apply these rules:

- If `total < 25`: warn about difficult migration requiring significant manual work
- If blockers exist: they must be resolved before loading data — ask how each should be handled
- If `stored_procedure_count > 0`: offer to generate application code stubs (Python/Go/Java/JS)
- If `trigger_count > 0`: triggers must move to application middleware — ask which language
- If `assembly_count > 0`: CLR requires complete rewrite
- If `has_ssis`: SSIS packages need separate ETL redesign

**Tier-specific decisions:**
- If `tier == "starter" AND total_data_mb > 25600`: Starter cannot hold this data within the free tier. Recommend upgrading to Essential (autoscaling) or Dedicated (enterprise). Show the cost comparison.
- If `tier == "starter"`: skip the sync phase entirely — Starter has no Changefeeds or DM. The migration must be a cutover with scheduled downtime. Warn the user about planning a maintenance window.
- If `tier == "starter"`: warn about the 30-minute transaction timeout. Large LOAD DATA operations may need to be batched by table or by row range.
- If `tier == "essential" AND total_data_mb > 512000`: recommend upgrading to Dedicated for TiDB Lightning support.
- If `tier == "dedicated" AND total_data_mb > 512000`: recommend TiDB Lightning over direct load.
- If `tier != "starter" AND is_cdc_enabled = 0`: warn and suggest `ALTER DATABASE [$DB] SET CHANGE_DATA_CAPTURE ON` for live sync via Changefeeds.

---

## Reference files

Read these when you need detailed lookup tables during conversion:

- `references/scan-queries.md` — Exact SQL for all 15 Phase 2 scan steps, with version fallbacks for SQL Server 2016 and earlier
- `references/type-mapping.md` — Complete SQL Server → TiDB type mapping with length/precision handling
- `references/compatibility-rules.md` — All blocker and warning rules with IDs, T-SQL detection patterns, compatible features list
- `references/function-mapping.md` — T-SQL → MySQL function translations, collation mapping table
- `references/scoring.md` — Detailed scoring pseudocode for all 5 categories
