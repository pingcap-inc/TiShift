# TiShift Supabase

TiShift Supabase is a Python toolkit for Supabase → TiDB migration workflows. It assesses a Supabase project's readiness for TiDB, extracts row-level-security policies as structured findings, converts schema and procedural code, orchestrates the bulk load, and validates the result.

Supabase is vanilla Postgres plus a set of platform services (PostgREST, GoTrue, Realtime, Storage, Edge Functions, Supavisor, plus extensions like `pgsodium`, `pg_graphql`, `pg_net`, `pg_cron`). This toolkit handles the database portion. The platform services are out of scope for the DB move; the assessment surfaces them so they can be planned as parallel work streams.

## Commands

- `tishift-supabase scan`: Assess Supabase readiness and generate reports (inventory, RLS policies, platform signals, compatibility findings, score).
- `tishift-supabase convert`: Convert scan output to TiDB DDL, plus an RLS rewrite checklist and an external-work plan.
- `tishift-supabase load`: Run the bulk-load strategy chosen by tier and data size.
- `tishift-supabase sync`: Start / stop / check CDC sync lifecycle (Essential / Dedicated only).
- `tishift-supabase check`: Validate source / target consistency.

## Quick Start

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'

cp config/tishift-supabase.example.yaml tishift-supabase.yaml
# Edit tishift-supabase.yaml with your Supabase and TiDB connection details.

# Scan
tishift-supabase scan --config tishift-supabase.yaml --format cli --format json

# Convert from scan report
tishift-supabase convert --scan-report ./tishift-reports/tishift-supabase-report.json --dry-run

# Load / Check / Sync
tishift-supabase load --config tishift-supabase.yaml --strategy auto
tishift-supabase check --config tishift-supabase.yaml --output cli,json
tishift-supabase sync --config tishift-supabase.yaml --status
```

## Skill-first workflow

For an AI-guided migration, use the skill: open an AI coding assistant session in this directory and say *"Migrate my Supabase database to TiDB."* The assistant will load `SKILL.md` and walk you through each phase one command at a time (connect → scan → assess → score → convert → load → validate → optional sync).

## Connection modes

Supabase exposes three connection endpoints. Different modes work for different phases:

| Endpoint | Port | Username | Scan / Load | Sync | Notes |
|---|---|---|---|---|---|
| Direct | 5432 | `postgres` | Yes | Yes | Free tier: IPv6-only |
| Session pooler | 5432 (pooler host) | `postgres.{ref}` | Yes | No | Supports IPv4 |
| Transaction pooler | 6543 (pooler host) | `postgres.{ref}` | **Refused** | No | Breaks prepared statements, `pg_dump`, replication |

TiShift refuses port 6543 at the connection layer with a clear message. Use the session pooler for scan and load, or the direct endpoint if your host has IPv6.

## What this toolkit does NOT migrate

Only the database portion is migrated. The following are **out of scope** and surfaced in the scan report as external work items:

- **PostgREST REST API** — client code calling `supabase.from(...)` must be rewritten to talk to TiDB directly (ORM / raw SQL / Hasura / PostGraphile).
- **GoTrue auth** — export `auth.users` (bcrypt hashes preserve on compatible targets) to Auth0 / Clerk / Cognito / custom.
- **Realtime subscriptions** — replace with TiCDC + fanout, Debezium + Kafka, or application-level pub/sub.
- **Storage bytes** — copy separately via S3 sync from Supabase's S3-compatible endpoint; replace signed-URL generation.
- **pgsodium / supabase_vault secrets** — decrypt on source, re-encrypt against target KMS.
- **pg_graphql endpoint** — rewrite with Hasura / PostGraphile / custom resolvers.
- **pg_net webhooks** — move to application-layer workers.
- **pg_cron jobs** — map to TiDB `CREATE EVENT` or external scheduler.
- **Wrappers FDW** — rewrite each integration (Stripe / Firebase / S3 / etc.) at the application layer.
- **Edge Functions** — redeploy on Deno Deploy / Cloudflare Workers / AWS Lambda.

The scan report lists every triggered item so you can scope the full migration project, not just the DB slice.

## Row-level security

RLS is the most common database-layer blocker on Supabase. TiDB has no equivalent. The convert phase extracts every policy as a structured finding in `05-rls-rewrite-checklist.md` — policy name, table, command, roles, USING / WITH CHECK expressions — for the application / middleware rewrite team. Policies are **not** emitted to the target DDL.

## Test

```bash
pytest tests -q
```

## Documentation

- [`SKILL.md`](./SKILL.md) — phased migration skill
- [`docs/getting-started.md`](./docs/getting-started.md) — prerequisites and first run
- [`docs/scan-guide.md`](./docs/scan-guide.md) — interpreting the assessment report
- [`docs/convert-guide.md`](./docs/convert-guide.md) — DDL conversion, RLS extraction, and the external-work plan
- [`docs/load-guide.md`](./docs/load-guide.md) — bulk load strategies per tier and data size
- [`docs/check-guide.md`](./docs/check-guide.md) — post-load validation
- [`docs/sync-guide.md`](./docs/sync-guide.md) — optional CDC replication and cutover
- [`references/compatibility-rules.md`](./references/compatibility-rules.md) — blocker and warning rules
- [`references/scoring.md`](./references/scoring.md) — scoring methodology
- [`references/type-mapping.md`](./references/type-mapping.md) — type mapping table
- [`references/function-mapping.md`](./references/function-mapping.md) — function and operator mapping

## License

Apache 2.0.
