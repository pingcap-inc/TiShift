# CDC Providers

How `tishift-mongodb sync` streams ongoing Mongo changes to TiDB. **The
primary path is TiDB-native and cloud-agnostic.** Three adapters wrap
external services for customers who already operate them.

## `direct-changestream` — PRIMARY (TiDB-native, cloud-agnostic)

A TiShift-owned daemon. Subscribes to Mongo Change Streams via PyMongo,
applies events to TiDB via PyMySQL. Runs in any container runtime
(Cloud Run, ECS, AKS, GKE, K8s, plain VM, bare metal).

### Implementation outline

```python
def run_daemon(cfg, resume_token=None):
    client = pymongo.MongoClient(cfg.source.uri)
    target = pymysql.connect(...)
    pipeline = []          # optional: filter to in-scope collections
    options = {
        "resume_after": resume_token,
        "full_document": "updateLookup",     # bring full doc on UPDATE
    }
    with client[cfg.source.database].watch(pipeline, **options) as stream:
        for event in stream:
            apply_to_tidb(target, event, cfg)
            persist_resume_token(event["_id"])
            emit_metric("tishift_cdc_lag_seconds", now() - event_cluster_time(event))
```

### Key properties

- **Resume tokens** persisted to a local file (or, optionally, a TiDB
  table via `_tishift_cdc_state`) so the daemon survives restarts without
  losing position.
- **Partitioning**: a single daemon handles modest write rates (~5k ops/sec).
  Higher rates shard into N daemons each watching a subset of collections.
- **Backpressure**: implicit via PyMongo's cursor (pulls one batch ahead).
  If TiDB write throughput drops, the cursor naturally slows.
- **Topology requirement**: replica set or sharded cluster. Standalone
  deployments cannot use Change Streams — BLOCKER-1 catches this.
- **Schema drift mid-stream**: if a new Mongo field appears that wasn't in
  the convert-time DDL, the daemon logs an error per event and continues.
  Customer can drop the field, expand DDL, or rerun convert. Surfaces in
  metrics.
- **Cost**: a single Cloud Run / ECS / K8s pod. No per-event pricing.

### Deployment

```bash
tishift-mongodb sync start --provider direct-changestream \
    --since "$LOAD_COMPLETED_AT"
```

For Cloud Run:

```bash
gcloud run deploy tishift-mongodb-cdc \
    --image=gcr.io/$PROJECT/tishift-mongodb:0.1.0 \
    --service-account=$SA \
    --vpc-connector=$VPC_CONNECTOR \
    --command="tishift-mongodb,sync,start,--provider,direct-changestream,--config,gs://config/tishift-mongodb.yaml"
```

For ECS / K8s — same image, customer's existing runtime.

## `aws-dms` — ADAPTER (when customer already operates DMS)

The DMS replication task started in the load phase continues in CDC mode.
TiShift polls the task via `boto3`; metrics surface as
`tishift_cdc_lag_seconds`.

```bash
tishift-mongodb sync start --provider aws-dms --task-arn $TASK_ARN
```

### Cutover

```
Stop DMS task → wait for drain → verify counts → switch app.
```

## `datastream` — ADAPTER (when customer already operates GCP Datastream)

The Datastream stream that fed the load remains active. TiShift runs a
Dataflow streaming job (the customer's, not ours) that reads BigQuery's
`_raw` tables and writes to TiDB.

```bash
tishift-mongodb sync start --provider datastream --stream-id $STREAM_ID
```

## `debezium` — ADAPTER (when customer already operates Kafka Connect)

OSS path. TiShift emits the JSON configurations for:

- `MongoDbConnector` (source) — Change Streams → Kafka topics
- `JdbcSinkConnector` (sink) — Kafka topics → TiDB

The customer applies the configs via Kafka Connect REST API. TiShift polls
the REST API for connector status.

```bash
tishift-mongodb sync start --provider debezium --emit-connector-config
```

Output:
- `tishift-output/debezium-mongodb-source.json`
- `tishift-output/debezium-jdbc-sink.json`

Customer applies via:

```bash
curl -X POST http://kafka-connect:8083/connectors -d @debezium-mongodb-source.json
curl -X POST http://kafka-connect:8083/connectors -d @debezium-jdbc-sink.json
```

## Common cutover runbook (any provider)

```
T-14d: Start CDC (direct-changestream daemon OR configure adapter provider).
       Bulk load completes; CDC catches up.
T-7d:  Verify counts and structure via tishift-mongodb check.
T-0:   Application read-only against Mongo.
       Wait for tishift_cdc_lag_seconds < 5.
       Final tishift-mongodb check --full.
       Switch application config to TiDB.
       Stop CDC.
       Retain Mongo read-only as rollback safety for N days.
```

## Lag monitoring

Every provider exposes `tishift_cdc_lag_seconds`. Healthy state: stable
< 5 minutes. Spikes during write bursts are expected. Grafana dashboard
template at `docs/grafana/mongodb-cdc-dashboard.json`.

## When to pick each provider

| Customer profile | Recommendation |
|---|---|
| Greenfield (no existing CDC infra) | `direct-changestream` |
| Already operating AWS DMS for other workloads | `aws-dms` |
| Already operating Datastream for BigQuery analytics | `datastream` |
| Already operating Kafka Connect + Debezium | `debezium` |
| Multi-PB scale, single-daemon insufficient | `direct-changestream` with N-shard partitioning, OR adapter |
| Compliance requires "blessed" enterprise tool | adapter |

For every other case, `direct-changestream` is the right answer — cheapest,
simplest, no external dependency.
