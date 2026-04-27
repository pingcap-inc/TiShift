# Supabase (Postgres) → TiDB Type Mapping

Supabase runs vanilla Postgres 15+. This table covers every Postgres type a `scan` might encounter, including the extension-provided types common on Supabase projects (`uuid`, `jsonb`, `hstore`, `vector`, `geometry`, `tsvector`).

## Numeric types

| Postgres type | TiDB/MySQL type | Notes |
|---|---|---|
| `smallint` / `int2` | `SMALLINT` | Exact |
| `integer` / `int4` / `int` | `INT` | Exact |
| `bigint` / `int8` | `BIGINT` | Exact |
| `smallserial` | `SMALLINT AUTO_INCREMENT` | sqlglot handles |
| `serial` | `INT AUTO_INCREMENT` | sqlglot handles |
| `bigserial` | `BIGINT AUTO_INCREMENT` | sqlglot handles |
| `decimal(p, s)` / `numeric(p, s)` | `DECIMAL(p, s)` | Postgres max precision is 1000; TiDB max is 65. Flag if `p > 65`. |
| `real` / `float4` | `FLOAT` | Approximate |
| `double precision` / `float8` | `DOUBLE` | Exact |
| `money` | `DECIMAL(19, 2)` | Lossy — loses locale-dependent formatting |

## Boolean

| Postgres type | TiDB/MySQL type | Notes |
|---|---|---|
| `boolean` / `bool` | `TINYINT(1)` | `TRUE` → `1`, `FALSE` → `0`. Application code handling raw `TRUE`/`FALSE` strings must be reviewed. |

## Character types

| Postgres type | TiDB/MySQL type | Notes |
|---|---|---|
| `char(n)` / `character(n)` | `CHAR(n)` | Exact up to 255 |
| `varchar(n)` / `character varying(n)` | `VARCHAR(n)` | Exact |
| `varchar` (unlimited) | `TEXT` | Postgres allows unbounded `varchar`; TiDB requires a length or `TEXT` |
| `text` | `TEXT` (or `LONGTEXT` for very large rows) | Use `TEXT` unless column profile shows >64 KB strings |
| `citext` (extension) | `VARCHAR(n) COLLATE utf8mb4_general_ci` | Map to case-insensitive collation |
| `name` | `VARCHAR(64)` | Internal Postgres type — rare in user schemas |

## Date / time

| Postgres type | TiDB/MySQL type | Notes |
|---|---|---|
| `date` | `DATE` | Exact |
| `time` / `time without time zone` | `TIME(6)` | Fractional seconds preserved |
| `time with time zone` (`timetz`) | `TIME(6)` | Lossy — timezone info dropped |
| `timestamp` / `timestamp without time zone` | `DATETIME(6)` | Exact |
| `timestamp with time zone` (`timestamptz`) | `DATETIME(6)` | Lossy — TiDB does not UTC-normalize. Application must enforce UTC at write time. See WARNING-21. |
| `interval` | `VARCHAR(255)` or application logic | No native interval arithmetic in TiDB. Store as text or seconds. |

## Binary

| Postgres type | TiDB/MySQL type | Notes |
|---|---|---|
| `bytea` | `LONGBLOB` | Binary data mapping. Watch row size limits. |
| `bit(n)` | `BIT(n)` | Exact up to 64 |
| `bit varying(n)` / `varbit(n)` | `VARBINARY(CEIL(n/8))` | Approximate |

## UUID

| Postgres type | TiDB/MySQL type | Notes |
|---|---|---|
| `uuid` | `VARCHAR(36)` (readable) or `BINARY(16)` (compact) | See WARNING-10. `gen_random_uuid()` → TiDB `UUID()`. |

## JSON

| Postgres type | TiDB/MySQL type | Notes |
|---|---|---|
| `json` | `JSON` | Direct mapping |
| `jsonb` (no operator usage) | `JSON` | Lossy — loses binary storage and GIN indexing (WARNING-17) |
| `jsonb` (with `@>` / `?` / `#>` usage) | `JSON` + rewrite call sites | BLOCKER-10. Rewrite operators to `JSON_CONTAINS()` / `JSON_EXTRACT()` / `JSON_OVERLAPS()`. |
| `hstore` (extension) | `JSON` | Functional equivalent; WARNING-18 |

## Network types

| Postgres type | TiDB/MySQL type | Notes |
|---|---|---|
| `inet` | `VARCHAR(45)` | IPv4 + IPv6 string form. Loses IP arithmetic operators. |
| `cidr` | `VARCHAR(45)` | Same as `inet` plus prefix length |
| `macaddr` | `VARCHAR(17)` | `xx:xx:xx:xx:xx:xx` string form |
| `macaddr8` | `VARCHAR(23)` | EUI-64 string form |

## Arrays (BLOCKER-9)

| Postgres type | TiDB/MySQL type | Notes |
|---|---|---|
| `int[]`, `text[]`, any `T[]` | `JSON` (array) or child table | BLOCKER. Convert to JSON array (preserves data, loses array operators) or normalize. Manual review per column. |

## Range types (BLOCKER-16)

| Postgres type | TiDB/MySQL type | Notes |
|---|---|---|
| `int4range`, `int8range`, `numrange` | Two columns: `{col}_lower`, `{col}_upper` | Flatten boundaries |
| `tsrange`, `tstzrange`, `daterange` | Two columns: `{col}_lower`, `{col}_upper` | Flatten boundaries |

## Composite / custom types (BLOCKER-11)

| Postgres type | TiDB/MySQL type | Notes |
|---|---|---|
| `CREATE TYPE ... AS (...)` composite | `JSON` or flattened columns | BLOCKER. No MySQL equivalent. |
| `CREATE TYPE ... AS ENUM (...)` named enum | Inline `ENUM(...)` in column def | WARNING-7. Loses named-type reuse. |
| `CREATE DOMAIN` | Base type + CHECK constraint | WARNING-13. Requires TiDB v6.6+ for CHECK enforcement. |

## Full-text search (BLOCKER-15)

| Postgres type | TiDB/MySQL type | Notes |
|---|---|---|
| `tsvector` | `TEXT` (non-functional) | BLOCKER. Offload search to external engine. |
| `tsquery` | N/A | BLOCKER. No equivalent. |
| `regconfig` | `VARCHAR(64)` | Only relevant if using parametric text search configs |

## Spatial (BLOCKER-20)

| Postgres type | TiDB/MySQL type | Notes |
|---|---|---|
| `point`, `line`, `lseg`, `box`, `path`, `polygon`, `circle` | `TEXT` or `JSON` | BLOCKER. No spatial operations in TiDB. |
| `geometry`, `geography` (PostGIS) | `TEXT` or `JSON` | BLOCKER. Offload to PostGIS or application-layer geo library. |

## Vector / AI (BLOCKER-21)

| Postgres type | TiDB/MySQL type | Notes |
|---|---|---|
| `vector(n)` (pgvector) | N/A — migrate embeddings out of DB | BLOCKER. Move to Qdrant / Weaviate / Pinecone / Milvus. Keep source text in TiDB. |
| `halfvec(n)` / `sparsevec(n)` | N/A | Same as `vector` |

## XML (blocker — rarely seen on Supabase)

| Postgres type | TiDB/MySQL type | Notes |
|---|---|---|
| `xml` | `LONGTEXT` | Lossy — no XML functions. Process in application layer. |

## Supabase-specific schemas (NOT migrated)

The following types appear only in Supabase-internal schemas and are never migrated:

| Source schema.type | Rationale |
|---|---|
| `auth.users.encrypted_password` | Bcrypt hash; export separately as part of the auth-migration plan |
| `storage.objects.metadata` | JSON metadata for S3-backed objects; migrate only if keeping Storage service |
| `vault.secrets.secret` | Encrypted via pgsodium project key; cannot round-trip |
| `pgsodium.key.decrypted_*` | Encryption keys; project-scoped |
| `realtime.*` | Service-internal state |

---

## Collation

Supabase databases default to `en_US.UTF-8`. TiDB uses `utf8mb4_general_ci` (case-insensitive) or `utf8mb4_bin` (case-sensitive) by default.

| Postgres collation | TiDB/MySQL collation | Notes |
|---|---|---|
| `en_US.UTF-8` (default) | `utf8mb4_general_ci` | Case-insensitive equivalence |
| `"C"` / `"POSIX"` | `utf8mb4_bin` | Byte-wise comparison |
| `pg_catalog."default"` | `utf8mb4_general_ci` | Treat as UTF-8 default |
| ICU collation (e.g., `en-US-x-icu`) | `utf8mb4_0900_ai_ci` (TiDB 5.4+) or `utf8mb4_general_ci` | Verify sort order with a spot-check on string-sensitive columns |

If the scan reports non-standard collation on any column, validate string comparison behavior (`ORDER BY`, `=`, `LIKE`) post-migration before cutover.
