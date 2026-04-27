# Load Guide — Oracle to TiDB

## Data Extraction from Oracle

TiShift uses CSV extraction, NOT Oracle Data Pump. Data Pump produces proprietary binary .dmp files that TiDB cannot consume.

### Primary Method: Oracle SQLcl

```bash
sql $ORACLE_CONNECT <<'EOF'
SET SQLFORMAT csv
SPOOL /tmp/employees.csv
SELECT * FROM HR.EMPLOYEES;
SPOOL OFF
EOF
```

### Fallback: sqlplus (Oracle 12.2+)

```bash
sqlplus -S $ORACLE_CONNECT <<'EOF'
SET MARKUP CSV ON
SET PAGESIZE 0
SET FEEDBACK OFF
SET TRIMSPOOL ON
SPOOL /tmp/employees.csv
SELECT * FROM HR.EMPLOYEES;
SPOOL OFF
EOF
```

## Load Strategy by Tier and Size

| Tier | Data Size | Strategy | Method |
|---|---|---|---|
| Starter | ≤ 25 GiB | ticloud import | CSV → `ticloud serverless import start` |
| Essential | < 100 GB | Direct | CSV → `LOAD DATA LOCAL INFILE` |
| Essential | 100–500 GB | DMS | AWS DMS with Oracle LogMiner source |
| Dedicated | < 100 GB | Direct | CSV → `LOAD DATA LOCAL INFILE` |
| Dedicated | 100 GB–1 TB | DMS | AWS DMS with Oracle LogMiner source |
| Dedicated | > 1 TB | Lightning | CSV → S3 → TiDB Lightning physical import |

## Loading Steps (Direct)

1. Apply schema DDL: `mysql ... < 01-create-tables.sql`
2. Apply sequences: `mysql ... < 05-create-sequences.sql`
3. Extract each table to CSV (SQLcl or sqlplus)
4. Load each table: `LOAD DATA LOCAL INFILE 'table.csv' INTO TABLE ...`
5. Recreate secondary indexes: `mysql ... < 02-create-indexes.sql`
6. Apply views: `mysql ... < 03-create-views.sql`
7. Apply foreign keys: `mysql ... < 04-foreign-keys.sql`

## Performance Tips

- **Drop secondary indexes before load, recreate after.** 3–5x faster for large datasets.
- **Parallel extraction.** Run multiple SQLcl sessions for different tables simultaneously.
- **LOB columns.** For tables with large CLOB/BLOB values, extract LOBs separately using chunked reads via python-oracledb. Reference by PK in the CSV.
- **LONG columns.** AWS DMS cannot handle LONG values > 64 KB. Use CSV extraction for these tables.

## DMS Setup (for larger datasets)

AWS DMS with Oracle source requires:
1. Supplemental logging enabled: `ALTER DATABASE ADD SUPPLEMENTAL LOG DATA`
2. DMS source endpoint configured with LogMiner mode
3. DMS target endpoint configured for TiDB (MySQL-compatible)
4. Full load task created and started

CDC mode (LogMiner vs Binary Reader) is selected during DMS endpoint configuration. LogMiner requires no OS access; Binary Reader is faster but needs file-system access to redo logs.
