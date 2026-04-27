# Getting Started — CockroachDB to TiDB Migration

## Prerequisites

1. **CockroachDB access** — Read-only credentials. The user needs `SELECT` on `information_schema`, `crdb_internal` (for sizes, hash-sharded indexes, regions), and `pg_catalog`.
2. **CockroachDB client** — `cockroach sql` CLI or `psql` (any Postgres client).
3. **TiDB Cloud cluster** — A free [Starter](https://tidbcloud.com/) tier works.
4. **MySQL client** — For connecting to TiDB.

## Quick Start

### AI-assisted (recommended)

```
/cockroachdb-to-tidb
```

### CLI toolkit

```bash
cd cockroachdb-to-tidb
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
cp config/tishift-crdb.example.yaml tishift-crdb.yaml
tishift-crdb scan --config tishift-crdb.yaml
```

## Credentials

```bash
export PGPASSWORD="crdb_password"
export CRDB_URL="postgresql://user@host:26257/dbname?sslmode=verify-full&sslrootcert=/path/to/ca.crt"
export TISHIFT_TARGET_PASSWORD="tidb_password"
```

Note: CockroachDB default port is **26257**, not 5432.
