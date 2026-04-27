# Convert Guide — Oracle to TiDB

## Schema Conversion

The convert phase transforms Oracle DDL into TiDB-compatible DDL using:

1. **Type mapping** — see [references/type-mapping.md](../references/type-mapping.md) for the complete table
2. **Function mapping** — see [references/function-mapping.md](../references/function-mapping.md) for Oracle→MySQL translations
3. **SQL dialect rewriting** — sqlglot (`read="oracle", write="mysql"`) handles ~60% of conversions. Custom post-processing handles the rest.

## Critical Type Mappings

| Oracle | TiDB | Why It Matters |
|---|---|---|
| `DATE` | `DATETIME` | Oracle DATE includes time. Mapping to MySQL DATE loses hours/minutes/seconds. |
| `NUMBER` (no precision) | `DECIMAL(38,10)` | 38-digit floating point. Scan data for better fit. |
| `VARCHAR2(n CHAR)` | `VARCHAR(n*4)` | Character semantics = up to 4 bytes/char in utf8mb4. |
| `TIMESTAMP(9)` | `DATETIME(6)` | TiDB caps at microseconds. Nanosecond precision is lost. |

## SQL Syntax Rewrites

### CONNECT BY → WITH RECURSIVE

sqlglot parses CONNECT BY but does not transpile it. Each hierarchical query must be structurally rewritten:

```sql
-- Oracle
SELECT emp_id, name, LEVEL FROM employees
START WITH manager_id IS NULL
CONNECT BY PRIOR emp_id = manager_id;

-- TiDB
WITH RECURSIVE org AS (
  SELECT emp_id, name, 1 AS lvl FROM employees WHERE manager_id IS NULL
  UNION ALL
  SELECT e.emp_id, e.name, o.lvl + 1
  FROM employees e JOIN org o ON e.manager_id = o.emp_id
)
SELECT emp_id, name, lvl FROM org;
```

### ROWNUM → LIMIT

```sql
-- Oracle
SELECT * FROM (SELECT * FROM employees ORDER BY salary DESC) WHERE ROWNUM <= 10;

-- TiDB
SELECT * FROM employees ORDER BY salary DESC LIMIT 10;
```

### (+) Outer Join → ANSI JOIN

```sql
-- Oracle
SELECT a.id, b.name FROM a, b WHERE a.id = b.id(+);

-- TiDB
SELECT a.id, b.name FROM a LEFT JOIN b ON a.id = b.id;
```

### LISTAGG → GROUP_CONCAT

```sql
-- Oracle
SELECT dept_id, LISTAGG(name, ', ') WITHIN GROUP (ORDER BY name) FROM employees GROUP BY dept_id;

-- TiDB
SELECT dept_id, GROUP_CONCAT(name ORDER BY name SEPARATOR ', ') FROM employees GROUP BY dept_id;
```

## PL/SQL Conversion

PL/SQL cannot run in TiDB. Stored procedures, functions, packages, and triggers must be rewritten as application code.

TiShift classifies each PL/SQL unit by complexity and generates code stubs in the user's chosen language (Python, Go, Java, or JavaScript). The stubs preserve the original logic structure and include comments mapping back to the Oracle source.

## Output Files

| File | Contents |
|---|---|
| `01-create-tables.sql` | CREATE TABLE statements with type mappings |
| `02-create-indexes.sql` | Secondary indexes (apply after data load) |
| `03-create-views.sql` | Views with syntax conversions |
| `04-foreign-keys.sql` | ALTER TABLE ADD FOREIGN KEY |
| `05-create-sequences.sql` | CREATE SEQUENCE statements |
| `06-conversion-notes.md` | PL/SQL requiring AI-assisted or manual conversion |
