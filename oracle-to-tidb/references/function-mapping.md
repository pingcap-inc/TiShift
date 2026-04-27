# Function Mapping — Oracle → TiDB/MySQL

## Automatic (sqlglot handles)

These conversions are performed by `sqlglot.transpile(sql, read="oracle", write="mysql")`:

| Oracle | TiDB/MySQL | Notes |
|---|---|---|
| `SYSDATE` | `CURRENT_TIMESTAMP()` | |
| `NVL(a, b)` | `COALESCE(a, b)` | |
| `DECODE(a, b, c, d, e, f)` | `CASE a WHEN b THEN c WHEN d THEN e ELSE f END` | |
| `TO_DATE(str, fmt)` | `STR_TO_DATE(str, fmt)` | Format strings auto-converted (YYYY→%Y, MM→%m, DD→%d, HH24→%H, MI→%i, SS→%s) |
| `MINUS` | `EXCEPT` | Requires MySQL 8.0.31+ / TiDB |

## Manual Rewrite Required (sqlglot does NOT convert)

These require custom post-processing rules in TiShift's convert phase:

| Oracle | TiDB/MySQL | Rewrite Strategy |
|---|---|---|
| `CONNECT BY` / `START WITH` | `WITH RECURSIVE` CTE | Structural rewrite — each CONNECT BY query must be rewritten as a recursive CTE. No mechanical translation possible. |
| `ROWNUM` (in WHERE) | `LIMIT n` | `WHERE ROWNUM <= N` → append `LIMIT N`. For `ROWNUM` used in subqueries or with ordering, use `ROW_NUMBER() OVER () AS rn` + outer filter. |
| `(+)` outer join | `LEFT JOIN` / `RIGHT JOIN` | Rewrite to ANSI join syntax. `WHERE a.col = b.col(+)` → `FROM a LEFT JOIN b ON a.col = b.col`. sqlglot silently drops (+). |
| `LISTAGG(col, sep) WITHIN GROUP (ORDER BY ...)` | `GROUP_CONCAT(col ORDER BY ... SEPARATOR sep)` | Direct functional equivalent but different syntax. |
| `NVL2(a, b, c)` | `IF(a IS NOT NULL, b, c)` | |
| `TO_CHAR(date, fmt)` | `DATE_FORMAT(date, fmt)` | Format string conversion needed. |
| `TO_CHAR(number)` | `CAST(number AS CHAR)` | |
| `TO_NUMBER(str)` | `CAST(str AS DECIMAL)` | Or `str + 0` for simple cases. |
| `TRUNC(date)` | `DATE(date)` | Truncate to day. |
| `TRUNC(date, 'MM')` | `DATE_FORMAT(date, '%Y-%m-01')` | Truncate to month. |
| `TRUNC(date, 'YYYY')` | `DATE_FORMAT(date, '%Y-01-01')` | Truncate to year. |
| `ADD_MONTHS(date, n)` | `DATE_ADD(date, INTERVAL n MONTH)` | |
| `MONTHS_BETWEEN(d1, d2)` | `TIMESTAMPDIFF(MONTH, d2, d1)` | Approximate — Oracle returns fractional months. |
| `INSTR(str, substr)` | `LOCATE(substr, str)` | Argument order swapped. |
| `LENGTH(str)` | `CHAR_LENGTH(str)` | Character length. |
| `LENGTHB(str)` | `LENGTH(str)` | Byte length (MySQL LENGTH is byte-based). |
| `\|\|` (string concat) | `CONCAT(a, b)` | Or nested CONCAT for 3+ args. |
| `SYSTIMESTAMP` | `NOW(6)` | Microsecond precision. |
| `REGEXP_LIKE(str, pattern)` | `str REGEXP pattern` | |

## Sequence Syntax

| Oracle | TiDB | Notes |
|---|---|---|
| `sequence_name.NEXTVAL` | `NEXT VALUE FOR sequence_name` | TiDB sequence syntax (v4.0+) |
| `sequence_name.CURRVAL` | `LASTVAL(sequence_name)` | Must follow a NEXTVAL call in same session |
| `CREATE SEQUENCE seq START WITH 1 INCREMENT BY 1 CACHE 20` | `CREATE SEQUENCE seq START WITH 1 INCREMENT BY 1 CACHE 20` | Nearly identical syntax |

## Date Format String Conversion

| Oracle Format | MySQL Format | Meaning |
|---|---|---|
| `YYYY` | `%Y` | 4-digit year |
| `YY` | `%y` | 2-digit year |
| `MM` | `%m` | Month (01-12) |
| `MON` | `%b` | Abbreviated month name |
| `MONTH` | `%M` | Full month name |
| `DD` | `%d` | Day of month (01-31) |
| `DY` | `%a` | Abbreviated day name |
| `DAY` | `%W` | Full day name |
| `HH24` | `%H` | Hour (00-23) |
| `HH` / `HH12` | `%h` | Hour (01-12) |
| `MI` | `%i` | Minutes (00-59) |
| `SS` | `%s` | Seconds (00-59) |
| `FF` / `FF6` | `%f` | Microseconds |
| `AM` / `PM` | `%p` | AM/PM indicator |

## NULL Semantics

Oracle treats empty string (`''`) as `NULL`. TiDB/MySQL does not. This affects:

- `WHERE col IS NULL` — in Oracle, matches both NULL and empty string values
- `NVL(col, 'default')` — in Oracle, triggers on empty strings too
- String concatenation: `'abc' || NULL` = `NULL` in Oracle but `CONCAT('abc', NULL)` = `NULL` in MySQL too (same behavior)

During validation (Phase 7), spot-check VARCHAR columns for empty-string vs NULL discrepancies.
