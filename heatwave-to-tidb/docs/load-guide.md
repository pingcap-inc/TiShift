# Load Guide

**Status: intentionally disabled.** Data loading is a high-stakes step that
this tool deliberately does not handle — you must run it yourself,
independently of the tool and the AI skill. `tishift-heatwave load` prints a
notice to that effect and exits non-zero (2), and the skill's Phase 5 will
not walk you through these commands either. Run the steps below manually,
following your organization's change-control process.

The strategy matrix in `references/load-strategies.md` picks by target tier
and data size:

| Tier | Export | Import |
|---|---|---|
| Starter | Dumpling → CSV | `ticloud serverless import start` |
| Essential | Dumpling → SQL/CSV | Direct load |
| Dedicated | Dumpling → CSV | TiDB Lightning |

Notes:

- Export runs over the MySQL protocol — directly against the public TLS
  endpoint when the DB System has public accessibility enabled, otherwise
  through your SSH tunnel/bastion. AWS DMS does not apply to OCI-hosted sources.
- `ML_SCHEMA_%` schemas and Lakehouse tables are always excluded.
- `FLUSH TABLES WITH READ LOCK` is restricted on HeatWave; Dumpling falls back
  to per-table locking. Schedule the export during low traffic, or use continue replication
  (see sync-guide.md) to catch up changes made during export.
- TiFlash replica statements are inlined in `converted-schema.sql` right after
  each RAPID table's `CREATE TABLE`, so replicas exist before the import and
  TiFlash replicates during the load — this slows large imports. If import
  speed matters, remove the ALTERs from the schema file and run them after the
  load. Either way, wait for replicas to report AVAILABLE before running
  analytics.
