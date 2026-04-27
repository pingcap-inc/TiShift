# Convert Guide

`tishift-supabase convert` takes the scan report and produces TiDB-compatible DDL plus the artifacts needed for the application rewrite work that accompanies the DB migration.

```bash
tishift-supabase convert \
  --scan-report ./tishift-reports/tishift-supabase-report.json \
  --output-dir ./migration-output \
  --dry-run
```

The `--dry-run` flag prints the generated SQL without writing files. Drop it to persist to disk.

## Output files

| File | Purpose |
|---|---|
| `01-create-tables.sql` | `CREATE TABLE` statements with Postgres → TiDB type mapping, charset/collation, `AUTO_INCREMENT` for SERIAL, `VARCHAR(36)` (or `BINARY(16)`) for UUID, `JSON` for JSONB and arrays, inline `ENUM` for named enums |
| `02-create-indexes.sql` | Secondary indexes. GIN/GiST indexes appear as comments with a redesign note — they don't translate directly. Drop this file's contents before bulk load, recreate after (3–5× faster). |
| `03-create-views.sql` | Views with `extensions.` qualifier stripped and function calls mapped. Views that reference `auth.*` helpers are commented out with a pointer to `05-rls-rewrite-checklist.md`. |
| `04-foreign-keys.sql` | `ALTER TABLE ... ADD FOREIGN KEY` — applied after load so index/row order doesn't cause FK-insert ordering issues. |
| `05-rls-rewrite-checklist.md` | **Every RLS policy, every `auth.*` call site, every `net.*` / `vault.*` / `cron.*` / `graphql.*` call site** — structured for the app / middleware rewrite team. Not code. Not DDL. A checklist. |
| `06-conversion-notes.md` | PL/pgSQL functions, triggers, sequences with non-default semantics, ENUM reuse across columns — items that need per-case human judgment. |
| `07-external-work-plan.md` | PostgREST / GoTrue / Realtime / Storage / pgsodium / pg_graphql / pg_cron / wrappers — each triggered track with the scan evidence, options, and a suggested sequence. |

## What gets transformed

### Types

See `references/type-mapping.md` for the full table. Highlights:

- `uuid` → `VARCHAR(36)` (default) or `BINARY(16)` (opt-in via `--uuid-type=binary`)
- `jsonb` → `JSON`
- `boolean` → `TINYINT(1)`
- `serial` / `bigserial` → `AUTO_INCREMENT`
- `timestamp with time zone` → `DATETIME(6)` plus a comment about app-side UTC enforcement
- `text[]` / any array → `JSON` plus a comment noting normalization may be preferable
- Named enums → inline `ENUM(...)` at the column — loses named-type reuse
- `tsvector`, `geometry`, `vector` (pgvector), range types → flagged as blockers; left out of the DDL with a comment pointing to `06-conversion-notes.md`

### Functions in views and generated columns

sqlglot handles most mappings (`COALESCE`, `NOW()`, `GREATEST`, window functions, `->` / `->>` JSON accessors). Supabase-specific passes happen before sqlglot:

- `extensions.gen_random_uuid()` → `UUID()` (qualifier stripped)
- `extensions.uuid_generate_v4()` → `UUID()`
- `auth.uid()` / `auth.jwt()` / `auth.role()` / `auth.email()` call sites are flagged and the enclosing view / function is commented out in `03-create-views.sql` with a pointer to the rewrite checklist
- `net.http_*` call sites — same treatment
- `vault.*` call sites — same treatment
- `cron.schedule(...)` calls — emitted to `07-external-work-plan.md` as TiDB `CREATE EVENT` stub
- JSONB operators `@>`, `?`, `#>`, `#>>` — left in place with a comment; convert phase cannot auto-rewrite without false positives, and the rewrite depends on the query author's intent

### RLS

**`CREATE POLICY` statements are never emitted to the target DDL.** TiDB has no RLS. Every policy lands in `05-rls-rewrite-checklist.md` with:

- Schema, table, policy name, command, roles
- Full USING expression
- Full WITH CHECK expression
- Complexity classification (simple / moderate / complex)
- References detected (`auth.uid`, `auth.jwt`, subquery, JOIN, JSON path)
- Suggested rewrite pattern:
  - **Simple equality** (`auth.uid() = user_id`) → middleware WHERE-injection
  - **Role-gated** (`TO authenticated USING (...)`) → authenticated-DB-user pool, or WHERE-injection with a role variable
  - **Tenant isolation** (`tenant_id = (auth.jwt() ->> 'tenant_id')::uuid`) → middleware injects `tenant_id` from the validated JWT
  - **Complex** (subqueries, JOINs) → flagged for human review; likely becomes an application-tier query

`ALTER TABLE ... ENABLE / DISABLE / FORCE ROW LEVEL SECURITY` statements are stripped silently and logged.

### Supabase system schemas

Everything in `auth`, `storage`, `realtime`, `_realtime`, `extensions`, `graphql`, `graphql_public`, `supabase_migrations`, `vault`, `pgsodium`, `pgsodium_masks`, `net`, `pgbouncer`, `_analytics` is dropped from the DDL regardless of whether it appeared in the scan. These hold platform state and are never migrated.

## Procedural code conversion

PL/pgSQL functions and procedures are parsed but TiDB cannot execute them. Three paths:

1. **Pure SQL** — the function body is a single SELECT / UPDATE / INSERT. `03-create-views.sql` may be able to express it as a view, or the caller can inline the SQL. Flag in `06-conversion-notes.md`.
2. **Application code** — rewrite as a Python / Go / JavaScript / TypeScript method. With `--ai`, the AI reads the function body and emits a stub in the chosen language, plus a classification (trivial / simple / moderate / complex / requires_redesign).
3. **Requires redesign** — functions with cursors, deep dynamic SQL, package state, or autonomous-transaction-like patterns. Flagged for human review.

Triggers always move to the application layer. Pre-insert and pre-update triggers become ORM hooks or middleware. Audit-log triggers become CDC consumers (TiCDC).

## Dry-run vs apply

- `--dry-run` (default) prints to stdout; no files written.
- Without `--dry-run`, files are written to `--output-dir`.
- The DDL is **never** auto-applied to TiDB. The load phase is a separate command.

## What to do before load

1. Review `01-create-tables.sql` against your TiDB deployment. Resolve any type-mapping edge cases (e.g., a `DECIMAL(80, 5)` that needs manual truncation to `DECIMAL(65, 30)` — the scan flags this).
2. Review `05-rls-rewrite-checklist.md` with your app / middleware team. Decide on a rewrite pattern per policy — or group of policies — before the migration window.
3. Review `07-external-work-plan.md` with your platform team. Kick off the PostgREST / GoTrue / Realtime / Storage / pgsodium tracks in parallel with the DB work.
4. Apply `01-create-tables.sql` to an empty TiDB database as a dry run. If it applies cleanly, you're ready for Phase 6 (load).

See [load-guide.md](./load-guide.md).
