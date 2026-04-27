# Scan Guide — Oracle to TiDB

## What the Scan Collects

The scan phase connects read-only to your Oracle database and runs 15 catalog queries to collect:

1. **Schema inventory** — tables, columns, indexes, constraints, views, sequences, synonyms, database links, materialized views
2. **Procedural code inventory** — stored procedures, functions, packages (spec + body), triggers, types
3. **Data profile** — per-table sizes (from DBA_SEGMENTS or ALL_TABLES estimates), LOB columns, special types
4. **Feature detection** — PL/SQL patterns (CONNECT BY, autonomous transactions, BULK COLLECT, FORALL, PIPE ROW, DBMS_*/UTL_* usage, dynamic SQL, ROWNUM)
5. **Server metadata** — Oracle version, NLS character set, supplemental logging status, partitioning

## Required Privileges

The scan user needs `SELECT` on these Oracle catalog views:

| View | Purpose |
|---|---|
| `ALL_TABLES` | Table inventory |
| `ALL_TAB_COLUMNS` | Column details and types |
| `ALL_INDEXES`, `ALL_IND_COLUMNS` | Index inventory |
| `ALL_CONSTRAINTS`, `ALL_CONS_COLUMNS` | Constraints (PK, FK, UK, CHECK) |
| `ALL_SOURCE` | PL/SQL source code |
| `ALL_OBJECTS` | Object counts by type |
| `ALL_VIEWS` | View definitions |
| `ALL_SEQUENCES` | Sequence definitions |
| `ALL_SYNONYMS` | Synonym mappings |
| `ALL_DB_LINKS` | Database link inventory |
| `ALL_MVIEWS` | Materialized views |
| `ALL_TRIGGERS` | Trigger definitions |
| `ALL_PART_TABLES`, `ALL_TAB_PARTITIONS` | Partitioning details |
| `ALL_LOBS` | LOB column detection |
| `DBA_SEGMENTS` (optional) | Accurate segment sizes |
| `V$VERSION` (optional) | Oracle version banner |
| `V$DATABASE` (optional) | Supplemental logging status |
| `NLS_DATABASE_PARAMETERS` | Character set and NLS settings |

If `DBA_SEGMENTS` is not accessible, the scan falls back to `ALL_TABLES.BLOCKS * 8192` for size estimates.

## Output

The scan produces a structured checklist with 30+ fields covering table counts, procedural code counts, feature flags, data sizes, and server metadata. This checklist feeds into the assessment and scoring phases.

## Key Oracle-Specific Considerations

- **PL/SQL source code is read from ALL_SOURCE** — line-by-line. The scan counts lines per object and detects complexity patterns (cursors, dynamic SQL, DBMS_* usage, autonomous transactions).
- **Oracle DATE includes time** — the scan flags DATE columns so the convert phase maps them to DATETIME, not DATE.
- **NUMBER without precision** — flagged for data inspection. The default mapping is DECIMAL(38,10) but scanning actual data can yield a tighter type.
- **Supplemental logging** — checked via V$DATABASE. Required for CDC (DMS/Debezium). If not enabled, flagged as an operational readiness deduction.
