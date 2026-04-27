# Scan Guide

`tishift-supabase scan` produces the migration assessment: inventory, RLS findings, platform signals, compatibility classification, and a 0–100 readiness score.

```bash
tishift-supabase scan --config tishift-supabase.yaml --format cli --format json --format html
```

Output lands in `./tishift-reports/` (configurable in YAML).

## What the scan does

Read-only. Every query hits `pg_catalog` / `information_schema` with an explicit schema filter that excludes the 13 Supabase-internal schemas:

```
auth, storage, realtime, _realtime, extensions, graphql, graphql_public,
supabase_migrations, vault, pgsodium, pgsodium_masks, net, pgbouncer, _analytics
```

The filter is enforced at the SQL `WHERE` clause, not after row fetch — so the scan never reads `auth.users` rows or `storage.objects` metadata content.

## Collectors

| Collector | What it reports |
|---|---|
| Schema inventory | Tables, views, materialized views, columns, indexes (including GIN/GiST), constraints (PK/FK/UNIQUE/CHECK/EXCLUDE), functions, procedures, triggers, sequences, custom types (composite/enum/range/domain), extensions, partitioned tables |
| RLS policies | Every policy with name, table, command (SELECT/INSERT/UPDATE/DELETE/ALL), roles, USING expression, WITH CHECK expression, and a complexity classification (simple / moderate / complex) |
| Platform signals | Boolean presence of `auth`, `storage`, `realtime`, `graphql_public` schemas; `supabase_realtime` replication slot and publication; `pg_cron` jobs; `pg_net` call sites; `wrappers` foreign tables; auth user count; storage object count |
| Data profile | Per-table size via `pg_total_relation_size()`, row estimates via `pg_class.reltuples`, LOB/BYTEA columns, largest tables |
| Feature usage | Array columns, JSONB columns (with operator-usage detection if `pg_stat_statements` is available), UUID columns, tsvector columns, range types, `auth.*` call sites in user function bodies and views, `extensions.`-qualified call sites |
| Procedural deep-dive | For each PL/pgSQL function: line count, cursor usage, dynamic SQL (`EXECUTE ... USING`), exception blocks, `auth.*` references, SECURITY DEFINER flag. Optional `--ai` flag sends definitions to the AI for semantic classification. |

## The readiness score

5 categories summing to 100:

| Category | Max | Focus |
|---|---|---|
| Schema Compatibility | 20 | Types + Supabase extensions |
| Data Complexity | 15 | Volume + LOBs + Storage scope |
| Query Compatibility | 15 | Postgres dialect features |
| Procedural Code | 30 | PL/pgSQL + triggers + **RLS policies** |
| Operational Readiness | 20 | Connection / WAL / stats + **Application Coupling** |

### Why Procedural Code is weighted 30

On Supabase, RLS policies are where application auth / tenant / ownership logic lives. A project with 60 policies has 60 pieces of procedural code to rewrite — more, in practice, than its stored functions. The scoring treats them as procedural code, not schema.

### The Application Coupling sub-signal

Inside Operational Readiness, up to 14 of the 20 points go to a sub-signal that measures service-layer rewrite scope:

| Signal | Points |
|---|---|
| GoTrue (auth users > 0) | 3 |
| Storage (objects > 0) | 3 |
| Realtime slot active | 2 |
| PostgREST likely in use (GRANT to anon/authenticated, or active pg_graphql) | 3 |
| pg_cron active jobs | up to 2 |
| Vault secrets present | 1 |

A project using the full Supabase service stack will burn most of these points. That's intentional — the point is to surface the scope, not to punish the user.

## Reading the report

The JSON report has four top-level arrays:

- `blockers` — features TiDB cannot do. Must be resolved before loading.
- `warnings` — features that work differently. Worth reviewing.
- `compatible` — features that carry over unchanged.
- `external_work` — non-DB pieces that break when leaving Supabase (PostgREST, GoTrue, Realtime, Storage, pgsodium, pg_graphql, pg_net, pg_cron, wrappers).

Each blocker includes a `findings` array with per-occurrence detail. For RLS, that's every policy with its expressions. For `auth.*` call sites, that's every enclosing function / view.

### Score interpretation

| Score | Rating | Meaning |
|---|---|---|
| 90–100 | EXCELLENT | Near drop-in migration |
| 75–89 | GOOD | Straightforward with some refactoring |
| 50–74 | MODERATE | Significant refactoring; feasible |
| 25–49 | CHALLENGING | Major application changes required |
| 0–24 | DIFFICULT | Substantial redesign; plan a multi-quarter project |

Expected distribution for Supabase projects:

- Hello-world SaaS (5 tables, 5 simple RLS policies) → 75–85
- Typical production SaaS (30 tables, 60 RLS policies, Auth+Storage+Realtime) → 35–50
- Heavy-feature app (pgvector, pg_net, Vault, 80+ policies) → 10–25

## Before proceeding

Do not run `convert` until you've reviewed:

1. The score and rating.
2. The full blocker list.
3. The RLS policies — every one is a piece of app/middleware work.
4. The external-work checklist — these are the non-DB pieces that must be planned alongside the migration.

See [convert-guide.md](./convert-guide.md) for the next step.
