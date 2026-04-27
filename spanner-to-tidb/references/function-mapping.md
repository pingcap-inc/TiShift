# GoogleSQL to MySQL/TiDB Function Mapping

Use this reference when converting views, rewriting queries, or generating application code.

## Date/Time Functions

| GoogleSQL Function | MySQL/TiDB Equivalent | Notes |
|---|---|---|
| CURRENT_TIMESTAMP() | NOW(6) | Exact |
| CURRENT_DATE() | CURRENT_DATE | Exact |
| PENDING_COMMIT_TIMESTAMP() | NOW(6) | Lossy — loses TrueTime guarantee |
| TIMESTAMP_ADD(ts, INTERVAL n unit) | DATE_ADD(ts, INTERVAL n unit) | sqlglot handles via bigquery dialect |
| TIMESTAMP_SUB(ts, INTERVAL n unit) | DATE_SUB(ts, INTERVAL n unit) | sqlglot handles |
| TIMESTAMP_DIFF(ts1, ts2, unit) | TIMESTAMPDIFF(unit, ts2, ts1) | Argument order differs |
| TIMESTAMP_TRUNC(ts, unit) | DATE_FORMAT() + truncation | No direct equivalent. Rewrite per granularity. |
| DATE_ADD(date, INTERVAL n unit) | DATE_ADD(date, INTERVAL n unit) | Exact |
| DATE_SUB(date, INTERVAL n unit) | DATE_SUB(date, INTERVAL n unit) | Exact |
| DATE_DIFF(d1, d2, unit) | DATEDIFF(d1, d2) | MySQL DATEDIFF only returns days. For other units use TIMESTAMPDIFF. |
| DATE_TRUNC(date, unit) | DATE_FORMAT() + truncation | Same as TIMESTAMP_TRUNC |
| EXTRACT(part FROM ts) | EXTRACT(part FROM ts) | Mostly exact. Spanner `DAYOFWEEK` (1=Sunday) → MySQL `DAYOFWEEK()` (1=Sunday). |
| FORMAT_TIMESTAMP(fmt, ts) | DATE_FORMAT(ts, fmt) | Format string translation: `%Y`=year, `%m`=month, `%d`=day, `%H`=hour, `%M`=minute, `%S`=second |
| PARSE_TIMESTAMP(fmt, str) | STR_TO_DATE(str, fmt) | Format string translation |
| FORMAT_DATE(fmt, date) | DATE_FORMAT(date, fmt) | Same format translation |
| PARSE_DATE(fmt, str) | STR_TO_DATE(str, fmt) | Same format translation |

## String Functions

| GoogleSQL Function | MySQL/TiDB Equivalent | Notes |
|---|---|---|
| CONCAT(a, b, ...) | CONCAT(a, b, ...) | Exact |
| LENGTH(str) | CHAR_LENGTH(str) | Spanner LENGTH is character-based; MySQL LENGTH is byte-based |
| BYTE_LENGTH(str) | LENGTH(str) | MySQL LENGTH is byte-based |
| UPPER(str) / LOWER(str) | UPPER(str) / LOWER(str) | Exact |
| TRIM(str) | TRIM(str) | Exact |
| LTRIM(str) / RTRIM(str) | LTRIM(str) / RTRIM(str) | Exact |
| SUBSTR(str, pos, len) | SUBSTRING(str, pos, len) | sqlglot handles |
| REPLACE(str, old, new) | REPLACE(str, old, new) | Exact |
| REVERSE(str) | REVERSE(str) | Exact |
| REPEAT(str, n) | REPEAT(str, n) | Exact |
| LPAD(str, len, pad) | LPAD(str, len, pad) | Exact |
| RPAD(str, len, pad) | RPAD(str, len, pad) | Exact |
| STARTS_WITH(str, prefix) | str LIKE CONCAT(prefix, '%') | Or LEFT(str, LENGTH(prefix)) = prefix |
| ENDS_WITH(str, suffix) | str LIKE CONCAT('%', suffix) | Or RIGHT(str, LENGTH(suffix)) = suffix |
| REGEXP_CONTAINS(str, re) | str REGEXP re | Different syntax |
| REGEXP_EXTRACT(str, re) | REGEXP_SUBSTR(str, re) | TiDB 6.x+ |
| REGEXP_REPLACE(str, re, rep) | REGEXP_REPLACE(str, re, rep) | TiDB 6.x+ |
| STRING(value) | CAST(value AS CHAR) | Type cast to string |
| SPLIT(str, delim) | No direct equivalent | Use SUBSTRING_INDEX or JSON_TABLE with application logic |
| FORMAT('%d', n) | FORMAT(n, 0) or CAST | Limited — MySQL FORMAT adds commas. Use CAST instead. |
| GENERATE_UUID() | UUID() | Exact |

## Numeric Functions

| GoogleSQL Function | MySQL/TiDB Equivalent | Notes |
|---|---|---|
| ABS(n) | ABS(n) | Exact |
| CEIL(n) / CEILING(n) | CEIL(n) / CEILING(n) | Exact |
| FLOOR(n) | FLOOR(n) | Exact |
| ROUND(n, d) | ROUND(n, d) | Exact |
| TRUNC(n, d) | TRUNCATE(n, d) | Rename |
| MOD(a, b) | MOD(a, b) | Exact |
| POW(n, p) / POWER(n, p) | POW(n, p) / POWER(n, p) | Exact |
| SQRT(n) | SQRT(n) | Exact |
| LOG(n) | LN(n) | Spanner LOG is natural log |
| LOG(n, base) | LOG(base, n) | Argument order differs |
| LOG10(n) | LOG10(n) | Exact |
| GREATEST(a, b, ...) | GREATEST(a, b, ...) | Exact |
| LEAST(a, b, ...) | LEAST(a, b, ...) | Exact |
| SIGN(n) | SIGN(n) | Exact |
| SAFE_DIVIDE(a, b) | a / NULLIF(b, 0) | SAFE_DIVIDE returns NULL on zero; MySQL throws |
| IEEE_DIVIDE(a, b) | a / b | MySQL follows IEEE 754 for FLOAT/DOUBLE |
| FARM_FINGERPRINT(str) | No equivalent | Application-level hash. Use CRC32() or MD5() as alternatives. |
| SAFE_CAST(x AS type) | CAST(x AS type) | Lossy — SAFE_CAST returns NULL on error; CAST throws. Wrap in application error handling. |

## Aggregate Functions

| GoogleSQL Function | MySQL/TiDB Equivalent | Notes |
|---|---|---|
| COUNT(*) / SUM() / AVG() / MIN() / MAX() | Same | Exact |
| COUNTIF(cond) | SUM(CASE WHEN cond THEN 1 ELSE 0 END) | No direct equivalent |
| ANY_VALUE(expr) | ANY_VALUE(expr) | Supported in TiDB |
| ARRAY_AGG(expr) | JSON_ARRAYAGG(expr) | Returns JSON array instead of Spanner ARRAY |
| STRING_AGG(expr, delim) | GROUP_CONCAT(expr SEPARATOR delim) | sqlglot handles |
| LOGICAL_AND(expr) | MIN(expr) | With TINYINT(1) boolean representation |
| LOGICAL_OR(expr) | MAX(expr) | With TINYINT(1) boolean representation |
| APPROX_COUNT_DISTINCT(expr) | COUNT(DISTINCT expr) | Exact count instead of approximate |
| APPROX_QUANTILES(expr, n) | No direct equivalent | Use application-level quantile calculation |

## JSON Functions

| GoogleSQL Function | MySQL/TiDB Equivalent | Notes |
|---|---|---|
| JSON_VALUE(json, path) | JSON_UNQUOTE(JSON_EXTRACT(json, path)) | Or `->>` operator |
| JSON_QUERY(json, path) | JSON_EXTRACT(json, path) | Or `->` operator |
| JSON_VALUE_ARRAY(json, path) | JSON_EXTRACT(json, path) | Returns array — verify with JSON_TYPE |
| TO_JSON_STRING(val) | CAST(val AS JSON) | Approximate |
| PARSE_JSON(str) | CAST(str AS JSON) | Exact |
| JSON_TYPE(json) | JSON_TYPE(json) | Return values may differ |

## Conditional Functions

| GoogleSQL Function | MySQL/TiDB Equivalent | Notes |
|---|---|---|
| IF(cond, a, b) | IF(cond, a, b) | Exact |
| IFNULL(a, b) | IFNULL(a, b) | Exact |
| NULLIF(a, b) | NULLIF(a, b) | Exact |
| COALESCE(a, b, ...) | COALESCE(a, b, ...) | Exact |
| CASE WHEN ... END | CASE WHEN ... END | Exact |

## Array Functions (require ARRAY→JSON conversion)

After ARRAY columns are converted to JSON, these functions need rewriting:

| GoogleSQL Function | MySQL/TiDB Equivalent | Notes |
|---|---|---|
| ARRAY_LENGTH(arr) | JSON_LENGTH(json_col) | Direct |
| UNNEST(arr) | JSON_TABLE(json_col, '$[*]' COLUMNS(...)) | Row expansion |
| arr[OFFSET(n)] | JSON_EXTRACT(json_col, CONCAT('$[', n, ']')) | Array subscript access |
| arr[ORDINAL(n)] | JSON_EXTRACT(json_col, CONCAT('$[', n-1, ']')) | 1-based indexing |
| ARRAY_CONCAT(a, b) | JSON_MERGE_PRESERVE(a, b) | Concatenate JSON arrays |
| ARRAY_REVERSE(arr) | No direct equivalent | Application-level reversal |
| GENERATE_ARRAY(start, end) | No direct equivalent | Use recursive CTE |
