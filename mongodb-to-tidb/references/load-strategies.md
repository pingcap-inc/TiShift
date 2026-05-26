# Load Strategies

How `tishift-mongodb load` transfers data from MongoDB to TiDB. **Primary
strategies are TiDB-native and cloud-agnostic.** Adapters wrap external
services for customers who already operate them.

## Strategy matrix

```
IF total_data_gb_estimate < 10                                → direct          [PRIMARY]
IF customer.has_existing_dms_task                              → aws-dms         [ADAPTER]
IF customer.has_existing_datastream                            → datastream      [ADAPTER]
DEFAULT (any size, any cloud, any topology)                   → mongodump-lightning  [PRIMARY]
IF topology == "standalone"                                    → mongodump-lightning  [forced]
```

## `direct` — PRIMARY, < 10 GB

PyMongo `find().batch_size(1000)` → batched INSERT to TiDB. No staging, no
third party. Dev / CI / smoke / very small customers.

```bash
tishift-mongodb load --strategy direct
```

Caps at ~10 GB on a single machine. Memory pressure and connection saturation
become real above that.

## `mongodump-lightning` — PRIMARY, 10 GB – multi-TB, any cloud or self-hosted

```
mongodump --uri="$MONGO_URI" --db=$DB --oplog --out=$DUMP_DIR --numParallelCollections=N
  ↓
TiShift BSON-to-NDJSON converter (multi-process, per collection)
  ↓
fsspec-routed write:
   s3://staging/dump/<collection>/part-NNNN.ndjson      (AWS / MinIO / any S3-compatible)
   gs://staging/dump/<collection>/part-NNNN.ndjson      (GCP)
   azure://staging/dump/<collection>/part-NNNN.ndjson    (Azure)
   local:///mnt/staging/dump/<collection>/part-NNNN.ndjson  (NFS / bare metal)
  ↓
TiDB Lightning physical mode ingest (reads any of those URLs natively)
```

The BSON-to-NDJSON converter is TiShift code. It reads `*.bson` files using
PyMongo's BSON decoder (canonical parser, no maintenance burden), applies
BSON-type → JSON serialization (ObjectId → 24-char hex, Decimal128 → string,
UUID → standard format), and writes NDJSON via `fsspec`. Serialization rules
are shared with `check/hash_diff` canonicalization — tested in one place.

### Parallelism knobs

- `mongodump --numParallelCollections=N` — Mongo's own flag, no TiShift work
- **Sharded clusters**: TiShift orchestrates one `mongodump` per shard's
  primary node concurrently, each writing to a separate staging path. 3–6×
  faster than a single mongodump against `mongos`.
- **Very large collections**: TiShift's optional parallel-reader mode
  partitions a single collection by `_id` ranges across N workers. Used when
  mongodump can't be installed or when a single mongodump process is too slow.
- **Lightning runner sizing**: typical multi-TB load uses an
  `n2-standard-32` / `c5.4xlarge`-class VM with 2 TB local SSD for SST sort.

### Storage backend selection

```yaml
load:
  staging:
    backend: s3                    # s3 | gs | azure | local
    base_url: s3://my-staging/mongo-export/
    region: us-east-1
    # backend-specific auth:
    #   s3: env AWS_ACCESS_KEY_ID/SECRET, or instance profile, or SSO
    #   gs: ADC or service-account JSON path
    #   azure: AZURE_STORAGE_CONNECTION_STRING or workload identity
    #   local: filesystem permissions
```

This is the cloud-agnostic point. Same load code runs in every environment;
only this config block changes.

## `aws-dms` — ADAPTER, when customer already operates AWS DMS

TiShift does **not** provision DMS resources from scratch. The adapter:

1. Validates the customer has supplied a DMS replication-instance ARN, source-endpoint ARN, and target-endpoint ARN
2. Emits a DMS task config (JSON) for the customer to apply
3. Customer applies via AWS Console or `aws dms create-replication-task`
4. TiShift polls the task via `boto3` for status / row counts / errors

```bash
tishift-mongodb load --strategy aws-dms --emit-task-config
```

Output is `tishift-output/dms-task-config.json` — customer applies. ~200 LOC
of adapter code. Not a runtime engine.

## `datastream-lightning` — ADAPTER, when customer already operates GCP Datastream

Same shape as `aws-dms`: TiShift emits a Datastream stream config + a
BigQuery-to-GCS export job, customer applies, TiShift polls.

```bash
tishift-mongodb load --strategy datastream-lightning --emit-stream-config
```

## Direct strategy resumability

Direct strategy writes a state file `tishift-output/.load-state.json`:

```json
{
  "load_id": "uuid",
  "strategy": "direct",
  "collections": {
    "users":     {"status": "complete", "row_count": 12345678},
    "orders":    {"status": "running",  "row_count": 4500000},
    "products":  {"status": "pending"}
  }
}
```

Resume after interruption:

```bash
tishift-mongodb load --resume tishift-output/.load-state.json
```

## Post-load index application

Always defer secondary indexes and FKs to after the data is loaded:

```bash
mysql ... < tishift-output/02-create-indexes.sql
mysql ... < tishift-output/04-multi-valued-indexes.sql
mysql ... < tishift-output/03-foreign-keys.sql
```

Applying them before the load makes the ingest 5–10× slower (every row
insert touches every index).

## Cost considerations

For a representative 1 TB MongoDB source on `mongodump-lightning`:

- `mongodump` against replica set: ~30 minutes for 1 TB on a moderate cluster
- BSON-to-NDJSON conversion: ~15 minutes on 8-core converter VM
- Staging storage (GCS / S3 / Azure): ~1.2 TB for 7 days ≈ $30
- Lightning runner VM (n2-standard-32, 2 TB local SSD): ~$5 / hour × 6 hours = $30
- TiDB Cloud ingest capacity: covered by the customer's tier
- Total: **~$60–100 one-time** for 1 TB

Compare AWS DMS or Datastream: typically $500–2000 / month plus per-row costs.
The TiDB-native path is dramatically cheaper for typical migrations.

## Cost considerations for very large (multi-PB)

When the TiDB-native path's single-runner Lightning hits CPU/IO ceilings
(typically around 10 TB / day), the adapter paths become attractive:
- AWS DMS scales parallelism across replication instances
- Datastream is serverless and scales linearly

But for almost every customer, that ceiling is well above what their
migration needs.
