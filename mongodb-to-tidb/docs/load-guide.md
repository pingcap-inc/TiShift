# Load Guide

How `tishift-mongodb load` transfers data from MongoDB to TiDB. See
[load-strategies.md](../references/load-strategies.md) for the strategy
matrix; this guide is the operational walkthrough.

## Strategy auto-select

```bash
tishift-mongodb load --strategy auto
```

Resolves to:

| Source size | Customer state | Strategy |
|---|---|---|
| < 10 GB | any | `direct` |
| Any | already operates AWS DMS | `aws-dms` (adapter) |
| Any | already operates Datastream | `datastream` (adapter) |
| Any | else (default) | `mongodump-lightning` |
| Any | standalone topology | `mongodump-lightning` (forced) |

Force a strategy:

```bash
tishift-mongodb load --strategy mongodump-lightning
```

## `direct` — small databases

Single-process PyMongo read + batched INSERT:

```bash
tishift-mongodb load --strategy direct --config tishift-mongodb.yaml
```

Output:
- `tishift-output/.load-state.json` (per-collection progress)
- Rows directly into TiDB

Use for: < 10 GB, dev / CI, smoke tests, very small customers.

## `mongodump-lightning` — the TiDB-native primary path

Three stages:

### Stage 1 — mongodump

```bash
tishift-mongodb load --strategy mongodump-lightning --config tishift-mongodb.yaml
```

Under the hood, TiShift orchestrates:

```bash
mongodump \
  --uri="$MONGO_URI" \
  --db=$DB \
  --oplog \
  --out=$LOCAL_DUMP_DIR \
  --numParallelCollections=4
```

The `--oplog` flag captures concurrent writes during the dump for
point-in-time consistency.

For sharded clusters, TiShift spawns one mongodump per shard primary in
parallel.

### Stage 2 — BSON-to-NDJSON conversion + cloud-agnostic staging

TiShift reads `*.bson` files using PyMongo's BSON decoder, applies
BSON-type → JSON serialization (ObjectId → 24-char hex, Decimal128 → string,
UUID → standard form), and writes NDJSON via `fsspec`.

The `fsspec` layer routes to whichever backend the config specified:

```yaml
load:
  staging:
    backend: s3                # s3 | gs | azure | local
    base_url: s3://my-staging/mongo-export/
    region: us-east-1
```

| backend | base_url examples |
|---|---|
| `s3` | `s3://bucket/prefix/`, `s3://endpoint/...` for MinIO/S3-compatible |
| `gs` | `gs://bucket/prefix/` |
| `azure` | `azure://container/prefix/` (with connection string in env) |
| `local` | `file:///mnt/staging/`, `local:///mnt/staging/` |

Output structure:

```
<base_url>/dump/<collection>/part-NNNN.ndjson
<base_url>/dump/<collection>/part-NNNN+1.ndjson
...
```

### Stage 3 — TiDB Lightning ingest

TiShift writes a `tidb-lightning.toml` with the staging URL as
`data-source-dir`:

```toml
[mydumper]
data-source-dir = "s3://my-staging/mongo-export/dump/"

[tikv-importer]
backend = "local"
sorted-kv-dir = "/data/lightning-sort"

[tidb]
host = "..."
port = 4000
user = "..."
# password supplied via TIDB_LIGHTNING_TIDB_PASSWORD env var (never inlined)

[[mydumper.files]]
pattern = '^(?P<table>[^/]+)/part-.*\.ndjson$'
type = 'ndjson'
```

Then runs:

```bash
TIDB_LIGHTNING_TIDB_PASSWORD="$TIDB_PASS" tidb-lightning -config tidb-lightning.toml
```

Lightning's `local` backend writes SST files directly to TiKV via PD —
5–10× faster than logical mode at TB scale.

## Storage backend authentication

### S3 / MinIO / S3-compatible

```bash
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
# Optional: AWS_SESSION_TOKEN for STS
# Optional: AWS_ENDPOINT_URL=https://minio.example.com for MinIO
```

Or use instance profile / IRSA on AWS — works automatically.

### Google Cloud Storage

```bash
gcloud auth application-default login
# Or: export GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json
```

Or use Workload Identity on GKE / GCE — works automatically.

### Azure Blob

```bash
export AZURE_STORAGE_CONNECTION_STRING="DefaultEndpointsProtocol=https;..."
# Or: managed identity in AKS
```

### Local

No auth. Just filesystem permissions.

## Sizing the Lightning runner

For multi-TB loads, the Lightning runner VM needs:

| Resource | Recommendation |
|---|---|
| CPU | 16–32 cores |
| RAM | 64–128 GB |
| Local SSD | 1.5× largest table size, for SST sort |
| Network | 10 Gbps or better |

Cloud-agnostic — any VM family on any cloud works:
- AWS: `c5.4xlarge` + 2 TB gp3
- GCP: `n2-standard-32` + 2 TB local SSD
- Azure: `D32s_v5` + 2 TB Premium SSD
- Self-hosted: any 32-core machine with enough scratch

## Adapter strategies

For customers already operating DMS or Datastream, TiShift acts as
config-emitter + status-poller, not runtime engine.

### `aws-dms` (when customer already operates AWS DMS)

```bash
# Requires customer-supplied ARNs in tishift-mongodb.yaml
tishift-mongodb load --strategy aws-dms --emit-task-config
# Outputs tishift-output/dms-task-config.json
# Customer applies via AWS Console or CLI:
aws dms create-replication-task --cli-input-json file://tishift-output/dms-task-config.json
# Then TiShift polls:
tishift-mongodb load --strategy aws-dms --poll
```

### `datastream` (when customer already operates GCP Datastream)

```bash
tishift-mongodb load --strategy datastream --emit-stream-config
# Outputs tishift-output/datastream-stream-config.json + bq-export-job.json
# Customer applies, TiShift polls.
```

## Resumability

State written to `tishift-output/.load-state.json` every 10 collections:

```json
{
  "load_id": "uuid",
  "strategy": "mongodump-lightning",
  "stage": "mongodump",            // mongodump | bson-conversion | lightning
  "collections": {
    "users":    {"status": "complete", "row_count": 12345678},
    "orders":   {"status": "converted", "ndjson_files": 24},
    "products": {"status": "pending"}
  }
}
```

Resume:

```bash
tishift-mongodb load --resume tishift-output/.load-state.json
```

## Post-load index application

Always defer secondary indexes to after the load — 5–10× faster:

```bash
mysql ... < tishift-output/02-create-indexes.sql
mysql ... < tishift-output/04-multi-valued-indexes.sql
mysql ... < tishift-output/03-foreign-keys.sql
```

## Error recovery

| Error | Action |
|---|---|
| `mongodump` failed mid-collection | Check disk space; retry — `--oplog` window matters |
| BSON conversion ran out of memory | Reduce `convert.parallel_workers` |
| Lightning out of sort-disk | Increase `sorted_kv_dir` mount size, or shard the load |
| TiKV write timeout | Reduce Lightning concurrency; check TiKV `region-split-size` |
| Mid-load auth expired | Re-export credentials, resume via `--resume` |

## Cost considerations

For a representative 1 TB MongoDB source on `mongodump-lightning`:

- mongodump: ~$0 (CPU on customer VM)
- BSON conversion: ~$10 (8 core × 1h)
- Staging storage 1.2 TB × 7 days: ~$30
- Lightning runner VM 32-core × 6h: ~$30
- **Total: ~$60–100 one-time**

Compare AWS DMS: ~$500-2000/month + per-row costs. The TiDB-native path is
dramatically cheaper.

For 10 TB:

- mongodump: ~$0
- Conversion: ~$80
- Staging 12 TB × 7d: ~$300
- Lightning runner 64-core × 24h: ~$200
- **Total: ~$600 one-time**

Still well below managed-service alternatives.
