# TiShift — Firestore → TiDB

A migration toolkit for moving Google Cloud Firestore databases into TiDB
Cloud. Ships as an AI-driven skill (interactive, conversational) backed by a
deterministic Python CLI (scriptable, CI-friendly).

## What this does

Firestore is a NoSQL document database; TiDB is a distributed SQL database.
This toolkit handles the document → relational mapping that makes the
migration tractable:

- **Scan** — samples documents to infer the schema (Firestore has no
  `information_schema`), enumerates composite indexes, profiles data size,
  and detects polymorphic and sparse fields.
- **Assess + Score** — produces a 0–100 readiness score across schema
  inferability, data complexity, query/index coverage, application coupling,
  and operational readiness. Flags BLOCKERs and WARNINGs.
- **Convert** — emits TiDB DDL with a composite-index-driven schema policy:
  collections with composite indexes land as typed columns; collections
  without land as JSON-mostly; hybrids are the common case.
- **Load** — transfers data via Apache Beam on Dataflow → GCS NDJSON →
  TiDB Lightning (BYOC/Dedicated) or `ticloud serverless import`
  (Starter/Essential).
- **Check** — validates document counts, column structure, and per-document
  hash diffs across a sample.
- **Sync** — optional CDC during cutover, using the
  `firestore-bigquery-export` Firebase Extension as the change stream and a
  Dataflow streaming job as the BQ → TiDB bridge.

## Architecture in one diagram

```
   Cloud Firestore
        │
        ├─── scan/check ─── google-cloud-firestore (Admin SDK)
        │
        ├─── load ──────── Apache Beam on Dataflow ── GCS NDJSON ── TiDB Lightning
        │                                                              ↓
        │                                                          TiDB Cloud
        │
        └─── sync ──────── firestore-bigquery-export (Firebase Extension)
                                          │
                                          ▼
                                    BigQuery <collection>_raw
                                          │
                                          └── Dataflow streaming ── TiDB Cloud
```

## Quickstart with the AI skill

Open this project in an AI coding assistant that supports skills, and run:

```
/firestore-to-tidb
```

The skill walks through every phase: connecting to Firestore and TiDB,
scanning, scoring, gating at the assessment, converting schema, loading
data, validating, and (optionally) running CDC during cutover.

## Quickstart with the CLI

For environments where AI-assisted migration is not available, the same
phases run as CLI subcommands:

```bash
cd firestore-to-tidb
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'

cp config/tishift-firestore.example.yaml tishift-firestore.yaml
# Edit credentials and project IDs

# Confirm connectivity
tishift-firestore preflight --config tishift-firestore.yaml

# Scan and assess
tishift-firestore scan --config tishift-firestore.yaml --format cli --format json
tishift-firestore score --config tishift-firestore.yaml \
    --scan-report tishift-reports/firestore-scan-report.json

# Convert schema
tishift-firestore convert --config tishift-firestore.yaml \
    --scan-report tishift-reports/firestore-scan-report.json --dry-run
# Review tishift-output/convert-advisor.md
tishift-firestore convert --config tishift-firestore.yaml \
    --scan-report tishift-reports/firestore-scan-report.json --apply

# Load data
tishift-firestore load --config tishift-firestore.yaml \
    --scan-report tishift-reports/firestore-scan-report.json --strategy auto

# Validate
tishift-firestore check --config tishift-firestore.yaml \
    --scan-report tishift-reports/firestore-scan-report.json
```

## TiDB Cloud tier awareness

TiShift adjusts recommendations based on the target tier:

| Feature | Starter | Essential | Dedicated | BYOC |
|---|---|---|---|---|
| Load method | `ticloud serverless import` | `ticloud serverless import` | TiDB Lightning | TiDB Lightning |
| CDC bridge | BigQuery extension + bridge | BigQuery extension + bridge | BigQuery extension + bridge | BigQuery extension + bridge |
| Storage | 25 GiB free | Auto-scaled | Configurable | Customer-managed |
| Best for | < 10 GB getting-started | 10 GB – 1 TB | 1 – 10 TB | 1 TB – 100+ TB, intra-GCP |

## Source-side requirements

- A Cloud Firestore database in **Native mode** (Datastore mode supported at
  limited fidelity; MongoDB-API mode is explicitly out of scope — use the
  `mongo-to-tidb` skill instead)
- IAM identity with `roles/datastore.viewer` and `roles/datastore.indexAdmin`
- A GCS bucket in the same region for staging during load (≥1.2× source size)
- Optional: the `firestore-bigquery-export` Firebase Extension installed on
  in-scope collections (only required if you need near-zero-downtime cutover)

## What this toolkit does NOT do

- **Does not translate Firestore SDK calls into TiDB queries.** The
  application's data-access layer is rewritten by the application team.
- **Does not rewrite security rules.** They become application-layer
  authorization in TiDB; the convert phase emits the rule listing for
  manual review.
- **Does not migrate Firestore Cloud Functions.** Cloud Functions are
  application code; out of scope.
- **Does not migrate the MongoDB-API surface** of Firestore Enterprise — use
  the `mongo-to-tidb` skill.

## Configuration reference

```yaml
source:
  project_id: my-gcp-project
  database_id: "(default)"
  service_account_key: ${TISHIFT_GCP_SA_KEY}    # blank to use ADC
  mode: native                                  # native | datastore

  staging:
    gcs_bucket: my-tishift-staging
    gcs_prefix: firestore-export/
    region: us-central1

target:
  host: gateway01.us-east-1.prod.aws.tidbcloud.com
  port: 4000
  user: root
  password: ${TISHIFT_TARGET_PASSWORD}
  database: firestore_migrated
  tls: true
  tier: byoc                                    # starter | essential | dedicated | byoc

scan:
  sample_size_per_collection: 200
  full_scan_threshold_docs: 5000
  subcollection_max_depth: 10
  parent_sample_for_subcollections: 100

convert:
  schema_policy_default: auto
  preserve_document_ids: true
  emit_foreign_keys: true

load:
  strategy: auto
  dataflow:
    region: us-central1
    machine_type: n2-standard-4
    max_workers: 200
    autoscaling: THROUGHPUT_BASED
  lightning:
    backend: local
    pd_addr: tidb.byoc.example.com:2379

sync:
  enabled: false
  bigquery:
    project_id: my-gcp-project
    dataset_id: firestore_export
    polling_interval_seconds: 30
```

See `config/tishift-firestore.example.yaml` for the complete annotated form.

## Documentation

- [Getting started](docs/getting-started.md) — 30-minute walkthrough
- [Scan guide](docs/scan-guide.md) — sampling tuning and report format
- [Convert guide](docs/convert-guide.md) — schema policy and DDL emission
- [Load guide](docs/load-guide.md) — strategy matrix and Dataflow tuning
- [Check guide](docs/check-guide.md) — validation and canonicalization
- [Sync guide](docs/sync-guide.md) — CDC via BigQuery bridge
- [BYOC deployment](docs/byoc-deployment.md) — GCP-native production setup

## Tests

```bash
cd firestore-to-tidb
pytest tests -q
```

Tests use the Firestore Emulator for unit/integration and don't require a
live GCP project. Install the emulator:

```bash
gcloud components install cloud-firestore-emulator
```

## License

Apache 2.0
