# Readiness Scoring Methodology

5-category weighted model. Maximum score: 100. Every point deducted is traceable to a specific condition — no hidden penalties.

## Category weights

| Category | Max | What it measures |
|---|---|---|
| Schema Compatibility | 20 | Postgres type diversity, unsupported schema features, Supabase-specific extension dependencies |
| Data Complexity | 15 | Total data volume, per-table size, LOB usage, table count, Storage-object count |
| Query Compatibility | 15 | Postgres dialect features detected in queries (JSONB operators, RETURNING, array operators, LISTEN/NOTIFY, full-text search, extensions-qualified calls) |
| Procedural Code | 30 | PL/pgSQL functions + triggers + **RLS policies** (RLS policies are treated as procedural code on Supabase — they encode the app's auth/tenant logic) |
| Operational Readiness | 20 | Connection / WAL / stats health, plus **Application Coupling** sub-signal (PostgREST, GoTrue, Realtime, Storage, pg_cron, Vault presence) |

---

## Category 1: Schema Compatibility (20 points max)

```
SET schema_score = 20

IF array_column_count > 0         THEN schema_score -= MIN(array_column_count, 4)
IF jsonb_column_count > 0         THEN schema_score -= MIN(jsonb_column_count, 3)
IF custom_composite_type_count > 0 THEN schema_score -= MIN(custom_composite_type_count * 2, 5)
IF range_type_column_count > 0    THEN schema_score -= MIN(range_type_column_count, 3)
IF inheritance_count > 0          THEN schema_score -= MIN(inheritance_count * 3, 5)
IF materialized_view_count > 0    THEN schema_score -= MIN(materialized_view_count, 2)
IF exclude_constraint_count > 0   THEN schema_score -= MIN(exclude_constraint_count * 2, 3)
IF enum_type_count > 0            THEN schema_score -= 1
IF domain_type_count > 0          THEN schema_score -= 1
IF uuid_column_count > 0          THEN schema_score -= 1

// Supabase-specific extension blockers
// Each contributing extension deducts up to 3, capped at 8 total.
//   - pgsodium with non-empty key table     → 3
//   - supabase_vault with non-empty secrets → 2
//   - pg_net with http_* call sites         → 3
//   - wrappers with foreign tables          → 3
IF supabase_extension_blockers > 0 THEN
    schema_score -= MIN(supabase_extension_blockers, 8)

IF pg_graphql_active THEN schema_score -= 2
   // "active" = extension installed AND app evidence of use
   // (GRANT to anon/authenticated, or `graphql_public.graphql()` in app query log)

schema_score = MAX(schema_score, 0)
```

## Category 2: Data Complexity (15 points max)

```
SET data_score = 15
total_data_gb = total_data_bytes / (1024 * 1024 * 1024)

IF total_data_gb > 100 THEN data_score -= 2
IF total_data_gb > 500 THEN data_score -= 4
IF total_data_gb > 1000 THEN data_score -= 7

largest_table_gb = largest_table_bytes / (1024 * 1024 * 1024)
IF largest_table_gb > 50 THEN data_score -= 2

IF bytea_column_count > 0 THEN data_score -= MIN(bytea_column_count, 3)
IF table_count > 500 THEN data_score -= 2
IF unlogged_table_count > 0 THEN data_score -= MIN(unlogged_table_count, 2)

// Storage-object count (diagnostic — signals migration scope, not DB size)
IF storage_objects_count > 100000 THEN data_score -= 2

data_score = MAX(data_score, 0)
```

## Category 3: Query Compatibility (15 points max)

```
// If pg_stat_statements is unavailable or empty, assume minor issues likely
IF no pg_stat_statements data AND no function bodies to analyze THEN
    query_score = 12
    NOTE: "Assumed 12/15 — no query corpus to analyze"
ELSE
    SET query_score = 15

    IF jsonb_operator_query_count > 0  THEN query_score -= MIN(3, jsonb_operator_query_count / 10)
    IF returning_clause_count > 0      THEN query_score -= MIN(2, returning_clause_count / 10)
    IF array_operator_query_count > 0  THEN query_score -= MIN(2, array_operator_query_count / 10)
    IF listen_notify_count > 0         THEN query_score -= 2
    IF advisory_lock_count > 0         THEN query_score -= 1
    IF fulltext_query_count > 0        THEN query_score -= MIN(3, fulltext_query_count / 5)
    IF extensions_qualified_call_sites > 0 THEN
                                       query_score -= MIN(2, extensions_qualified_call_sites / 5)

query_score = MAX(query_score, 0)
```

## Category 4: Procedural Code (30 points max)

Three sub-deductions: PL/pgSQL functions (up to 12), triggers (up to 6), RLS policies (up to 12).

```
SET code_score = 30

// --- 4a: PL/pgSQL functions and procedures (up to 12 points) ---
SET function_deduction_total = 0

FOR EACH function/procedure in user schemas:
    Count lines in pg_get_functiondef()
    Check for: CURSOR, EXECUTE ... USING, RAISE, PERFORM, nested calls,
               auth.uid/jwt/role/email references, SECURITY DEFINER

    IF has dynamic SQL (EXECUTE ... USING) OR nested function calls:
        IF lines > 100 THEN deduct 4 (requires_redesign)
        ELSE deduct 3 (complex)
    ELSE IF lines < 10 AND no CURSOR AND no auth.* references:
        deduct 0.5 (trivial)
    ELSE IF lines < 30 AND no CURSOR:
        deduct 1 (simple)
    ELSE IF has CURSOR OR lines >= 100:
        deduct 2 (moderate)
    ELSE:
        deduct 1 (simple)

    IF references auth.uid()/auth.jwt()/auth.role()/auth.email():
        deduct additional 1 (call-site rewrite at app layer)

function_deduction_total = MIN(function_deduction_total, 12)
code_score -= function_deduction_total

// --- 4b: Triggers (up to 6 points) ---
trigger_deduction = MIN(trigger_count * 1.5, 6)
code_score -= trigger_deduction

// --- 4c: RLS policies (up to 12 points — the Supabase-specific weight) ---
SET rls_deduction_total = 0

FOR EACH RLS policy:
    Parse USING / WITH CHECK expressions
    IF expression contains subquery OR JOIN OR (auth.jwt() -> path extraction):
        deduct 0.5 (complex — careful app-layer rewrite)
    ELSE IF expression is a simple equality (e.g., (select auth.uid()) = user_id):
        deduct 0.25 (straightforward middleware WHERE-injection)
    ELSE:
        deduct 0.4 (moderate)

// Tables with relrowsecurity=true but zero policies (deny-all pattern)
rls_deduction_total += (tables_with_rls_enabled_no_policy * 0.25)

rls_deduction_total = MIN(rls_deduction_total, 12)
code_score -= rls_deduction_total

code_score = MAX(code_score, 0)
```

## Category 5: Operational Readiness (20 points max)

Two sub-deductions: connection/WAL/stats health (up to 6) and the Application Coupling sub-signal (up to 14).

```
SET ops_score = 20

// --- 5a: Connection + WAL + stats (up to 6 points) ---
IF wal_level != 'logical' AND sync_planned       THEN ops_score -= 2
IF connection_is_pooler_transaction_mode         THEN ops_score -= 2  // refused at runtime
IF connection_is_pooler_session_mode AND sync_planned THEN ops_score -= 1
IF stats_stale (last_analyze IS NULL for majority of tables) THEN ops_score -= 1
IF pg_version < 14                               THEN ops_score -= 1
IF free_tier_ipv6_only_detected AND user_host_lacks_ipv6 THEN ops_score -= 1

// --- 5b: Application Coupling sub-signal (up to 14 points) ---
// Measures service-layer rewrite scope. These are NOT DB-migration issues;
// they are out-of-band work that ships alongside the DB move.
IF has_auth AND auth_user_count > 0        THEN ops_score -= 3   // GoTrue replacement
IF has_storage AND storage_object_count > 0 THEN ops_score -= 3  // S3 bytes + signer rewrite
IF has_realtime AND supabase_realtime_slot_active THEN ops_score -= 2  // WebSocket rewrite

// PostgREST heuristic: any of the following counts as likely use
//   - any user table has GRANT to role 'anon' or 'authenticated'
//   - any user function is owned by 'anon' or 'authenticated'
//   - pg_graphql is installed AND active
IF postgrest_likely_in_use                 THEN ops_score -= 3

IF pg_cron_active_jobs > 0                 THEN ops_score -= MIN(pg_cron_active_jobs, 2)
IF has_supabase_vault AND vault_secrets_count > 0 THEN ops_score -= 1

ops_score = MAX(ops_score, 0)
```

---

## Final score

```
total = schema_score + data_score + query_score + code_score + ops_score
```

## Rating thresholds

| Score | Rating | Meaning |
|---|---|---|
| 90–100 | EXCELLENT | Near drop-in migration, minimal effort |
| 75–89 | GOOD | Straightforward migration with some refactoring |
| 50–74 | MODERATE | Significant refactoring needed, but feasible |
| 25–49 | CHALLENGING | Major application changes required (PostgREST/GoTrue/Realtime rewrite) |
| 0–24 | DIFFICULT | Requires substantial redesign; plan a multi-quarter project |

## Expected distribution for Supabase projects

| Profile | Expected score |
|---|---|
| Hello-world SaaS: 5 tables, 5 simple RLS policies, no extensions beyond pgcrypto, Auth only | ~75–85 (GOOD) |
| Typical production SaaS: 30 tables, 60 RLS policies, Auth + Storage + Realtime, 5 PL/pgSQL functions, pg_cron jobs | ~35–50 (CHALLENGING) |
| Heavy-feature app: pgvector RAG, pg_net webhooks, Vault secrets, custom extensions, 80+ policies, triggers, materialized views | ~10–25 (DIFFICULT) |

## Important scoring rules

- Each category floor is 0 — never go negative.
- Every deduction must be traceable to a specific condition listed above.
- `AUTO_INCREMENT` / `AUTO_RANDOM` mapping causes NO deduction on its own (it's a behavioral warning, not a blocker).
- RLS policies count as procedural code, not schema. A project with 50 simple ownership policies pays Procedural Code points, not Schema Compatibility points.
- The Application Coupling sub-signal (5b) can consume up to 14 of the 20 Ops points by itself. A project using the full Supabase service stack may land near zero Ops before any DB-level signals apply.

## Tier-specific scoring adjustments

When the target TiDB Cloud tier is Starter or Essential, apply these on top of the base scoring.

### Starter tier

```
IF tier == "starter":
    // Data Complexity — Starter is free up to 25 GiB
    IF total_data_gb > 25 THEN data_score -= 8   // Exceeds free tier
    ELSE IF total_data_gb > 20 THEN data_score -= 3  // Approaching limit

    // Operational Readiness — no Changefeeds or DM on Starter
    ops_score -= 2  // no zero-downtime cutover path
    IF wal_level == 'logical' THEN
        // Source supports CDC but Starter can't consume it — wasted capability
        ops_score -= 1
```

### Essential tier

```
IF tier == "essential":
    IF total_data_gb > 500 THEN data_score -= 3  // Lightning unavailable; recommend Dedicated
```

### Dedicated / self-hosted

No tier adjustments — use base rules as-is.
