# TiShift — MongoDB → TiDB

A migration toolkit for moving MongoDB databases into TiDB Cloud. Ships as
an AI-driven skill (interactive, conversational) backed by a deterministic
Python CLI (scriptable, CI-friendly).

## What this does

MongoDB is a NoSQL document database; TiDB is a distributed SQL database.
This toolkit handles the document → relational mapping that makes the
migration tractable:

- **Scan** — samples documents (BSON-type-aware) to infer schema, enumerates
  composite + 2dsphere + text + wildcard + partial + TTL indexes, inventories
  aggregation pipelines, profiles data size, detects polymorphic and sparse
  fields, detects standalone / replica set / sharded topology.
- **Assess + Score** — produces a 0–100 readiness score across schema
  inferability, data complexity, query/index coverage, application coupling,
  and operational readiness. Flags BLOCKERs and WARNINGs.
- **Convert** — emits TiDB DDL with a composite-index-driven schema policy:
  collections with composite indexes land as typed columns; collections
  without land as JSON-mostly; hybrid (one merged `doc JSON` column for
  non-indexed fields) is the common case.
- **Load** — transfers data via TiDB-native paths by default (`direct` for
  small DBs, `mongodump-lightning` for medium-to-large). Optional adapters
  for AWS DMS, GCP Datastream, or Debezium when customers already operate them.
- **Check** — validates document counts, column structure, and BSON-aware
  per-document hash diffs across a sample.
- **Sync** — optional CDC during cutover, via TiShift-native
  `direct-changestream` daemon (PRIMARY, cloud-agnostic) or adapters for
  customers running AWS DMS / GCP Datastream / Debezium.

## Cloud-agnostic by design

TiShift's primary paths run in any cloud or on bare metal. Only the
storage-backend URL (`s3://` / `gs://` / `azure://` / `local://`) and the
daemon-runtime choice vary per environment. The same code runs on AWS, GCP,
Azure, or self-hosted — no per-cloud adapters needed.

## Architecture in one diagram

```
   MongoDB (any topology, any cloud)
        │
        ├─── scan/check ──── PyMongo (Admin SDK + Change Streams)
        │
        ├─── load ──────── mongodump → BSON-to-NDJSON → fsspec ── TiDB Lightning
        │                                              ↓
        │                                          TiDB Cloud
        │                                          (any tier, any cloud)
        │
        └─── sync ──────── direct-changestream daemon (PyMongo Change Streams)
                                          OR
                            adapters (AWS DMS / Datastream / Debezium)
```

## Quickstart with the AI skill

Open this project in an AI coding assistant that supports skills, and run:

```
/mongodb-to-tidb
```

The skill walks through every phase: connecting, scanning (with topology
detection), scoring, gating at the assessment, converting schema, loading
data, validating, and (optionally) running CDC during cutover.

## Quickstart with the CLI

```bash
cd mongodb-to-tidb
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'

cp config/tishift-mongodb.example.yaml tishift-mongodb.yaml
# Edit URI, target credentials, storage backend.

# Confirm connectivity
tishift-mongodb preflight --config tishift-mongodb.yaml

# Scan + score
tishift-mongodb scan --config tishift-mongodb.yaml --format cli --format json
tishift-mongodb score --config tishift-mongodb.yaml \
    --scan-report tishift-reports/mongodb-scan-report.json

# Convert schema (review the advisor + aggregation rewrites first)
tishift-mongodb convert --config tishift-mongodb.yaml \
    --scan-report tishift-reports/mongodb-scan-report.json --dry-run
tishift-mongodb convert --config tishift-mongodb.yaml \
    --scan-report tishift-reports/mongodb-scan-report.json --apply

# Load data
tishift-mongodb load --config tishift-mongodb.yaml \
    --scan-report tishift-reports/mongodb-scan-report.json --strategy auto

# Validate
tishift-mongodb check --config tishift-mongodb.yaml \
    --scan-report tishift-reports/mongodb-scan-report.json
```

## Install variants

```bash
pip install tishift-mongodb                            # Core: TiDB-native paths only
pip install tishift-mongodb[aws-dms]                   # + AWS DMS adapter
pip install tishift-mongodb[datastream]                # + GCP Datastream adapter
pip install tishift-mongodb[debezium]                  # + Debezium / Kafka Connect adapter
pip install 'tishift-mongodb[aws-dms,datastream,debezium]'    # All adapters
```

The core install has **no managed-service dependencies** — pure Python
plus `mongodump` (Mongo's own CLI) and `tidb-lightning` (TiDB's open-source
bulk loader).

## TiDB Cloud tier awareness

| Feature | Starter | Essential | Dedicated | BYOC |
|---|---|---|---|---|
| Load method | direct / mongodump-lightning | mongodump-lightning | mongodump-lightning | mongodump-lightning |
| CDC primary | direct-changestream | direct-changestream | direct-changestream | direct-changestream |
| Storage staging | any backend (s3/gs/azure/local) | any backend | any backend | any backend |
| Best for | < 10 GB getting-started | 10 GB – 1 TB | 1 TB – 10 TB | 1 TB – 100+ TB, any cloud |

## Source-side requirements

- A MongoDB instance — **replica set strongly recommended** (Change Streams
  require it). Standalone works for bulk-only migrations.
- MongoDB 4.2+ recommended (4.0+ minimum for CDC; 3.6+ for any Change Streams)
- A migration user with the `read` role on the in-scope database
- A staging location: any S3-compatible bucket / GCS bucket / Azure container / local FS

## What this toolkit does NOT do

- **Doesn't translate Mongo driver calls into TiDB SQL.** Application-side rewrite.
- **Doesn't rewrite aggregation pipelines automatically.** The advisor produces
  suggestions for human review — never auto-applied.
- **Doesn't migrate GridFS contents.** Files must be offloaded to object storage first.
- **Doesn't migrate CSFLE-encrypted fields** without the original client keys.
- **Doesn't operate Kafka / DMS / Datastream for you.** Adapters emit configs;
  the customer's infrastructure runs them.

## Configuration reference

```yaml
source:
  uri: mongodb+srv://user:${TISHIFT_SOURCE_PASS}@cluster.abc.mongodb.net/myapp?authSource=admin
  database: myapp
  topology_hint: replica_set    # standalone | replica_set | sharded | auto

target:
  host: gateway01.us-east-1.prod.aws.tidbcloud.com
  port: 4000
  user: root
  password: ${TISHIFT_TARGET_PASSWORD}
  database: myapp_migrated
  tls: true
  tls_ca: ""
  tls_insecure_skip_verify: false
  tier: dedicated

load:
  strategy: auto                # auto | direct | mongodump-lightning | aws-dms | datastream
  staging:
    backend: gs                 # s3 | gs | azure | local
    base_url: gs://my-staging/mongo-export/
    region: us-central1
  mongodump:
    parallel_collections: 4
    per_shard_parallel: true    # for sharded clusters
    use_oplog: true
  lightning:
    backend: local
    pd_addr: ""
    sorted_kv_dir: /data/lightning-sort

sync:
  enabled: false
  provider: direct-changestream   # direct-changestream | aws-dms | datastream | debezium
  resume_token_storage: file      # file | tidb

scan:
  sample_size_per_collection: 200
  full_scan_threshold_docs: 5000
  inventory_aggregations: true

convert:
  schema_policy_default: auto
  preserve_object_ids: true
  emit_foreign_keys: true
  aggregation_advisor:
    enabled: true
    completion_fn: ""             # caller-injected at runtime

check:
  sample_size: 1000
```

See `config/tishift-mongodb.example.yaml` for the full annotated form.

## Documentation

- [Getting started](docs/getting-started.md)
- [Scan guide](docs/scan-guide.md) — BSON sampling + aggregation inventory
- [Convert guide](docs/convert-guide.md) — schema policy + Hybrid merged JSON + aggregation rewrites
- [Load guide](docs/load-guide.md) — strategy matrix + cloud-agnostic storage
- [Check guide](docs/check-guide.md) — BSON-aware canonicalization
- [Sync guide](docs/sync-guide.md) — direct-changestream daemon + adapters
- [Deployment topologies](docs/deployment-topologies.md) — standalone / RS / sharded

## Tests

```bash
cd mongodb-to-tidb
pytest tests -q
```

Tests use `mongomock` for unit tests and a Docker `mongo:7` + Docker `tidb`
container for integration. No live cloud needed.

## License

Apache 2.0
