# Neon/Postgres to TiDB Type Mapping Reference

## Table of Contents
1. [Numeric Types](#numeric-types)
2. [Date/Time Types](#datetime-types)
3. [String Types](#string-types)
4. [Binary Types](#binary-types)
5. [JSON Types](#json-types)
6. [Special Types](#special-types)
7. [Types Requiring Redesign](#types-requiring-redesign)

---

## Numeric Types

| Postgres | TiDB | Notes |
|---|---|---|
| smallint | SMALLINT | Direct equivalent |
| integer / int | INT | Direct equivalent |
| bigint | BIGINT | Direct equivalent |
| smallserial | SMALLINT AUTO_INCREMENT | Auto-incrementing shorthand |
| serial | INT AUTO_INCREMENT | Auto-incrementing shorthand |
| bigserial | BIGINT AUTO_INCREMENT | Auto-incrementing shorthand |
| decimal(p,s) / numeric(p,s) | DECIMAL(p,s) | Exact. Postgres max precision 1000; TiDB max 65. Flag if p > 65 |
| real | FLOAT | 4-byte approximate |
| double precision | DOUBLE | 8-byte approximate |
| money | DECIMAL(19,2) | Lossy — loses locale-dependent formatting |
| boolean | TINYINT(1) | TRUE/FALSE → 1/0 |

## Date/Time Types

| Postgres | TiDB | Notes |
|---|---|---|
| date | DATE | Direct equivalent |
| time | TIME(6) | Microsecond precision |
| time with time zone | TIME(6) | Lossy — timezone info dropped |
| timestamp | DATETIME(6) | Microsecond precision |
| timestamp with time zone | DATETIME(6) | Lossy — TiDB stores in session timezone, not UTC-normalized. Application must handle TZ conversion |
| interval | VARCHAR(255) | Lossy — no native interval arithmetic. Alternative: store as total seconds in BIGINT |

## String Types

| Postgres | TiDB | Notes |
|---|---|---|
| char(n) | CHAR(n) | Direct equivalent |
| varchar(n) | VARCHAR(n) | Direct equivalent |
| varchar (unlimited) | TEXT | Postgres unlimited varchar maps to TEXT |
| text | TEXT | Direct equivalent |
| name | VARCHAR(63) | Postgres internal identifier type |
| "char" | CHAR(1) | Single-byte internal type |

## Binary Types

| Postgres | TiDB | Notes |
|---|---|---|
| bytea | LONGBLOB | Binary data |
| bit(n) | BIT(n) | Fixed-length bit string |
| bit varying(n) | VARBINARY(n) | Variable-length bit string (approximate) |

## JSON Types

| Postgres | TiDB | Notes |
|---|---|---|
| json | JSON | Direct equivalent |
| jsonb | JSON | Lossy — loses binary optimization, GIN index support, and JSONB-specific operators. Data is preserved |

## Special Types

| Postgres | TiDB | Notes |
|---|---|---|
| uuid | VARCHAR(36) | Alternative: BINARY(16) for storage efficiency. `gen_random_uuid()` → `UUID()` |
| inet | VARCHAR(45) | Lossy — no IP-specific operators or indexing |
| cidr | VARCHAR(45) | Lossy — no network address operators |
| macaddr | VARCHAR(17) | String representation |
| xml | TEXT | Lossy — no XML functions in TiDB |
| oid | INT UNSIGNED | Postgres object identifier |

## Types Requiring Redesign

These types have no direct equivalent. Each requires a design decision.

| Postgres | Recommended TiDB | Alternative | Notes |
|---|---|---|---|
| int[] / text[] / any array | JSON | Normalized child table | BLOCKER-1. `ARRAY[1,2,3]` → `'[1,2,3]'` as JSON. Array operators must be rewritten |
| hstore | JSON | — | Key-value pairs. `'a=>1, b=>2'::hstore` → `'{"a":"1","b":"2"}'` |
| tsvector | TEXT | External search engine | BLOCKER-8. Non-functional as TEXT — full-text search must use Elasticsearch/Meilisearch |
| int4range / tsrange / etc. | Two columns (lower, upper) | JSON | BLOCKER-9. `'[1,10)'::int4range` → `lower_bound=1, upper_bound=10, bound_type='[)'` |
| composite type | JSON | Flattened columns | BLOCKER-3. `(name text, age int)` → `JSON` column or `name TEXT, age INT` |
| geometry / geography | DOUBLE lat + DOUBLE lng | JSON (GeoJSON) | BLOCKER-13. No spatial operations. Store coordinates as separate columns |
| vector(N) | JSON | External vector DB | BLOCKER-14. No ANN index support. Use dedicated vector database |
| ltree | VARCHAR(255) | — | Materialized path as string. ltree operators must be rewritten |
| citext | VARCHAR(n) | — | Case-insensitive text. Use `utf8mb4_general_ci` collation instead |

## Precision and Length Handling

- **DECIMAL precision > 65:** Postgres allows up to 1000 digits; TiDB caps at 65. Flag columns where `numeric_precision > 65` and truncate with a warning.
- **VARCHAR without length:** Postgres `varchar` without length is unlimited; map to `TEXT`.
- **CHAR without length:** Defaults to `CHAR(1)` in both systems.
- **SERIAL overflow:** `serial` is 4-byte (max 2,147,483,647). If the sequence is near this limit, use `bigserial` → `BIGINT AUTO_INCREMENT`.
