# Sync Guide — CDC via BigQuery Bridge

How `tishift-firestore sync` streams ongoing Firestore changes to TiDB during
cutover.

## When you need this

You need sync if **your acceptable downtime is shorter than the bulk load
takes**. For a 7 TB Firestore source, a Dataflow + Lightning load typically
runs 24–48 hours. If the application can be read-only for that long, skip
sync entirely.

Sync is required when:

- Cutover tolerance is hours, not days
- The application has steady write traffic that cannot pause
- A rollback option is needed (Firestore stays primary while TiDB warms)

## Why BigQuery bridge

Datastream does not support Firestore as a source. There is no native
binlog/WAL/change-stream API exposed for arbitrary external consumers.

The only structured, production-grade change stream Firestore offers is the
**[`firestore-bigquery-export` Firebase Extension](https://extensions.dev/extensions/firebase/firestore-bigquery-export)**.
The extension is a Cloud Function that listens to Firestore writes on
configured collections and writes each change as a row in a BigQuery raw
table. TiShift reads from that table and writes to TiDB.

```
Firestore writes
   ↓ (Cloud Function trigger)
firestore-bigquery-export
   ↓
BigQuery firestore_export.<collection>_raw
   ↓ (TiShift Dataflow streaming job)
TiDB BYOC
```

## Prerequisites

1. **The extension must be installed per-collection at least 7 days before
   cutover.** TiShift can't retrofit historical changes — the change history
   only exists from the extension's install time forward.
2. **A BigQuery dataset** in the same GCP project as Firestore. The extension
   creates tables in it.
3. **A backfill of existing data** to the `_raw` table. If sync was added
   after the bulk load, run the extension's backfill script first.

## Convert emits an install manifest

When sync is configured, `tishift-firestore convert` emits a manifest:

```bash
tishift-firestore sync install-manifest \
    --config tishift-firestore.yaml \
    --collections users,orders,products
```

Output (`tishift-output/sync-install.sh`):

```bash
#!/usr/bin/env bash
set -e

for COL in users orders products ; do
    firebase ext:install firebase/firestore-bigquery-export@0.2.7 \
        --project=$PROJECT \
        --params=COLLECTION_PATH=$COL,DATASET_ID=firestore_export,TABLE_ID=${COL}_raw,...
done
```

**TiShift does not run this script.** The customer's Firebase admin runs it.

## Backfill (one-time, for existing data)

Skip if sync is configured before the bulk load and you've timed cutover
relative to extension install. Otherwise, run the extension's bundled
backfill script per collection:

```bash
npx @firebaseextensions/fs-bq-import-collection \
    --project=$PROJECT \
    --source-collection-path=users \
    --dataset=firestore_export \
    --table-name-prefix=users
```

Wait for it to complete. The `_raw` table now contains all existing docs
plus any changes since the extension was installed.

## Starting the bridge

```bash
tishift-firestore sync start --config tishift-firestore.yaml \
    --since "2026-05-15T03:00:00Z"
```

`--since` is the timestamp of the bulk load's `read_time`. The bridge replays
every BQ row newer than that into TiDB.

This submits a Dataflow streaming job:

```
BigQuery firestore_export.users_raw
   ↓ (BQ Storage Read API, with row-level timestamp filter)
Dataflow streaming job
   ↓ (apply CREATE / UPDATE / DELETE per row's operation field)
TiDB JDBC sink
```

One streaming job per collection. The CLI polls and reports job status.

## Monitoring lag

TiShift exposes Prometheus metrics:

| Metric | Type | Meaning |
|---|---|---|
| `tishift_cdc_lag_seconds{collection="users"}` | Gauge | Difference between current time and the latest BQ row's commit_time that has been applied |
| `tishift_cdc_apply_rate{collection="users"}` | Counter | Rows applied per second |
| `tishift_cdc_apply_errors_total{collection="users",error_type="..."}` | Counter | Application errors (constraint violations, type mismatches) |
| `tishift_cdc_bq_read_errors_total` | Counter | BigQuery read failures |

Plug into Grafana with the dashboard at
`docs/grafana/firestore-cdc-dashboard.json`.

Healthy state: `tishift_cdc_lag_seconds` consistently below 5 minutes,
applying at >100 rows/sec, no errors.

## Cutover procedure

```
T-14d: Install firestore-bigquery-export on all in-scope collections.
       Verify _raw tables are populated.

T-7d:  Run bulk load. Note the load's read_time as T-bulk.
       Run tishift-firestore check. Resolve any mismatches.

T-7d to T-0:  Start sync with --since T-bulk.
              Watch tishift_cdc_lag_seconds.
              Tune Dataflow worker count if lag grows.

T-0:   Place application into read-only mode against Firestore.
       Wait for tishift_cdc_lag_seconds < 5.
       Run a final tishift-firestore check --full.
       Switch application config to write to TiDB.
       Stop the sync job.
       Retain Firestore as read-only backup for N days.
```

## What sync does NOT support

- **Bidirectional sync** (TiDB → Firestore). v1 only flows source → target.
- **Schema evolution during sync.** If a new Firestore field appears after
  the bulk load, the bridge logs an error for rows containing that field and
  continues with other rows. To pick up the field, re-run convert + load for
  that collection.
- **Sub-second latency.** End-to-end latency is bounded by the extension's
  Cloud Function execution and BigQuery streaming insert delay. Realistic
  steady-state lag is 30s–2min.
- **Strict ordering across collections.** Per-document order is preserved
  (BigQuery `commit_time` is monotonic per doc); cross-document or
  cross-collection order may be reshuffled by parallel processing. Build
  application logic accordingly.

## Cost considerations

For a representative 7 TB Firestore source running sync over a 7-day cutover
window:

- Cloud Functions invocations: ~$0.40/M; at 10k writes/sec = $250/day
- BigQuery streaming inserts: $0.05/GB; at 10 KB/doc = $50/day
- BigQuery storage: $0.02/GB-month, but rows churn — under $50/week
- Dataflow streaming: ~$300/day for moderate write rates
- TiDB write capacity: covered by your TiDB Cloud commit

Roughly $4,000 / week of cutover. Plan accordingly.

## Stopping sync

```bash
tishift-firestore sync stop --config tishift-firestore.yaml
```

Cancels all Dataflow streaming jobs. The BigQuery `_raw` tables remain;
delete them via `bq rm` once Firestore is decommissioned.
