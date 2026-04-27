# TiDB Compatibility Rules for Cloud Spanner Migrations

## Table of Contents
1. [Blockers](#blockers)
2. [Warnings](#warnings)
3. [Spanner Feature Detection Patterns](#spanner-feature-detection-patterns)
4. [Compatible Features](#compatible-features)

---

## Blockers

These are hard stops. TiDB cannot handle these features — they must be redesigned before migration.

| ID | Feature | Why It Blocks | Action |
|---|---|---|---|
| BLOCKER-1 | Interleaved tables (`INTERLEAVE IN PARENT`) | No physical row co-location mechanism in TiDB | Flatten to standard tables with FK constraints. Preserve composite PK (it's valid MySQL). Remove `INTERLEAVE IN PARENT` clause from DDL. |
| BLOCKER-2 | ARRAY columns (`ARRAY<STRING>`, `ARRAY<INT64>`, etc.) | No native array type in MySQL/TiDB | Convert to `JSON` column (array stored as JSON array) or normalize into child table. Rewrite `ARRAY_LENGTH()`, `UNNEST()`, array subscript access. |
| BLOCKER-3 | PROTO columns (Protocol Buffer types) | No proto type in MySQL/TiDB | Convert to `JSON` column (proto serialized as JSON) or flatten proto fields into separate columns. Lose proto schema validation. |
| BLOCKER-4 | TOKENLIST / full-text search index | No equivalent full-text search in TiDB | Migrate to external search engine (Elasticsearch, Meilisearch, Typesense). Store raw text in `TEXT` column. |
| BLOCKER-5 | Graph schema (`CREATE PROPERTY GRAPH`) | No graph query support in TiDB | Migrate to dedicated graph DB (Neo4j, Neptune) or implement traversal in application code. |
| BLOCKER-6 | STRUCT type in views/queries | No STRUCT type in MySQL/TiDB | Rewrite queries to use scalar columns or JSON. STRUCT is query-only in Spanner (not a column type), so schema migration is unaffected — only view definitions and application queries need rewriting. |

## Warnings

These features work differently in TiDB. They won't block migration but require review and possible adjustment.

| ID | Feature | How It Differs | Action |
|---|---|---|---|
| WARNING-1 | Commit timestamps (`allow_commit_timestamp`) | TiDB has no TrueTime. `PENDING_COMMIT_TIMESTAMP()` has no equivalent. | Map to `DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6)`. Lose server-side TrueTime guarantees and nanosecond precision. |
| WARNING-2 | Bit-reversed sequences / IDENTITY columns | Spanner uses bit-reversed sequences to avoid hotspots. TiDB uses `AUTO_RANDOM` for the same purpose. | Map to `AUTO_RANDOM` (recommended) or `AUTO_INCREMENT`. Both produce non-sequential unique values. |
| WARNING-3 | Row deletion policies (TTL) | Spanner `ROW DELETION POLICY` syntax differs from TiDB `TTL`. | Map to TiDB `TTL` attribute (v6.5+): `TTL = ts_column + INTERVAL 30 DAY`. Syntax translation needed. |
| WARNING-4 | Generated columns (`GENERATED ALWAYS AS (expr) STORED`) | TiDB supports generated columns but with a subset of functions. | Verify each expression is supported in TiDB. Common Spanner expressions (`FARM_FINGERPRINT`, `GENERATE_UUID`) need rewriting. |
| WARNING-5 | Interleaved indexes (`INTERLEAVE IN parent`) | No index interleaving in TiDB. | Convert to standard secondary indexes. Lose co-location optimization. |
| WARNING-6 | PROTO ENUM columns | TiDB supports MySQL-style inline `ENUM(...)` only. | Extract enum values from proto definition and create inline `ENUM('val1','val2',...)`. |
| WARNING-7 | NUMERIC type | Spanner NUMERIC is always (38,9). TiDB DECIMAL supports (1-65, 0-30). | Map to `DECIMAL(38,9)`. Exact mapping — no precision loss. |
| WARNING-8 | STRING(MAX) columns | Unbounded string. | Map to `TEXT` (up to 64 KB typical) or `LONGTEXT` (up to 4 GB). |
| WARNING-9 | BYTES(MAX) columns | Unbounded binary. | Map to `LONGBLOB`. |
| WARNING-10 | BOOL columns | Spanner native boolean. TiDB uses TINYINT(1). | `TRUE`/`FALSE` → `1`/`0`. Application code must handle the difference. |
| WARNING-11 | Foreign keys | TiDB supports FK enforcement in v6.6+. | Verify target TiDB version. Warn about performance implications on write-heavy tables. |
| WARNING-12 | Stale reads (`STALENESS` clause) | TiDB has `AS OF TIMESTAMP` for stale reads. | Syntax translation needed. Concept is equivalent. |
| WARNING-13 | Change streams (DDL objects) | No equivalent DDL in TiDB. TiDB has TiCDC for outbound CDC. | Change streams are consumed during the sync phase, not migrated as schema objects. Drop from DDL output. |
| WARNING-14 | Multi-region configuration | TiDB Cloud Dedicated supports multi-AZ but not multi-region with same linearizability. | Flag for architecture review. Document consistency model differences. |

## Spanner Feature Detection Patterns

Query `INFORMATION_SCHEMA` to detect features:

| Pattern | Detection Query | Maps To |
|---|---|---|
| Interleaved tables | `TABLES WHERE PARENT_TABLE_NAME IS NOT NULL` | BLOCKER-1 |
| ARRAY columns | `COLUMNS WHERE SPANNER_TYPE LIKE 'ARRAY%'` | BLOCKER-2 |
| PROTO columns | `COLUMNS WHERE SPANNER_TYPE LIKE 'PROTO%'` | BLOCKER-3 |
| TOKENLIST columns | `COLUMNS WHERE SPANNER_TYPE = 'TOKENLIST'` | BLOCKER-4 |
| STRUCT in views | Parse `VIEW_DEFINITION` for `STRUCT<` or `AS STRUCT` | BLOCKER-6 |
| Commit timestamps | `COLUMN_OPTIONS WHERE OPTION_NAME = 'allow_commit_timestamp' AND OPTION_VALUE = 'TRUE'` | WARNING-1 |
| Sequences / IDENTITY | `SEQUENCES` table has rows, or `COLUMNS.IS_IDENTITY = 'YES'` | WARNING-2 |
| Row deletion policies | `TABLES WHERE ROW_DELETION_POLICY_EXPRESSION IS NOT NULL` | WARNING-3 |
| Generated columns | `COLUMNS WHERE IS_GENERATED = 'ALWAYS'` | WARNING-4 |
| Interleaved indexes | `INDEXES WHERE PARENT_TABLE_NAME IS NOT NULL` | WARNING-5 |
| PROTO ENUM columns | `COLUMNS WHERE SPANNER_TYPE LIKE 'ENUM%'` | WARNING-6 |
| Change streams | `CHANGE_STREAMS` table has rows | WARNING-13 |

## Compatible Features

These Spanner features work identically or near-identically in TiDB. No action needed.

| Feature | Notes |
|---|---|
| INT64 → BIGINT | Direct mapping |
| FLOAT32 → FLOAT | Direct mapping |
| FLOAT64 → DOUBLE | Direct mapping |
| STRING(N) → VARCHAR(N) | Direct mapping (flag if N > 16383 → use TEXT) |
| DATE → DATE | Direct mapping |
| TIMESTAMP → DATETIME(6) | Microsecond precision (nanosecond precision loss) |
| JSON columns | Fully supported in TiDB |
| INSERT / UPDATE / DELETE / SELECT | Standard SQL |
| JOINs (INNER, LEFT, RIGHT, CROSS) | Fully supported |
| Subqueries (scalar, correlated, EXISTS) | Fully supported |
| Window functions (ROW_NUMBER, RANK, etc.) | Fully supported |
| CTEs (`WITH` and `WITH RECURSIVE`) | Fully supported |
| CASE / COALESCE / NULLIF / IF | Standard SQL |
| LIMIT / OFFSET | Supported |
| Views (read-only) | Supported |
| CHECK constraints | Supported in TiDB v6.6+ |
| Standard secondary indexes | Fully supported |
| Composite primary keys | Fully supported |
| NULL filtering on indexes | Not directly supported — use partial index workarounds |
