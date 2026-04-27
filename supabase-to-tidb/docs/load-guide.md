# Load Guide

`tishift-supabase load` moves user-schema data from Supabase to TiDB. Strategy is chosen by the target tier and data size.

```bash
tishift-supabase load --config tishift-supabase.yaml --strategy auto
```

`--strategy` options: `auto` (default), `direct`, `dms`, `ticloud`, `lightning`.

## The schema allow-list is mandatory

The load command **refuses to run with a wildcard schema filter.** It reads `source.schema_include` from the YAML config and uses that as the `--schema` argument to `pg_dump` / `pgcopydb`. If you manually set `schema_include: ['*']` or try to bypass the filter, the command errors out.

Why: a naive `pg_dump` against a Supabase project ships `auth.users` (including bcrypt password hashes), `storage.objects` (metadata + owners), and every service-layer schema to the target. That's a security incident waiting to happen. The command makes it impossible by default.

## Strategy matrix

| Target tier | Data size | Strategy | Tooling |
|---|---|---|---|
| Starter | Any (≤ 25 GiB) | `ticloud` | `pg_dump --schema=public -Fc` → CSV → `ticloud serverless import start` |
| Essential | < 50 GB | `direct` | CSV via `\COPY` → `LOAD DATA LOCAL INFILE` |
| Essential | 50–500 GB | `dms` | AWS DMS PostgreSQL source → MySQL target |
| Dedicated | < 50 GB | `direct` | Same as Essential |
| Dedicated | 50–500 GB | `dms` | Same as Essential |
| Dedicated | > 500 GB | `lightning` | CSV → S3 → TiDB Lightning physical import |

`auto` picks from this matrix using `tier` from YAML and the `total_data_gb` from the scan report.

## Connection mode

- **Session pooler** (port 5432 on `*.pooler.supabase.com`) works for `pg_dump` and `\COPY`. Required if your host lacks IPv6.
- **Direct endpoint** (`db.{ref}.supabase.co:5432`) works too, and is slightly faster because there's no pooler hop. Free-tier direct is IPv6-only.
- **Transaction pooler** (port 6543) is refused.

## Load procedure (all strategies)

1. **Apply schema.** `mysql ... < 01-create-tables.sql`
2. **Drop secondary indexes.** The tool runs `02-create-indexes.sql` in reverse (generating `DROP INDEX` statements). This is optional but recommended — load is 3–5× faster with no secondary indexes.
3. **Export per table** from source (strategy-specific).
4. **Import per table** into target (strategy-specific).
5. **Recreate secondary indexes.** `mysql ... < 02-create-indexes.sql`
6. **Apply foreign keys.** `mysql ... < 04-foreign-keys.sql`
7. **Analyze.** `ANALYZE TABLE t` on every imported table so TiDB's optimizer has stats.

## Strategy-specific details

### `direct` (CSV via LOAD DATA)

Per-table export using `\COPY (SELECT * FROM public.t) TO 't.csv' WITH CSV HEADER`. Per-table load with `LOAD DATA LOCAL INFILE 't.csv' INTO TABLE t FIELDS TERMINATED BY ',' ENCLOSED BY '"' LINES TERMINATED BY '\n' IGNORE 1 LINES`. Runs up to 4 tables in parallel by default (configurable).

### `ticloud` (TiDB Cloud Starter)

Per-table export the same as `direct`. Files larger than 250 MiB are split with `split -b 250m`. Then:

```bash
ticloud serverless import start \
  --cluster-id $CLUSTER_ID \
  --project-id $PROJECT_ID \
  --source-type LOCAL \
  --local.file-path "$FILE" \
  --local.target-database $DB \
  --local.target-table $TABLE
```

### `dms` (AWS Database Migration Service)

Creates a DMS task with:

- **Source endpoint:** PostgreSQL, pointed at the Supabase direct endpoint (NOT the pooler — DMS replication requires direct)
- **Target endpoint:** MySQL, pointed at TiDB
- **Table mappings:** explicit table include-list from the scan — no wildcards. Excludes every Supabase-internal schema.
- **Full-load mode** for initial migration; optional CDC mode for live sync (see [sync-guide.md](./sync-guide.md)).

### `lightning` (TiDB Lightning physical import)

CSV files go to S3, Lightning reads and writes SST files directly to TiKV. Fastest for > 500 GB datasets. Requires Dedicated tier. Source data is CSV; same `\COPY` extraction as `direct`.

## Storage bytes and auth users are NOT loaded by this command

They are separate deliverables tracked in `07-external-work-plan.md`:

- **Storage bytes** — `aws s3 sync s3://supabase-storage-{project_ref}/ s3://your-target-bucket/` (service_role credentials)
- **Auth users** — export `auth.users` + `auth.identities` via a direct `pg_dump -n auth` against the direct endpoint, then import into the chosen auth target (Auth0 / Clerk / Cognito / custom bcrypt-verifier)

If the scan reported auth_user_count > 0 or storage_object_count > 0, the load command prints a reminder at the end of the run.

## Error recovery

- **`pg_dump` output contains `auth.` or `storage.` DDL:** the schema filter didn't apply. Confirm `source.schema_include` in YAML is `[public]` (or your user-schema list) — not empty and not `['*']`. Rerun.
- **`LOAD DATA` fails partway through a table:** rows up to the failure may be inserted. Check with `SELECT COUNT(*) FROM t` on target. If partial, `TRUNCATE TABLE t` and retry that table. Don't re-load tables that already succeeded — the tool's continuation log tracks per-table progress.
- **`ticloud` import rejects a CSV:** usually a column-count mismatch (e.g., a quoted newline in a TEXT column wasn't escaped). Re-export with `\COPY ... WITH (FORMAT csv, HEADER, QUOTE '"', ESCAPE '\\')` and retry.
- **Foreign-key apply fails:** a referenced row is missing. Check if the referencing row was loaded before the referenced table — if so, `SET foreign_key_checks = 0` around `04-foreign-keys.sql`, apply, then `SET foreign_key_checks = 1`. Then run Phase 7 (check) to verify integrity.
- **DMS task stalls on LOB columns:** use "limited LOB mode" with a conservative max size (e.g., 32 KB). For larger LOBs, extract via a separate per-column CSV and patch in with `UPDATE ... SET col = LOAD_FILE(...)`.
- **Lightning "out of space":** Lightning needs 2–3× the source data size in local scratch space. Mount a larger volume or use `--sort-kv-dir` to point at cheap storage.

## Continuation

The load command writes a continuation log (`migration-output/load.continuation.json`). If it's interrupted, rerun the same command — it reads the log and resumes from the last completed table. `--fresh` wipes the log and restarts.

## Gate before proceeding to check

- All user-schema tables loaded with expected row counts.
- Indexes recreated.
- Foreign keys applied.
- No `auth.*` or `storage.*` tables on target.

See [check-guide.md](./check-guide.md).
