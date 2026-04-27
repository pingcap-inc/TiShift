# Type Mapping — Oracle → TiDB

## Numeric Types

| Oracle Type | TiDB/MySQL Type | Notes |
|---|---|---|
| `NUMBER(p,0)` where p ≤ 2 | `TINYINT` | Signed: -128 to 127 |
| `NUMBER(p,0)` where p ≤ 4 | `SMALLINT` | |
| `NUMBER(p,0)` where p ≤ 9 | `INT` | |
| `NUMBER(p,0)` where p ≤ 18 | `BIGINT` | |
| `NUMBER(p,s)` where p ≤ 65, s ≤ 30 | `DECIMAL(p,s)` | Exact precision mapping |
| `NUMBER(p,s)` where p > 65 | `DECIMAL(65,30)` | TiDB max precision. Potential precision loss. |
| `NUMBER` (no precision/scale) | `DECIMAL(38,10)` | Lossy — Oracle NUMBER is 38-digit floating point. Scan actual data for better fit. Add comment. |
| `FLOAT` / `FLOAT(p)` | `DOUBLE` | Oracle FLOAT is binary precision, not decimal. |
| `BINARY_FLOAT` | `FLOAT` | 32-bit IEEE 754 |
| `BINARY_DOUBLE` | `DOUBLE` | 64-bit IEEE 754 |
| `INTEGER` | `INT` | Oracle INTEGER = NUMBER(38,0); INT is sufficient for most cases |
| `SMALLINT` | `SMALLINT` | Oracle SMALLINT = NUMBER(38,0); map to actual range |

## String Types

| Oracle Type | TiDB/MySQL Type | Notes |
|---|---|---|
| `VARCHAR2(n BYTE)` / `VARCHAR2(n)` | `VARCHAR(n)` | Byte semantics (default) |
| `VARCHAR2(n CHAR)` | `VARCHAR(n*4)` | Char semantics — worst case 4 bytes/char in utf8mb4 |
| `NVARCHAR2(n)` | `VARCHAR(n*4)` | National character set → utf8mb4 |
| `CHAR(n)` | `CHAR(n)` | Fixed-length, space-padded |
| `NCHAR(n)` | `CHAR(n*4)` | National character set |
| `CLOB` | `LONGTEXT` | Up to 4 GB in both |
| `NCLOB` | `LONGTEXT` | National character CLOB |
| `LONG` | `LONGTEXT` | Deprecated Oracle type — still found in legacy schemas |

## Binary Types

| Oracle Type | TiDB/MySQL Type | Notes |
|---|---|---|
| `BLOB` | `LONGBLOB` | Up to 4 GB in both |
| `RAW(n)` | `VARBINARY(n)` | Raw binary data |
| `LONG RAW` | `LONGBLOB` | Deprecated. DMS limitation: > 64 KB not supported — extract via CSV. |

## Date and Time Types

| Oracle Type | TiDB/MySQL Type | Notes |
|---|---|---|
| `DATE` | `DATETIME` | **CRITICAL: Oracle DATE includes time (to the second). NEVER map to MySQL DATE.** Oracle stores 7 bytes: century, year, month, day, hour, minute, second. |
| `TIMESTAMP(p)` where p ≤ 6 | `DATETIME(p)` | Direct mapping. Microsecond precision. |
| `TIMESTAMP(p)` where p > 6 | `DATETIME(6)` | TiDB max = microseconds (6). Oracle supports nanoseconds (9). Precision loss if p > 6. |
| `TIMESTAMP WITH TIME ZONE` | `VARCHAR(40)` | TiDB DATETIME has no timezone. Store as string, or convert to UTC DATETIME + offset column. |
| `TIMESTAMP WITH LOCAL TIME ZONE` | `DATETIME(6)` | Convert to UTC at extraction time. |
| `INTERVAL YEAR TO MONTH` | `VARCHAR(20)` | No TiDB equivalent. Store as string or decompose to integer months. |
| `INTERVAL DAY TO SECOND` | `VARCHAR(30)` | No TiDB equivalent. Store as string or decompose to total seconds. |

## Special Types

| Oracle Type | TiDB/MySQL Type | Notes |
|---|---|---|
| `ROWID` / `UROWID` | `VARCHAR(18)` | Physical row address — no TiDB equivalent. Store as string if needed by application. |
| `XMLType` | `LONGTEXT` | No XML type in TiDB. Store as text; process XML in application layer. |
| `SDO_GEOMETRY` | `GEOMETRY` or `LONGTEXT` | Limited TiDB spatial support. Use LONGTEXT for complex spatial data. |
| `BFILE` | `VARCHAR(255)` | External file reference → store path as string. |
| `BOOLEAN` (PL/SQL only) | `TINYINT(1)` | Oracle BOOLEAN is PL/SQL-only; if exposed to SQL, map to TINYINT. |

## Conversion Notes

1. **Oracle DATE → DATETIME is non-negotiable.** This is the single most common type-mapping mistake in Oracle migrations. Oracle `DATE` stores date AND time. MySQL/TiDB `DATE` is date-only. Data loss is silent.

2. **NUMBER without precision requires data inspection.** `NUMBER` with no precision/scale can hold anything from 0.001 to 10^38. The default mapping to `DECIMAL(38,10)` is safe but wasteful. If possible, scan actual data (`SELECT MIN(col), MAX(col), MAX(LENGTH(col))`) to pick a tighter target type.

3. **VARCHAR2 CHAR vs BYTE semantics matter.** `VARCHAR2(100 CHAR)` means 100 characters, which in utf8mb4 could be up to 400 bytes. Map to `VARCHAR(400)` to avoid truncation. `VARCHAR2(100 BYTE)` or `VARCHAR2(100)` (byte is default) maps directly to `VARCHAR(100)`.

4. **TIMESTAMP precision capping.** Oracle supports up to 9 digits of fractional seconds (nanoseconds). TiDB supports up to 6 (microseconds). Precision loss for TIMESTAMP(7), TIMESTAMP(8), TIMESTAMP(9).

5. **LONG and LONG RAW are deprecated but still in use.** Many legacy Oracle schemas still have LONG columns (Oracle deprecated them in favor of CLOB/BLOB in Oracle 8i, circa 1999). AWS DMS cannot handle LONG values > 64 KB. Extract via CSV for these columns.
