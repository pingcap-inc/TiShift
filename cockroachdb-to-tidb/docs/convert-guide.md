# Convert Guide — CockroachDB to TiDB

## Conversion Pipeline

1. **Strip CRDB extensions** — remove `USING HASH WITH BUCKET_COUNT`, `REGIONAL BY ROW`, `SURVIVE ZONE FAILURE`, `WITH (ttl_...)`, `INTERLEAVE IN PARENT`, `CREATE INVERTED INDEX`
2. **Type mapping** — INT→BIGINT, STRING→TEXT, BYTES→BLOB, UUID→CHAR(36), SERIAL→BIGINT AUTO_RANDOM, JSONB→JSON, ARRAY→JSON
3. **sqlglot transpile** — `read="postgres", write="mysql"`
4. **Post-processing** — rewrite JSONB operators, handle RETURNING, add ENGINE=InnoDB

## Critical Mappings

| CRDB | TiDB | Gotcha |
|---|---|---|
| `INT` | `BIGINT` | 64-bit! Silent truncation if mapped to INT. |
| `SERIAL` | `BIGINT AUTO_RANDOM` | Non-sequential scatter IDs in both. |
| `UUID DEFAULT gen_random_uuid()` | `CHAR(36) DEFAULT (UUID())` | |
| `JSONB` + `@>` operator | `JSON` + `JSON_CONTAINS()` | Every JSONB operator needs manual rewrite. |
| `STRING[]` (array) | `JSON` | Serialize as JSON array. |

## Output Files

- `01-create-tables.sql` — CREATE TABLE with type mappings
- `02-create-indexes.sql` — secondary indexes (drop before load)
- `03-create-views.sql` — views with function translations
- `04-foreign-keys.sql` — ALTER TABLE ADD FOREIGN KEY
- `05-create-sequences.sql` — CREATE SEQUENCE
- `06-conversion-notes.md` — procs, triggers, arrays, JSONB rewrites
