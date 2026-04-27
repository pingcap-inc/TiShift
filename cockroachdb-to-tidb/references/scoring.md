# Readiness Scoring Methodology — CockroachDB → TiDB

5-category weighted model. Maximum score: 100.

CockroachDB and TiDB are both distributed SQL databases, so many features have near-equivalents. Procedural Code is weighted lowest (15) because CRDB only added stored procedures in v23.2 — most applications use app-tier logic.

## Category 1: Schema Compatibility (25 points max)

```
SET schema_score = 25

IF array_column_count > 0 THEN schema_score -= MIN(array_column_count, 5)
IF has_custom_types THEN schema_score -= 4
IF has_spatial_geography THEN schema_score -= 3
IF has_interleaved_tables THEN schema_score -= 3

hash_shard_ded = MIN(hash_sharded_index_count, 3)
schema_score -= hash_shard_ded

inverted_ded = MIN(inverted_index_count, 3)
schema_score -= inverted_ded

IF has_multi_region THEN schema_score -= 2
IF has_row_level_ttl THEN schema_score -= 1

schema_score = MAX(schema_score, 0)
```

## Category 2: Query Compatibility (25 points max)

```
SET query_score = 25

// If no view/procedure definitions analyzed, assume 20/25

jsonb_op_count = count of JSONB operator usage
query_score -= MIN(jsonb_op_count * 2, 6)

IF has_writable_ctes THEN query_score -= 4
IF has_returning_clause THEN query_score -= 2
IF has_full_text_search THEN query_score -= 3

array_usage = count of array operations in queries
query_score -= MIN(array_usage, 4)

IF has_as_of_system_time THEN query_score -= 1

query_score = MAX(query_score, 0)
```

## Category 3: Procedural Code (15 points max)

```
SET code_score = 15

IF zero procedures, functions, triggers → keep 15

FOR EACH stored procedure or function:
    IF lines < 10: deduct 1
    ELSE IF lines < 30: deduct 2
    ELSE IF lines < 100: deduct 3
    ELSE: deduct 4

trigger_ded = MIN(trigger_count * 2, 6)
code_score -= trigger_ded

code_score = MAX(code_score, 0)
```

## Category 4: Data Complexity (20 points max)

```
SET data_score = 20

IF total_data_mb > 5000000 THEN data_score -= 10
ELSE IF total_data_mb > 1000000 THEN data_score -= 5
ELSE IF total_data_mb > 500000 THEN data_score -= 2

IF largest_table_mb > 100000 THEN data_score -= 2

jsonb_col_ded = MIN(jsonb_column_count, 4)
data_score -= jsonb_col_ded

IF table_count > 1000 THEN data_score -= 2

data_score = MAX(data_score, 0)
```

## Category 5: Operational Readiness (15 points max)

```
SET ops_score = 15

crdb_major = major version number
IF crdb_major < 23 THEN ops_score -= 2
IF crdb_major < 22 THEN ops_score -= 2

IF has_multi_region AND no_placement_plan THEN ops_score -= 2
IF changefeeds_not_available THEN ops_score -= 3

// Tier-specific
IF target_tier = 'starter':
    IF total_data_mb > 25000 THEN ops_score -= 4
    ops_score -= 2  // no CDC

ops_score = MAX(ops_score, 0)
```

## Score Interpretation

| Score | Rating |
|---|---|
| 90–100 | Excellent |
| 75–89 | Good |
| 50–74 | Moderate |
| 25–49 | Challenging |
| 0–24 | Difficult |
