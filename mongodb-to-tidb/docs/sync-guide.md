# Sync Guide — CDC

How `tishift-mongodb sync` streams ongoing MongoDB changes to TiDB during
cutover. See [cdc-providers.md](../references/cdc-providers.md) for the full
provider matrix; this guide is the operational walkthrough.

## When you need this

You need sync if your acceptable downtime is shorter than the bulk load
takes. For a 1 TB MongoDB source, mongodump-lightning typically completes
in 6–8 hours. If the application can be read-only for that long, skip sync.

Sync is required when:

- Cutover tolerance is hours, not days
- Steady write traffic that cannot pause
- Rollback option needed (Mongo stays primary while TiDB warms)

## Provider choice

```
| Customer profile                                | Recommended         |
|-------------------------------------------------|---------------------|
| Greenfield (no existing CDC infra)              | direct-changestream |
| Already operates AWS DMS                        | aws-dms             |
| Already operates GCP Datastream                 | datastream          |
| Already operates Kafka Connect + Debezium       | debezium            |
| Compliance requires enterprise-blessed tool     | adapter             |
| Other                                           | direct-changestream |
```

For most customers — **`direct-changestream` is the right answer**:
cheapest, simplest, no external dependency, runs in any container runtime.

## `direct-changestream` — TiDB-native (PRIMARY)

A TiShift-owned daemon. PyMongo Change Streams subscriber + PyMySQL writer.

### Requirements

- Mongo topology: **replica set or sharded cluster** (Change Streams need an oplog)
- Mongo user role: `read` + `changeStreamPreAndPostImages` if you want before-images
- TiDB connection: same as bulk load
- A runtime: Cloud Run / ECS / AKS / GKE / K8s / VM — any

### Starting it

```bash
tishift-mongodb sync start --provider direct-changestream \
    --since "$LOAD_COMPLETED_AT"
```

`--since` is the timestamp of the load's snapshot point (from
`tishift-output/.load-state.json`).

### Deploying as a service

#### Cloud Run (GCP)

```bash
gcloud run deploy tishift-mongodb-cdc \
    --image=gcr.io/$PROJECT/tishift-mongodb:0.1.0 \
    --service-account=$SA \
    --vpc-connector=$VPC_CONNECTOR \
    --vpc-egress=all-traffic \
    --no-allow-unauthenticated \
    --command="tishift-mongodb" \
    --args="sync,start,--provider,direct-changestream,--config,gs://config/tishift-mongodb.yaml,--since,$LOAD_TIMESTAMP" \
    --cpu=2 --memory=4Gi --timeout=86400
```

#### ECS (AWS)

```yaml
# ecs-task-definition.json (abbreviated)
{
  "family": "tishift-mongodb-cdc",
  "containerDefinitions": [{
    "image": "....ecr.us-east-1.amazonaws.com/tishift-mongodb:0.1.0",
    "command": ["sync", "start", "--provider", "direct-changestream",
                "--config", "s3://config/tishift-mongodb.yaml",
                "--since", "$LOAD_TIMESTAMP"],
    "environment": [...],
    "secrets": [...]
  }]
}
```

#### K8s

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: tishift-mongodb-cdc
spec:
  replicas: 1                    # increase + partition for high write rates
  template:
    spec:
      containers:
      - name: cdc
        image: tishift-mongodb:0.1.0
        command: ["tishift-mongodb", "sync", "start",
                  "--provider", "direct-changestream",
                  "--config", "/etc/tishift/tishift-mongodb.yaml",
                  "--since", "$LOAD_TIMESTAMP"]
        envFrom:
        - secretRef:
            name: tishift-secrets
```

### Resume tokens

The daemon persists resume tokens to local file (`tishift-output/.cdc-state.json`)
or, optionally, to a TiDB table:

```yaml
sync:
  resume_token_storage: tidb     # file | tidb
  resume_token_table: _tishift_cdc_state
```

On restart, the daemon resumes from the last persisted token. Mongo's resume-
token contract means no events are lost or replayed.

### High-throughput partitioning

For write rates > 5k ops/sec, partition Change Streams across multiple daemons:

```yaml
sync:
  partitions:
    - name: shard1
      collections: [users, sessions, audit_logs]
    - name: shard2
      collections: [orders, products, inventory]
```

Deploy N daemon instances, each watching only its assigned collections.

## `aws-dms` adapter

When the customer's DMS replication task started in load phase continues in
CDC mode. TiShift polls the task via `boto3`:

```bash
tishift-mongodb sync start --provider aws-dms --task-arn $TASK_ARN
```

## `datastream` adapter

When the customer's Datastream stream feeds BigQuery. TiShift starts a
Dataflow streaming job (in the customer's project) that reads BQ `_raw`
tables and writes to TiDB:

```bash
tishift-mongodb sync start --provider datastream --stream-id $STREAM_ID
```

## `debezium` adapter

OSS path. Customer operates Kafka + Kafka Connect. TiShift emits configs:

```bash
tishift-mongodb sync start --provider debezium --emit-connector-config
# Outputs:
#   tishift-output/debezium-mongodb-source.json
#   tishift-output/debezium-jdbc-sink.json
```

Customer applies via Kafka Connect REST API:

```bash
curl -X POST http://kafka-connect:8083/connectors -d @debezium-mongodb-source.json
curl -X POST http://kafka-connect:8083/connectors -d @debezium-jdbc-sink.json
```

TiShift polls the REST API for status.

## Monitoring

All providers expose `tishift_cdc_lag_seconds`. Healthy state: < 5 minutes
consistently. Write-burst spikes are expected.

| Metric | Type | Meaning |
|---|---|---|
| `tishift_cdc_lag_seconds{collection}` | Gauge | Time between event creation in Mongo and apply in TiDB |
| `tishift_cdc_apply_rate{collection}` | Counter | Events applied per second |
| `tishift_cdc_apply_errors_total{collection,type}` | Counter | Constraint violations, type errors, etc. |
| `tishift_cdc_resume_token_age_seconds` | Gauge | How recently was the resume token persisted (warning if growing) |

## Cutover

```
T-14d: Start CDC.
       Bulk load already completed. CDC catches up.
T-7d:  Verify counts + structure via tishift-mongodb check.
T-0:   Application read-only against Mongo.
       Wait for tishift_cdc_lag_seconds < 5.
       Final tishift-mongodb check --full.
       Switch application config to TiDB.
       Stop CDC.
       Retain Mongo read-only as rollback safety for N days.
```

## Stopping sync

```bash
tishift-mongodb sync stop --config tishift-mongodb.yaml
```

For `direct-changestream`: gracefully shuts down the daemon, persists the
final resume token. For adapters: stops the customer's task/job (or surfaces
the stop command if it requires customer-side action).

## What sync does NOT support

- **Bidirectional sync.** v1 only flows Mongo → TiDB.
- **Schema evolution during sync.** New Mongo fields not in the convert-time DDL log errors per event. Customer can drop, expand DDL, or re-converge.
- **Sub-second latency.** Realistic steady-state lag is 5–60 seconds. Higher under load bursts.
- **Strict ordering across collections.** Per-document order preserved; cross-collection order may be reshuffled by parallel processing.

## Cost considerations

`direct-changestream` daemon as Cloud Run / ECS:

- 1 vCPU, 2 GB RAM continuous = ~$40/month per partition
- Single partition suits most customers
- N partitions for high throughput → N × $40

Compare adapters:
- AWS DMS ongoing replication: ~$500-1500/month
- Datastream: usage-based; typically $200-500/month
- Debezium / Kafka Connect: customer already pays for their Kafka

The TiDB-native daemon is the cheapest path for almost every customer.
