# Check Guide

`tishift-supabase check` validates source and target consistency after load (or during live sync). Cross-protocol — queries Supabase via `psycopg`, queries TiDB via `PyMySQL`.

```bash
tishift-supabase check --config tishift-supabase.yaml --output cli,json
```

## What check does

### Step 7.1 — Source row counts

Prefers `SELECT COUNT(*)` per table for accuracy. Falls back to `pg_class.reltuples` (statistics) if a table has > 10M rows and `--exact-counts` is not set.

### Step 7.2 — Target row counts

`information_schema.tables.table_rows` for a quick pass, then `SELECT COUNT(*)` for any table flagged in Step 7.1 as potentially mismatched.

### Step 7.3 — Column structure

Compares column names, mapped types, nullability, and default expressions between `information_schema.columns` on Postgres and `information_schema.columns` on MySQL. Type matching uses the mapping in `references/type-mapping.md` — a Postgres `uuid` against a TiDB `VARCHAR(36)` is a match, not a mismatch.

### Step 7.4 — Optional checksum

`--checksum` enables per-primary-key-range `MD5(CONCAT_WS(',', ...))` comparison. Shards by PK range so 100M-row tables don't need a single giant query. Type normalization happens before hashing (Postgres `TRUE` and TiDB `1` hash the same; UUID strings hash the same whether stored as `VARCHAR(36)` or `BINARY(16)`).

## Output

Rich-formatted CLI summary:

```
✓ 24 tables matched
⚠ 2 tables mismatched (row count delta > 1%)
✗ 0 tables missing on target
✗ 0 tables orphan on target

Mismatched:
  public.events       source=1,234,567  target=1,234,520  delta=-47 (-0.004%)
  public.sessions     source=98,201     target=97,800     delta=-401 (-0.41%)
```

JSON report (`tishift-reports/check-result.json`):

```json
{
  "summary": {"matched": 24, "mismatched": 2, "missing_target": 0, "orphan_target": 0},
  "tables": [
    {"name": "public.users", "source_rows": 5432, "target_rows": 5432, "status": "match"},
    {"name": "public.events", "source_rows": 1234567, "target_rows": 1234520,
     "status": "mismatch", "delta": -47, "delta_pct": -0.004,
     "column_diffs": [], "checksum": null}
  ]
}
```

## Modes

| Mode | When to use | What it does |
|---|---|---|
| `--mode=once` (default) | After load, before cutover | Single snapshot comparison |
| `--mode=live` | During active sync | Accepts small lag; reports delta without failing if within `--live-tolerance-pct` |
| `--mode=deep` | Before cutover in a maintenance window | Full `COUNT(*)` + `--checksum` |

## What check does NOT validate

- **Auth user migration correctness** — that's the auth target's job (Auth0 / Clerk / Cognito / custom). Check with a test login after import.
- **Storage byte copy** — verify with `aws s3 sync --dryrun` (should report 0 changes) or `aws s3 ls --recursive` row counts.
- **RLS policy rewrites** — no DB-level signal. Validate with application-level integration tests that assert the expected row visibility under each user role.
- **PostgREST / GoTrue / Realtime replacement correctness** — application-layer concerns. Integration tests, not DB comparison.
- **Row-level semantic equality for types with lossy conversions** — `timestamptz` → `DATETIME(6)` drops timezone metadata; the raw values compare equal only if the application was already storing UTC. Flag these columns for spot-checks.

## Gate before cutover

- Zero missing tables on target.
- Zero orphan tables on target (or: orphan tables have been explicitly dropped after user confirmation).
- All user-schema row-count deltas within an acceptable threshold (usually 0 for once-mode; < 1% for live-mode during active sync).
- Column structure matches for every user-schema column (modulo the documented type-mapping equivalences).
- `auth.*` and `storage.*` tables are confirmed absent on target.

## Error recovery

- **Row count difference 1–5%:** most likely concurrent writes during export. Re-export and re-load the affected table; if source is live, enable Phase 8 (sync) before the final Check.
- **Row count difference > 5%:** check load logs for LOAD DATA errors, verify CSV integrity (`wc -l`), look for encoding issues. Truncate and re-load.
- **Column type mismatch:** rare after a successful convert + load. Usually indicates a manual DDL edit between convert and load. Compare `01-create-tables.sql` against the actual TiDB schema (`SHOW CREATE TABLE t`).
- **Missing on target:** verify the table was included in convert output. Re-apply DDL + re-load that table.
- **Orphan on target:** usually a dropped-on-source table. Confirm with the user and drop from target.
- **Checksum mismatch with identical row counts:** indicates semantic drift — often a `timestamptz` UTC-normalization difference or a `boolean` → `TINYINT(1)` coercion mismatch. Spot-check a few rows with a direct `SELECT` on both sides.
