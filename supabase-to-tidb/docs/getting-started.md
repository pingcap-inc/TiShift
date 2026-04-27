# Getting Started

TiShift Supabase runs a Supabase project through a 5-phase migration toolkit: scan → convert → load → check → sync. This guide covers prerequisites, installation, and a first end-to-end run against a small project.

## Prerequisites

### Supabase project access

You need the database connection credentials for your Supabase project. Supabase exposes **three** connection endpoints — each matters for different phases:

| Endpoint | Host | Port | Username | Used by |
|---|---|---|---|---|
| Direct | `db.{project_ref}.supabase.co` | 5432 | `postgres` | All phases (required for sync) |
| Session pooler | `aws-0-{region}.pooler.supabase.com` | 5432 | `postgres.{project_ref}` | scan, convert, load |
| Transaction pooler | `aws-0-{region}.pooler.supabase.com` | 6543 | `postgres.{project_ref}` | **Refused by TiShift** |

Transaction mode (port 6543) breaks `pg_dump`, prepared statements, and replication. TiShift refuses it at the connection layer. Use either the direct endpoint or the session pooler.

On the Supabase dashboard: Settings → Database → Connection string. The "Session" option gives you the session pooler URL; the "Direct" option gives you the direct URL; avoid the "Transaction" option for migration work.

**Free tier quirk:** As of 2024 Supabase removed dedicated IPv4 from the free tier. The direct endpoint resolves to an IPv6-only AAAA record. If your host or CI runner lacks IPv6, use the session pooler for scan and load — the pooler terminates TCP and supports IPv4. Sync (Phase 8) still requires the direct endpoint, so plan accordingly.

### TiDB target

Choose a tier before you start:

- **Starter** — free up to 25 GiB, import via `ticloud` CLI, no CDC sync. Good for assessments and small migrations.
- **Essential** — autoscaling, Changefeeds, 99.99% SLA. Production workloads.
- **Dedicated** — full HTAP, Lightning, DM, compliance. Enterprise.

You'll need the host, port (4000 for Cloud), user, and password. For Cloud you'll also need `cluster_id` and `project_id` if you plan to use `ticloud` import.

### Local tools

- Python 3.10+
- `psql` client (to run the occasional one-off command)
- `mysql` client
- For Cloud load: `ticloud` CLI (`curl https://raw.githubusercontent.com/tidbcloud/tiup/master/ticloud.sh | sh`)
- For Lightning / DMS: the respective AWS credentials or self-hosted Lightning binary

## Installation

```bash
git clone <this-repo-url>
cd supabase-to-tidb
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

Optional extras:

```bash
pip install -e '.[ai]'    # AI API for PL/pgSQL + RLS rewrite suggestions
pip install -e '.[mcp]'   # MCP server for AI-driven workflows
pip install -e '.[aws]'   # boto3 for DMS and Storage S3 sync
pip install -e '.[pdf]'   # WeasyPrint for PDF reports
```

## First run

### 1. Configure

```bash
cp config/tishift-supabase.example.yaml tishift-supabase.yaml
```

Edit `tishift-supabase.yaml`:

```yaml
source:
  host: db.abcdefghijklmnop.supabase.co
  port: 5432
  user: postgres
  password: ${TISHIFT_SOURCE_PASSWORD}
  database: postgres
  sslmode: require

target:
  host: gateway01.us-east-1.prod.aws.tidbcloud.com
  port: 4000
  user: root
  password: ${TISHIFT_TARGET_PASSWORD}
  database: myapp_target
  tls: true
  tier: starter
```

Export credentials as environment variables (never inline them in config):

```bash
export TISHIFT_SOURCE_PASSWORD="<your-supabase-db-password>"
export TISHIFT_TARGET_PASSWORD="<your-tidb-password>"
```

### 2. Scan

```bash
tishift-supabase scan --config tishift-supabase.yaml --format cli --format json
```

This runs read-only queries against `pg_catalog`, extracts RLS policies as structured findings, detects Supabase platform signals (auth users, storage objects, Realtime slot, extensions), and emits a compatibility report with a readiness score (0–100).

Output lands in `./tishift-reports/` by default:

- `tishift-supabase-report.json` — machine-readable
- `tishift-supabase-report.html` — browser-friendly
- Rich-formatted CLI summary printed to stdout

**Stop here. Read the report.** The key things to notice:

1. **Score and rating.** ≥ 75 = proceed. 50–74 = resolve top blockers first. < 50 = plan a phased migration.
2. **Blocker list.** Each entry has an ID (see `references/compatibility-rules.md`), a count, and an action.
3. **RLS findings.** If your project uses row-level security (most do), every policy is listed with its full expression. This is the rewrite checklist for your app / middleware team.
4. **External-work checklist.** PostgREST, GoTrue, Realtime, Storage, pgsodium, pg_graphql, pg_cron, wrappers — whichever are triggered by your project. These are *not* migrated by TiShift; they're parallel work streams.

### 3. Convert

```bash
tishift-supabase convert --scan-report ./tishift-reports/tishift-supabase-report.json
```

This generates:

- `01-create-tables.sql`, `02-create-indexes.sql`, `03-create-views.sql`, `04-foreign-keys.sql` — TiDB DDL
- `05-rls-rewrite-checklist.md` — every RLS policy + `auth.*` call site for the app team
- `06-conversion-notes.md` — functions, triggers, sequences, ENUMs that need manual conversion
- `07-external-work-plan.md` — PostgREST / GoTrue / Realtime / Storage / etc. tracks

### 4. Load

```bash
tishift-supabase load --config tishift-supabase.yaml --strategy auto
```

The `auto` strategy picks between direct load, DMS, and TiDB Lightning based on data size and target tier. Schema is applied first; indexes dropped before load and recreated after (3–5× faster). The load uses an explicit schema allow-list (default: `public`) — it refuses to run with a wildcard, which prevents `auth.users` from being accidentally shipped.

### 5. Check

```bash
tishift-supabase check --config tishift-supabase.yaml --output cli,json
```

Row counts + column structure diff per table. Any mismatch is reported with details.

### 6. Sync (optional, Essential/Dedicated only)

```bash
tishift-supabase sync --config tishift-supabase.yaml --status
tishift-supabase sync --config tishift-supabase.yaml --start
```

CDC replication from Supabase to TiDB using Postgres logical replication. Creates a TiShift-owned slot (`tishift_migration`) and a publication filtered to your user tables (never `FOR ALL TABLES`). Leaves Supabase's own `supabase_realtime` slot alone.

## What happens next

The DB migration is about 30% of the total project. The other 70% is replacing PostgREST, GoTrue, Realtime, Storage, and any Supabase-specific extensions your app depends on. See `07-external-work-plan.md` after conversion for the full list scoped to your project.

## Troubleshooting

- **"transaction_pooler_refused":** You provided a port-6543 URL. Get the session pooler URL (port 5432 on the pooler host) or the direct URL (`db.{ref}.supabase.co:5432`).
- **Hangs on first connection:** Supabase free-tier compute has scale-to-zero; cold start can take 1–3 seconds. TiShift waits up to 15 seconds on first connect. If it keeps failing, check Supabase dashboard for compute status.
- **"permission denied for table auth.users":** Expected on some Supabase tiers. The scan records 0 auth users and continues — diagnostic signals don't block the migration.
- **Empty `pg_stat_statements`:** Query Compatibility falls back to 12/15. Not an error.
- **TLS error to TiDB Cloud:** Ensure you have the ISRG Root X1 CA certificate (for Starter/Essential) available to the MySQL client.
