# Type Mapping — CockroachDB → TiDB

## Critical Rule

**CockroachDB `INT` is 64-bit.** Always map to `BIGINT`. This is the #1 type-mapping mistake.

## Numeric Types

| CockroachDB | TiDB/MySQL | Notes |
|---|---|---|
| `INT` / `INT8` / `INT64` | `BIGINT` | **64-bit in CRDB.** Do NOT map to MySQL INT (32-bit). |
| `INT4` / `INT32` | `INT` | 32-bit. |
| `INT2` / `INT16` / `SMALLINT` | `SMALLINT` | |
| `BOOL` / `BOOLEAN` | `TINYINT(1)` | |
| `FLOAT4` / `REAL` | `FLOAT` | 32-bit IEEE 754. |
| `FLOAT8` / `DOUBLE PRECISION` | `DOUBLE` | 64-bit IEEE 754. |
| `DECIMAL(p,s)` / `NUMERIC(p,s)` | `DECIMAL(p,s)` | Exact mapping. |
| `SERIAL` | `BIGINT AUTO_RANDOM` | CRDB SERIAL uses `unique_rowid()` (non-sequential 64-bit). AUTO_RANDOM is the closest TiDB equivalent. Use AUTO_INCREMENT if sequential is acceptable. |

## String Types

| CockroachDB | TiDB/MySQL | Notes |
|---|---|---|
| `STRING` / `TEXT` | `TEXT` or `LONGTEXT` | CRDB STRING is unbounded. |
| `STRING(n)` / `VARCHAR(n)` | `VARCHAR(n)` | |
| `CHAR(n)` | `CHAR(n)` | |
| `NAME` | `VARCHAR(64)` | PG system type, rarely in user tables. |

## Binary Types

| CockroachDB | TiDB/MySQL | Notes |
|---|---|---|
| `BYTES` / `BYTEA` | `BLOB` or `LONGBLOB` | |
| `BYTES(n)` | `VARBINARY(n)` | |

## Date/Time Types

| CockroachDB | TiDB/MySQL | Notes |
|---|---|---|
| `DATE` | `DATE` | Date-only (unlike Oracle). Safe direct mapping. |
| `TIME` | `TIME` | |
| `TIMESTAMP` | `DATETIME(6)` | Without timezone. |
| `TIMESTAMPTZ` | `DATETIME(6)` | CRDB stores UTC, renders in session TZ. Extract as UTC. |
| `INTERVAL` | `VARCHAR(40)` | No TiDB equivalent. Store as string or decompose. |

## JSON Types

| CockroachDB | TiDB/MySQL | Notes |
|---|---|---|
| `JSONB` | `JSON` | TiDB JSON is text-based, no binary optimization. Operators `@>`, `?`, `#>` must be rewritten. `->` and `->>` work in TiDB. |

## Special Types

| CockroachDB | TiDB/MySQL | Notes |
|---|---|---|
| `UUID` | `CHAR(36)` or `BINARY(16)` | If PK: `CHAR(36) DEFAULT (UUID())` or `BINARY(16) DEFAULT (UUID_TO_BIN(UUID()))`. |
| `INET` | `VARCHAR(45)` | IPv4/IPv6 as string. |
| `BIT(n)` | `BIT(n)` | Direct. |
| `ARRAY` (e.g., `INT[]`) | `JSON` or child table | Serialize as JSON array, or normalize into child table. |
| `ENUM` (named type) | Inline `ENUM('a','b','c')` | Inline enum values in column definition. |
| `GEOMETRY` | `GEOMETRY` | TiDB basic spatial support. |
| `GEOGRAPHY` | `GEOMETRY` or `LONGTEXT` | Geodesic → planar conversion needed, or store as text. |
| `OID` | `INT UNSIGNED` | Rarely used. |

## Conversion Notes

1. **INT → BIGINT is mandatory.** CRDB `INT` = `INT8` = 64-bit. MySQL/TiDB `INT` = 32-bit. Silent data truncation if mapped incorrectly.
2. **SERIAL → AUTO_RANDOM preferred.** CRDB SERIAL generates `unique_rowid()` values that are non-sequential and 64-bit. `BIGINT AUTO_RANDOM` produces similar scatter behavior in TiDB. `BIGINT AUTO_INCREMENT` works but loses scatter.
3. **UUID PK storage choice.** `CHAR(36)` is human-readable but 36 bytes per row in every index. `BINARY(16)` is compact (16 bytes) but requires `UUID_TO_BIN()`/`BIN_TO_UUID()` for display. Recommend CHAR(36) for ease unless storage is critical.
4. **TIMESTAMPTZ → DATETIME(6).** CRDB stores internally as UTC. Extract timestamps in UTC to avoid timezone confusion.
5. **JSONB → JSON loses binary optimization.** CRDB JSONB is binary-indexed; TiDB JSON is text-parsed. Queries may be slower. Consider expression indexes on hot JSON paths.
