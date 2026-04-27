# TiDB Compatibility Rules for Supabase Migrations

## Table of Contents

1. [Blockers](#blockers)
2. [Warnings](#warnings)
3. [Postgres Feature Detection Patterns](#postgres-feature-detection-patterns)
4. [Compatible Features](#compatible-features)
5. [External Work Checklist](#external-work-checklist)

---

## Blockers

These are hard stops. TiDB cannot handle these features — they must be resolved before migration.

| ID | Condition | Feature | Action |
|---|---|---|---|
| BLOCKER-1 | Any row in `pg_policy` for a user-schema table | Row-level security policies (`CREATE POLICY`) | **The #1 Supabase blocker.** TiDB has zero RLS support. Extract each policy as a structured finding (name, table, command, roles, USING expression, WITH CHECK expression) and rewrite at the application layer: middleware WHERE-clause injection, a dedicated API tier, or row-owner predicates in every query. Do NOT emit RLS DDL to the target. |
| BLOCKER-2 | Table with `relrowsecurity = true` but no policy row in `pg_policy` | RLS enabled without policy (deny-all pattern) | Same as BLOCKER-1. Report the table; user decides whether the deny-all was intentional (then app layer enforces access) or accidental (then drop the flag before migration). |
| BLOCKER-3 | `auth.uid()` / `auth.jwt()` / `auth.role()` / `auth.email()` call sites inside user functions, views, or materialized views | Supabase auth helper functions | Rewrite call sites to accept parameters injected by app/middleware. Report each site with a `schema.object` locator. These functions read from a Postgres GUC (`request.jwt.claims`) populated by PostgREST per request — no equivalent mechanism exists on TiDB. |
| BLOCKER-4 | `pgsodium` extension installed AND any row in `pgsodium.key` | Libsodium encryption / column masking | Project-scoped master key — ciphertext cannot round-trip off Supabase. Decrypt on the source (`pgsodium.decrypt_*`), re-encrypt against the target KMS, then load. Plan for a maintenance window if the encrypted data is business-critical. |
| BLOCKER-5 | `supabase_vault` extension installed AND non-empty `vault.secrets` | Encrypted secrets KV | Read via `vault.decrypted_secrets` view (while still on Supabase), materialize into the target secrets manager (AWS Secrets Manager / HashiCorp Vault / application config), then drop the Supabase copy. The `vault.secrets` table itself should NOT be migrated — secrets don't belong in the application DB. |
| BLOCKER-6 | `pgjwt` extension installed AND any user function body calls `sign()` / `verify()` / `url_decode()` / `url_encode()` | JWT sign/verify in SQL | Rewrite at app/middleware layer (`PyJWT`, `jsonwebtoken`, Go `jwt/v5`). Modern Supabase apps rarely call pgjwt directly — they use `auth.jwt()` — but legacy apps may. |
| BLOCKER-7 | `pg_net.http_*` call sites in user functions or triggers | Outbound HTTP from SQL | No TiDB equivalent. Rewrite as app-layer worker: application publishes events to a queue (Redis / Kafka / SQS), a consumer process makes the HTTP call. Flag every call site with the target URL pattern for triage. |
| BLOCKER-8 | `wrappers` extension installed AND any `pg_foreign_table` row | Foreign data wrappers (Stripe / Firebase / S3 / Clickhouse / Airtable FDW) | No TiDB equivalent. Foreign-table queries become application-layer API calls. Capture the FDW server configs (endpoints, API keys) for the rewrite team — these don't migrate, but the integration points do. |
| BLOCKER-9 | Any column with `data_type = 'ARRAY'` | Postgres arrays (`INT[]`, `TEXT[]`, etc.) | Convert to JSON array column (preserves data, loses native array operators and GIN indexing) or normalize into a child table (preserves relational semantics, requires query rewrites). Manual per-column review required. |
| BLOCKER-10 | JSONB binary-operator usage detected in queries or function bodies: `@>`, `<@`, `?`, `?|`, `?&`, `#>`, `#>>` | JSONB binary operators | Rewrite to `JSON_CONTAINS()`, `JSON_EXTRACT()`, `JSON_OVERLAPS()`. Convert JSONB columns to `JSON`. sqlglot parses the operators but does not auto-convert. |
| BLOCKER-11 | Custom composite types (`pg_type.typtype = 'c'`) | `CREATE TYPE ... AS (...)` | Flatten into separate columns or store as JSON. No MySQL/TiDB equivalent. |
| BLOCKER-12 | Non-empty `pg_inherits` | Table inheritance (`INHERITS`) | Flatten parent + child into a single table with a discriminator column, or split into separate tables and handle polymorphism in the application. |
| BLOCKER-13 | Any PL/pgSQL function or procedure in user schemas | Stored functions / procedures | TiDB parses `CREATE FUNCTION` / `CREATE PROCEDURE` syntax but has no procedural runtime — bodies do not execute. Rewrite as application code. For non-trivial logic, enable `--ai` for AI-assisted conversion. |
| BLOCKER-14 | Any trigger on a user-schema table | Triggers (`CREATE TRIGGER`) | TiDB parses trigger DDL but does not fire them. Move the logic to application-level event hooks, middleware, or change-data-capture consumers. |
| BLOCKER-15 | Any `tsvector` column OR GIN/GiST index on a text column | Full-text search (`tsvector`, `tsquery`, `to_tsvector`, `@@` operator) | No TiDB equivalent (MySQL FULLTEXT is limited and TiDB's support varies by deployment). Offload to an external search engine: Elasticsearch, Meilisearch, Typesense, or OpenSearch. |
| BLOCKER-16 | Range-type columns (`int4range`, `int8range`, `numrange`, `tsrange`, `tstzrange`, `daterange`) | Range types | Flatten to two columns (`lower_bound`, `upper_bound`) plus optional inclusivity flags. Rewrite range operators (`@>`, `&&`, `-|-`) in the application. |
| BLOCKER-17 | Any view with `relkind = 'm'` | Materialized views | Convert to a regular table plus a scheduled refresh process (application cron, TiDB `CREATE EVENT`, or an external scheduler). |
| BLOCKER-18 | Any `pg_constraint.contype = 'x'` row | EXCLUDE constraints | Must be enforced in application logic. Remove from the target DDL. |
| BLOCKER-19 | `LISTEN` or `NOTIFY` call sites in the application or in function bodies | Postgres pub/sub | No equivalent. Replace with Redis Pub/Sub, Kafka, NATS, or cloud message buses (SNS/SQS, Pub/Sub). |
| BLOCKER-20 | `postgis` extension installed AND any `geometry` / `geography` column | PostGIS spatial types | TiDB has no spatial indexing. Offload spatial queries to a dedicated PostGIS instance, application-layer geo libraries (Shapely + S2), or a managed geo service. Store coordinates as `DECIMAL` or `POINT` if spatial indexing is not required. |
| BLOCKER-21 | `vector` extension installed AND any `vector` column OR `ivfflat` / `hnsw` index | pgvector (vector similarity search) | No TiDB equivalent. Migrate embeddings to a dedicated vector DB (Qdrant, Weaviate, Pinecone, Milvus) or use an application-level embedding index. Keep the source text in TiDB; keep the vectors elsewhere. |

---

## Warnings

These features work differently in TiDB. They won't block migration but require review and possible adjustment.

| ID | Condition | Feature | Action |
|---|---|---|---|
| WARNING-1 | `auth.users` table has at least one row | Supabase Auth user data | Export `auth.users` + `auth.identities` separately (not via TiShift load). Passwords are bcrypt hashes in `encrypted_password` (misnomer) — Auth0, Clerk, Cognito, and custom bcrypt-verifying backends accept the hashes as-is and preserve user login. Firebase uses scrypt exclusively and forces a universal password reset. Pick an auth target before migration day. |
| WARNING-2 | `storage.objects` table has at least one row | Supabase Storage metadata | The Postgres rows are metadata only; actual file bytes live in Supabase's S3-compatible object store. Copy bytes separately with `aws s3 sync` against `https://{project_ref}.storage.supabase.co/storage/v1/s3` (service_role credentials required). If you drop Supabase Storage entirely, you must also replace signed-URL generation in the application. |
| WARNING-3 | `pg_replication_slots` row with name starting `supabase_realtime` or `realtime` | Realtime service replication slot | Do NOT rename, drop, or reuse. TiShift sync creates its own slot (`tishift_migration`). After cutover, if you decommission Supabase Realtime, rebuild WebSocket subscriptions on TiCDC + fanout service, Debezium + Kafka, or app-level pub/sub. |
| WARNING-4 | `pg_graphql` extension installed | Auto-generated GraphQL API | If the application calls `/graphql/v1`, rewrite the GraphQL layer with Hasura (on a Postgres compat proxy), PostGraphile, or hand-rolled resolvers. If no code path uses it, drop without action. Note: Supabase auto-disables pg_graphql after 7 days of zero requests — its presence in `pg_extension` is not proof of use. |
| WARNING-5 | `cron.job` table has at least one active row (`active = true`) | Scheduled jobs (pg_cron) | Map each job to TiDB `CREATE EVENT ... DO ...`. Flag jobs whose `command` text references `net.*` (blocker BLOCKER-7 applies), `vault.*` (BLOCKER-5), or any function in an extension schema — those need additional rewrite work on top of the event translation. |
| WARNING-6 | `supabase_migrations.schema_migrations` has at least one row | Supabase CLI migration history | Discard. Target will use a different migration tool (Atlas, Flyway, Liquibase, dbt migrations, TiDB Lightning). Record the final version string for the changelog, then leave it behind. |
| WARNING-7 | Any named ENUM type in user schemas (`pg_type.typtype = 'e'`) | Postgres-style `CREATE TYPE ... AS ENUM` | Convert to MySQL-style inline `ENUM(...)` in the column definition. Loses named-type reusability (if the enum is used by multiple columns, each becomes its own inline enum). |
| WARNING-8 | Any sequence in user schemas | `CREATE SEQUENCE`, `nextval()` | Map to `AUTO_INCREMENT` or `AUTO_RANDOM`. Lose `currval()`, `setval()`, and cross-table sharing. If a sequence backs multiple tables, flag for manual review. |
| WARNING-9 | `RETURNING` clause in any INSERT / UPDATE / DELETE (in function bodies or application queries via `pg_stat_statements`) | `INSERT ... RETURNING` | TiDB does not support `RETURNING`. Rewrite as `INSERT` + `SELECT LAST_INSERT_ID()` or as two explicit queries. |
| WARNING-10 | Any `uuid` column | Postgres UUID type | Map to `VARCHAR(36)` (readable) or `BINARY(16)` (compact). `gen_random_uuid()` maps to TiDB's `UUID()`. If the application depends on UUIDv4 uniqueness guarantees, verify the MySQL driver's UUID generation. |
| WARNING-11 | Any `serial` / `bigserial` / `smallserial` column | Auto-increment shorthand | sqlglot handles → `AUTO_INCREMENT`. For scatter-heavy write workloads, consider `AUTO_RANDOM` to avoid hotspots. |
| WARNING-12 | `pg_advisory_lock` / `pg_try_advisory_lock` call sites | Postgres advisory locks | TiDB has `GET_LOCK` / `RELEASE_LOCK` — single-lock, not reentrant, session-scoped. Heavy usage requires application-layer lock service (Redis + Redlock). |
| WARNING-13 | Any domain type (`pg_type.typtype = 'd'`) | `CREATE DOMAIN` | Map to the base type plus a CHECK constraint. TiDB v6.6+ enforces CHECK constraints; verify the target version. |
| WARNING-14 | Any `boolean` column | Native boolean | sqlglot → `TINYINT(1)`. Application code must handle `TRUE/FALSE` ↔ `1/0` conversion — most ORMs do this automatically, but raw SQL needs review. |
| WARNING-15 | Any table with `relpersistence = 'u'` | Unlogged tables | Unusual on Supabase. Convert to regular tables before export. If the app relies on the "vanishes on restart" behavior, redesign with a TTL table or a Redis-backed cache. |
| WARNING-16 | Any foreign key constraint in user schemas | `REFERENCES` | TiDB v6.6+ enforces FK constraints. Verify the target version; on older deployments, FKs are parsed but not enforced. Heavy write tables may see performance impact under enforcement. |
| WARNING-17 | Any JSONB column without detected binary-operator usage | JSONB storage type | Convert to `JSON`. Loses binary optimization and GIN index support; data is preserved byte-for-byte. |
| WARNING-18 | `hstore` extension installed AND any `hstore` column | Postgres key-value type | Convert to `JSON` column. Application code that uses hstore operators (`->`, `?`, `&&`) needs a rewrite pass. |
| WARNING-19 | `extensions.`-qualified function calls in user functions/views | Supabase default search_path includes `extensions` | Strip the `extensions.` qualifier during convert. For each function, map to the TiDB equivalent or flag if no equivalent exists: `gen_random_uuid` → `UUID()`, `crypt` → no equivalent (app layer), `digest` → no equivalent, `uuid_generate_v4` → `UUID()`. |
| WARNING-20 | Any function with `prosecdef = true` (SECURITY DEFINER) in user schemas | Function-level role override | MySQL has `SQL SECURITY DEFINER` but the role semantics differ. The function body likely references `auth.*` helpers anyway and must be rewritten — at which point the SECURITY DEFINER becomes moot. Flag with the owning role for the rewrite team. |
| WARNING-21 | Any `timestamp with time zone` (`timestamptz`) column | Timezone-normalized timestamp | Map to `DATETIME(6)`. Loses Postgres's UTC-normalization guarantees — the application must enforce UTC at write time or store the offset separately. |
| WARNING-22 | `pg_cron` job whose command text references `net.*`, `vault.*`, or any function in an extension schema | pg_cron job with cross-extension dependency | On top of WARNING-5 (map to `CREATE EVENT`), the job needs the dependency resolved: `net.*` via BLOCKER-7 path, `vault.*` via BLOCKER-5 path, `extensions.*` via WARNING-19. Do not create the TiDB event until the dependency rewrite is complete. |

---

## Postgres Feature Detection Patterns

Patterns to grep in function bodies, view definitions, and (if available) `pg_stat_statements` text.

| Pattern | Regex | Finding |
|---|---|---|
| `auth.uid()` call site | `\mauth\.uid\s*\(` | BLOCKER-3 |
| `auth.jwt()` call site | `\mauth\.jwt\s*\(` | BLOCKER-3 |
| `auth.role()` call site | `\mauth\.role\s*\(` | BLOCKER-3 |
| `auth.email()` call site | `\mauth\.email\s*\(` | BLOCKER-3 |
| `net.http_*` call site | `\mnet\.http_(get\|post\|put\|delete\|patch)\s*\(` | BLOCKER-7 |
| JSONB containment | `@>` or `<@` | BLOCKER-10 |
| JSONB key existence | `\?`, `\?\|`, `\?&` (outside string literals) | BLOCKER-10 |
| JSONB path extract | `#>` or `#>>` | BLOCKER-10 |
| RETURNING clause | `RETURNING\s+\w+` | WARNING-9 |
| LISTEN / NOTIFY | `\b(LISTEN\|NOTIFY)\s+` | BLOCKER-19 |
| Advisory lock | `pg_(try_)?advisory_(un)?lock` | WARNING-12 |
| Dynamic SQL | `EXECUTE\s+.*USING` | Contributes to BLOCKER-13 complexity scoring |
| Cursor declaration | `DECLARE\s+\w+\s+CURSOR` | Contributes to BLOCKER-13 complexity scoring |
| extensions-schema call | `\mextensions\.\w+\s*\(` | WARNING-19 |
| sign/verify (pgjwt) | `\b(sign\|verify)\s*\(.*,.*secret` | BLOCKER-6 |

---

## Compatible Features

These work identically on Supabase's Postgres and TiDB. No action needed.

| Feature | Notes |
|---|---|
| `SMALLINT` / `INTEGER` / `BIGINT` | Direct mapping |
| `VARCHAR(n)` / `TEXT` / `CHAR(n)` | Direct mapping (unlimited `varchar` → `TEXT`) |
| `TIMESTAMP` (without time zone) | Maps to `DATETIME(6)`; lossless |
| `NUMERIC(p, s)` / `DECIMAL(p, s)` | Direct mapping up to `DECIMAL(65, 30)` |
| `DATE`, `TIME` | Direct mapping |
| `JSON` columns (non-JSONB, `->` / `->>` operators) | `JSON` type in TiDB supports both |
| Basic DML (`INSERT`, `UPDATE`, `DELETE`, `SELECT`) | Standard SQL |
| `JOIN` family (INNER / LEFT / RIGHT / FULL OUTER / CROSS / LATERAL) | Supported |
| Subqueries (scalar, correlated, `EXISTS`, `IN`) | Supported |
| Window functions (`ROW_NUMBER`, `RANK`, `DENSE_RANK`, `LAG`, `LEAD`, `NTILE`, `FIRST_VALUE`, `LAST_VALUE`) | Fully supported |
| CTEs (`WITH`, `WITH RECURSIVE`) | Supported |
| `CASE` / `COALESCE` / `NULLIF` / `GREATEST` / `LEAST` | Standard SQL |
| `LIMIT` / `OFFSET`, `DISTINCT`, `GROUP BY`, `HAVING`, `ORDER BY` | Standard SQL |
| Pessimistic transactions | TiDB default matches Postgres default |
| `RANGE` / `LIST` / `HASH` partitioning | Supported; syntax differs slightly |
| UTF-8 encoding | Supabase enforces UTF-8; TiDB defaults to `utf8mb4` — compatible |
| `NOT NULL`, `UNIQUE`, `CHECK` (v6.6+), `PRIMARY KEY` constraints | Supported |
| Expression indexes (TiDB 5.1+) | Approximate substitute for some GIN use cases |

---

## External Work Checklist

These are not TiShift's problem to solve, but they are prerequisites for a real Supabase → TiDB migration. TiShift's scan report surfaces them so they can be planned alongside the DB work.

| Item | Trigger | What's needed |
|---|---|---|
| PostgREST API replacement | Any table with `GRANT` to `anon` or `authenticated`; any public RPC function; `pg_graphql` active | The client SDK (`supabase-js`, `supabase-py`) talks to PostgREST, not the DB. Options: direct SQL/ORM against TiDB, Hasura/PostGraphile on a Postgres proxy, or a custom API tier. |
| GoTrue auth replacement | `auth.users` has rows | Pick a target: Auth0 / Clerk / Cognito / custom bcrypt-verifying service. Export `auth.users` + `auth.identities`. Import — passwords preserve if target accepts bcrypt. Rewrite `supabase.auth.*` client calls. |
| Realtime replacement | `supabase_realtime` slot present AND app uses `supabase.channel(...)` | Rebuild on TiCDC + fanout service, Debezium + Kafka, or app-level pub/sub. Rewrite client code. |
| Storage bytes + signed URLs | `storage.objects` non-empty | `aws s3 sync` from Supabase's S3-compatible endpoint to target bucket. Replace Supabase signed-URL generation with your own (S3 presigned URLs, Cloudfront signed URLs, etc.). |
| Edge Functions | Any functions deployed via Supabase CLI | Relocate Deno runtime to Deno Deploy, Cloudflare Workers, AWS Lambda, or a self-hosted Deno host. Not DB-related; track separately. |
| pgsodium / Vault re-encryption | BLOCKER-4 or BLOCKER-5 triggered | Decrypt on Supabase → migrate plaintext → re-encrypt against target KMS. Plan maintenance window. |
| pg_net → app-layer HTTP worker | BLOCKER-7 triggered | Application or external worker that subscribes to an event queue and performs HTTP calls. |
| pg_graphql → GraphQL tier | WARNING-4 triggered AND app uses `/graphql/v1` | Hasura / PostGraphile / hand-rolled resolvers. |
| pg_cron jobs → scheduler | WARNING-5 triggered | Map each to TiDB `CREATE EVENT`, or external scheduler (Airflow / cron / Kubernetes CronJob). |
| Wrappers (FDW) → API integration | BLOCKER-8 triggered | Each FDW server (Stripe / Firebase / S3 / Clickhouse) becomes an application-layer API integration. |
