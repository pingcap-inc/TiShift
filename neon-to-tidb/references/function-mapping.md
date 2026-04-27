# Postgres to MySQL/TiDB Function Mapping

Use this reference when converting views, rewriting queries, or generating application code stubs.

## Direct Function Translations

| Postgres Function | MySQL/TiDB Equivalent | Notes |
|---|---|---|
| now() | NOW() | Exact |
| current_timestamp | CURRENT_TIMESTAMP | Exact |
| current_date | CURRENT_DATE | Exact |
| current_time | CURRENT_TIME | Exact |
| clock_timestamp() | NOW(6) | Approximate — clock_timestamp() returns wall-clock time; NOW() returns transaction start |
| gen_random_uuid() | UUID() | TiDB supports UUID() natively |
| random() | RAND() | Same range (0.0 to 1.0) |
| ceil() / ceiling() | CEIL() / CEILING() | Exact |
| floor() | FLOOR() | Exact |
| round(numeric, int) | ROUND(numeric, int) | Exact |
| trunc(numeric, int) | TRUNCATE(numeric, int) | Rename only |
| abs(n) | ABS(n) | Exact |
| power(n, p) | POWER(n, p) | Exact |
| sqrt(n) | SQRT(n) | Exact |
| mod(a, b) | MOD(a, b) | Exact |
| div(a, b) | a DIV b | Integer division |
| log(base, n) | LOG(base, n) | Exact |
| ln(n) | LN(n) | Exact |
| greatest(a, b, ...) | GREATEST(a, b, ...) | Exact |
| least(a, b, ...) | LEAST(a, b, ...) | Exact |

## String Functions

| Postgres Function | MySQL/TiDB Equivalent | Notes |
|---|---|---|
| length(str) | CHAR_LENGTH(str) | Postgres `length()` is character-based. MySQL `LENGTH()` is byte-based — use `CHAR_LENGTH()` |
| octet_length(str) | LENGTH(str) | Byte count |
| char_length(str) | CHAR_LENGTH(str) | Exact |
| \|\| (string concat) | CONCAT(a, b) | Operator → function. sqlglot handles |
| concat(a, b, ...) | CONCAT(a, b, ...) | Exact |
| substring(str FROM n FOR m) | SUBSTRING(str, n, m) | sqlglot handles syntax |
| substr(str, n, m) | SUBSTRING(str, n, m) | Exact |
| left(str, n) | LEFT(str, n) | Exact |
| right(str, n) | RIGHT(str, n) | Exact |
| upper(str) | UPPER(str) | Exact |
| lower(str) | LOWER(str) | Exact |
| trim(str) | TRIM(str) | Exact |
| ltrim(str) | LTRIM(str) | Exact |
| rtrim(str) | RTRIM(str) | Exact |
| replace(str, old, new) | REPLACE(str, old, new) | Exact |
| reverse(str) | REVERSE(str) | Exact |
| repeat(str, n) | REPEAT(str, n) | Exact |
| lpad(str, len, fill) | LPAD(str, len, fill) | Exact |
| rpad(str, len, fill) | RPAD(str, len, fill) | Exact |
| position(sub IN str) | LOCATE(sub, str) | sqlglot handles |
| strpos(str, sub) | LOCATE(sub, str) | Argument order swap |
| split_part(str, delim, n) | SUBSTRING_INDEX() | Not exact — requires nested SUBSTRING_INDEX for middle parts |
| string_agg(expr, delim) | GROUP_CONCAT(expr SEPARATOR delim) | sqlglot handles. Note: GROUP_CONCAT has a default max length (`group_concat_max_len`) |
| regexp_replace(str, pat, rep) | REGEXP_REPLACE(str, pat, rep) | Supported in TiDB 6.x+ |
| regexp_matches(str, pat) | REGEXP_SUBSTR(str, pat) | Different return type (set of text[] vs string) |
| initcap(str) | No direct equivalent | Implement in application or use `CONCAT(UPPER(LEFT(str,1)), LOWER(SUBSTRING(str,2)))` for single words |
| md5(str) | MD5(str) | Exact |

## Date/Time Functions

| Postgres Function | MySQL/TiDB Equivalent | Notes |
|---|---|---|
| extract(field FROM source) | EXTRACT(field FROM source) | Mostly exact. Postgres `epoch` → use `UNIX_TIMESTAMP()`. Postgres `isodow` → `DAYOFWEEK()` adjusted |
| date_trunc(field, source) | No direct equivalent | Rewrite per granularity: `date_trunc('month', ts)` → `DATE_FORMAT(ts, '%Y-%m-01')` |
| date_part(field, source) | EXTRACT(field FROM source) | Alias for extract |
| age(ts1, ts2) | TIMESTAMPDIFF(unit, ts2, ts1) | Different semantics — age returns interval; TIMESTAMPDIFF returns integer in specified unit |
| to_char(ts, fmt) | DATE_FORMAT(ts, fmt) | Format string translation: `YYYY`→`%Y`, `MM`→`%m`, `DD`→`%d`, `HH24`→`%H`, `MI`→`%i`, `SS`→`%s` |
| to_date(str, fmt) | STR_TO_DATE(str, fmt) | Same format string translation as to_char |
| to_timestamp(str, fmt) | STR_TO_DATE(str, fmt) | Returns DATETIME, not timestamp |
| to_number(str, fmt) | CAST(str AS DECIMAL) | Approximate — loses format mask |
| make_date(y, m, d) | DATE(CONCAT(y,'-',m,'-',d)) | Constructed date |
| make_timestamp(...) | No direct equivalent | Build with CONCAT + STR_TO_DATE |
| interval '1 day' | INTERVAL 1 DAY | Syntax differs. sqlglot handles basic cases |
| now() + interval '1 hour' | DATE_ADD(NOW(), INTERVAL 1 HOUR) | sqlglot handles |
| generate_series(start, end) | No equivalent | Use recursive CTE: `WITH RECURSIVE ... UNION ALL` |
| generate_series(start, end, step) | No equivalent | Recursive CTE with step |

## Aggregate Functions

| Postgres Function | MySQL/TiDB Equivalent | Notes |
|---|---|---|
| array_agg(expr) | JSON_ARRAYAGG(expr) | Returns JSON array, not Postgres array |
| json_agg(expr) / jsonb_agg(expr) | JSON_ARRAYAGG(expr) | Exact for JSON output |
| json_object_agg(k, v) | No direct equivalent | Use `JSON_OBJECTAGG(k, v)` in TiDB 7.x+, or `CONCAT('{',...,'}')` |
| string_agg(expr, delim) | GROUP_CONCAT(expr SEPARATOR delim) | See string functions |
| bool_and(expr) | MIN(expr) | With TINYINT(1) boolean representation |
| bool_or(expr) | MAX(expr) | With TINYINT(1) boolean representation |
| every(expr) | MIN(expr) | Alias for bool_and |
| count(*) | COUNT(*) | Exact |
| sum() / avg() / min() / max() | Same | Exact |

## JSON Functions

| Postgres Function | MySQL/TiDB Equivalent | Notes |
|---|---|---|
| -> (field access) | -> | Exact in TiDB |
| ->> (text access) | ->> | Exact in TiDB |
| @> (contains) | JSON_CONTAINS(target, candidate) | BLOCKER-2. Argument order differs |
| <@ (contained by) | JSON_CONTAINS(candidate, target) | BLOCKER-2. Reversed |
| ? (key exists) | JSON_CONTAINS_PATH(doc, 'one', '$.key') | BLOCKER-2 |
| ?\| (any key exists) | JSON_CONTAINS_PATH(doc, 'one', '$.k1', '$.k2') | BLOCKER-2 |
| ?& (all keys exist) | JSON_CONTAINS_PATH(doc, 'all', '$.k1', '$.k2') | BLOCKER-2 |
| #> (path access) | JSON_EXTRACT(doc, '$.path') | Returns JSON |
| #>> (path text access) | JSON_UNQUOTE(JSON_EXTRACT(doc, '$.path')) | Returns text |
| json_build_object(k1, v1, ...) | JSON_OBJECT(k1, v1, ...) | Same semantics |
| json_build_array(v1, v2, ...) | JSON_ARRAY(v1, v2, ...) | Same semantics |
| json_each(doc) | JSON_TABLE(doc, '$[*]' COLUMNS(...)) | Different API, similar result |
| jsonb_set(doc, path, val) | JSON_SET(doc, path, val) | sqlglot may handle |
| jsonb_insert(doc, path, val) | JSON_INSERT(doc, path, val) | sqlglot may handle |
| json_array_length(doc) | JSON_LENGTH(doc) | Exact for arrays |
| json_typeof(val) | JSON_TYPE(val) | Similar but return values differ |

## Conditional / Misc

| Postgres Function | MySQL/TiDB Equivalent | Notes |
|---|---|---|
| coalesce(a, b, ...) | COALESCE(a, b, ...) | Exact (ANSI SQL) |
| nullif(a, b) | NULLIF(a, b) | Exact |
| CASE WHEN ... END | CASE WHEN ... END | Exact |
| cast(x AS type) | CAST(x AS type) | Exact. Note: Postgres `::` cast operator → `CAST()` (sqlglot handles) |
| x::int | CAST(x AS SIGNED) | sqlglot handles |
| x::text | CAST(x AS CHAR) | sqlglot handles |
| EXISTS (subquery) | EXISTS (subquery) | Exact |
| IN (subquery) | IN (subquery) | Exact |
| ILIKE | LOWER(col) LIKE LOWER(pattern) | Or use a case-insensitive collation (utf8mb4_general_ci) |
