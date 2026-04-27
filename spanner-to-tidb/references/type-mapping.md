# Cloud Spanner to TiDB Type Mapping Reference

## Table of Contents
1. [Numeric Types](#numeric-types)
2. [String and Binary Types](#string-and-binary-types)
3. [Date/Time Types](#datetime-types)
4. [Other Types](#other-types)
5. [Types Requiring Redesign](#types-requiring-redesign)
6. [Length and Precision Handling](#length-and-precision-handling)

---

## Numeric Types

| Spanner | TiDB | Notes |
|---|---|---|
| INT64 | BIGINT | Direct equivalent. Spanner has no smaller integer types (no INT32, INT16). |
| FLOAT32 | FLOAT | Single-precision approximate |
| FLOAT64 | DOUBLE | Double-precision approximate |
| NUMERIC | DECIMAL(38,9) | Exact. Spanner NUMERIC is always precision 38, scale 9. No customization. |
| BOOL | TINYINT(1) | TRUE/FALSE → 1/0 |

## String and Binary Types

| Spanner | TiDB | Notes |
|---|---|---|
| STRING(N) | VARCHAR(N) | Direct. If N > 16383, use TEXT instead. Spanner max N = 2,621,440 (2.5 MB). |
| STRING(MAX) | TEXT | Unbounded string. Use LONGTEXT if values typically exceed 64 KB. |
| BYTES(N) | VARBINARY(N) | Direct. If N > 65535, use LONGBLOB. |
| BYTES(MAX) | LONGBLOB | Unbounded binary |

## Date/Time Types

| Spanner | TiDB | Notes |
|---|---|---|
| DATE | DATE | Direct equivalent. Range: 0001-01-01 to 9999-12-31 in both. |
| TIMESTAMP | DATETIME(6) | Lossy — Spanner has nanosecond precision, TiDB has microsecond (6 fractional digits). Spanner TIMESTAMP is timezone-independent; TiDB DATETIME stores in session timezone. |

## Other Types

| Spanner | TiDB | Notes |
|---|---|---|
| JSON | JSON | Direct equivalent. Spanner max 10 MB, max 80 nesting levels. TiDB has no hard limit. |
| UUID | VARCHAR(36) | Alternative: BINARY(16) for storage efficiency. `GENERATE_UUID()` → `UUID()`. |

## Types Requiring Redesign

These types have no direct equivalent. Each requires a design decision.

| Spanner | Recommended TiDB | Alternative | Notes |
|---|---|---|---|
| ARRAY<INT64> | JSON | Normalized child table | BLOCKER-2. `[1,2,3]` stored as JSON array `'[1,2,3]'`. ARRAY functions (`ARRAY_LENGTH`, `UNNEST`) must be rewritten to JSON functions (`JSON_LENGTH`, `JSON_TABLE`). |
| ARRAY<STRING(N)> | JSON | Normalized child table | BLOCKER-2. `["a","b"]` as JSON array. |
| ARRAY<FLOAT64> | JSON | Normalized child table | BLOCKER-2. Floating-point precision may differ in JSON serialization. |
| ARRAY<STRUCT<...>> | JSON | Normalized child table | BLOCKER-2. Nested struct arrays serialize as JSON array of objects. |
| PROTO | JSON | Flattened columns | BLOCKER-3. Proto messages serialized as JSON. Lose proto validation and type safety. |
| ENUM (proto-backed) | ENUM('v1','v2',...) | VARCHAR | WARNING-6. Extract enum values from proto definition. |
| TOKENLIST | TEXT (non-functional) | External search engine | BLOCKER-4. Full-text search must use Elasticsearch/Meilisearch. |
| STRUCT | N/A (query-only) | JSON or scalar columns | BLOCKER-6. Not a column type in Spanner. Only appears in queries/views — rewrite those. |

## Length and Precision Handling

- **STRING length > 16383:** VARCHAR max in TiDB is 16383 characters (65532 bytes with utf8mb4). For longer strings, use `TEXT` (up to 64 KB) or `LONGTEXT` (up to 4 GB).
- **BYTES length > 65535:** VARBINARY max is 65535. For longer binary, use `LONGBLOB`.
- **NUMERIC precision:** Spanner NUMERIC is fixed at (38,9). Map directly to `DECIMAL(38,9)` — within TiDB's max of (65,30).
- **TIMESTAMP nanosecond precision:** Spanner stores nanoseconds; TiDB stores microseconds. Sub-microsecond data is truncated (loss of 3 digits). Flag if application requires nanosecond precision.
- **INT64 is the only integer type:** Spanner has no INT32, INT16, or TINYINT. All integers are 64-bit. Map all to BIGINT. If storage efficiency matters, the converter can suggest smaller types based on actual data range (via scan), but BIGINT is the safe default.
