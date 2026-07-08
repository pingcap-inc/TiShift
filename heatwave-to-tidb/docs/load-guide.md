# Load Guide

**Status: not implemented yet.** `tishift-heatwave load` currently prints a
pointer to this guide and exits non-zero (2) — see `_not_implemented` in
`tishift_heatwave/cli.py`. Run the steps below manually (or via the AI skill,
which issues them one command at a time) until the command is automated.

Once implemented, `tishift-heatwave load` will transfer data using the
strategy matrix in `references/load-strategies.md`.

`--strategy auto` picks by target tier and data size:

| Tier | Export | Import |
|---|---|---|
| Starter | Dumpling → CSV | `ticloud serverless import start` |
| Essential | Dumpling → SQL/CSV | Direct load |
| Dedicated | Dumpling → CSV | TiDB Lightning |

Notes:

- Export runs over the MySQL protocol through your SSH tunnel/bastion —
  HeatWave DB Systems have no public endpoint and AWS DMS does not apply.
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
