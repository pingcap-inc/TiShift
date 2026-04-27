# Postgres / Supabase Function → TiDB Function Mapping

Every Postgres function `scan` might encounter, plus the Supabase-specific helpers, mapped to TiDB equivalents. sqlglot handles most of these automatically via `write="mysql"`; the rows marked "manual rewrite" need explicit handling by TiShift's convert phase.

## Standard Postgres functions

### Date / time

| Postgres | TiDB | sqlglot | Notes |
|---|---|---|---|
| `now()` | `NOW()` | ✓ | Exact |
| `current_timestamp` | `CURRENT_TIMESTAMP` | ✓ | Exact |
| `current_date` | `CURRENT_DATE` | ✓ | Exact |
| `current_time` | `CURRENT_TIME` | ✓ | Exact |
| `extract(field FROM src)` | `EXTRACT(field FROM src)` | ✓ | Mostly exact; `epoch`, `isodow`, `isoyear` need rewrite |
| `date_trunc(granularity, ts)` | `DATE_FORMAT(ts, fmt)` + truncation | manual | No direct equivalent — map per granularity (`day` → `DATE(ts)`, `hour` → `DATE_FORMAT(ts, '%Y-%m-%d %H:00:00')`, etc.) |
| `age(ts)` / `age(ts1, ts2)` | `TIMESTAMPDIFF(unit, ts1, ts2)` | manual | Different semantics — `age` returns an interval; `TIMESTAMPDIFF` returns an integer in the specified unit |
| `to_char(ts, fmt)` | `DATE_FORMAT(ts, fmt)` | partial | Format string translation required (`YYYY-MM-DD` → `%Y-%m-%d`) |
| `to_date(str, fmt)` | `STR_TO_DATE(str, fmt)` | partial | Format string translation |
| `to_timestamp(str, fmt)` | `STR_TO_DATE(str, fmt)` | partial | Format string translation |

### String

| Postgres | TiDB | sqlglot | Notes |
|---|---|---|---|
| `length(str)` | `CHAR_LENGTH(str)` | ✓ | Postgres `length()` is character-based; MySQL `LENGTH()` is byte-based. Use `CHAR_LENGTH`. |
| `octet_length(str)` | `LENGTH(str)` | ✓ | Byte-based length |
| `substring(str FROM n FOR m)` | `SUBSTRING(str, n, m)` | ✓ | sqlglot handles the syntax difference |
| `trim(BOTH x FROM y)` | `TRIM(BOTH x FROM y)` | ✓ | Exact |
| `upper(str)` / `lower(str)` | `UPPER(str)` / `LOWER(str)` | ✓ | Exact |
| `concat(a, b, ...)` | `CONCAT(a, b, ...)` | ✓ | Exact |
| `a \|\| b` (concat operator) | `CONCAT(a, b)` | ✓ | sqlglot handles |
| `position(sub IN str)` | `LOCATE(sub, str)` | ✓ | sqlglot handles |
| `replace(str, from, to)` | `REPLACE(str, from, to)` | ✓ | Exact |
| `split_part(str, delim, n)` | `SUBSTRING_INDEX(SUBSTRING_INDEX(str, delim, n), delim, -1)` | manual | No direct equivalent; nested `SUBSTRING_INDEX` |
| `regexp_match(str, pat)` | `REGEXP_SUBSTR(str, pat)` | partial | Different return type (array vs string) — TiDB 6.x+ |
| `regexp_matches(str, pat, 'g')` | Loop or application | manual | No equivalent for the set-returning form |
| `regexp_replace(str, pat, repl)` | `REGEXP_REPLACE(str, pat, repl)` | ✓ | TiDB 6.x+ |
| `regexp_split_to_array` / `regexp_split_to_table` | Application logic | manual | No equivalent |

### Numeric

| Postgres | TiDB | sqlglot | Notes |
|---|---|---|---|
| `abs(n)` | `ABS(n)` | ✓ | Exact |
| `ceil(n)` / `ceiling(n)` | `CEIL(n)` / `CEILING(n)` | ✓ | Exact |
| `floor(n)` | `FLOOR(n)` | ✓ | Exact |
| `round(n, p)` | `ROUND(n, p)` | ✓ | Exact |
| `trunc(n, p)` | `TRUNCATE(n, p)` | ✓ | sqlglot handles the name change |
| `mod(a, b)` / `a % b` | `MOD(a, b)` / `a % b` | ✓ | Exact |
| `power(a, b)` / `^` | `POW(a, b)` | ✓ | sqlglot handles |
| `random()` | `RAND()` | ✓ | sqlglot handles |
| `greatest(...)` / `least(...)` | `GREATEST(...)` / `LEAST(...)` | ✓ | Exact |

### Null-handling

| Postgres | TiDB | sqlglot | Notes |
|---|---|---|---|
| `coalesce(...)` | `COALESCE(...)` | ✓ | Exact |
| `nullif(a, b)` | `NULLIF(a, b)` | ✓ | Exact |
| `ifnull(a, b)` (not standard) | `IFNULL(a, b)` | ✓ | MySQL-specific but sqlglot accepts |

### Aggregates

| Postgres | TiDB | sqlglot | Notes |
|---|---|---|---|
| `count(*)`, `sum()`, `avg()`, `min()`, `max()` | Same | ✓ | Exact |
| `string_agg(expr, delim)` | `GROUP_CONCAT(expr SEPARATOR delim)` | ✓ | sqlglot handles |
| `array_agg(expr)` | `JSON_ARRAYAGG(expr)` | partial | Returns JSON array instead of Postgres array |
| `json_agg(expr)` / `jsonb_agg(expr)` | `JSON_ARRAYAGG(expr)` | partial | Slight format differences |
| `json_object_agg(k, v)` / `jsonb_object_agg(k, v)` | `JSON_OBJECTAGG(k, v)` | partial | TiDB 5.x+ |
| `json_build_object(k, v, ...)` / `jsonb_build_object(...)` | `JSON_OBJECT(k, v, ...)` | partial | Argument format differs (pairs vs alternating) |
| `array_length(arr, dim)` | `JSON_LENGTH(json_arr)` | manual | After array → JSON conversion |

### Window functions

| Postgres | TiDB | sqlglot | Notes |
|---|---|---|---|
| `row_number()` / `rank()` / `dense_rank()` | Same | ✓ | Exact |
| `lag(expr, n, default)` / `lead(expr, n, default)` | Same | ✓ | Exact |
| `ntile(n)` | `NTILE(n)` | ✓ | Exact |
| `first_value(expr)` / `last_value(expr)` | Same | ✓ | Exact |
| `percent_rank()`, `cume_dist()` | Same | ✓ | Exact |

### JSON / JSONB operators

| Postgres operator | TiDB | sqlglot | Notes |
|---|---|---|---|
| `->` (field access, returns JSON) | `->` | ✓ | Exact in TiDB |
| `->>` (field access, returns text) | `->>` | ✓ | Exact in TiDB |
| `#>` (path access, returns JSON) | `JSON_EXTRACT(json, '$.path')` | manual | Rewrite required |
| `#>>` (path access, returns text) | `JSON_UNQUOTE(JSON_EXTRACT(...))` | manual | Rewrite required |
| `@>` (contains) | `JSON_CONTAINS(json, candidate)` | manual | BLOCKER-10 rewrite |
| `<@` (contained-by) | `JSON_CONTAINS(candidate, json)` | manual | Swap arguments |
| `?` (key exists) | `JSON_CONTAINS_PATH(json, 'one', '$.key')` | manual | Rewrite required |
| `?|` (any key exists) | Multiple `JSON_CONTAINS_PATH` with OR | manual | No single-call equivalent |
| `?&` (all keys exist) | Multiple `JSON_CONTAINS_PATH` with AND | manual | No single-call equivalent |
| `||` (concatenate JSON) | `JSON_MERGE_PATCH(a, b)` | manual | Semantics differ slightly |
| `-` (remove key) | `JSON_REMOVE(json, '$.key')` | manual | Rewrite required |

### JSON functions

| Postgres | TiDB | sqlglot | Notes |
|---|---|---|---|
| `json_each(json)` / `jsonb_each(json)` | `JSON_TABLE(json, '$.*' COLUMNS (...))` | manual | Different API; same result shape |
| `json_array_elements(json)` / `jsonb_array_elements(json)` | `JSON_TABLE(json, '$[*]' COLUMNS (...))` | manual | Rewrite required |
| `json_extract_path(json, 'a', 'b')` | `JSON_EXTRACT(json, '$.a.b')` | partial | Path format differs |
| `json_extract_path_text(...)` | `JSON_UNQUOTE(JSON_EXTRACT(...))` | manual | Rewrite required |
| `to_jsonb(val)` / `to_json(val)` | `CAST(val AS JSON)` | ✓ | sqlglot handles |

### Array functions (BLOCKER-9 — all need manual rewrite after array → JSON conversion)

| Postgres | Post-conversion approach |
|---|---|
| `array_length(arr, dim)` | `JSON_LENGTH(json_arr)` |
| `array_append(arr, elem)` | `JSON_ARRAY_APPEND(json_arr, '$', elem)` |
| `array_prepend(elem, arr)` | `JSON_ARRAY_INSERT(json_arr, '$[0]', elem)` |
| `unnest(arr)` | `JSON_TABLE(json_arr, '$[*]' COLUMNS (...))` |
| `ANY(arr)` / `ALL(arr)` | Rewrite as `JSON_CONTAINS` or subquery |
| `@>`, `<@`, `&&` on arrays | `JSON_CONTAINS` / `JSON_OVERLAPS` |

### Sequences (WARNING-8)

| Postgres | TiDB | Notes |
|---|---|---|
| `nextval('seq')` | `AUTO_INCREMENT` column default | Semantics differ (TiDB non-sequential) |
| `currval('seq')` | `LAST_INSERT_ID()` | Session-scoped |
| `setval('seq', n)` | `ALTER TABLE t AUTO_INCREMENT = n` | DDL, not a function |
| `lastval()` | `LAST_INSERT_ID()` | Session-scoped |

### Misc

| Postgres | TiDB | sqlglot | Notes |
|---|---|---|---|
| `generate_series(start, stop, step)` | Recursive CTE or application | manual | No equivalent; rewrite per use case |
| `::type` (cast operator) | `CAST(expr AS type)` | ✓ | sqlglot handles |
| `pg_advisory_lock(key)` | `GET_LOCK('name', timeout)` | manual | WARNING-12; limited semantics |
| `pg_advisory_unlock(key)` | `RELEASE_LOCK('name')` | manual | WARNING-12 |
| `pg_sleep(seconds)` | `SLEEP(seconds)` | ✓ | Exact |

---

## Supabase-specific helpers

All Supabase auth helpers (`auth.uid`, `auth.jwt`, `auth.role`, `auth.email`) read from a Postgres session GUC (`request.jwt.claims`) populated by PostgREST per request. TiDB has no equivalent mechanism — these call sites **must be rewritten** at the application layer.

| Supabase function | Target approach | Notes |
|---|---|---|
| `auth.uid()` | Inject user ID as a query parameter or session variable from middleware | BLOCKER-3. The pattern shifts from "the DB knows who's calling" to "the app knows and tells the DB". |
| `auth.jwt()` | Inject full JWT claims as JSON parameter | BLOCKER-3. If policies read `auth.jwt() -> 'app_metadata' -> 'tenant_id'`, the app now extracts and passes `tenant_id` directly. |
| `auth.role()` | Inject role string as parameter, or derive from the DB user connection | BLOCKER-3. For TiDB, the connection's DB user can serve this role — but only if you provision per-role DB users, which is usually not worth the operational complexity. |
| `auth.email()` | Inject email as parameter if needed | BLOCKER-3. Rarely load-bearing; usually used in audit logs. |

## Extension-schema function calls (WARNING-19)

Supabase's default `search_path` is `"$user", extensions, public`, so function calls like `gen_random_uuid()` resolve to `extensions.gen_random_uuid()`. TiDB has no `extensions` schema. The convert phase must strip the qualifier and map to the TiDB equivalent.

| Supabase qualified call | TiDB equivalent |
|---|---|
| `extensions.gen_random_uuid()` | `UUID()` |
| `extensions.uuid_generate_v4()` (uuid-ossp) | `UUID()` |
| `extensions.uuid_generate_v1()` | No equivalent — application-generated |
| `extensions.crypt(password, salt)` (pgcrypto) | No equivalent — bcrypt in application layer |
| `extensions.digest(data, type)` (pgcrypto) | `SHA1()` / `SHA2()` / `MD5()` for known algorithms |
| `extensions.encode(bytes, fmt)` | `TO_BASE64()` / `HEX()` for known encodings |
| `extensions.decode(text, fmt)` | `FROM_BASE64()` / `UNHEX()` for known encodings |

## Supabase platform functions (NOT migrated)

These never appear in code that survives the migration — call sites become BLOCKER-7 (pg_net) or get dropped entirely:

| Function | Handling |
|---|---|
| `net.http_get(url)` / `net.http_post(url, body, headers)` | BLOCKER-7 — rewrite as app-layer worker |
| `vault.create_secret(secret, name)` / `vault.decrypted_secrets` | BLOCKER-5 — migrate to target secrets manager |
| `cron.schedule(name, schedule, command)` | WARNING-5 — map to TiDB `CREATE EVENT` |
| `graphql.resolve(query, variables)` | WARNING-4 — rewrite GraphQL tier |
| `realtime.broadcast_changes(...)` | WARNING-3 — replace with TiCDC/Debezium |
