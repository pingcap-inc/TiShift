---
name: neon-to-tidb-migration
description: Migrate Neon or PostgreSQL databases to TiDB — assess readiness, convert schema, load data, and validate. Use this skill whenever someone mentions migrating from Neon, Postgres, or PostgreSQL to TiDB, wants to assess Postgres compatibility with TiDB, needs to convert PostgreSQL schema to MySQL/TiDB DDL, or is planning any Neon/Postgres to TiDB migration project, even if they don't use the word "migration" explicitly.
metadata:
  version: 0.1.0
---

# Neon/Postgres to TiDB Migration

This skill walks you through a complete Neon/Postgres to TiDB migration, one command at a time. The user runs each command and pastes the output back; you interpret the results and move to the next step. The reason for this call-and-response pattern is that database migrations are high-stakes — each step needs human verification before proceeding.

## How to use this skill

When the user provides database credentials, start Phase 1 immediately. Output one command, say "Run this and paste the output," and wait. Don't summarize all phases upfront or explain what you'll do — just execute.

**Security note:** Passwords on the command line are visible in shell history and process listings. Before starting, ask the user to set environment variables for credentials so passwords never appear in commands:
```
export PGPASSWORD="<source password>"
export MYSQL_PWD="<target password>"
```
`PGPASSWORD` is natively supported by psql (no password prompt). `MYSQL_PWD` is natively supported by the mysql client (no `-p` flag needed). If the user prefers not to use environment variables, they can use `.pgpass` / `-p` flags, but warn them about shell history exposure.

When pasting output back, remind the user to paste only the query results, not the command itself — this avoids credentials appearing in conversation history.

**Command format for Neon/Postgres:**
```
psql "postgres://$USER@$HOST/$DB?sslmode=require" -c "SQL"
```
For non-Neon Postgres without SSL:
```
psql -h $HOST -p $PORT -U $USER -d $DB -c "SQL"
```

**IMPORTANT — Neon connection strings:**
- Use the **direct (unpooled)** connection string. Pooled connections (with `-pooler` suffix or port 6543) will NOT work for `pg_dump`, `COPY`, or logical replication.
- If the user provides a pooled connection string, ask them to switch to the direct one (available in the Neon Console under Connection Details → uncheck "Pooled connection").

**Command format for TiDB (MySQL protocol):**
```
mysql -h $HOST -P $PORT -u $USER -e "SQL"
```

Substitute the user's actual values for `$HOST`, `$USER`, etc. Output one command per step — never combine queries.

---

## Phase 1: Connect

Verify connectivity to both source (Neon/Postgres) and target (TiDB Cloud).

Before connecting, ask the user which TiDB Cloud tier they're targeting:
- **Starter** (default) — free up to 25 GiB, ideal for assessment and small migrations
- **Essential** — production workloads, autoscaling, Changefeeds for CDC
- **Dedicated** — enterprise, full HTAP, Lightning, DM, PCI-DSS/SOC 2

This choice affects load strategy, CDC options, and constraint warnings throughout.

**Step 1.1 — Test source:**
```
psql "postgres://$USER@$HOST/$DB?sslmode=require" -c "SELECT version()"
```

Verify: output contains "PostgreSQL". Note the version number.

**Step 1.2 — Detect Neon:**
```
psql "postgres://$USER@$HOST/$DB?sslmode=require" -c "SELECT extname FROM pg_extension WHERE extname = 'neon'"
```

If "neon" is returned, the source is a Neon database. Apply Neon-specific constraints throughout.

**Step 1.3 — Test target:**

For TiDB Cloud Starter/Essential (TLS required):
```
mysql --ssl-mode=VERIFY_IDENTITY -h $TARGET_HOST -P 4000 -u $TARGET_USER -e "SELECT VERSION()"
```
For self-hosted TiDB:
```
mysql -h $TARGET_HOST -P $TARGET_PORT -u $TARGET_USER -e "SELECT VERSION()"
```

**Gate:** Both must return version strings. Source should show "PostgreSQL", target should show TiDB. If the target is TiDB Cloud and TLS fails, ensure the user has the correct CA certificate (ISRG Root X1 for Starter/Essential).

---

## Phase 2: Scan

Collect schema inventory from the Neon/Postgres source. Run all steps — each as a single command. `$DB` is the database name the user wants to migrate.

**Step 2.0 — Check connection type and stats freshness (Neon only):**
```
psql "postgres://$USER@$HOST/$DB?sslmode=require" -c "
SELECT current_setting('max_connections') AS max_connections,
       current_setting('wal_level') AS wal_level,
       pg_encoding_to_char(encoding) AS encoding
FROM pg_database WHERE datname = current_database()
"
```

If the user connected via a pooled endpoint, warn them and ask for the direct connection string.

Check stats freshness:
```
psql "postgres://$USER@$HOST/$DB?sslmode=require" -c "
SELECT COUNT(*) AS tables_without_stats
FROM pg_stat_user_tables
WHERE last_analyze IS NULL AND last_autoanalyze IS NULL
"
```
If most tables lack stats, recommend: `psql ... -c "ANALYZE"` before proceeding.

**Step 2.1 — Tables:**
```
psql "postgres://$USER@$HOST/$DB?sslmode=require" -c "
SELECT n.nspname AS schema, c.relname AS table_name, c.relkind AS kind,
       c.relpersistence AS persistence, c.reltuples::bigint AS row_estimate,
       pg_total_relation_size(c.oid) AS total_bytes,
       c.relrowsecurity AS rls_enabled, c.relhastriggers AS has_triggers
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname NOT IN ('pg_catalog','information_schema','pg_toast','neon')
  AND c.relkind IN ('r','p','v','m')
ORDER BY pg_total_relation_size(c.oid) DESC
"
```

**Step 2.2 — Columns:**
```
psql "postgres://$USER@$HOST/$DB?sslmode=require" -c "
SELECT table_schema, table_name, column_name, ordinal_position,
       column_default, is_nullable, data_type, udt_name,
       character_maximum_length, numeric_precision, numeric_scale,
       is_identity, is_generated
FROM information_schema.columns
WHERE table_schema NOT IN ('pg_catalog','information_schema')
ORDER BY table_schema, table_name, ordinal_position
"
```

**Step 2.3 — Indexes:**
```
psql "postgres://$USER@$HOST/$DB?sslmode=require" -c "
SELECT schemaname, tablename, indexname, indexdef
FROM pg_indexes
WHERE schemaname NOT IN ('pg_catalog','information_schema')
ORDER BY schemaname, tablename
"
```

**Step 2.4 — Constraints (PK, FK, UNIQUE, CHECK, EXCLUDE):**
```
psql "postgres://$USER@$HOST/$DB?sslmode=require" -c "
SELECT n.nspname AS schema, cl.relname AS table_name,
       c.conname AS constraint_name, c.contype,
       pg_get_constraintdef(c.oid) AS definition
FROM pg_constraint c
JOIN pg_class cl ON cl.oid = c.conrelid
JOIN pg_namespace n ON n.oid = c.connamespace
WHERE n.nspname NOT IN ('pg_catalog','information_schema')
ORDER BY n.nspname, cl.relname
"
```

**Step 2.5 — Functions and procedures:**
```
psql "postgres://$USER@$HOST/$DB?sslmode=require" -c "
SELECT n.nspname AS schema, p.proname AS name, p.prokind,
       l.lanname AS language, p.provolatile, p.prosecdef AS security_definer,
       pg_get_functiondef(p.oid) AS definition
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
JOIN pg_language l ON l.oid = p.prolang
WHERE n.nspname NOT IN ('pg_catalog','information_schema')
  AND l.lanname IN ('plpgsql','sql')
"
```

**Step 2.6 — Triggers:**
```
psql "postgres://$USER@$HOST/$DB?sslmode=require" -c "
SELECT trigger_schema, trigger_name, event_manipulation,
       event_object_table, action_timing, action_orientation,
       action_statement
FROM information_schema.triggers
WHERE trigger_schema NOT IN ('pg_catalog','information_schema')
"
```

**Step 2.7 — Views and materialized views:**
```
psql "postgres://$USER@$HOST/$DB?sslmode=require" -c "
SELECT n.nspname AS schema, c.relname AS view_name, c.relkind,
       pg_get_viewdef(c.oid, true) AS definition
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('v','m')
  AND n.nspname NOT IN ('pg_catalog','information_schema')
"
```

**Step 2.8 — Sequences:**
```
psql "postgres://$USER@$HOST/$DB?sslmode=require" -c "
SELECT sequence_schema, sequence_name, data_type,
       start_value, minimum_value, maximum_value, increment
FROM information_schema.sequences
WHERE sequence_schema NOT IN ('pg_catalog','information_schema')
"
```

**Step 2.9 — Custom types (enum, composite, range, domain):**
```
psql "postgres://$USER@$HOST/$DB?sslmode=require" -c "
SELECT n.nspname AS schema, t.typname AS type_name, t.typtype,
       CASE t.typtype
           WHEN 'e' THEN (SELECT string_agg(enumlabel, ', ' ORDER BY enumsortorder)
                          FROM pg_enum WHERE enumtypid = t.oid)
           WHEN 'd' THEN pg_catalog.format_type(t.typbasetype, t.typtypmod)
       END AS type_detail
FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
WHERE n.nspname NOT IN ('pg_catalog','information_schema','pg_toast')
  AND t.typtype IN ('c','e','r','d')
"
```

**Step 2.10 — Extensions:**
```
psql "postgres://$USER@$HOST/$DB?sslmode=require" -c "
SELECT extname, extversion FROM pg_extension ORDER BY extname
"
```

**Step 2.11 — Inheritance relationships:**
```
psql "postgres://$USER@$HOST/$DB?sslmode=require" -c "
SELECT p.relname AS parent, c.relname AS child
FROM pg_inherits i
JOIN pg_class p ON p.oid = i.inhparent
JOIN pg_class c ON c.oid = i.inhrelid
"
```

**Step 2.12 — Data profile:**
```
psql "postgres://$USER@$HOST/$DB?sslmode=require" -c "
SELECT pg_database_size(current_database()) AS db_size_bytes,
       (SELECT COUNT(*) FROM information_schema.tables
        WHERE table_schema NOT IN ('pg_catalog','information_schema')
          AND table_type = 'BASE TABLE') AS table_count
"
```

**Step 2.13 — RLS policies:**
```
psql "postgres://$USER@$HOST/$DB?sslmode=require" -c "
SELECT n.nspname AS schema, c.relname AS table_name,
       pol.polname AS policy_name, pol.polcmd
FROM pg_policy pol
JOIN pg_class c ON c.oid = pol.polrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
"
```

**Step 2.14 — Unlogged tables (Neon: data lost on restart):**
```
psql "postgres://$USER@$HOST/$DB?sslmode=require" -c "
SELECT n.nspname AS schema, c.relname AS table_name
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relpersistence = 'u'
  AND n.nspname NOT IN ('pg_catalog','information_schema')
"
```

**Gate:** All steps must succeed. Step 2.1 must return at least 1 table.

**Error recovery:** If a scan step fails:
- **Permission denied on pg_catalog views:** The user needs the `neon_superuser` role (Neon) or equivalent. On Neon, this is the default owner role — check the connection user.
- **Extension not found (pg_stat_statements):** Non-critical for scan. Skip query-pattern analysis, use default query score (17/20).
- **Timeout on large catalogs:** Suggest setting `statement_timeout` to 120 seconds. If it still times out, scan one schema at a time.

---

## Phase 2.5: Build the Checklist

Extract structured counts from the scan output. Fill in every field — no "unknown" or "N/A" allowed.

```
table_count, view_count, materialized_view_count
function_count, procedure_count, trigger_count
sequence_count, extension_count
enum_type_count, composite_type_count, range_type_count, domain_type_count
array_column_count, jsonb_column_count, uuid_column_count
bytea_column_count, tsvector_column_count, interval_column_count
inheritance_count, rls_table_count, unlogged_table_count
exclude_constraint_count, foreign_key_count
total_data_mb, largest_table_mb
pg_version, is_neon, wal_level, encoding
has_postgis, has_pgvector, has_hstore, has_ltree
```

**Gate:** Every field has a concrete value. `table_count > 0`.

---

## Phase 3: Assess Compatibility

Classify findings as BLOCKER, WARNING, or COMPATIBLE using the checklist. Read `references/compatibility-rules.md` for the complete rule set with IDs, descriptions, and recommended actions.

The key distinction: **blockers** are features TiDB fundamentally cannot do (arrays, JSONB operators, custom composite types, inheritance, RLS, PL/pgSQL execution, triggers, full-text search, range types, materialized views, EXCLUDE constraints, LISTEN/NOTIFY, PostGIS, pgvector). **Warnings** are features that work differently and need review (named ENUMs, sequences, RETURNING, UUID, SERIAL, advisory locks, domain types, BOOLEAN, unlogged tables, foreign keys, JSONB without operators, hstore, timestamptz, interval).

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
| Schema Compatibility | 25 | Arrays, JSONB, custom types, ranges, inheritance, RLS, materialized views, EXCLUDE, unsupported extensions |
| Procedural Code | 25 | PL/pgSQL function/procedure complexity (line count + features), triggers |
| Query Compatibility | 20 | Postgres-specific query patterns (JSONB operators, RETURNING, array ops, LISTEN/NOTIFY, advisory locks) |
| Data Complexity | 20 | Total data volume, largest table size, table count, BYTEA columns, unlogged tables |
| Operational Readiness | 10 | WAL level, pooled connection, stats freshness, PG version, encoding |

**Rating:** >= 90 excellent, 75-89 good, 50-74 moderate, 25-49 challenging, < 25 difficult.

Output a JSON score with per-category breakdowns and deduction explanations.

---

## *** USER GATE — DO NOT PROCEED WITHOUT EXPLICIT APPROVAL ***

**STOP HERE.** Present the full assessment and score to the user. Show:
1. The readiness score with per-category breakdown
2. All blockers with recommended actions
3. All warnings with recommended actions
4. Automation coverage estimate

Ask explicitly: **"Do you want to proceed with schema conversion? All blockers will be addressed as described above."**

Do NOT continue to Phase 5 until the user explicitly approves.

---

## Phase 5: Convert Schema

Generate TiDB-compatible DDL. Read `references/type-mapping.md` for the complete Postgres → TiDB type mapping table, and `references/function-mapping.md` for Postgres → MySQL function translations.

**Key conversion rules:**
- `serial` → `INT AUTO_INCREMENT`, `bigserial` → `BIGINT AUTO_INCREMENT`
- `boolean` → `TINYINT(1)`
- `bytea` → `LONGBLOB`
- `uuid` → `VARCHAR(36)` (with comment about `UUID()` function)
- `jsonb` → `JSON` (with comment about lost binary optimization)
- `timestamptz` → `DATETIME(6)` (with comment about timezone handling)
- `interval` → `VARCHAR(255)` (with comment about lost interval arithmetic)
- Arrays → `JSON` (with comment about rewritten operators)
- Named ENUMs → inline `ENUM(...)` in column definition
- Sequences → `AUTO_INCREMENT` on owning column
- All tables: `ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci`

**Schema handling:** If the scan found non-`public` schemas, present these options:
1. **Flatten** (recommended): `public.users` → `users`, `analytics.events` → `analytics_events`
2. **Prefix**: all non-public tables get schema prefix
3. **Separate databases**: each Postgres schema → separate TiDB database

If only `public` exists, proceed with direct mapping.

**Output files:**
- `01-create-tables.sql` — CREATE TABLE with type mappings
- `02-create-indexes.sql` — secondary indexes (drop before load, recreate after for 3-5x speed)
- `03-create-views.sql` — views with function translations
- `04-foreign-keys.sql` — ALTER TABLE ADD FOREIGN KEY
- `05-conversion-notes.md` — functions, triggers, extensions requiring manual conversion

**Gate:** No Postgres types remain in output. Every SERIAL → AUTO_INCREMENT. Special types annotated with COMMENTs.

---

## Phase 6: Load Data

Transfer data using the strategy matched to the target tier and data volume:

| Tier | Data Size | Strategy | Method |
|---|---|---|---|
| **Starter** | Any (≤ 25 GiB) | ticloud import | `COPY TO STDOUT CSV` → CSV → `ticloud serverless import start` |
| **Essential** | < 50 GB | Direct | `COPY TO STDOUT CSV` → `LOAD DATA LOCAL INFILE` |
| **Essential** | 50-500 GB | DMS | AWS DMS (PostgreSQL source → MySQL target) |
| **Dedicated** | < 50 GB | Direct | `COPY TO STDOUT CSV` → `LOAD DATA LOCAL INFILE` |
| **Dedicated** | 50-500 GB | DMS | AWS DMS (PostgreSQL source → MySQL target) |
| **Dedicated** | > 500 GB | Lightning | CSV → S3 → TiDB Lightning physical import |

**Starter loading steps (ticloud import):**
1. Apply schema: `mysql --ssl-mode=VERIFY_IDENTITY -h $HOST -P 4000 -u $USER $DB < 01-create-tables.sql`
2. Export per table:
   ```
   psql "postgres://$USER@$HOST/$DB?sslmode=require" \
     -c "\COPY $SCHEMA.$TABLE TO STDOUT WITH (FORMAT csv, HEADER, NULL '\N')" > $TABLE.csv
   ```
3. Split CSVs larger than 250 MiB: `split -b 250m "$TABLE.csv" "$TABLE.part."`
4. Import per file: `ticloud serverless import start --cluster-id $CLUSTER_ID --project-id $PROJECT_ID --source-type LOCAL --local.file-path "$FILE" --local.target-database $DB --local.target-table $TABLE`
5. Recreate indexes: `mysql ... $DB < 02-create-indexes.sql`
6. Apply foreign keys: `mysql ... $DB < 04-foreign-keys.sql`

**Direct loading steps (Essential/Dedicated):**
1. Apply schema: `mysql ... $DB < 01-create-tables.sql`
2. Export per table (CSV via COPY):
   ```
   psql "postgres://$USER@$HOST/$DB?sslmode=require" \
     -c "\COPY $SCHEMA.$TABLE TO STDOUT WITH (FORMAT csv, HEADER, NULL '\N')" > $TABLE.csv
   ```
3. Load per table: `mysql ... -e "LOAD DATA LOCAL INFILE '$TABLE.csv' INTO TABLE $TABLE FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '\"' LINES TERMINATED BY '\n' IGNORE 1 LINES"`
4. Recreate indexes: `mysql ... $DB < 02-create-indexes.sql`
5. Apply foreign keys: `mysql ... $DB < 04-foreign-keys.sql`

**Gate:** Get user confirmation before loading. Schema must apply cleanly. All tables loaded without errors.

**Error recovery:**
- **Schema apply fails:** Show the exact error. Common causes: reserved word as column name (wrap in backticks), type mapping missed (check `references/type-mapping.md`), duplicate key name. Fix the DDL file and re-apply.
- **COPY export fails:** Usually permissions or connection issues. Verify the connection is unpooled (direct). For large tables, consider `pgcopydb` for parallel export.
- **LOAD DATA fails partway:** Note which tables succeeded. For failed tables, check partial load (`SELECT COUNT(*) FROM table`), `TRUNCATE TABLE`, and retry.
- **Foreign key apply fails:** Check that referenced table was loaded and referential integrity holds.

---

## Phase 7: Validate

Compare source and target to confirm data integrity.

**Step 7.1 — Source row counts:**
```
psql "postgres://$USER@$HOST/$DB?sslmode=require" -c "
SELECT schemaname, relname AS table_name, n_live_tup AS row_count
FROM pg_stat_user_tables
ORDER BY schemaname, relname
"
```

**Step 7.2 — Target row counts:**
```
mysql ... -e "
SELECT table_schema, table_name, table_rows
FROM information_schema.tables
WHERE table_schema = '$DB'
ORDER BY table_name
"
```

Compare row counts. Flag any difference > 1%.

**Step 7.3-7.4 — Column structure:** Compare column names, mapped types, and nullability between source (`information_schema.columns` on Postgres) and target (`information_schema.columns` on TiDB).

Report: matching tables, mismatched tables (with details), missing tables in either direction.

**Gate:** Zero mismatches = migration verified.

**Error recovery:**
- **Row count difference 1-5%:** Likely caused by concurrent writes during export. Re-export and re-load only affected tables. Consider a maintenance window or CDC for final cutover.
- **Row count difference > 5%:** Check for COPY/LOAD DATA errors, encoding issues, or NULL handling mismatches. Truncate and re-load.
- **Column type mismatch:** Compare against `references/type-mapping.md` and fix DDL. Use `ALTER TABLE MODIFY COLUMN` if table has data.

---

## Decision Points

After all phases, apply these rules:

- If `total < 25`: warn about difficult migration requiring significant manual work
- If blockers exist: they must be resolved before loading data — ask how each should be handled
- If `function_count > 0 OR procedure_count > 0`: offer to generate application code stubs (Python/Go/Java/JS)
- If `trigger_count > 0`: triggers must move to application middleware — ask which language
- If `has_postgis OR has_pgvector`: these require separate infrastructure (dedicated geo service or vector DB)

**Tier-specific decisions:**
- If `tier == "starter" AND total_data_mb > 25600`: Starter cannot hold this data within the free tier. Recommend Essential or Dedicated.
- If `tier == "starter"`: skip the sync phase entirely — Starter has no Changefeeds or DM. Migration must be cutover with scheduled downtime.
- If `tier == "starter"`: warn about 30-minute transaction timeout. Large LOAD DATA operations may need to be batched.
- If `tier != "starter" AND wal_level != 'logical'`: warn and suggest enabling logical replication for live sync (irreversible in Neon).

---

## Reference files

Read these when you need detailed lookup tables during conversion:

- `references/type-mapping.md` — Complete Postgres → TiDB type mapping with precision handling
- `references/compatibility-rules.md` — All blocker and warning rules with IDs, detection patterns, compatible features
- `references/function-mapping.md` — Postgres → MySQL function translations, JSON operator mapping
- `references/scoring.md` — Detailed scoring pseudocode for all 5 categories
