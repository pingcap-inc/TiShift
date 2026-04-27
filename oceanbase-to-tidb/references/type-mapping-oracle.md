# Type Mapping — OceanBase Oracle Mode → TiDB

Same mapping as Oracle → TiDB. Key rules:

| OceanBase Oracle Type | TiDB Type | Notes |
|---|---|---|
| `NUMBER(p,s)` | `DECIMAL(p,s)` / `INT` / `BIGINT` | Map by precision. |
| `NUMBER` (no precision) | `DECIMAL(38,10)` | Scan data for better fit. |
| `VARCHAR2(n)` | `VARCHAR(n)` or `VARCHAR(n*4)` | CHAR vs BYTE semantics. |
| `DATE` | `DATETIME` | **CRITICAL: Oracle-mode DATE includes time.** |
| `TIMESTAMP(p)` | `DATETIME(MIN(p,6))` | Capped at microseconds. |
| `CLOB` / `NCLOB` | `LONGTEXT` | |
| `BLOB` | `LONGBLOB` | |
| `RAW(n)` | `VARBINARY(n)` | |
| `ROWID` | `VARCHAR(18)` | |

See the Oracle variant `references/type-mapping.md` for the full table.
