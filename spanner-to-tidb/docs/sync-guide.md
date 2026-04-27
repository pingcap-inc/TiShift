# Sync Guide

The sync command sets up CDC replication from Cloud Spanner to TiDB for minimal-downtime migration.

## Mechanism: Change Streams

Spanner Change Streams capture INSERT, UPDATE, DELETE changes in near real-time:

```
Spanner (change stream) → Spanner Client pull API → TiShift CDC bridge → PyMySQL → TiDB
```

## Prerequisites

1. **Change stream created** on source database:
   ```sql
   CREATE CHANGE STREAM tishift_stream FOR ALL;
   ```
2. **IAM permissions**: Service account needs `roles/spanner.databaseReader`

## How It Differs from Other Sources

Unlike PostgreSQL (WAL-based logical replication) or MySQL (binlog), Spanner change streams use a **pull-based API**. TiShift reads change data records via the Spanner client's TVF (Table-Valued Function) API, not a streaming protocol.

## Cutover Procedure

1. Pause application writes to Spanner
2. Wait for TiShift CDC bridge to catch up (watermark matches latest commit)
3. Validate with `tishift-spanner check --mode=live`
4. Switch application connection strings to TiDB
5. Drop change stream on Spanner: `DROP CHANGE STREAM tishift_stream`

## Tier Availability

| Tier | CDC Sync |
|---|---|
| Starter | Not available — cutover only |
| Essential | Available via Changefeeds |
| Dedicated | Available via Changefeeds or DM |

## Usage

```bash
tishift-spanner sync --config tishift-spanner.yaml --start
tishift-spanner sync --config tishift-spanner.yaml --status
tishift-spanner sync --config tishift-spanner.yaml --stop
```
