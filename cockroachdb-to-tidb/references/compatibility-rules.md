# Compatibility Rules — CockroachDB → TiDB

## Blockers

| ID | Condition | Feature | Action |
|---|---|---|---|
| BLOCKER-1 | `array_column_count > 0` | Array Columns (`INT[]`, `TEXT[]`, etc.) | No TiDB equivalent. Normalize into child table or serialize as JSON array column with expression index. |
| BLOCKER-2 | `has_jsonb_operators` | JSONB Operators (`@>`, `?`, `#>`, `?|`, `?&`) | Rewrite to `JSON_CONTAINS()`, `JSON_CONTAINS_PATH()`, `JSON_EXTRACT()`. TiDB has JSON but not JSONB binary operators. |
| BLOCKER-3 | `has_custom_types` | Custom Composite Types (`CREATE TYPE ... AS (...)`) | No TiDB equivalent. Flatten fields into columns or store as JSON. |
| BLOCKER-4 | `stored_procedure_count > 0` | Stored Procedures (v23.2+) | TiDB parses but does not execute. Rewrite as application code (AI-assisted). |
| BLOCKER-5 | `trigger_count > 0` | Triggers (v24.3+) | TiDB parses but does not execute. Rewrite as application middleware. |
| BLOCKER-6 | `has_writable_ctes` | Writable CTEs (`WITH ... INSERT/UPDATE/DELETE`) | No TiDB equivalent. Rewrite as separate DML in a transaction. |
| BLOCKER-7 | `has_full_text_search` | Full-Text Search (tsvector/tsquery) | TiDB has limited FULLTEXT (Cloud only, MySQL syntax). Recommend external search engine. |

## Warnings

| ID | Condition | Feature | Action |
|---|---|---|---|
| WARNING-1 | `hash_sharded_index_count > 0` | Hash-Sharded Indexes | Strip `USING HASH WITH BUCKET_COUNT` from DDL. Use `AUTO_RANDOM` PK or `SHARD_ROW_ID_BITS` for scatter. |
| WARNING-2 | `inverted_index_count > 0` | Inverted Indexes (GIN) | Rewrite as expression indexes on JSON paths. No multi-key index in TiDB. |
| WARNING-3 | `has_multi_region` | Multi-Region | Strip `REGIONAL BY ROW`, `SURVIVE ZONE/REGION FAILURE`. Map to TiDB `CREATE PLACEMENT POLICY`. |
| WARNING-4 | `has_row_level_ttl` | Row-Level TTL | Rewrite CRDB `WITH (ttl_expiration_expression = ...)` to TiDB `TTL = col + INTERVAL n`. Nearly 1:1. |
| WARNING-5 | `has_as_of_system_time` | AS OF SYSTEM TIME | Strip from queries. Map to TiDB `AS OF TIMESTAMP` or `SET @@tidb_read_staleness` in application. |
| WARNING-6 | `uuid_pk_count > 0` | UUID Primary Keys | Map `UUID` to `CHAR(36)` or `BINARY(16)`. Map `gen_random_uuid()` to `UUID()`. Consider `AUTO_RANDOM` as alternative. |
| WARNING-7 | `serial_column_count > 0` | SERIAL Columns | CRDB SERIAL uses `unique_rowid()` (non-sequential 64-bit). Map to `BIGINT AUTO_RANDOM` (scatter) or `BIGINT AUTO_INCREMENT`. |
| WARNING-8 | `has_returning_clause` | RETURNING Clause | TiDB 6.4+ has experimental support. Otherwise INSERT + SELECT LAST_INSERT_ID(). |
| WARNING-9 | `enum_type_count > 0` | Named ENUM Types | Convert `CREATE TYPE ... AS ENUM` to inline `ENUM('a','b','c')` in column definition. |
| WARNING-10 | `sequence_count > 0` | Sequences | TiDB supports `CREATE SEQUENCE` (v4.0+). Direct migration. |
| WARNING-11 | `has_zone_configs` | Zone Configurations | Strip from DDL. Map to `CREATE PLACEMENT POLICY`. |
| WARNING-12 | `partition_count > 0` | Table Partitioning | CRDB range partitioning syntax differs from TiDB. Rewrite with TiDB RANGE/LIST/HASH syntax. |
| WARNING-13 | `has_interleaved_tables` | Interleaved Tables (deprecated) | Drop interleaving. Use composite PKs with shared prefix for co-location. |
| WARNING-14 | `has_spatial_geography` | GEOGRAPHY Type | TiDB supports planar GEOMETRY only. GEOGRAPHY (geodesic) requires app-side conversion. |

## Compatible

- Standard types: VARCHAR, INT4, SMALLINT, BIGINT, DECIMAL, BOOLEAN, DATE, TIME, TIMESTAMP
- ANSI JOINs, subqueries, window functions
- CTEs (non-writable), CASE, UNION/EXCEPT/INTERSECT
- Aggregate functions, GROUP BY, HAVING, ORDER BY, LIMIT/OFFSET
- JSON type (without binary JSONB operators) and `->`, `->>` shorthand
- CREATE SEQUENCE (TiDB v4.0+)
- Generated/computed columns
- RANGE/LIST/HASH partitioning (syntax rewrite needed)
- Prepared statements, transactions
- `LOAD DATA LOCAL INFILE`

## JSON Output Format

```json
{
  "blockers": [{"id": "BLOCKER-1", "feature": "Array Columns", "count": 3, "action": "Normalize or serialize as JSON"}],
  "warnings": [{"id": "WARNING-1", "feature": "Hash-Sharded Indexes", "count": 2, "action": "Strip, use AUTO_RANDOM"}],
  "compatible": ["VARCHAR columns", "DECIMAL columns", "Window functions", "CTEs", "Sequences"]
}
```
