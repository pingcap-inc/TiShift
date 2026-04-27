# Function Mapping — OceanBase → TiDB

## MySQL Mode

Minimal — most MySQL functions are identical. Strip OceanBase-specific hints:

| OB Hint / Extension | Action |
|---|---|
| `/*+READ_CONSISTENCY(WEAK)*/` | Remove. Map to TiDB Stale Read if needed. |
| `/*+FROZEN_VERSION(...)*/` | Remove. |
| `/*+USE_PLAN_CACHE(...)*/` | Remove. |
| `/*+PARALLEL(N)*/` | Remove. TiDB handles parallel execution automatically. |

## Oracle Mode

Same as Oracle variant function mapping:

| OceanBase Oracle Function | TiDB/MySQL Equivalent |
|---|---|
| `NVL(a, b)` | `COALESCE(a, b)` |
| `DECODE(...)` | `CASE WHEN ...` |
| `TO_DATE(str, fmt)` | `STR_TO_DATE(str, fmt)` |
| `TO_CHAR(date, fmt)` | `DATE_FORMAT(date, fmt)` |
| `SYSDATE` | `NOW()` |
| `ROWNUM` | `LIMIT` / `ROW_NUMBER()` |
| `CONNECT BY` | `WITH RECURSIVE` |
| `LISTAGG(...)` | `GROUP_CONCAT(...)` |
| `(+)` outer join | `LEFT JOIN` / `RIGHT JOIN` |
| `\|\|` string concat | `CONCAT(a, b)` |
| `SEQUENCE.NEXTVAL` | `NEXT VALUE FOR seq` |

See Oracle variant `references/function-mapping.md` for complete table.
