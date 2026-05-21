# Getting Started — Firestore → TiDB

A 30-minute walk-through to get a small Firestore database scanned, converted,
and loaded into TiDB Cloud Starter (free tier).

## Prerequisites

1. **GCP project** with at least one Firestore database in Native mode.
   - `gcloud config set project YOUR_PROJECT`
   - `gcloud firestore databases list` — confirm at least one database exists.
2. **Application Default Credentials** set up locally:
   - `gcloud auth application-default login`
3. **A TiDB Cloud cluster.** A free Starter cluster works for getting-started
   and small databases. Sign up at [tidbcloud.com](https://tidbcloud.com).
4. **Python 3.10+** and `pip`.

## Install

```bash
git clone https://github.com/pingcap-inc/TiShift.git
cd TiShift/firestore-to-tidb
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
```

Verify:

```bash
tishift-firestore --version
```

## Configure

```bash
cp config/tishift-firestore.example.yaml tishift-firestore.yaml
```

Edit `tishift-firestore.yaml`:

```yaml
source:
  project_id: YOUR_PROJECT
  database_id: "(default)"

  staging:
    gcs_bucket: YOUR_STAGING_BUCKET
    gcs_prefix: firestore-export/
    region: us-central1

target:
  host: gateway01.us-east-1.prod.aws.tidbcloud.com   # from TiDB Cloud console
  port: 4000
  user: YOUR_TIDB_USER
  password: ${TISHIFT_TARGET_PASSWORD}
  database: firestore_migrated
  tls: true
  tier: starter
```

Export the target password:

```bash
export TISHIFT_TARGET_PASSWORD='your-tidb-password'
```

## Phase 1 — Connect

```bash
tishift-firestore preflight --config tishift-firestore.yaml
```

Expected output: all checks green. If a check fails, fix it before
proceeding — every later phase depends on these connections.

## Phase 2 — Scan

```bash
tishift-firestore scan --config tishift-firestore.yaml --format cli --format json
```

Output:
- `tishift-reports/firestore-scan-report.json` — machine-readable
- CLI panel showing collections, document counts, polymorphic-field flags

Sampling defaults: 200 docs per collection or 1% of the collection, whichever
is larger, capped at 5,000. Adjust via `scan.sample_size_per_collection` in
the config.

## Phase 3–4 — Assess and Score

```bash
tishift-firestore score --config tishift-firestore.yaml \
    --scan-report tishift-reports/firestore-scan-report.json
```

The score prints in the canonical readiness format. If your score is below
55, read the "WHAT NEEDS WORK" section before continuing.

**Mandatory user gate** — confirm whether to proceed to convert. For a
small getting-started database, proceed.

## Phase 5 — Convert

```bash
# Dry-run first
tishift-firestore convert --config tishift-firestore.yaml \
    --scan-report tishift-reports/firestore-scan-report.json --dry-run

# Review the convert advisor
cat tishift-output/convert-advisor.md

# Apply DDL
tishift-firestore convert --config tishift-firestore.yaml \
    --scan-report tishift-reports/firestore-scan-report.json --apply
```

The dry-run produces SQL files in `tishift-output/`. The advisor surfaces
per-collection policy decisions and any flagged polymorphic fields.

## Phase 6 — Load

For getting-started (< 10 GB), use the direct strategy:

```bash
tishift-firestore load --config tishift-firestore.yaml \
    --scan-report tishift-reports/firestore-scan-report.json \
    --strategy direct
```

For larger databases on Starter tier, use `dataflow-cloudimport`. For BYOC or
Dedicated, use `dataflow-lightning`. See [load-guide.md](load-guide.md) for
the full strategy matrix.

After load, apply the post-load index and FK files:

```bash
mysql -h $TIDB_HOST -P 4000 -u $TIDB_USER -p"$TISHIFT_TARGET_PASSWORD" \
    --ssl-mode=VERIFY_IDENTITY \
    < tishift-output/02-create-indexes.sql

mysql -h $TIDB_HOST -P 4000 -u $TIDB_USER -p"$TISHIFT_TARGET_PASSWORD" \
    --ssl-mode=VERIFY_IDENTITY \
    < tishift-output/03-foreign-keys.sql
```

## Phase 7 — Check

```bash
tishift-firestore check --config tishift-firestore.yaml \
    --scan-report tishift-reports/firestore-scan-report.json \
    --sample-size 1000
```

Reports document-count parity, structure parity, and a hash-diff sample
across collections. Zero count mismatches = the migration is verified.

## Where to go next

- [scan-guide.md](scan-guide.md) — sampling tuning and what the scan
  report contains
- [convert-guide.md](convert-guide.md) — how the schema policy decides
  per-collection mapping, and how to override
- [load-guide.md](load-guide.md) — strategy matrix and Dataflow tuning
- [sync-guide.md](sync-guide.md) — CDC via the BigQuery bridge for
  near-zero-downtime cutover
- [byoc-deployment.md](byoc-deployment.md) — full BYOC architecture and
  IAM setup for production migrations
