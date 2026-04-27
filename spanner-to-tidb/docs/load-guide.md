# Load Guide

The load command transfers data from Cloud Spanner to TiDB.

## Key Difference: No Dump CLI

Unlike PostgreSQL (`pg_dump`) or MySQL (`mysqldump`), **Spanner has no dump CLI**. All data extraction requires:
- **Dataflow jobs** writing to Google Cloud Storage (GCS) — for production workloads
- **Spanner client read API** — for small databases (< 1 GB)

## Strategy Selection

| Data Size | TiDB Tier | Strategy |
|---|---|---|
| < 1 GB | Any | Direct read via Spanner client API |
| Any (≤ 25 GiB) | Starter | Dataflow CSV export → `ticloud serverless import start` |
| < 50 GB | Essential/Dedicated | Dataflow CSV export → `LOAD DATA LOCAL INFILE` |
| 50-500 GB | Essential/Dedicated | Dataflow CSV (with Data Boost) → `LOAD DATA LOCAL INFILE` |
| > 500 GB | Dedicated | Dataflow CSV → download → TiDB Lightning |

## Prerequisites

1. **GCS bucket**: A Cloud Storage bucket for Dataflow to write export files
2. **Dataflow permissions**: `roles/dataflow.worker` on the service account
3. **Data Boost** (optional): For zero-impact reads on large exports

## Export Command

```bash
gcloud dataflow jobs run tishift-export-$TABLE \
  --gcs-location gs://dataflow-templates/latest/Cloud_Spanner_to_GCS_Text \
  --region $REGION \
  --parameters \
    instanceId=$INSTANCE_ID,\
    databaseId=$DATABASE_ID,\
    outputDir=gs://$BUCKET/tishift-export/$TABLE/,\
    spannerTable=$TABLE
```

## Load Order

1. Apply schema DDL (`01-create-tables.sql`) — without secondary indexes
2. Run Dataflow export per table
3. Download CSVs from GCS: `gsutil -m cp -r gs://$BUCKET/tishift-export/ ./`
4. Load per table via `LOAD DATA LOCAL INFILE`
5. Recreate secondary indexes (`02-create-indexes.sql`)
6. Apply foreign keys (`04-foreign-keys.sql`)
7. Run `ANALYZE TABLE` on all imported tables

## Usage

```bash
tishift-spanner load --config tishift-spanner.yaml --strategy auto
```
