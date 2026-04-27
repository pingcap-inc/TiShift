# Check Guide — Oracle to TiDB

## Validation Steps

After loading data, validate integrity by comparing source and target:

### 1. Row Count Comparison

Compare table row counts between Oracle and TiDB.

**Oracle (estimates from catalog):**
```sql
SELECT table_name, num_rows FROM all_tables WHERE owner = 'HR' ORDER BY table_name;
```

**Oracle (exact counts for critical tables):**
```sql
SELECT COUNT(*) FROM HR.EMPLOYEES;
```

**TiDB:**
```sql
SELECT table_name, table_rows FROM information_schema.tables WHERE table_schema = 'hr';
```

Flag any difference > 1%. For exact comparison, use `COUNT(*)` on both sides.

### 2. Column Structure Comparison

Verify that every Oracle column was mapped correctly to TiDB:

**TiDB:**
```sql
SELECT table_name, column_name, column_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_schema = 'hr'
ORDER BY table_name, ordinal_position;
```

Check:
- Oracle `DATE` columns → TiDB `DATETIME` (not `DATE`)
- Oracle `NUMBER(p,s)` → appropriate DECIMAL/INT
- Oracle `CLOB` → `LONGTEXT`
- Oracle `VARCHAR2(n)` → `VARCHAR(n)` or `VARCHAR(n*4)` for CHAR semantics

### 3. NULL Semantics Spot-Check

Oracle treats empty string as NULL. Verify this was handled correctly:

```sql
-- Oracle: count NULLs (includes empty strings)
SELECT COUNT(*) FROM HR.EMPLOYEES WHERE email IS NULL;

-- TiDB: count NULLs
SELECT COUNT(*) FROM hr.employees WHERE email IS NULL;

-- TiDB: count empty strings (should be 0 if Oracle data)
SELECT COUNT(*) FROM hr.employees WHERE email = '';
```

### 4. Sequence State Verification

Confirm TiDB sequences resume from correct values:

```sql
SELECT * FROM information_schema.sequences WHERE sequence_schema = 'hr';
```

Compare with Oracle's `ALL_SEQUENCES.LAST_NUMBER` to verify the starting point is correct.

### 5. Data Checksum (Optional)

For critical tables, compare checksums:

```sql
-- TiDB
SELECT COUNT(*), SUM(CRC32(CONCAT_WS(',', emp_id, first_name, last_name, salary)))
FROM hr.employees;
```

## Common Validation Issues

| Issue | Cause | Fix |
|---|---|---|
| Row count mismatch 1–5% | Concurrent writes during extraction | Re-extract and re-load affected tables |
| Row count mismatch > 5% | CSV encoding or load error | Check CSV row count (`wc -l`), verify encoding, truncate and re-load |
| DATE values lost time | Mapped to DATE instead of DATETIME | Fix type mapping, ALTER TABLE MODIFY COLUMN, re-load |
| NUMBER precision loss | Mapped to INT instead of DECIMAL | Fix type mapping, ALTER TABLE MODIFY COLUMN, re-load |
| Extra NULLs in TiDB | Oracle empty-string-as-NULL | Expected behavior — document for application team |
