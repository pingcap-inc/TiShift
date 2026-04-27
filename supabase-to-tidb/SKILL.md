---
name: supabase-to-tidb-migration
description: Migrate Supabase databases to TiDB — assess readiness, extract RLS policies, convert schema, load data, and validate. Use this skill whenever someone mentions migrating from Supabase to TiDB, wants to assess Supabase compatibility with TiDB, needs to convert Supabase Postgres schema to MySQL/TiDB DDL, is planning any Supabase-to-TiDB migration project, or needs to understand what a move off Supabase involves (including the PostgREST / GoTrue / Realtime / Storage application-layer rewrite), even if they don't use the word "migration" explicitly.
metadata:
  version: 0.1.0
---

# Supabase to TiDB Migration

This skill walks you through a complete Supabase → TiDB migration, one command at a time. The user runs each command and pastes the output back; you interpret the results and move to the next step. The reason for this call-and-response pattern is that database migrations are high-stakes — each step needs human verification before proceeding.

Supabase is vanilla Postgres 15+ plus a stack of external services (PostgREST auto-REST API, GoTrue auth, Realtime WebSocket fanout, Storage with S3-compatible object bytes, Edge Functions, Supavisor pooler, plus a curated extension set). The database portion is what this skill migrates. The service-layer pieces are out of scope for the DB move and must be replaced separately — this skill surfaces them in the assessment so the user can plan the full project, not just the DB slice.

## How to use this skill

When the user provides database credentials, start Phase 1 immediately. Output one command, say "Run this and paste the output," and wait. Don't summarize all phases upfront or explain what you'll do — just execute.

**Security note:** Passwords on the command line are visible in shell history and process listings. Before starting, ask the user to set environment variables for credentials so passwords never appear in commands:
```
export PGPASSWORD="<supabase password>"
export MYSQL_PWD="<tidb password>"
```
`PGPASSWORD` is natively supported by `psql` (no `-W` flag needed). `MYSQL_PWD` is natively supported by the mysql client (no `-p` flag needed). If the user prefers not to use environment variables, they can use `-W` / `-p` flags, but warn them about shell history exposure.

When pasting output back, remind the user to paste only the query results, not the command itself — this avoids credentials appearing in conversation history.

**Command format for Supabase (psql):**
```
psql "postgres://postgres:$PGPASSWORD@$HOST:$PORT/$DB?sslmode=require" -c "SQL"
```

**Command format for TiDB (MySQL protocol):**
```
mysql -h $HOST -P $PORT -u $USER -e "SQL"
```

Substitute the user's actual values. Output one command per step — never combine queries.

---

## Phase 1: Connect

Verify connectivity to both source (Supabase) and target (TiDB). Before connecting, ask the user three questions:

1. **Which TiDB Cloud tier are you targeting?**
   - **Starter** (default) — free up to 25 GiB, ideal for assessment and small migrations
   - **Essential** — production workloads, autoscaling, Changefeeds for CDC
   - **Dedicated** — enterprise, full HTAP, Lightning, DM, PCI-DSS/SOC 2

2. **Which Supabase connection endpoint do you have?** Supabase provides three endpoints and each breaks differently:
   - **Direct** — `db.{project_ref}.supabase.co:5432`, user `postgres`. Required for Phase 8 (sync). On free tier: IPv6-only after the 2024 IPv4 change.
   - **Session pooler** — `aws-0-{region}.pooler.supabase.com:5432`, user `postgres.{project_ref}`. Works for Phases 2–7. Supports IPv4.
   - **Transaction pooler** — same host, port `6543`. **Refuse** — breaks `pg_dump`, prepared statements, and replication.

3. **Which Supabase services does your app use?** Track the answers — they drive the "external work checklist" in Phase 4.
   - PostgREST REST API (`supabase.from(...)` calls in client code)
   - GoTrue auth (`supabase.auth.*`)
   - Realtime subscriptions (`supabase.channel(...)`)
   - Storage (`supabase.storage.*`)
   - Edge Functions
   - pg_graphql (`/graphql/v1` endpoint)

**Step 1.1 — Test source:**
```
psql "postgres://postgres:$PGPASSWORD@$HOST:$PORT/postgres?sslmode=require" -c "SELECT version()"
```

If the user provides a transaction-mode URL (port 6543), stop and ask them for either the session pooler URL (port 5432 on the pooler host) or the direct URL (`db.{ref}.supabase.co:5432`). Do not attempt the scan on port 6543.

**Step 1.2 — Test target:**

For TiDB Cloud Starter/Essential (TLS required):
```
mysql --ssl-mode=VERIFY_IDENTITY -h $TARGET_HOST -P 4000 -u $TARGET_USER -e "SELECT VERSION()"
```
For self-hosted TiDB:
```
mysql -h $TARGET_HOST -P $TARGET_PORT -u $TARGET_USER -e "SELECT VERSION()"
```

**Gate:** Source must return a PostgreSQL version string (15.x or later on Supabase). Target must return a TiDB version. If the target is TiDB Cloud and TLS fails, ensure the user has the correct CA certificate (ISRG Root X1 for Starter/Essential).

---

## Phase 2: Scan

Collect the schema inventory, RLS policies, platform signals, and data profile. Every scan query applies the Supabase schema filter — excluding `auth`, `storage`, `realtime`, `_realtime`, `extensions`, `graphql`, `graphql_public`, `supabase_migrations`, `vault`, `pgsodium`, `pgsodium_masks`, `net`, `pgbouncer`, `_analytics`. These contain platform state and must never be shipped to TiDB.

Run all 14 steps, one command at a time. The step numbers are logical IDs, not strict execution order — but **run Step 2.11 (Postgres version + encoding) first** before the others, since the version controls extension availability and some catalog view columns.

| Step | What |
|---|---|
| 2.11 | Server metadata (Postgres version, encoding, `wal_level`, `max_connections`) — **run this first** |
| 2.1 | Tables (name, kind, persistence, row estimate, size, RLS flag) |
| 2.2 | Columns (type, nullable, default, identity, generated expression) |
| 2.3 | Indexes (type, unique, PK, columns, GIN/GiST detection) |
| 2.4 | Constraints (PK, FK, UNIQUE, CHECK, EXCLUDE) |
| 2.5 | Functions and procedures (language, definition, volatility, SECURITY DEFINER flag) |
| 2.6 | Triggers (table, timing, action) |
| 2.7 | Views (regular + materialized, definitions) |
| 2.8 | Sequences (start, increment, min/max, cycle) |
| 2.9 | Custom types (composite, enum, range, domain) |
| 2.10 | Extensions installed (version, schema) |
| 2.12 | Partitioned tables (strategy, partition key) |
| 2.13 | **RLS policies** (name, table, command, roles, USING/WITH CHECK expressions) — Supabase-critical |
| 2.14 | **Platform signals** (Supabase schema presence, Realtime slot, pg_cron jobs, pg_net call sites, foreign tables) — Supabase-specific |

Each query must filter on `WHERE n.nspname NOT IN (<exclusion list>)`. The exclusion list is in `config/tishift-supabase.example.yaml` and must not be overridden by the user.

**Gate:** All 14 steps must succeed. Step 2.1 must return at least 1 table from a user schema. If Step 2.13 returns zero policies AND Step 2.1 shows no tables with `relrowsecurity = true`, note it — a Supabase project with no RLS is unusual and may indicate a lifted-and-shifted app.

**Error recovery:**
- **Permission denied on `pg_authid` / `pg_statistic`:** The `postgres` role on Supabase is not a true superuser. Skip the affected detail — it's usually diagnostic, not load-bearing. Record the skip and continue.
- **`pg_stat_statements` empty or unavailable:** The extension may be disabled or the view may be reset. The Query Compatibility category falls back to 12/15. Record that `pg_stat_statements` was unavailable.
- **Auth or storage schema access denied:** The `postgres` role on some Supabase tiers cannot read `auth.users` or `storage.objects`. Report `auth_user_count = 0` and `storage_object_count = 0`, note the permission issue, and continue — these are diagnostic signals, not migration blockers.
- **Connection closes mid-scan:** Could indicate the transaction-mode pooler sneaking in, or a timeout on a large catalog. Verify the user is on session-mode pooler (port 5432) or direct endpoint, then retry.
- For any other error, show the user the error message and ask them to investigate before retrying. Don't skip steps silently.

---

## Phase 2.5: Build the Checklist

Extract structured counts from the scan output. Fill in every field — no "unknown" or "N/A" allowed.

```
# Inventory
table_count, view_count, materialized_view_count
function_count, procedure_count, trigger_count
sequence_count, foreign_key_count
index_count, gin_index_count, gist_index_count

# Column-level
uuid_column_count, array_column_count, jsonb_column_count
json_column_count, bytea_column_count, tsvector_column_count
serial_column_count, boolean_column_count, timestamptz_column_count

# Custom types
composite_type_count, enum_type_count, range_type_column_count, domain_type_count

# Schema features
unlogged_table_count, inheritance_count, exclude_constraint_count
has_foreign_tables, foreign_table_count

# Data profile
total_data_gb, largest_table_gb, per_table_row_counts

# Postgres / Supabase platform
pg_version, encoding, wal_level, max_connections
has_auth, auth_user_count
has_storage, storage_object_count, storage_total_gb
has_realtime, supabase_realtime_slot_active
has_graphql, pg_graphql_active
supabase_migrations_count

# Extensions (boolean per extension + call-site counts)
has_pgsodium, pgsodium_key_count
has_supabase_vault, vault_secrets_count
has_pgjwt, pgjwt_call_sites
has_pg_net, pg_net_call_sites
has_pg_cron, pg_cron_active_jobs, pg_cron_jobs_with_extension_deps
has_wrappers, wrappers_foreign_table_count
has_postgis, has_pgvector, has_pgcrypto, has_hstore, has_pg_trgm

# RLS
rls_policy_count
rls_tables_with_policies
rls_tables_enabled_no_policy
rls_policies_referencing_auth_uid
rls_policies_referencing_auth_jwt
rls_policies_with_subquery_or_join

# Procedural code features
functions_calling_auth_helpers
functions_with_security_definer
functions_with_dynamic_sql
functions_with_returning_clause
functions_with_cursor
extensions_qualified_call_sites

# Connection characteristics
connection_mode               # "direct" | "session_pooler" | "transaction_pooler_refused"
free_tier_ipv6_only_detected

# PostgREST heuristic inputs
grants_to_anon_count, grants_to_authenticated_count, grants_to_service_role_count
```

**Gate:** Every field has a concrete value. `table_count > 0`. `connection_mode` is never `transaction_pooler_refused` (should have been caught in Phase 1).

---

## Phase 3: Assess Compatibility

Classify findings as BLOCKER, WARNING, or COMPATIBLE using the checklist. Read `references/compatibility-rules.md` for the complete rule set with IDs, conditions, and recommended actions.

The key distinction: **blockers** are features TiDB fundamentally cannot do (stored functions execution, triggers, RLS, pgsodium encryption, pg_net HTTP, wrappers FDW, arrays, JSONB operators, materialized views, full-text search, ranges, composite types, PostGIS, pgvector). **Warnings** are features that work differently and need review (IDENTITY/SERIAL, UUID, sequences, ENUM, RETURNING, JSONB without operators, BOOLEAN → TINYINT(1), timestamptz, auth users, storage objects, Realtime slot, pg_graphql, pg_cron, `extensions.` qualifier, SECURITY DEFINER, supabase_migrations).

**The #1 blocker is RLS.** Every serious Supabase project has 20–80 policies. Extract each as a structured finding with `schema.table.policy_name`, `command`, `roles`, `using_expr`, `check_expr`, and complexity (`simple` = equality, `moderate` = AND/OR of simple terms, `complex` = subquery / JOIN / JSON-path). The output is not a "translated RLS" file — it's a rewrite checklist for the application/middleware team. Do NOT attempt to translate `CREATE POLICY` DDL to the target.

Also scan function and view definitions for the detection patterns in `references/compatibility-rules.md` — `auth.uid()`, `auth.jwt()`, `net.http_*`, JSONB operators, RETURNING, LISTEN/NOTIFY, extensions-qualified calls, pgjwt `sign()`/`verify()`.

**Tier-specific constraints** — apply these on top of the base rules:

| Constraint | Starter | Essential | Dedicated |
|---|---|---|---|
| Storage limit | 25 GiB free | No cap | No cap |
| Max connections | 400 (5,000 with spend limit) | Auto-scaled | Configurable |
| Changefeeds (CDC sync) | Not available | Available | Available |
| Data Migration (DM) | Not available | Not available | Available |
| TiDB Lightning | Not available | Not available | Available |
| Transaction timeout | 30 minutes | No limit | No limit |
| Import method | `ticloud serverless import start` | Direct / DMS | Direct / DMS / Lightning |

If `total_data_gb > 25` and the target is Starter, flag it as a blocker and recommend Essential or Dedicated.

Output a JSON assessment:
```json
{
  "blockers": [
    {"id": "BLOCKER-1", "feature": "Row-level security policies", "count": N,
     "action": "...", "findings": [{"schema": "public", "table": "...",
     "policy_name": "...", "command": "SELECT", "roles": ["authenticated"],
     "using_expr": "...", "check_expr": "...", "complexity": "simple"}]}
  ],
  "warnings": [{"id": "WARNING-1", "feature": "...", "count": N, "action": "..."}],
  "compatible": ["INT/BIGINT types", "VARCHAR", "Window functions", "..."],
  "external_work": [
    {"item": "PostgREST API replacement", "triggered_by": "grants_to_anon OR pg_graphql_active",
     "description": "..."},
    {"item": "GoTrue auth replacement", "triggered_by": "auth_user_count > 0", "description": "..."}
  ]
}
```

The `external_work` array is Supabase-specific and captures the out-of-band work (PostgREST rewrite, GoTrue migration, Realtime replacement, Storage bytes sync, pgsodium/Vault re-encryption, pg_graphql rewrite, pg_cron mapping, wrappers rewrite). Users must understand that the DB migration is ~30% of the total project; `external_work` describes the rest.

---

## Phase 4: Score

Calculate a readiness score from 0–100 using 5 weighted categories. Read `references/scoring.md` for the exact pseudocode and deduction rules.

| Category | Max | What it measures |
|---|---|---|
| Schema Compatibility | 20 | Postgres type diversity, extension dependencies, schema shape |
| Data Complexity | 15 | Data volume, per-table size, BYTEA count, Storage-object count |
| Query Compatibility | 15 | Postgres dialect features in queries (JSONB ops, RETURNING, arrays, LISTEN/NOTIFY, fulltext, extensions-qualified) |
| Procedural Code | 30 | PL/pgSQL functions + triggers + **RLS policies** (RLS is procedural code on Supabase) |
| Operational Readiness | 20 | Connection/WAL/stats + **Application Coupling** sub-signal (PostgREST/GoTrue/Realtime/Storage/pg_cron/Vault) |

**Rating:** ≥ 85 excellent, 70–84 good, 50–69 moderate, 25–49 challenging, < 25 difficult.

Expected Supabase project distribution:
- Hello-world SaaS (5 tables, 5 simple RLS policies, no extensions) → ~75–85
- Typical production SaaS (30 tables, 60 RLS policies, Auth+Storage+Realtime, 5 PL/pgSQL functions, pg_cron) → ~35–50
- Heavy-feature app (pgvector RAG, pg_net webhooks, Vault, 80+ policies, materialized views) → ~10–25

Output a JSON score with per-category breakdowns, deduction explanations, and the rating.

---

## USER GATE

**Stop here. Do not proceed to Phase 5 (convert) without explicit user approval.**

Show the user:

1. The readiness score (0–100) and rating.
2. The blocker list with counts.
3. The warning list with counts.
4. **The `external_work` checklist** — prominently. The user must understand that PostgREST, GoTrue, Realtime, Storage, pgsodium, pg_graphql, pg_cron, and pg_net are **not** solved by TiShift. They are parallel streams of work that must be planned alongside the DB migration.
5. A recommendation:
   - If score ≥ 75 and no unsolved blockers → proceed to Phase 5
   - If score 50–74 → call out the top 5 blockers and ask how the user plans to resolve each before proceeding
   - If score < 50 → recommend a phased migration or a discovery-level engagement before committing to dates

Ask explicitly: **"Have you reviewed the blockers, warnings, and external-work checklist? Are you ready to proceed to schema conversion (Phase 5)?"**

Do not proceed on implicit consent. Wait for an explicit yes.

---

## Phase 5: Convert Schema

Generate TiDB-compatible DDL. Read `references/type-mapping.md` for the complete Postgres → TiDB type mapping and `references/function-mapping.md` for function/operator translations.

**Key conversion rules:**
- `uuid` → `VARCHAR(36)` (readable) or `BINARY(16)` (compact) — ask user preference once
- `jsonb` → `JSON`
- `boolean` → `TINYINT(1)`
- `serial` / `bigserial` → `AUTO_INCREMENT`
- `timestamp with time zone` → `DATETIME(6)` with a comment about UTC enforcement
- `text[]` / any array → `JSON` with a comment noting normalization may be preferable
- Named enums → inline `ENUM(...)`
- `DEFAULT gen_random_uuid()` / `DEFAULT extensions.gen_random_uuid()` → `DEFAULT (UUID())`
- All tables: `ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci`

**Supabase-specific passes (these run BEFORE sqlglot):**
1. Strip `CREATE POLICY ...` statements entirely. Emit each to `05-rls-rewrite-checklist.md` with full expression text.
2. Strip `ALTER TABLE ... ENABLE/DISABLE/FORCE ROW LEVEL SECURITY` statements. Log.
3. Strip `CREATE PUBLICATION` / `CREATE SUBSCRIPTION` / `CREATE REPLICATION SLOT` statements. Log.
4. Strip the `extensions.` qualifier from function calls in views and generated-column expressions.
5. Flag — but do not strip — `auth.uid()` / `auth.jwt()` / `auth.role()` / `auth.email()` call sites inside function bodies and view definitions. Emit each to `05-rls-rewrite-checklist.md` with the enclosing object.
6. Detect `net.http_*`, `vault.*`, `cron.schedule()`, `graphql.resolve()`, and `supabase_vault` call sites. Emit to `05-rls-rewrite-checklist.md` as app-layer rewrite items.
7. Drop all references to `auth`, `storage`, `realtime`, `_realtime`, `extensions`, `graphql`, `graphql_public`, `supabase_migrations`, `vault`, `pgsodium`, `pgsodium_masks`, `net`, `pgbouncer`, `_analytics` schemas from DDL.

**Output files:**
- `01-create-tables.sql` — CREATE TABLE with type mappings (no RLS, no policies, user schemas only)
- `02-create-indexes.sql` — secondary indexes (drop before load, recreate after for 3–5x speed). Note: GIN / GiST indexes require manual redesign — emit as comments with an explanation.
- `03-create-views.sql` — views with function translations and `extensions.` stripped
- `04-foreign-keys.sql` — `ALTER TABLE ADD FOREIGN KEY` (TiDB v6.6+ enforces FKs)
- `05-rls-rewrite-checklist.md` — every RLS policy, `auth.*` call site, and platform-function call site as structured findings for the app/middleware rewrite team
- `06-conversion-notes.md` — functions, triggers, sequences, ENUMs requiring manual conversion
- `07-external-work-plan.md` — PostgREST / GoTrue / Realtime / Storage / pgsodium / pg_graphql / pg_cron / wrappers tracks with links back to the rules

**Gate:** No Postgres-only types remain in `01-create-tables.sql`. No `CREATE POLICY` statements in any `.sql` output. Every `auth.*` call site appears in `05-rls-rewrite-checklist.md`. Every `extensions.` qualifier in views is stripped. `01` applies cleanly on an empty TiDB database.

---

## Phase 6: Load Data

Transfer data using the strategy matched to the target tier and data volume. **The load command MUST use an explicit `--schema` allow-list.** Never `pg_dump` the whole database — that ships `auth.users` (including password hashes) and `storage.objects` (metadata with internal IDs) to the target.

| Tier | Data Size | Strategy | Method |
|---|---|---|---|
| **Starter** | Any (≤ 25 GiB) | ticloud import | `pg_dump --schema=public -Fc` → CSV per table → `ticloud serverless import start` |
| **Essential** | < 50 GB | Direct | `pg_dump --schema=public -Fc` → CSV per table → `LOAD DATA LOCAL INFILE` |
| **Essential** | 50–500 GB | DMS | AWS DMS PostgreSQL source → MySQL target, with explicit table include-list |
| **Dedicated** | < 50 GB | Direct | Same as Essential |
| **Dedicated** | 50–500 GB | DMS | Same as Essential |
| **Dedicated** | > 500 GB | Lightning | CSV → S3 → TiDB Lightning physical import |

**Connection mode for load:**
- Session-mode pooler (port 5432 on pooler host) works for `pg_dump` and CSV extraction. Use this for free-tier projects on IPv6-only hosts.
- Direct endpoint works too and is preferred when the local host has IPv6.
- Transaction-mode pooler (port 6543) is refused.

**Starter loading steps (`ticloud` import):**
1. Apply schema: `mysql --ssl-mode=VERIFY_IDENTITY -h $HOST -P 4000 -u $USER $DB < 01-create-tables.sql`
2. Export per table (schema filter is mandatory): `psql "$CONN" -c "\COPY (SELECT * FROM public.$TABLE) TO '$TABLE.csv' WITH CSV HEADER"`
3. Split CSVs larger than 250 MiB: `split -b 250m "$TABLE.csv" "$TABLE.part."`
4. Import per file: `ticloud serverless import start --cluster-id $CLUSTER_ID --project-id $PROJECT_ID --source-type LOCAL --local.file-path "$FILE" --local.target-database $DB --local.target-table $TABLE`
5. Recreate indexes: `mysql ... $DB < 02-create-indexes.sql`
6. Apply foreign keys: `mysql ... $DB < 04-foreign-keys.sql`

**Direct loading steps (Essential/Dedicated):**
1. Apply schema: `mysql ... $DB < 01-create-tables.sql`
2. Export per table: `psql "$CONN" -c "\COPY (SELECT * FROM public.$TABLE) TO '$TABLE.csv' WITH CSV HEADER"`
3. Load per table: `mysql ... -e "LOAD DATA LOCAL INFILE '$TABLE.csv' INTO TABLE $TABLE FIELDS TERMINATED BY ',' ENCLOSED BY '\"' LINES TERMINATED BY '\\n' IGNORE 1 LINES"`
4. Recreate indexes: `mysql ... $DB < 02-create-indexes.sql`
5. Apply foreign keys: `mysql ... $DB < 04-foreign-keys.sql`

**Storage bytes and auth users are NOT loaded here.** They are separate deliverables from the external-work plan:
- Storage bytes: `aws s3 sync s3://supabase-storage-{ref}/ s3://target-bucket/` (with service_role credentials)
- Auth users: export `auth.users` + `auth.identities` and load into the chosen auth target (Auth0 / Clerk / Cognito / custom)

**Gate:** Get user confirmation before loading. Schema must apply cleanly. All user-schema tables load without errors. Explicitly confirm that `auth.*` and `storage.*` data were NOT shipped.

**Error recovery:**
- **Schema apply fails:** Show the exact error. Common causes: reserved word as column name (wrap in backticks), type mapping missed (check `references/type-mapping.md`), duplicate index name. Fix the DDL file and re-apply — don't ask the user to edit SQL manually.
- **`pg_dump` output contains `auth.` or `storage.` references:** Stop immediately. The schema filter was not applied. Verify the `pg_dump` command used `--schema=public` (and any other explicitly allowed user schemas) and rerun.
- **COPY fails with "permission denied":** The `postgres` role may lack privileges on some system tables — but for user `public` tables, this usually means the connection dropped or a pooler is intercepting. Verify direct / session-pooler mode.
- **LOAD DATA fails partway:** Note which tables succeeded and which failed. For the failed table, check if rows were partially loaded (`SELECT COUNT(*) FROM table`). If so, `TRUNCATE TABLE` and retry. Don't re-load tables that already succeeded.
- **Foreign key apply fails:** Usually a missing referenced table or data integrity issue. Show which FK failed, check that the referenced table was loaded, and verify referential integrity with a query before retrying.

---

## Phase 7: Validate

Compare source and target to confirm data integrity.

**Step 7.1–7.2:** Row counts — `pg_class.reltuples` + `SELECT COUNT(*)` on source vs `information_schema.tables` + `COUNT(*)` on target. Flag any difference > 1%.

**Step 7.3–7.4:** Column structure — compare column names, types, and nullability between source (`information_schema.columns`) and target (`information_schema.columns` on MySQL).

Report: matching tables, mismatched tables (with details), missing tables in either direction.

**Gate:** Zero mismatches on user-schema tables. The presence of `auth.*` or `storage.*` tables on source is EXPECTED — confirm they are NOT present on target.

**Error recovery:**
- **Row count difference 1–5%:** Likely caused by concurrent writes during export. Re-export and re-load only the affected tables. If the source is still active, consider enabling Phase 8 (sync) or a maintenance window for the final cutover.
- **Row count difference > 5%:** Check LOAD DATA errors in the mysql client output, verify the CSV row count (`wc -l $TABLE.csv`), and look for encoding issues (UTF-8 is the default on both sides — mismatches are rare). Truncate and re-load the table.
- **Column type mismatch:** Usually a type mapping gap — compare the source type from Step 2.2 against `references/type-mapping.md` and fix `01-create-tables.sql`. If the table already has data, use `ALTER TABLE ... MODIFY COLUMN` rather than recreating.
- **Missing tables on target:** Check if the table was excluded from `01-create-tables.sql` or if the CREATE TABLE failed silently. Re-apply the missing table's DDL and re-load its data.
- **Missing tables on source but present on target:** The scan is stale — a table may have been dropped. Drop the orphaned table from TiDB after confirming with the user.

---

## Phase 8: Sync (optional, Essential/Dedicated only)

CDC replication for zero-downtime cutover. Not available on Starter tier.

**Prerequisites:**
- `wal_level = logical` (default on paid Supabase tiers)
- Direct endpoint (`db.{ref}.supabase.co:5432`) — pooler does NOT proxy replication
- TiDB Cloud Essential or Dedicated (Changefeeds or DM)

**Supabase-specific slot/publication hygiene:**
1. **NEVER use `FOR ALL TABLES`** — that ships `auth.*`, `storage.*`, `realtime.*`, etc. Always explicit table list.
2. **NEVER reuse the slot name `supabase_realtime`** — that slot is owned by Supabase's Realtime service. Use `tishift_migration` (or a user-configured alternative).
3. Leave the Realtime slot and publication alone throughout the migration. They are untouchable.

**Setup:**
```sql
-- On Supabase:
SHOW wal_level;   -- must be 'logical'
CREATE PUBLICATION tishift_pub FOR TABLE public.users, public.posts, public.comments, public.invoices;
-- The table list comes from the scan's user-table inventory. Never FOR ALL TABLES.

-- TiShift creates the slot via the replication protocol:
--   pg_create_logical_replication_slot('tishift_migration', 'pgoutput')
```

**Cutover procedure:**
1. Pause application writes to Supabase (maintenance mode in Supabase Dashboard or app-level flag).
2. Wait for TiShift CDC bridge to catch up (LSN matches).
3. Verify with a final Phase 7 run in live-comparison mode.
4. Switch application connection strings to TiDB.
5. Drop the `tishift_pub` publication and `tishift_migration` slot on Supabase.
6. Leave `supabase_realtime` slot and publication alone (they are still needed until Realtime service is explicitly decommissioned).

---

## Decision Points

After all phases, apply these rules:

- If `total < 25`: warn about difficult migration requiring significant manual work AND a parallel application-rewrite project. Recommend a discovery-level engagement before committing to dates.
- If blockers exist: they must be resolved before loading data — ask how each will be handled.
- If `rls_policy_count > 0`: **this is always the first conversation.** The policies are in `05-rls-rewrite-checklist.md`. Ask the user how they plan to enforce access control on TiDB (middleware WHERE-injection, dedicated API tier, per-role DB users, etc.).
- If `function_count > 0` OR `trigger_count > 0`: offer to generate application code stubs (Python / Go / Java / JS / TypeScript). Triggers move to application middleware — ask which language.
- If `auth_user_count > 0`: ask which auth target (Auth0 / Clerk / Cognito / custom). Passwords preserve on bcrypt-compatible targets; Firebase forces reset.
- If `storage_object_count > 0`: confirm the user has the service_role key to read the Storage S3 bucket and has picked a target bucket.
- If `has_realtime AND supabase_realtime_slot_active`: confirm the user has a plan for replacing WebSocket subscriptions (TiCDC + fanout, Debezium + Kafka, app-level pub/sub).
- If `has_pgsodium OR has_supabase_vault`: warn that encrypted data cannot round-trip. Plan a maintenance window for decrypt-on-source / re-encrypt-on-target.
- If `has_pg_graphql AND pg_graphql_active`: confirm the GraphQL rewrite plan (Hasura, PostGraphile, hand-rolled).
- If `pg_cron_active_jobs > 0`: offer to generate TiDB `CREATE EVENT` stubs for each job.
- If `has_wrappers AND wrappers_foreign_table_count > 0`: list every FDW integration (Stripe, Firebase, S3, etc.); each becomes an app-layer API rewrite.

**Tier-specific decisions:**
- If `tier == "starter" AND total_data_gb > 25`: Starter cannot hold this data within the free tier. Recommend upgrading to Essential or Dedicated. Show the cost comparison.
- If `tier == "starter"`: skip Phase 8 (sync) entirely — Starter has no Changefeeds or DM. The migration must be a cutover with scheduled downtime. Warn the user about planning a maintenance window.
- If `tier == "starter"`: warn about the 30-minute transaction timeout. Large LOAD DATA operations may need to be batched by table or by row range.
- If `tier == "essential" AND total_data_gb > 500`: recommend upgrading to Dedicated for TiDB Lightning support.
- If `tier == "dedicated" AND total_data_gb > 500`: recommend TiDB Lightning over direct load.
- If `tier != "starter" AND wal_level != "logical"`: warn and note that enabling logical replication on Supabase requires a support ticket on free tier; paid tiers have it on by default.

---

## Reference files

Read these when you need detailed lookup tables during conversion:

- `references/compatibility-rules.md` — All blocker and warning rules with IDs, detection patterns, compatible-features list, and the external-work checklist
- `references/scoring.md` — Detailed scoring pseudocode for all 5 categories, including tier-specific adjustments
- `references/type-mapping.md` — Complete Postgres → TiDB type mapping with length/precision handling and collation notes
- `references/function-mapping.md` — Postgres / Supabase function → TiDB function translations, including Supabase auth helpers and `extensions.`-qualified calls
