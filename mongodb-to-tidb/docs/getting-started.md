# Getting Started — MongoDB → TiDB

A 30-minute walk-through to scan, convert, and load a small MongoDB database
into TiDB Cloud Starter (free tier).

## Prerequisites

1. **A running MongoDB instance** (replica set strongly recommended; standalone works for bulk-only migrations).
2. **`mongosh`** installed locally for connectivity checks.
3. **A TiDB Cloud cluster.** A free Starter cluster works for small databases. Sign up at [tidbcloud.com](https://tidbcloud.com).
4. **Python 3.10+** and `pip`.

## Install

```bash
git clone https://github.com/pingcap-inc/TiShift.git
cd TiShift/mongodb-to-tidb
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
```

By default, `pip install tishift-mongodb` only installs what's needed for the
TiDB-native paths (`direct`, `mongodump-lightning`, `direct-changestream`).
Add extras for adapters you'll use:

```bash
pip install -e '.[dev,aws-dms]'        # + AWS DMS adapter
pip install -e '.[dev,datastream]'     # + GCP Datastream adapter
pip install -e '.[dev,debezium]'       # + Debezium config adapter
```

Verify:

```bash
tishift-mongodb --version
```

## Configure

```bash
cp config/tishift-mongodb.example.yaml tishift-mongodb.yaml
```

Edit `tishift-mongodb.yaml`:

```yaml
source:
  uri: mongodb://user:${TISHIFT_SOURCE_PASS}@localhost:27017/myapp?authSource=admin
  database: myapp
  topology_hint: replica_set        # standalone | replica_set | sharded | auto

target:
  host: gateway01.us-east-1.prod.aws.tidbcloud.com
  port: 4000
  user: YOUR_TIDB_USER
  password: ${TISHIFT_TARGET_PASSWORD}
  database: myapp_migrated
  tls: true
  tier: starter

load:
  staging:
    backend: local                  # s3 | gs | azure | local
    base_url: file:///tmp/tishift-staging/
```

Export passwords:

```bash
export TISHIFT_SOURCE_PASS='your-mongo-password'
export TISHIFT_TARGET_PASSWORD='your-tidb-password'
```

## Phase 1 — Connect

```bash
tishift-mongodb preflight --config tishift-mongodb.yaml
```

Expected: all checks green.

## Phase 2 — Scan

```bash
tishift-mongodb scan --config tishift-mongodb.yaml --format cli --format json
```

Output:
- `tishift-reports/mongodb-scan-report.json` — machine-readable
- CLI panel showing collections, doc counts, polymorphic flags, aggregation inventory

## Phase 3–4 — Assess and Score

```bash
tishift-mongodb score --config tishift-mongodb.yaml \
    --scan-report tishift-reports/mongodb-scan-report.json
```

Score prints in the canonical readiness format. If below 55, read "WHAT NEEDS
WORK" before continuing.

**Mandatory user gate** — confirm whether to proceed to convert.

## Phase 5 — Convert

```bash
# Dry-run
tishift-mongodb convert --config tishift-mongodb.yaml \
    --scan-report tishift-reports/mongodb-scan-report.json --dry-run

# Review
cat tishift-output/convert-advisor.md
cat tishift-output/aggregation-rewrite.md     # if aggregations present

# Apply DDL
tishift-mongodb convert --config tishift-mongodb.yaml \
    --scan-report tishift-reports/mongodb-scan-report.json --apply
```

## Phase 6 — Load

For getting-started (< 10 GB), use direct:

```bash
tishift-mongodb load --config tishift-mongodb.yaml --strategy direct
```

For larger, use `mongodump-lightning`. See [load-guide.md](load-guide.md).

After load, apply post-load indexes:

```bash
mysql ... < tishift-output/02-create-indexes.sql
mysql ... < tishift-output/03-foreign-keys.sql
mysql ... < tishift-output/04-multi-valued-indexes.sql
```

## Phase 7 — Check

```bash
tishift-mongodb check --config tishift-mongodb.yaml \
    --scan-report tishift-reports/mongodb-scan-report.json --sample-size 1000
```

Zero count mismatches = migration verified.

## Where to go next

- [scan-guide.md](scan-guide.md) — sampling tuning + BSON type inference
- [convert-guide.md](convert-guide.md) — schema policy + aggregation advisor
- [load-guide.md](load-guide.md) — strategy matrix + cloud-agnostic staging
- [sync-guide.md](sync-guide.md) — CDC via direct-changestream daemon or adapters
- [deployment-topologies.md](deployment-topologies.md) — standalone / replica set / sharded
