# Sync Guide

`tishift-supabase sync` is the optional CDC phase. It replicates ongoing changes from Supabase to TiDB using Postgres logical replication so you can cut over with zero or near-zero downtime.

```bash
tishift-supabase sync --config tishift-supabase.yaml --start
tishift-supabase sync --config tishift-supabase.yaml --status
tishift-supabase sync --config tishift-supabase.yaml --stop
```

## Availability

| Tier | Sync available | Mechanism |
|---|---|---|
| Starter | **No** | No Changefeeds or DM on Starter. Migrations must be cutover-with-downtime. |
| Essential | Yes | TiDB Changefeeds or TiShift's own logical-replication bridge |
| Dedicated | Yes | Changefeeds, DM, or TiShift's own bridge |

If your target is Starter, skip this phase. Plan a maintenance window for the final cutover.

## Prerequisites

- `wal_level = logical` on Supabase. Paid tiers have this on by default; free tier may require a support ticket to enable (and enabling it is irreversible).
- **Direct endpoint** (`db.{project_ref}.supabase.co:5432`). Logical replication needs TCP streaming — the Supavisor pooler does NOT proxy the replication protocol.
- `REPLICATION` privilege on the `postgres` role (granted by default on Supabase).
- `max_replication_slots` capacity available (Supabase default ~10, not user-configurable on Cloud; TiShift uses 1).

## Supabase-specific slot and publication hygiene

Three rules, any of which can take down a live Supabase project if violated:

### 1. Never use `FOR ALL TABLES`

A blanket publication ships `auth.*`, `storage.*`, `realtime.*`, `vault.*`, and every extension-schema table to the target. TiShift creates the publication with an **explicit table allow-list** built from the scan inventory:

```sql
CREATE PUBLICATION tishift_pub FOR TABLE
  public.users,
  public.posts,
  public.comments,
  public.invoices;
```

### 2. Never reuse the slot name `supabase_realtime`

That slot is owned by Supabase's Realtime service and is load-bearing on production — drop it and Realtime stops broadcasting. TiShift uses `tishift_migration` (or a user-configured alternative in `sync.slot_name`).

### 3. Leave the Realtime slot and publication alone

Do not touch `supabase_realtime` (either the slot or the publication of the same name) for the duration of the migration. When the scan reports that slot as active, treat it as untouchable.

## How sync works

TiShift's sync bridge is a `psycopg` client that:

1. Creates slot `tishift_migration` (pgoutput decoder) on first run.
2. Creates publication `tishift_pub` with the explicit user-table allow-list.
3. Streams WAL changes (INSERT / UPDATE / DELETE / TRUNCATE) via the logical-replication protocol.
4. Decodes each change, applies the TiShift type mapping (same as convert), and executes via `PyMySQL` against TiDB.
5. Tracks LSN (Log Sequence Number) in a local state file — resumable across restarts.

The first run does NOT include a full snapshot. Run `tishift-supabase load` first to get the target populated; then `sync` streams only changes that happen after the load snapshot's `pg_current_wal_lsn()`.

## Cutover procedure

1. **Freeze application writes** to Supabase — maintenance mode in Supabase Dashboard, or an app-level feature flag that returns `503` on write endpoints.
2. **Wait for the sync bridge to catch up.** `tishift-supabase sync --status` reports lag in bytes and seconds. Target: < 1 second.
3. **Run a final check** with `tishift-supabase check --mode=live`. Expect zero deltas.
4. **Switch the application** to the new TiDB connection string. Unfreeze writes.
5. **Stop the sync bridge.** `tishift-supabase sync --stop`.
6. **Drop the TiShift slot and publication** on Supabase:
   ```sql
   SELECT pg_drop_replication_slot('tishift_migration');
   DROP PUBLICATION tishift_pub;
   ```
7. **Leave `supabase_realtime` alone** — Realtime is still running until you explicitly decommission it (probably later, as part of Phase 2 of your platform migration).

## Status output

```bash
tishift-supabase sync --status
```

```
Sync bridge: running
Slot:        tishift_migration (active, restart_lsn=0/1A2B3C4D, confirmed_flush_lsn=0/1A2B3C45)
Publication: tishift_pub
Tables:      4 (public.users, public.posts, public.comments, public.invoices)
Lag:         0.3 seconds / 128 KB
Uptime:      2h 14m
Applied:     12,847 INSERT, 3,201 UPDATE, 89 DELETE
Errors:      0
Last LSN:    0/1A2B3C4D
```

## Error recovery

- **"logical decoding requires wal_level >= logical":** Supabase project doesn't have logical replication enabled. Paid tier: enable via Dashboard → Database → Replication. Free tier: contact Supabase support (and note this change is irreversible — your project cannot go back).
- **"permission denied for database":** connection is using a non-`postgres` role. Only `postgres` has REPLICATION. Check `source.user` in YAML.
- **"replication slot already exists" (the TiShift slot, not supabase_realtime):** a previous sync run left it behind. Confirm it's TiShift's (`SELECT * FROM pg_replication_slots WHERE slot_name = 'tishift_migration'`) then drop with `pg_drop_replication_slot`. Safe to drop because TiShift's slot is not load-bearing.
- **Lag growing instead of shrinking:** source write rate exceeds bridge apply rate. Increase bridge parallelism (`--parallel`), check TiDB write latency, or batch the load instead of streaming.
- **Bridge crashes with WAL sender errors:** typically network instability between the TiShift host and Supabase. Retry with a wider TCP keepalive (`--keepalive-seconds=10`).
- **TRUNCATE on source didn't propagate:** `pgoutput` does emit TRUNCATE messages but some targets (and the default bridge behavior) drop them for safety. Use `--apply-truncate` to enable, with care.
- **`supabase_realtime` slot shows `active=false`** in your status probe: that's a Realtime problem, not a TiShift problem. Do not attempt to recover it with TiShift — the Realtime team on your end (or Supabase support) handles that.

## Live validation during sync

Run `tishift-supabase check --mode=live --live-tolerance-pct=0.1` periodically. It tolerates small deltas (reports them, doesn't fail) so you can monitor drift without blocking on micro-lag.

## After cutover

- Monitor application error rates for RLS-derived permission errors — these will surface quickly if a policy rewrite missed a code path.
- Validate auth login flow (passwords should work if target is bcrypt-compatible; forced resets if Firebase).
- Confirm storage bytes are accessible at their new URLs (signed-URL generation is your replacement, not Supabase's).
- Monitor Realtime consumers (if still using Supabase Realtime during a phased cutover) for slot backlog — if you paused the app for cutover, Realtime's slot may have a large catch-up queue.

After 2–4 weeks of stable operation, decommission the Supabase project (or downgrade to the free tier for a safety-net standby).
