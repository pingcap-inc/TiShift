# Function Mapping — CockroachDB → TiDB/MySQL

## Automatic (sqlglot handles via `read="postgres"`)

| CockroachDB / Postgres | TiDB/MySQL | Notes |
|---|---|---|
| `::type` (cast) | `CAST(expr AS type)` | sqlglot handles. |
| `COALESCE(a, b)` | `COALESCE(a, b)` | Direct. |
| `EXTRACT(field FROM ts)` | `EXTRACT(field FROM ts)` | Direct. |
| `SERIAL` / `BIGSERIAL` | `AUTO_INCREMENT` | sqlglot maps; TiShift overrides to AUTO_RANDOM. |
| `BOOLEAN` | `TINYINT(1)` | sqlglot maps. |
| `TRUE` / `FALSE` | `TRUE` / `FALSE` | Direct (MySQL supports). |

## Manual Rewrite Required

| CockroachDB / Postgres | TiDB/MySQL | Notes |
|---|---|---|
| `gen_random_uuid()` | `UUID()` | |
| `unique_rowid()` | `AUTO_RANDOM` (as PK strategy) | Not a function replacement — schema-level change. |
| `now()` / `current_timestamp` | `NOW()` / `CURRENT_TIMESTAMP()` | |
| `array_agg(col)` | `JSON_ARRAYAGG(col)` | Returns JSON array. |
| `string_agg(col, sep)` | `GROUP_CONCAT(col SEPARATOR sep)` | |
| `\|\|` (string concat) | `CONCAT(a, b)` | |
| `TO_CHAR(ts, fmt)` | `DATE_FORMAT(ts, fmt)` | Format string conversion needed. |
| `REGEXP_REPLACE(str, pat, rep)` | `REGEXP_REPLACE(str, pat, rep)` | MySQL 8.0+/TiDB. |
| `substring(str from pat)` | `REGEXP_SUBSTR(str, pat)` | |

## JSONB Operator Rewrites

| CockroachDB | TiDB/MySQL | Example |
|---|---|---|
| `col @> '{"k":"v"}'` | `JSON_CONTAINS(col, '{"k":"v"}')` | Contains check |
| `col -> 'key'` | `col->'$.key'` or `JSON_EXTRACT(col, '$.key')` | Get JSON field |
| `col ->> 'key'` | `col->>'$.key'` | Get as text |
| `col ? 'key'` | `JSON_CONTAINS_PATH(col, 'one', '$.key')` | Key exists |
| `col ?| array['a','b']` | `JSON_CONTAINS_PATH(col, 'one', '$.a', '$.b')` | Any key exists |
| `col ?& array['a','b']` | `JSON_CONTAINS_PATH(col, 'all', '$.a', '$.b')` | All keys exist |
| `col #> '{a,b}'` | `JSON_EXTRACT(col, '$.a.b')` | Nested path |
| `col #>> '{a,b}'` | `JSON_UNQUOTE(JSON_EXTRACT(col, '$.a.b'))` | Nested path as text |

## CRDB Extensions to Strip (Pre-Processing)

These are not function mappings — they must be removed from DDL before sqlglot:

| CRDB Syntax | Action |
|---|---|
| `USING HASH WITH BUCKET_COUNT N` | Remove. Apply AUTO_RANDOM to PK if scatter needed. |
| `REGIONAL BY ROW` | Remove. Add `PLACEMENT POLICY` separately. |
| `SURVIVE ZONE FAILURE` / `SURVIVE REGION FAILURE` | Remove. Configure via PD. |
| `WITH (ttl_expiration_expression = '...', ttl_job_cron = '...')` | Rewrite to TiDB `TTL = col + INTERVAL n` and `TTL_JOB_INTERVAL`. |
| `CREATE INVERTED INDEX` | Rewrite as `CREATE INDEX ... ((CAST(col->>'$.key' AS ...)))` or remove. |
| `AS OF SYSTEM TIME` | Remove from queries. |
| `INTERLEAVE IN PARENT` | Remove. |
