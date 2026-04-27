# Load Guide — OceanBase to TiDB

## Data Extraction

**Small-medium**: `mysqldump -h host -P 2881 -u user@tenant -p dbname > dump.sql`
**Large**: OBDUMPER with `--csv` for parallel CSV → TiDB Lightning.
**No DMS** — AWS DMS does not support OceanBase.

## Load Strategy

| Size | Method |
|---|---|
| < 25 GB (Starter) | mysqldump SQL → `ticloud serverless import start` |
| < 100 GB | mysqldump or OBDUMPER CSV → `LOAD DATA LOCAL INFILE` |
| 100 GB+ | OBDUMPER parallel CSV → TiDB Lightning |
