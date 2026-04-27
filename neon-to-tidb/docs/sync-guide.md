# Sync Guide

The sync command sets up CDC (Change Data Capture) replication from Neon/Postgres to TiDB for minimal-downtime migration.

## Mechanism

Uses Postgres **logical replication** with the `pgoutput` decoder plugin:

```
Neon (publisher) → pgoutput WAL stream → TiShift CDC bridge → PyMySQL → TiDB
```

## Prerequisites

1. **WAL level must be `logical`** — enable via Neon Console (Settings → Replication). This is irreversible.
2. **Direct (unpooled) connection** required for replication.
3. **Publication created** on source: `CREATE PUBLICATION tishift_pub FOR ALL TABLES;`

## Neon-Specific Caveats

- **Scale-to-zero is disabled** while a replication subscriber is connected. The Neon compute stays active, increasing cost.
- **Replication slot auto-GC**: Neon removes inactive replication slots after ~40 hours. If sync is paused longer, CDC must restart from scratch.
- **max_wal_senders**: Default 10 in Neon. TiShift needs 1. Check capacity with `SHOW max_wal_senders`.

## Cutover Procedure

1. Pause application writes to Neon
2. Wait for TiShift CDC bridge to catch up (LSN matches)
3. Validate with `tishift-neon check --mode=live`
4. Switch application connection strings to TiDB
5. Drop publication and replication slot on Neon

## Tier Availability

| Tier | CDC Sync |
|---|---|
| Starter | Not available — cutover only |
| Essential | Available via Changefeeds |
| Dedicated | Available via Changefeeds or DM |

## Usage

```bash
# Start sync
tishift-neon sync --config tishift-neon.yaml --start

# Check sync status
tishift-neon sync --config tishift-neon.yaml --status

# Stop sync
tishift-neon sync --config tishift-neon.yaml --stop
```
