# Load Guide

The load command transfers data from Neon/Postgres to TiDB.

## Strategy Selection

| Data Size | TiDB Tier | Strategy |
|---|---|---|
| Any (≤ 25 GiB) | Starter | CSV export → `ticloud serverless import start` |
| < 50 GB | Essential/Dedicated | CSV export → `LOAD DATA LOCAL INFILE` |
| 50-500 GB | Essential/Dedicated | AWS DMS (PostgreSQL source → MySQL target) |
| > 500 GB | Dedicated | CSV → S3 → TiDB Lightning physical import |

## Data Export from Neon

Data is exported using Postgres `COPY TO STDOUT` with CSV format:

```bash
psql "postgres://user@host/db?sslmode=require" \
  -c "\COPY schema.table TO STDOUT WITH (FORMAT csv, HEADER, NULL '\N')" > table.csv
```

**Important:** Use a direct (unpooled) connection. COPY does not work over PgBouncer pooled connections.

## Load Order

1. Apply schema DDL (`01-create-tables.sql`) — without secondary indexes
2. Export and load data per table
3. Recreate secondary indexes (`02-create-indexes.sql`)
4. Apply foreign keys (`04-foreign-keys.sql`)
5. Run `ANALYZE TABLE` on all imported tables

Dropping indexes before load and recreating after is 3-5x faster.

## Usage

```bash
# Auto-detect strategy based on data size and tier
tishift-neon load --config tishift-neon.yaml --strategy auto

# Force direct load
tishift-neon load --config tishift-neon.yaml --strategy direct
```
