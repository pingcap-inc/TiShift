# heatwave-to-tidb

MySQL HeatWave → TiDB Cloud migration module for [TiShift](../README.md).

HeatWave is MySQL 8.0/8.4/9.x under the hood, so core compatibility with TiDB is high.
This module focuses on the HeatWave-specific surface:

- **RAPID analytics offload** (`SECONDARY_ENGINE=RAPID`) → mapped to **TiFlash replicas**
- **Lakehouse external tables** → blocker; data lives in Object Storage, must be materialized
- **AutoML / GenAI** (`ML_SCHEMA_*`, `sys.ML_*` routines) → blocker; re-host models externally
- **VECTOR columns** (MySQL 9) → TiDB Cloud `VECTOR` with index-syntax rework
- **JavaScript (MLE) stored programs** → application-code stubs
- Standard MySQL gaps (stored procedures, triggers, events, spatial, FULLTEXT, 0900 collations)

## Implementation status

`scan` and `convert` are implemented and unit-tested. `check` and `sync` are
documented but not yet automated — each prints a pointer to its guide
(`docs/check-guide.md`, `docs/sync-guide.md`) and exits non-zero; follow
those guides manually, or use the AI skill, which walks through the same
steps interactively.

`scan --continue-replication` additionally gates the binlog readiness rules
(`log_bin`, `binlog_format`, `binlog_row_image`, `binlog_expire_logs_seconds`,
`binlog_transaction_compression`, `binlog_row_value_options` — must be empty,
not PARTIAL_JSON) against the score and runs the valid-indexes precheck
(every business table needs a PK or unique index for TiDB DM).

`load` is **intentionally disabled**: data loading is a high-stakes step
this tool deliberately does not handle. Neither the CLI nor the AI skill
will run it — complete it independently by following `docs/load-guide.md`.

**Cutover execution is likewise out of this tool's scope.** The skill and CLI
stop at a verified, healthy DM continue-replication task — actually stopping
writes on the source and repointing the application is a decision for you
(or your TiDB account team) to make and execute, not something to automate
or walk through live here.

## AI skill

Open this project in an AI coding assistant and run:

```
/heatwave-to-tidb
```

The skill (`SKILL.md`) walks through Connect → Scan → Assess & Score →
Convert → Validate → optional continue-replication sync, one command at a
time. The Load phase is intentionally excluded — the skill pauses and asks
you to complete the data load independently before validation.

See [`docs/checklist.md`](docs/checklist.md) for every compatibility rule,
DDL cleanup rule, and precheck/attention tip across all phases in one place.

## CLI toolkit

```bash
cd heatwave-to-tidb
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'

cp config/tishift-heatwave.example.yaml tishift-heatwave.yaml
# Edit with your HeatWave and TiDB credentials.
# Public-endpoint DB Systems connect directly over TLS; VCN-private ones
# need an SSH tunnel or OCI Bastion session (see config comments).

# Scan and assess — pass --continue-replication if DM sync (Phase 7) is planned
tishift-heatwave scan --config tishift-heatwave.yaml --continue-replication --format cli --format json --format md

# Convert schema — HeatWave-only clauses become TISHIFT-REMOVED comments
# (auditable, nothing deleted); each RAPID table gets an inline
# ALTER TABLE ... SET TIFLASH REPLICA right after its CREATE TABLE
tishift-heatwave convert --ddl-file schema.sql --tier dedicated --dry-run

# Load is intentionally disabled (complete it independently per
# docs/load-guide.md); check is not automated yet — both print a notice
# and exit non-zero. Follow docs/check-guide.md (or the AI skill) by hand.
tishift-heatwave load --config tishift-heatwave.yaml --strategy auto
tishift-heatwave check --config tishift-heatwave.yaml
```

### Full command reference (a real end-to-end run)

Everything below is copy-pasteable against a real HeatWave source and TiDB target — the config-file-mode AI skill runs these directly rather than asking you to paste output back. `$SRC_*`/`$TGT_*` are read from your config file; substitute your own.

```bash
# --- Phase 1: Connect ---
mysql --ssl-mode=VERIFY_IDENTITY --ssl-ca="$SRC_CA" -h "$SRC_HOST" -P "$SRC_PORT" -u "$SRC_USER" --password="$SRC_PWD" -e "SELECT VERSION(), @@version_comment"
mysql --ssl-mode=VERIFY_IDENTITY --ssl-ca="$SRC_CA" -h "$SRC_HOST" -P "$SRC_PORT" -u "$SRC_USER" --password="$SRC_PWD" -e "SELECT COUNT(*) AS rapid_nodes FROM performance_schema.rpd_nodes"
mysql --ssl-mode=VERIFY_IDENTITY --ssl-ca="$TGT_CA" -h "$TGT_HOST" -P "$TGT_PORT" -u "$TGT_USER" --password="$TGT_PWD" -e "SELECT VERSION()"

# --- Phase 2/3: Scan & Assess ---
tishift-heatwave scan --config tishift-heatwave.yaml --continue-replication --format cli --format json --format md

# --- Phase 4: Extract DDL, convert, apply ---
# --raw is required — without it, mysql's batch mode escapes newlines as literal \n
mysql --ssl-mode=VERIFY_IDENTITY --ssl-ca="$SRC_CA" -h "$SRC_HOST" -P "$SRC_PORT" -u "$SRC_USER" --password="$SRC_PWD" --raw -e "SHOW CREATE TABLE $SRC_DB.<table>\G"
tishift-heatwave convert --ddl-file schema.sql --tier essential
# SHOW CREATE TABLE output isn't FK-topologically ordered — applying it straight
# can fail with "ERROR 1824: Failed to open the referenced table '<parent>'"
mysql --ssl-mode=VERIFY_IDENTITY --ssl-ca="$TGT_CA" -h "$TGT_HOST" -P "$TGT_PORT" -u "$TGT_USER" --password="$TGT_PWD" -e "SET FOREIGN_KEY_CHECKS=0; SOURCE tishift-reports/converted-schema.sql; SET FOREIGN_KEY_CHECKS=1;"
mysql --ssl-mode=VERIFY_IDENTITY --ssl-ca="$TGT_CA" -h "$TGT_HOST" -P "$TGT_PORT" -u "$TGT_USER" --password="$TGT_PWD" -e "SHOW TABLES FROM $TGT_DB"

# --- Phase 6: Validate ---
mysql ... -e "SELECT COUNT(*) FROM $DB.<table>"                                    # per table, both sides
mysql ... -e "SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, IS_NULLABLE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='$DB'"  # diff both sides
mysql ... -e "SELECT BIT_XOR(CRC32(CONCAT_WS('#', col1, col2, ...))) FROM $DB.<table>"  # per table, both sides
mysql ... -e "SELECT TABLE_NAME, AVAILABLE, PROGRESS FROM information_schema.tiflash_replica WHERE TABLE_SCHEMA='$DB'"

# --- Phase 7: Continue-replication prechecks ---
mysql ... -e "SHOW GRANTS FOR CURRENT_USER()"                                       # both sides — confirm DM grants already present
# valid-indexes precheck — see SKILL.md Step 7.1 for the full query
# DM task creation itself is TiDB Cloud Console-only for Essential/Dedicated —
# `ticloud` (the TiDB Cloud CLI) only manages Serverless clusters, not DM tasks.
```

**Gotchas found running this for real:**
- OCI-managed HeatWave accounts frequently lack `SUPER`/`SYSTEM_VARIABLES_ADMIN` even with broad grants, so `SET GLOBAL binlog_expire_logs_seconds=...` / `binlog_row_value_options=''` fails with `ERROR 1227`. Fix these two through **OCI Console → DB System → Configuration** instead, then re-run `scan --continue-replication` to confirm.
- A DM task's `block-allow-list` scopes at the **database** level (`do-dbs: [...]`), not per-table — a table you deliberately excluded from schema-convert (Phase 4) can still get replicated to the target alongside everything else in-scope. Diff `information_schema.TABLES` on both sides after the DM task starts syncing to catch this.
- Before trusting a DM task for real cutover, validate it end-to-end: insert a batch of clearly-tagged synthetic rows (e.g. `TISHIFT_TEST_%` names) into the source in FK-safe order, then re-run the Phase 6 row-count/checksum checks to confirm they replicated correctly — then delete them from both sides.

## Layout

```
heatwave-to-tidb/
├── SKILL.md                    AI skill (interactive migration guide)
├── references/                 Type mappings, compatibility rules, load strategies, scoring
├── config/                     Example YAML configuration
├── docs/                       Getting started + per-phase guides
├── sql/                        Sample schema exercising HeatWave features
├── tishift_heatwave/           Python CLI toolkit
│   ├── core/scan/              Schema collectors, HeatWave detection, analyzers, reporters
│   ├── core/convert/           DDL transform, TiFlash emission, code stubs
│   ├── core/load/              Dumpling, ticloud import, direct, Lightning
│   ├── core/check/             Row count, column, checksum validation
│   ├── core/sync/              Continue replication via TiDB DM (binlog replication)
│   └── rules/                  Type mapping, compatibility rules, scoring
└── tests/                      Unit tests (offline, fixture-driven)
```

## Tests

```bash
pytest tests -q
```
