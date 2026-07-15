# Load Strategies — MySQL HeatWave → TiDB

**The load phase is intentionally not automated** — it is a high-stakes step
that must be executed independently by the user; the CLI (`tishift-heatwave
load`) and the AI skill both refuse to run it. The strategies below are the
manual playbook.

Every strategy starts by establishing a network path. DB Systems with public
accessibility enabled are reached directly over TLS (restricted to allowed IP
ranges); VCN-private DB Systems need an SSH tunnel through an OCI Bastion
session, a compute jump host in the same VCN, or a site-to-site VPN. AWS DMS
is not applicable to OCI-hosted sources; export always runs over the MySQL
protocol.

## Decision matrix

| Target tier | Export | Import | When |
|---|---|---|---|
| Starter | Dumpling → CSV | `ticloud serverless import start` | ≤ 25 GiB, cutover-only |
| Essential | Dumpling → SQL/CSV | Direct load (`mysql` / LOAD DATA) | Up to ~100 GiB, continue-replication follow-up via DM |
| Dedicated | Dumpling → CSV to object storage | TiDB Lightning (physical mode) | Large datasets, fastest path |
| Any (small) | Dumpling → SQL | Direct replay | < 5 GiB, simplest |

## Strategy details

### 1. Dumpling export (all strategies)

Dumpling speaks plain MySQL protocol and works against HeatWave through the tunnel:

```bash
ssh -f -N -L 3306:<heatwave-private-ip>:3306 opc@<bastion>
tiup dumpling -h 127.0.0.1 -P 3306 -u admin -p "$TISHIFT_SOURCE_PASSWORD" \
  --filetype csv -o ./dump --filter 'myapp.*' \
  --consistency lock -t 8 -r 200000 -F 256MiB
```

- `--consistency lock` (FLUSH TABLES WITH READ LOCK is restricted on HeatWave;
  Dumpling falls back to per-table locking — schedule during low traffic).
- Exclude `ML_SCHEMA_%` schemas (AutoML model catalogs) and any Lakehouse
  external tables (HW-BLOCKER-1) — their data is not in InnoDB.

### 2. ticloud import (Starter)

```bash
ticloud serverless import start \
  --cluster-id $TIDB_CLOUD_CLUSTER_ID \
  --source-type LOCAL --local.target-database myapp \
  --file-type CSV ./dump/myapp.orders.000000000.csv
```

### 3. Direct load (Essential / small datasets)

Replay Dumpling SQL output through mysql client, or LOAD DATA LOCAL INFILE for CSV.

### 4. TiDB Lightning (Dedicated / self-hosted)

Point Lightning at the Dumpling output directory; physical import mode for speed.

### Alternative export: MySQL Shell to Object Storage

`util.dumpSchemas()` with `osBucketName` writes directly to OCI Object Storage
without a local staging disk. Lightning cannot read the MySQL Shell dump format
directly — use `util.exportTable()` (CSV) per table, or prefer Dumpling.

## TiFlash replicas for RAPID tables

`convert` inlines `ALTER TABLE ... SET TIFLASH REPLICA n` immediately after
each RAPID table's `CREATE TABLE` in `converted-schema.sql`, so analytics
queries that previously offloaded to the HeatWave cluster run on TiFlash.

Because the replica exists before data load, TiFlash replicates during the
import, which slows large loads. If import speed matters, move the ALTERs to
after the load window. Check progress with:

```sql
SELECT * FROM information_schema.tiflash_replica WHERE TABLE_SCHEMA = 'myapp';
```
