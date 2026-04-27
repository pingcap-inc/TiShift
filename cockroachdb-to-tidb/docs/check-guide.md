# Check Guide — CockroachDB to TiDB

## Validation Steps

### 1. Row Count Comparison

**CockroachDB:**
```sql
SELECT count(*) FROM public.users;
```

**TiDB:**
```sql
SELECT COUNT(*) FROM myapp.users;
```

### 2. Column Structure

Compare `information_schema.columns` on both sides. Key checks:
- CRDB `INT` / `INT8` → TiDB `BIGINT` (not INT)
- CRDB `UUID` → TiDB `CHAR(36)` or `BINARY(16)`
- CRDB `STRING` → TiDB `TEXT`
- CRDB `JSONB` → TiDB `JSON`

### 3. JSON Data Verification

Spot-check JSONB columns to ensure JSON data is intact:
```sql
-- TiDB
SELECT id, JSON_VALID(metadata) FROM myapp.users LIMIT 10;
```

### 4. Sequence State

Verify TiDB sequences match CRDB:
```sql
SELECT * FROM information_schema.sequences WHERE sequence_schema = 'myapp';
```

## Common Issues

| Issue | Cause | Fix |
|---|---|---|
| Integer overflow | INT mapped to INT instead of BIGINT | ALTER TABLE MODIFY COLUMN to BIGINT |
| UUID format | BINARY(16) not displaying correctly | Use BIN_TO_UUID() for display |
| JSON query fails | JSONB operator not rewritten | Rewrite `@>` to `JSON_CONTAINS` |
