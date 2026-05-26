# Load Guide

How `tishift-firestore load` transfers data from Firestore to TiDB.

## Strategy matrix

| Source size | TiDB tier | Strategy | What runs |
|---|---|---|---|
| < 10 GB | any | `direct` | Admin SDK reads + batched INSERTs |
| 10 GB – 1 TB | Starter / Essential | `dataflow-cloudimport` | Beam → GCS NDJSON → `ticloud serverless import` |
| 10 GB – 1 TB | Dedicated / BYOC | `dataflow-lightning` | Beam → GCS NDJSON → TiDB Lightning physical mode |
| 1 TB – 10 TB | Dedicated / BYOC | `dataflow-lightning` | Same as above, more workers |
| > 10 TB | BYOC | `dataflow-lightning-sharded` | Parallel Beam jobs per collection group; parallel Lightning passes |

Auto-select via:

```bash
tishift-firestore load --strategy auto
```

Force a strategy:

```bash
tishift-firestore load --strategy dataflow-lightning
```

## The Dataflow pipeline (all non-direct strategies)

The same pipeline shape underlies every Dataflow-based strategy. One Beam job
per collection (root + each subcollection level):

```
ReadFromFirestore(read_time=T0)   ← pinned snapshot for consistency
    ↓
MapToNDJSON                       ← serialize each doc to one JSON line
    ↓
WriteToText(num_shards=N)         ← GCS gs://bucket/prefix/collection/part-*.ndjson
```

Pipeline configuration via `tishift-firestore.yaml`:

```yaml
load:
  dataflow:
    region: us-central1            # must match Firestore + TiDB region
    machine_type: n2-standard-4    # 4 vCPU, 16 GB RAM per worker
    max_workers: 200               # raise for >5 TB
    autoscaling: THROUGHPUT_BASED  # let Dataflow auto-scale
    network: default               # custom VPC for BYOC isolation
    subnetwork: regions/us-central1/subnetworks/default
    use_public_ips: false          # set true if no Private Google Access
```

**read_time pinning** is what guarantees a consistent snapshot across all
parallel workers. Without it, you get torn reads — different workers see
different write states.

## Direct strategy (< 10 GB)

No GCS, no Dataflow:

```python
for doc in collection.stream():
    row = transform_to_row(doc)
    batch.append(row)
    if len(batch) >= 1000:
        cursor.executemany(INSERT_SQL, batch)
        batch.clear()
```

Use for: getting-started, dev/test, small collections in CI.
Don't use for: anything multi-GB. The single-machine memory and connection
pressure kills you above 10 GB.

## dataflow-cloudimport (Starter / Essential)

Beam writes NDJSON to GCS. The CLI then issues `ticloud serverless import
start`:

```bash
ticloud serverless import start \
    --cluster-id $CLUSTER_ID \
    --source-type=NDJSON \
    --source-url="gs://my-staging/firestore-export/" \
    --file-pattern="*.ndjson"
```

Cloud Import handles ingest server-side. Free for Starter, metered for
Essential. Single Cloud Import job per collection; TiShift submits them in
parallel up to the per-cluster concurrency limit.

## dataflow-lightning (Dedicated / BYOC)

Beam writes NDJSON to GCS. TiDB Lightning ingests from GCS via the
`gs://` data-source-dir, using physical-import mode (writes SST files
directly to TiKV — bypasses the SQL layer):

```toml
[mydumper]
data-source-dir = "gs://my-staging/firestore-export/"

[tikv-importer]
backend = "local"
sorted-kv-dir = "/data/lightning-sort"

[[mydumper.files]]
pattern = '^(?P<table>\w+)/part-.*\.ndjson$'
type = 'ndjson'
```

Lightning sizing: scratch space at `sorted-kv-dir` needs ~1.5× the largest
table. Network bandwidth from Lightning runner to TiKV nodes is the bottleneck
at TB scale.

Lightning is invoked by `tishift-firestore` once all Dataflow jobs complete:

```bash
tishift-firestore load --strategy dataflow-lightning
# → submits Beam jobs
# → polls until all complete
# → invokes tidb-lightning
```

## dataflow-lightning-sharded (>10 TB BYOC)

Same shape but the load is split into independent passes. Useful when a
single Lightning run would exceed the staging VM's local SST sort capacity:

1. First pass: largest collection (e.g., events).
2. Second pass: next group of collections.
3. …until done.

Configure shards:

```yaml
load:
  shard_groups:
    - [events]
    - [users, products, orders]
    - [audit_logs, sessions]
```

Each shard group runs Beam → GCS → Lightning sequentially; the next group
starts after the prior group's Lightning completes.

## Post-load index application

Always defer secondary indexes and FKs to after the data is loaded:

```bash
mysql ... < tishift-output/02-create-indexes.sql
mysql ... < tishift-output/04-multi-valued-indexes.sql
mysql ... < tishift-output/03-foreign-keys.sql
```

Applying them before load makes the ingest 5–10× slower (every row insert
touches every index). Applying after means each index builds once, in bulk,
using TiDB's parallel DDL.

## State and resumability

Each load run writes `tishift-output/.load-state.json`:

```json
{
  "load_id": "uuid",
  "read_time": "2026-05-15T03:00:00Z",
  "collections": {
    "users":     {"status": "complete", "gcs_path": "gs://...", "row_count": 12345678},
    "orders":    {"status": "running",  "job_id": "2026-05-15_03_12_..."},
    "products":  {"status": "pending"}
  }
}
```

Resume after interruption:

```bash
tishift-firestore load --resume tishift-output/.load-state.json
```

Completed collections are skipped; running jobs are polled; pending ones are
submitted.

## Error recovery

| Error | What to do |
|---|---|
| Dataflow worker OOM | Increase `machine_type` to `n2-standard-8`; reduce `num_shards` in Beam options |
| GCS write throttled | Increase `num_shards` to spread across more objects |
| Lightning sort dir out of disk | Increase `sorted-kv-dir` mount size; or use sharded strategy |
| TiKV ingest timeout | Reduce Lightning concurrency; increase TiKV `region-split-size` |
| Mid-job credentials expired | Re-authenticate; resume via `--resume` |

## Cost considerations

For a representative 7 TB Firestore source on `dataflow-lightning`:

- Firestore reads: ~$4,200 (7B docs × $0.06/100k)
- Dataflow: ~$2,500 (200 × n2-standard-4 × 36 h)
- GCS staging: ~$140 (8 TB for 7 days)
- TiDB Lightning runner VM: ~$200 (n2-standard-32 × 36 h)
- Total compute: ~$7,000

The Firestore-read cost dominates. Network egress is $0 when source and
target are in the same GCP region.
