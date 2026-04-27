# TiDB Compatibility Rules for Neon/Postgres Migrations

## Table of Contents
1. [Blockers](#blockers)
2. [Warnings](#warnings)
3. [Postgres Feature Detection Patterns](#postgres-feature-detection-patterns)
4. [Compatible Features](#compatible-features)

---

## Blockers

These are hard stops. TiDB cannot handle these features — they must be redesigned before migration.

| ID | Feature | Why It Blocks | Action |
|---|---|---|---|
| BLOCKER-1 | Array columns (`INT[]`, `TEXT[]`, etc.) | No native array type in MySQL/TiDB | Convert to `JSON` array column or normalize into a child table. Rewrite array operators (`ANY`, `ALL`, `@>`, `&&`) |
| BLOCKER-2 | JSONB binary operators (`@>`, `<@`, `?`, `?|`, `?&`, `#>`, `#>>`) | TiDB has JSON but not JSONB or its operators | Rewrite to `JSON_CONTAINS()`, `JSON_EXTRACT()`, `JSON_OVERLAPS()`. Column type: `JSONB` → `JSON` |
| BLOCKER-3 | Custom composite types (`CREATE TYPE ... AS (...)`) | No user-defined composite types in MySQL/TiDB | Flatten into separate columns, or store as JSON |
| BLOCKER-4 | Table inheritance (`INHERITS`) | No table inheritance in MySQL/TiDB | Flatten parent+child into single table with discriminator column, or separate tables with application logic |
| BLOCKER-5 | Row-level security (RLS) policies | No RLS equivalent in TiDB | Must be reimplemented in application layer or middleware. Remove `CREATE POLICY` from DDL |
| BLOCKER-6 | PL/pgSQL functions and procedures | TiDB parses `CREATE FUNCTION`/`CREATE PROCEDURE` but has no procedural runtime — they cannot execute | Convert to application code (Python/Go/Java/JS). Use AI-assisted rewrite for complex logic |
| BLOCKER-7 | Triggers | TiDB parses `CREATE TRIGGER` but does not fire them | Move logic to application middleware or event hooks |
| BLOCKER-8 | Full-text search (`tsvector`, `tsquery`, GIN text indexes) | No equivalent full-text search engine in TiDB | Migrate to external search engine (Elasticsearch, Meilisearch, Typesense) |
| BLOCKER-9 | Range types (`int4range`, `tsrange`, `daterange`, etc.) | No range type in MySQL/TiDB | Flatten to two columns (`lower_bound`, `upper_bound`). Rewrite range operators (`@>`, `&&`, etc.) |
| BLOCKER-10 | Materialized views | TiDB does not support `CREATE MATERIALIZED VIEW` | Convert to regular table + scheduled refresh job (cron, application, or TiDB's `CREATE TABLE AS SELECT` + rebuild) |
| BLOCKER-11 | EXCLUDE constraints | No exclusion constraints in MySQL/TiDB | Must be enforced in application logic or with unique indexes where possible |
| BLOCKER-12 | LISTEN / NOTIFY | No pub/sub built into TiDB | Replace with application-level messaging (Redis Pub/Sub, Kafka, NATS) |
| BLOCKER-13 | PostGIS / spatial types (`geometry`, `geography`) | TiDB has no spatial indexes or spatial functions | Offload to dedicated geo service or application-layer library. Store coordinates as `DOUBLE` columns |
| BLOCKER-14 | pgvector (`vector` type, HNSW/IVFFlat indexes) | No vector type or ANN indexes in TiDB | Migrate to dedicated vector database (Pinecone, Qdrant, Weaviate) or application-level embeddings |

## Warnings

These features work differently in TiDB. They won't block migration but require review and possible adjustment.

| ID | Feature | How It Differs | Action |
|---|---|---|---|
| WARNING-1 | Named ENUM types (`CREATE TYPE ... AS ENUM`) | TiDB supports MySQL-style inline `ENUM(...)` only, not named types | Convert from `CREATE TYPE color AS ENUM ('red','blue')` to inline `ENUM('red','blue')` in column definition. Reusability lost |
| WARNING-2 | Sequences (`CREATE SEQUENCE`, `nextval()`, `currval()`) | TiDB uses `AUTO_INCREMENT` or `AUTO_RANDOM`. No explicit sequence objects | Map to `AUTO_INCREMENT`. Lose `currval()`, `setval()`, cross-table sequence sharing. If multiple tables share one sequence, flag for manual review |
| WARNING-3 | `RETURNING` clause | TiDB does not support `INSERT/UPDATE/DELETE ... RETURNING` | Rewrite as separate `INSERT` + `SELECT LAST_INSERT_ID()` or two-step query |
| WARNING-4 | UUID columns | Postgres has native `UUID` type and `gen_random_uuid()` | Map to `VARCHAR(36)` or `BINARY(16)`. TiDB supports `UUID()` function for generation |
| WARNING-5 | `SERIAL` / `BIGSERIAL` / `SMALLSERIAL` | Auto-incrementing shorthand | Map to `INT/BIGINT/SMALLINT AUTO_INCREMENT`. TiDB AUTO_INCREMENT is unique but not sequential across nodes. Consider `AUTO_RANDOM` for high-insert tables |
| WARNING-6 | Advisory locks (`pg_advisory_lock`) | TiDB has `GET_LOCK()`/`RELEASE_LOCK()` — limited: single lock, not reentrant | Warn if heavy usage. Suggest Redis-based distributed locks for complex locking patterns |
| WARNING-7 | Domain types (`CREATE DOMAIN`) | No domain type in MySQL/TiDB | Map to base type. Preserve CHECK constraint where possible (TiDB v6.6+ enforces CHECK) |
| WARNING-8 | `BOOLEAN` type | Postgres native boolean; TiDB uses `TINYINT(1)` | `TRUE`/`FALSE` → `1`/`0`. Application code must handle the difference |
| WARNING-9 | Unlogged tables | Data lost on Neon compute restart. TiDB has no "unlogged" concept | Convert to regular tables. Flag prominently if they contain business data — data may already be missing |
| WARNING-10 | Foreign keys | TiDB supports FK enforcement in v6.6+. Older versions parse but don't enforce | Verify target TiDB version. Warn about performance implications on write-heavy tables |
| WARNING-11 | `JSONB` columns (no operator usage) | TiDB stores JSON, not binary-optimized JSONB | Convert column type to `JSON`. Data is preserved. GIN index support lost |
| WARNING-12 | `hstore` extension | Key-value type, no equivalent in TiDB | Convert to `JSON` column |
| WARNING-13 | `timestamptz` (timestamp with time zone) | TiDB `DATETIME` stores in session timezone, not UTC-normalized like Postgres `timestamptz` | Map to `DATETIME(6)`. Ensure application handles timezone correctly. Document behavior difference |
| WARNING-14 | `interval` type | No interval arithmetic in TiDB | Store as string (`VARCHAR(255)`) or total seconds (`BIGINT`). Rewrite interval operations |

## Postgres Feature Detection Patterns

Scan function/procedure definitions (from `pg_proc`), trigger definitions (`information_schema.triggers`), and view definitions (`pg_get_viewdef`) for these patterns:

| Pattern | Detection | Maps To |
|---|---|---|
| Array usage | Column `data_type = 'ARRAY'` in `information_schema.columns` | BLOCKER-1 |
| JSONB operators | Query text matches `@>\|<@\|\?\|\?\|\|\?\&\|#>\|#>>` | BLOCKER-2 |
| Custom types | `pg_type.typtype IN ('c', 'r')` (composite, range) | BLOCKER-3, BLOCKER-9 |
| Table inheritance | `pg_inherits` has rows | BLOCKER-4 |
| Row-level security | `pg_class.relrowsecurity = true` | BLOCKER-5 |
| PL/pgSQL routines | `pg_proc` with `lanname = 'plpgsql'` | BLOCKER-6 |
| Triggers | `information_schema.triggers` has rows | BLOCKER-7 |
| Full-text search | Columns with `udt_name = 'tsvector'` | BLOCKER-8 |
| Range columns | `udt_name IN ('int4range','int8range','numrange','tsrange','tstzrange','daterange')` | BLOCKER-9 |
| Materialized views | `pg_class.relkind = 'm'` | BLOCKER-10 |
| EXCLUDE constraints | `pg_constraint.contype = 'x'` | BLOCKER-11 |
| LISTEN/NOTIFY | Query text matches `\b(LISTEN\|NOTIFY)\b` | BLOCKER-12 |
| PostGIS | `pg_extension.extname = 'postgis'` | BLOCKER-13 |
| pgvector | `pg_extension.extname = 'vector'` | BLOCKER-14 |
| Named ENUMs | `pg_type.typtype = 'e'` | WARNING-1 |
| Sequences | `information_schema.sequences` has rows | WARNING-2 |
| RETURNING clause | Function/view text matches `\bRETURNING\b` | WARNING-3 |
| UUID columns | `udt_name = 'uuid'` | WARNING-4 |
| SERIAL columns | `column_default LIKE 'nextval%'` | WARNING-5 |
| Advisory locks | Query text matches `pg_advisory_lock\|pg_try_advisory_lock` | WARNING-6 |
| Domain types | `pg_type.typtype = 'd'` | WARNING-7 |
| Unlogged tables | `pg_class.relpersistence = 'u'` | WARNING-9 |
| hstore | `pg_extension.extname = 'hstore'` | WARNING-12 |
| timestamptz columns | `udt_name = 'timestamptz'` | WARNING-13 |
| interval columns | `udt_name = 'interval'` | WARNING-14 |

## Compatible Features

These Postgres features work identically or near-identically in TiDB. No action needed.

| Feature | Notes |
|---|---|
| INT / BIGINT / SMALLINT | Direct mapping |
| DECIMAL / NUMERIC | Exact (max precision 65 in TiDB vs 1000 in Postgres — flag if p > 65) |
| FLOAT / DOUBLE PRECISION | Direct mapping |
| VARCHAR(n) / CHAR(n) / TEXT | Direct mapping |
| DATE / TIME / TIMESTAMP | Direct mapping (use DATETIME in TiDB) |
| JSON columns (standard `->` / `->>` operators) | Fully supported |
| INSERT / UPDATE / DELETE / SELECT | Standard SQL |
| JOINs (INNER, LEFT, RIGHT, CROSS) | Fully supported |
| Subqueries (scalar, correlated, EXISTS) | Fully supported |
| Window functions (ROW_NUMBER, RANK, DENSE_RANK, LEAD, LAG, etc.) | Fully supported |
| CTEs (`WITH` and `WITH RECURSIVE`) | Fully supported |
| CASE / COALESCE / NULLIF | Standard SQL functions |
| LIMIT / OFFSET | Supported |
| DISTINCT / GROUP BY / HAVING / ORDER BY | Standard SQL |
| Pessimistic transactions | Default mode in TiDB |
| RANGE / LIST / HASH partitioning | Supported (syntax may differ slightly) |
| UTF-8 (utf8mb4) | Neon enforces UTF-8; TiDB defaults to utf8mb4 |
| Prepared statements | Supported |
| LIKE / ILIKE | ILIKE → `LOWER(col) LIKE LOWER(pattern)` or collation-based |
