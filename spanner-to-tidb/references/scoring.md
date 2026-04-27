# Readiness Scoring Methodology

4-category weighted model (procedural code eliminated — Spanner has no stored procedures, triggers, or UDFs). Maximum score: 100.

## Category 1: Schema Compatibility (30 points max)

Start at 30, deduct for unsupported or problematic schema features.

```
SET schema_score = 30

IF interleaved_table_count > 0 THEN schema_score -= MIN(interleaved_table_count * 2, 10)
IF array_column_count > 0 THEN schema_score -= MIN(array_column_count, 6)
IF proto_column_count > 0 THEN schema_score -= MIN(proto_column_count * 3, 9)
IF tokenlist_column_count > 0 THEN schema_score -= MIN(tokenlist_column_count * 3, 6)
IF graph_schema_detected THEN schema_score -= 5
IF struct_usage_in_views > 0 THEN schema_score -= MIN(struct_usage_in_views * 2, 6)
IF commit_timestamp_count > 0 THEN schema_score -= 1
IF proto_enum_count > 0 THEN schema_score -= 1

schema_score = MAX(schema_score, 0)
```

## Category 2: Data Complexity (25 points max)

Start at 25, deduct for volume and extraction complexity. Higher weight than other variants because Spanner data extraction (Dataflow → GCS) is more complex than dump-based sources.

```
SET data_score = 25

IF total_data > 500 GB THEN data_score -= 3
IF total_data > 1 TB THEN data_score -= 6
IF total_data > 5 TB THEN data_score -= 12
IF largest_table > 100 GB THEN data_score -= 3
IF bytes_column_count > 0 THEN data_score -= MIN(bytes_column_count, 4)
IF table_count > 1000 THEN data_score -= 2
IF array_column_count > 0 THEN data_score -= 2  // array data requires special export handling

data_score = MAX(data_score, 0)
```

## Category 3: Query Compatibility (20 points max)

Start at 20, deduct for GoogleSQL-specific query patterns.

```
SET query_score = 20

IF struct_query_count > 0 THEN query_score -= MIN(4, struct_query_count / 5)
IF array_function_count > 0 THEN query_score -= MIN(4, array_function_count / 10)
IF pending_commit_timestamp_count > 0 THEN query_score -= 2
IF stale_read_count > 0 THEN query_score -= 1
IF spanner_specific_function_count > 0 THEN query_score -= MIN(3, spanner_specific_function_count / 5)
IF farm_fingerprint_count > 0 THEN query_score -= 1

query_score = MAX(query_score, 0)
```

Spanner-specific functions include: `FARM_FINGERPRINT`, `GENERATE_UUID` (maps to `UUID()`), `SAFE_CAST` (no error-safe cast in MySQL), `NET.*` functions, `KEYS.*` functions.

## Category 4: Operational Readiness (25 points max)

Start at 25, deduct for infrastructure and operational gaps. Higher weight than other variants because Spanner requires GCP infrastructure setup (GCS bucket, Dataflow permissions, IAM) that other sources don't.

```
SET ops_score = 25

IF no_gcs_bucket_configured THEN ops_score -= 5
IF no_dataflow_permissions THEN ops_score -= 5
IF change_streams_not_configured AND sync_planned THEN ops_score -= 4
IF multi_region_instance THEN ops_score -= 3
IF no_service_account_key AND no_adc THEN ops_score -= 3
IF data_boost_not_available THEN ops_score -= 2
IF spanner_pg_dialect THEN ops_score -= 3  // PostgreSQL dialect adds complexity

ops_score = MAX(ops_score, 0)
```

## Overall Score

```
overall_score = schema_score + data_score + query_score + ops_score
```

Note: Procedural Code category is eliminated (0 points, no deductions). Spanner has no stored procedures, triggers, or UDFs.

## Score Interpretation

| Score | Rating | Meaning |
|---|---|---|
| 90-100 | Excellent | Near drop-in migration, minimal effort |
| 75-89 | Good | Straightforward migration with some refactoring |
| 50-74 | Moderate | Significant refactoring needed, but feasible |
| 25-49 | Challenging | Major application changes required |
| 0-24 | Difficult | Requires substantial redesign; discuss with PingCAP SA team |

Every deduction must be traceable. No hidden penalties.
