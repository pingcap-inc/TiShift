# Compatibility Rules — Oracle → TiDB

## Blockers

Features TiDB fundamentally cannot do. Must be resolved before migration.

| ID | Condition | Feature | Action |
|---|---|---|---|
| BLOCKER-1 | `stored_procedure_count > 0 OR function_count > 0` | Stored Procedures / Functions | TiDB parses but does not execute PL/SQL. Rewrite as application code (AI-assisted). Classify by complexity: trivial (<10 lines), simple (<30), moderate (<100 with cursors), complex (>100 or dynamic SQL), requires_redesign (autonomous tx, pipelined). |
| BLOCKER-2 | `package_count > 0` | PL/SQL Packages | No TiDB equivalent. Decompose: spec → interface definitions, body → application modules (Python/Go/Java). Package-level persistent state → explicit storage (Redis, session table, application memory). |
| BLOCKER-3 | `trigger_count > 0` | Triggers | TiDB parses but does not execute triggers. Rewrite as application middleware or event handlers. |
| BLOCKER-4 | `dblink_count > 0` | Database Links | No TiDB equivalent. Replace with application-level federation, API calls, or TiCDC for cross-cluster replication. |
| BLOCKER-5 | `mview_count > 0` | Materialized Views | TiDB does not support materialized views. Convert to regular table + scheduled refresh ETL, or use TiFlash replicas for analytical acceleration. |
| BLOCKER-6 | `has_xmltype_columns = TRUE` | XMLType / XML Functions | No TiDB equivalent. Map XMLType to LONGTEXT. Move XML processing (XMLELEMENT, XMLAGG, EXTRACTVALUE, etc.) to application layer. |
| BLOCKER-7 | `has_sdo_geometry = TRUE` | SDO_GEOMETRY (Oracle Spatial) | TiDB has limited spatial support. Complex spatial queries (SDO_RELATE, SDO_WITHIN_DISTANCE) must move to application layer or external GIS engine. |
| BLOCKER-8 | `has_object_types = TRUE` | Oracle Object Types (CREATE TYPE ... AS OBJECT) | No TiDB equivalent. Flatten into relational tables; move object behavior to application layer. |
| BLOCKER-9 | `has_autonomous_transactions = TRUE` | PRAGMA AUTONOMOUS_TRANSACTION | No TiDB equivalent. Requires architectural redesign — use separate DB connections with independent commit in application code. |
| BLOCKER-10 | `has_pipelined_functions = TRUE` | Pipelined Table Functions | No TiDB equivalent. Rewrite as temp tables populated by application logic, or use CTEs. |
| BLOCKER-11 | `type_count > 0 AND has VARRAY/NESTED TABLE in types` | VARRAY / Nested Tables | No TiDB equivalent. Normalize into child tables or serialize as JSON columns. |
| BLOCKER-12 | Oracle Advanced Queuing detected in source | Oracle AQ | No TiDB equivalent. Replace with external message broker (Kafka, RabbitMQ, Pulsar). |

## Warnings

Features that work differently or need review. Migration can proceed with adjustments.

| ID | Condition | Feature | Action |
|---|---|---|---|
| WARNING-1 | `sequence_count > 0` | Sequences | TiDB supports `CREATE SEQUENCE` (v4.0+). Migrate directly. Verify cache size and cycle settings match. Consider `AUTO_INCREMENT` or `AUTO_RANDOM` as alternatives for simple auto-numbering. |
| WARNING-2 | `synonym_count > 0` | Synonyms (public/private) | No direct equivalent. Replace with VIEWs, connection-level schema config, or ORM mapping. Low migration effort. |
| WARNING-3 | `has_connect_by = TRUE` | Hierarchical Queries (CONNECT BY) | Rewrite as `WITH RECURSIVE` CTE. sqlglot does NOT auto-convert CONNECT BY to recursive CTEs. Manual or AI-assisted rewrite required per query. |
| WARNING-4 | `has_rownum_usage = TRUE` | ROWNUM pseudo-column | Rewrite as `LIMIT / OFFSET`. sqlglot passes ROWNUM through unchanged. Custom rewrite rule needed for each occurrence. |
| WARNING-5 | Views or code using (+) syntax | Oracle (+) outer join syntax | Rewrite as ANSI `LEFT JOIN` / `RIGHT JOIN`. sqlglot silently drops (+) conditions — each join must be manually rewritten. |
| WARNING-6 | `partition_count > 0` | Partitioned Tables | TiDB supports RANGE/LIST/HASH (single-level only). Interval partitions → RANGE + scheduled DDL for new partitions. Composite partitions must be flattened to single-level. |
| WARNING-7 | `has_global_temp_tables = TRUE` | Global Temporary Tables | TiDB supports `CREATE GLOBAL TEMPORARY TABLE`. Check `ON COMMIT DELETE ROWS` vs `ON COMMIT PRESERVE ROWS` semantics match. |
| WARNING-8 | LISTAGG usage in views or code | LISTAGG function | Rewrite as `GROUP_CONCAT(col ORDER BY ... SEPARATOR sep)`. sqlglot does NOT convert LISTAGG. |
| WARNING-9 | `has_dbms_packages = TRUE` | DBMS_* Built-in Packages | No TiDB equivalent. Map to application libraries: DBMS_OUTPUT → logging, DBMS_SCHEDULER → cron/Airflow, DBMS_LOB → app blob handling, DBMS_SQL → prepared statements. |
| WARNING-10 | `has_utl_packages = TRUE` | UTL_* Packages | No TiDB equivalent. Map to application libraries: UTL_FILE → file I/O, UTL_HTTP → HTTP clients, UTL_MAIL → SMTP libraries. |
| WARNING-11 | `has_long_columns = TRUE` | LONG / LONG RAW (deprecated) | Map to LONGTEXT / LONGBLOB. Note: AWS DMS does not support LONG > 64 KB — extract via CSV for large values. |
| WARNING-12 | `nls_characterset != 'AL32UTF8'` | Non-UTF8 Character Set | TiDB uses utf8mb4. Character set conversion needed during extraction. May cause data expansion or truncation for multi-byte characters. Verify data integrity after load. |
| WARNING-13 | `has_bfile_columns = TRUE` | BFILE (external file references) | No TiDB equivalent. Store file paths as VARCHAR; manage files in S3/object storage at application layer. |
| WARNING-14 | `has_bulk_collect = TRUE` | BULK COLLECT / FORALL in PL/SQL | No equivalent in TiDB. Rewrite as batch `INSERT ... SELECT`, `LOAD DATA`, or application-level `executemany`. |

## Compatible

Features that work identically or near-identically in TiDB:

- Standard types: VARCHAR2 → VARCHAR, NUMBER(p,s) → DECIMAL(p,s), INTEGER, FLOAT, BINARY_FLOAT, BINARY_DOUBLE
- DUAL table (supported natively in TiDB)
- ANSI JOINs (LEFT, RIGHT, INNER, CROSS, FULL via UNION of LEFT+RIGHT)
- Subqueries (correlated and non-correlated)
- Window functions (ROW_NUMBER, RANK, DENSE_RANK, LEAD, LAG, NTILE, etc.)
- Common Table Expressions (non-recursive)
- Recursive CTEs (`WITH RECURSIVE`) — TiDB supports this
- CASE expressions
- UNION / UNION ALL / EXCEPT (Oracle MINUS)
- Aggregate functions (SUM, COUNT, AVG, MIN, MAX, etc.)
- GROUP BY / HAVING
- ORDER BY
- CREATE SEQUENCE (TiDB v4.0+)
- Generated columns (virtual columns → `GENERATED ALWAYS AS`)
- RANGE / LIST / HASH partitioning (single-level)
- Global temporary tables (`CREATE GLOBAL TEMPORARY TABLE`)
- Prepared statements
- Pessimistic transactions (TiDB default)
- `LOAD DATA LOCAL INFILE`

## Detection Patterns

For scanning PL/SQL source code (ALL_SOURCE) and view definitions, detect these patterns:

| Pattern | Regex / LIKE | Maps to |
|---|---|---|
| CONNECT BY | `UPPER(text) LIKE '%CONNECT BY%'` | WARNING-3 |
| Autonomous transaction | `UPPER(text) LIKE '%PRAGMA AUTONOMOUS_TRANSACTION%'` | BLOCKER-9 |
| BULK COLLECT | `UPPER(text) LIKE '%BULK COLLECT%'` | WARNING-14 |
| FORALL | `UPPER(text) LIKE '%FORALL%'` | WARNING-14 |
| PIPE ROW | `UPPER(text) LIKE '%PIPE ROW%'` | BLOCKER-10 |
| DBMS_* packages | `UPPER(text) LIKE '%DBMS_%'` | WARNING-9 |
| UTL_* packages | `UPPER(text) LIKE '%UTL_%'` | WARNING-10 |
| Dynamic SQL | `UPPER(text) LIKE '%EXECUTE IMMEDIATE%'` | Complexity multiplier |
| ROWNUM | `UPPER(text) LIKE '%ROWNUM%'` | WARNING-4 |
| (+) join | `text LIKE '%(+)%'` | WARNING-5 |
| LISTAGG | `UPPER(text) LIKE '%LISTAGG%'` | WARNING-8 |
| XMLType methods | `UPPER(text) LIKE '%XMLELEMENT%' OR ... '%XMLAGG%' OR ... '%EXTRACTVALUE%'` | BLOCKER-6 |

## JSON Output Format

```json
{
  "blockers": [
    {"id": "BLOCKER-1", "feature": "Stored Procedures", "count": 12, "action": "Rewrite as application code (AI-assisted)"}
  ],
  "warnings": [
    {"id": "WARNING-1", "feature": "Sequences", "count": 5, "action": "Migrate to TiDB CREATE SEQUENCE"}
  ],
  "compatible": [
    "VARCHAR2 columns",
    "NUMBER(p,s) columns",
    "ANSI JOINs",
    "Window functions",
    "CTEs",
    "RANGE partitioning"
  ]
}
```
