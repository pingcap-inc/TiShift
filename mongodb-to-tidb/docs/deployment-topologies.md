# Deployment Topologies

MongoDB can be deployed in three topologies, each with different migration
implications.

## Standalone

A single `mongod` process. No replication, no oplog, no high availability.

| Aspect | Implication |
|---|---|
| Change Streams | **Not available.** No oplog. |
| Sync (CDC) | **Cannot use.** BLOCKER-1 catches this. |
| Bulk load | `mongodump-lightning` or `direct` — both work fine |
| Cutover | Must be a full read-only window during the bulk load |

### What to do if you're on standalone

You have two options:

1. **Convert to a single-node replica set before migrating** (recommended).
   This is a config change, not a data move:

   ```bash
   # Stop mongod
   sudo systemctl stop mongod

   # Edit config to add replication
   sudo vi /etc/mongod.conf
   # Add:
   #   replication:
   #     replSetName: "rs0"

   # Start mongod
   sudo systemctl start mongod

   # Initiate the replica set
   mongosh --eval "rs.initiate()"
   ```

   Then re-run TiShift Phase 1 — topology will now be `replica_set` and
   Change Streams will be available.

2. **Accept a full read-only cutover window.** If the application can be
   offline for the duration of the bulk load (6–12 hours for 1 TB), no CDC
   is needed:

   ```yaml
   # tishift-mongodb.yaml
   sync:
     enabled: false
   ```

## Replica Set

The standard production deployment. One primary + N secondaries.

| Aspect | Implication |
|---|---|
| Change Streams | **Available** (the default Mongo CDC primitive) |
| Sync (CDC) | All providers work — `direct-changestream` recommended |
| Bulk load | All strategies work. Default: `mongodump-lightning` |
| Cutover | Minimal-downtime cutover supported via CDC |

### Best practices for migration

- **Read from a secondary** during scan + bulk load to avoid primary load. Set in URI: `readPreference=secondary` or `secondaryPreferred`.
- **Use `--oplog` on mongodump** to capture concurrent writes during the dump for point-in-time consistency.
- **Ensure oplog size is adequate** for the dump duration. Check:
  ```javascript
  db.printReplicationInfo()
  ```
  Aim for an oplog window 2× the expected mongodump duration.

## Sharded Cluster

A `mongos` router fronting N shards (each shard is itself a replica set) and
config servers. Used for very large deployments.

| Aspect | Implication |
|---|---|
| Change Streams | **Available** at the `mongos` level (aggregates from all shards) |
| Sync (CDC) | All providers work; partitioning across shards may be helpful at scale |
| Bulk load | TiShift orchestrates **one `mongodump` per shard primary in parallel** — 3–6× faster than mongodump-against-mongos |
| Cutover | Same as replica set; minimal-downtime supported |

### TiShift sharded-cluster awareness

When `tishift-mongodb scan` detects `topology == "sharded"`:

- Connects to `mongos` for topology discovery
- Reads shard list via `sh.status()` / `db.adminCommand("listShards")`
- For each shard, records the shard's primary host

When `tishift-mongodb load --strategy mongodump-lightning`:

- Spawns one `mongodump` per shard primary in parallel
- Each writes to a separate staging path: `<base_url>/shard-<N>/<collection>/...`
- BSON-to-NDJSON conversion runs per-shard
- Lightning ingest reads the unified path tree (collection names are
  deduplicated across shards — same collection on different shards merges
  into one TiDB table)

### Per-shard mongodump configuration

```yaml
load:
  strategy: mongodump-lightning
  mongodump:
    per_shard_parallel: true       # default true for sharded clusters
    numParallelCollections: 4      # passed to each shard's mongodump
```

## How TiShift detects topology

In Phase 1, the SKILL flow runs `db.runCommand({hello: 1})` and inspects:

| Field | Topology |
|---|---|
| `"msg": "isdbgrid"` present | sharded |
| `setName` present | replica_set |
| Neither | standalone |

You can override the detection with `source.topology_hint` in the config —
useful if you want to bypass the runtime check.

## Cross-version considerations

| Mongo version | TiShift support |
|---|---|
| < 3.6 | Pre-Change-Streams. No CDC possible. BLOCKER-1 if sync needed. |
| 3.6 – 3.x | Change Streams available; some advanced features absent (no `fullDocument` updateLookup). WARNING-15 fires. |
| 4.0 | Multi-doc transactions for replica sets. |
| 4.2 | Multi-doc transactions for sharded clusters. Recommended minimum. |
| 4.4 – 5.0 | Mature CDC + transactions. |
| 6.0+ | `splitLargeChanges`, pre/post images. Modern operating point. |
| 7.0+ | Current. Fully supported. |

## Atlas-specific notes

If running on MongoDB Atlas:

- Connection URI is `mongodb+srv://...mongodb.net/...`
- TLS is mandatory and enabled by default
- Datastream Mongo source is available as an adapter (if customer prefers managed CDC)
- Atlas Online Archive collections are not migrated (out of scope)
- Atlas Search indexes are not migrated (different architecture; recommend Elasticsearch or TiDB Cloud FTS)
- Atlas Triggers / Functions / Realm Sync are application-layer (out of scope)

## Self-hosted vs managed

| Aspect | Self-hosted | Atlas | DocumentDB / CosmosDB |
|---|---|---|---|
| Native protocol | Mongo wire | Mongo wire | Mongo-compatible (varying fidelity) |
| Change Streams | Yes (RS or sharded) | Yes | Limited |
| TiShift support | Full | Full | Best-effort; some features may not surface |

For Mongo-compatible-but-not-actually-Mongo systems (AWS DocumentDB, Azure
Cosmos DB Mongo API), test the scan against the customer's specific version
before committing. Most TiShift code paths work, but feature coverage varies.
