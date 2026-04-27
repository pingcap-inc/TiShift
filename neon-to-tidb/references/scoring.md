# Readiness Scoring Methodology

5-category weighted model. Maximum score: 100.

## Category 1: Schema Compatibility (25 points max)

Start at 25, deduct for unsupported or problematic schema features.

```
SET schema_score = 25

IF array_column_count > 0 THEN schema_score -= MIN(array_column_count, 5)
IF jsonb_column_count > 0 THEN schema_score -= MIN(jsonb_column_count, 4)
IF custom_composite_type_count > 0 THEN schema_score -= MIN(custom_composite_type_count * 2, 6)
IF range_type_column_count > 0 THEN schema_score -= MIN(range_type_column_count, 4)
IF inheritance_count > 0 THEN schema_score -= MIN(inheritance_count * 3, 6)
IF rls_table_count > 0 THEN schema_score -= MIN(rls_table_count * 2, 6)
IF materialized_view_count > 0 THEN schema_score -= MIN(materialized_view_count, 3)
IF exclude_constraint_count > 0 THEN schema_score -= MIN(exclude_constraint_count * 2, 4)
IF extension_count_unsupported > 0 THEN schema_score -= MIN(extension_count_unsupported * 3, 9)
IF enum_type_count > 0 THEN schema_score -= 1
IF domain_type_count > 0 THEN schema_score -= 1
IF uuid_column_count > 0 THEN schema_score -= 1

schema_score = MAX(schema_score, 0)
```

**Unsupported extensions** include: `postgis`, `vector`, `ltree`, `pg_trgm` (if used for FTS), `hstore`, `citext`, `cube`, `earthdistance`, `tablefunc`, `intarray`. Standard Postgres extensions like `pg_stat_statements`, `pgcrypto`, `uuid-ossp` are not counted as unsupported.

## Category 2: Procedural Code (25 points max)

Start at 25, deduct for procedural code that must be rewritten.

```
SET code_score = 25

FOR EACH PL/pgSQL function or procedure:
    Count lines in definition (from pg_get_functiondef)
    Check for: CURSOR, EXECUTE ... USING, RAISE, PERFORM, nested function calls

    IF has dynamic SQL (EXECUTE) or nested function calls:
        IF lines > 100: deduct 5 (requires_redesign)
        ELSE: deduct 4 (complex)
    ELSE IF lines < 10 AND no CURSOR:
        deduct 1 (trivial)
    ELSE IF lines < 30 AND no CURSOR:
        deduct 2 (simple)
    ELSE IF has CURSOR or lines >= 100:
        deduct 3 (moderate)
    ELSE:
        deduct 2 (simple)

trigger_deduction = MIN(trigger_count * 2, 8)
code_score -= trigger_deduction

code_score = MAX(code_score, 0)
```

SQL-language functions (no PL/pgSQL body) deduct 1 each if they use Postgres-specific syntax that needs rewrite, 0 otherwise.

## Category 3: Query Compatibility (20 points max)

Start at 20, deduct for Postgres-specific query patterns. Requires `pg_stat_statements` extension for full accuracy. If unavailable, assume 17/20.

```
SET query_score = 20

// Only scored if pg_stat_statements is available
IF jsonb_operator_query_count > 0 THEN query_score -= MIN(3, jsonb_operator_query_count / 10)
IF returning_clause_count > 0 THEN query_score -= MIN(3, returning_clause_count / 10)
IF array_operator_query_count > 0 THEN query_score -= MIN(3, array_operator_query_count / 10)
IF listen_notify_count > 0 THEN query_score -= 2
IF advisory_lock_count > 0 THEN query_score -= 1
IF fulltext_query_count > 0 THEN query_score -= MIN(3, fulltext_query_count / 5)
IF generate_series_count > 0 THEN query_score -= 1

query_score = MAX(query_score, 0)
```

## Category 4: Data Complexity (20 points max)

Start at 20, deduct for volume and structural complexity.

```
SET data_score = 20

IF total_data > 500 GB THEN data_score -= 2
IF total_data > 1 TB THEN data_score -= 5
IF total_data > 5 TB THEN data_score -= 10
IF largest_table > 100 GB THEN data_score -= 2
IF bytea_column_count > 0 THEN data_score -= MIN(bytea_column_count, 5)
IF table_count > 1000 THEN data_score -= 2
IF unlogged_table_count > 0 THEN data_score -= MIN(unlogged_table_count, 3)

data_score = MAX(data_score, 0)
```

## Category 5: Operational Readiness (10 points max)

Start at 10, deduct for Neon/Postgres operational constraints.

```
SET ops_score = 10

IF wal_level != 'logical' AND sync_planned THEN ops_score -= 3
IF connection_is_pooled THEN ops_score -= 2
IF stats_stale (last_analyze IS NULL for majority of tables) THEN ops_score -= 2
IF pg_version < 14 THEN ops_score -= 1
IF encoding != 'UTF8' THEN ops_score -= 2

ops_score = MAX(ops_score, 0)
```

**Pooled connection detection:** Neon connection strings with `-pooler` suffix in hostname or port 6543 indicate PgBouncer pooling. This blocks `pg_dump`, `COPY`, and logical replication. The user must switch to a direct connection string.

**Stats staleness:** If `pg_stat_user_tables.last_analyze IS NULL` for most tables, the compute was recently restarted and statistics are not populated. Run `ANALYZE` before trusting row estimates or size calculations.

## Overall Score

```
overall_score = schema_score + code_score + query_score + data_score + ops_score
```

## Score Interpretation

| Score | Rating | Meaning |
|---|---|---|
| 90-100 | Excellent | Near drop-in migration, minimal effort |
| 75-89 | Good | Straightforward migration with some refactoring |
| 50-74 | Moderate | Significant refactoring needed, but feasible |
| 25-49 | Challenging | Major application changes required |
| 0-24 | Difficult | Requires substantial redesign; discuss with PingCAP SA team |

Every deduction must be traceable. No hidden penalties. The score report lists each deduction with the rule ID from `compatibility-rules.md` that triggered it.
