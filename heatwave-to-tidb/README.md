# heatwave-to-tidb

MySQL HeatWave → TiDB Cloud migration module for [TiShift](../README.md).

HeatWave is MySQL 8.0/8.4/9.x under the hood, so core compatibility with TiDB is high.
This module focuses on the HeatWave-specific surface:

- **RAPID analytics offload** (`SECONDARY_ENGINE=RAPID`) → mapped to **TiFlash replicas**
- **RAPID_COLUMN comment hints without a SECONDARY_ENGINE clause** (common once a dump
  tool strips table options) → same TiFlash replica, flagged for live-system verification
- **FULLTEXT indexes** (parse-only outside Starter) → same TiFlash replica, so columnar
  scans can accelerate `LIKE`/`REGEXP` filtering in place of the missing index; `MATCH
  ... AGAINST` still needs an application-side rewrite
- **Lakehouse external tables** → blocker; data lives in Object Storage, must be materialized
- **AutoML / GenAI** (`ML_SCHEMA_*`, `sys.ML_*` routines) → blocker; re-host models externally
- **VECTOR columns** (MySQL 9) → TiDB Cloud `VECTOR` with index-syntax rework
- **JavaScript (MLE) stored programs** → application-code stubs
- Standard MySQL gaps (stored procedures, triggers, events, spatial, 0900 collations)

## How it works

The migration runs as seven phases, the same sequence a DBA would follow by
hand. Each phase reads the previous phase's output and produces its own
artifact (report, converted SQL, etc.) you can inspect before moving on —
nothing downstream runs silently on your behalf.

| Phase | What happens | Automated by |
|---|---|---|
| 1. Connect | Verify source (HeatWave) and target (TiDB) are reachable over TLS; detect whether a RAPID cluster is attached | Manual (`mysql -e ...`) or the AI skill |
| 2. Scan | Inventory the schema and HeatWave-specific feature usage: RAPID-offloaded tables, Lakehouse external tables, AutoML schemas, VECTOR/spatial columns, FULLTEXT indexes, JS (MLE) routines, and — if continue-replication is planned — binlog readiness | `tishift-heatwave scan` |
| 3. Assess & Score | Apply the compatibility rule set (`references/compatibility-rules.md`) and compute a 0-100 readiness score with blockers/warnings broken out by category | `tishift-heatwave scan` (same command as Scan) |
| 4. Convert | Rewrite HeatWave-only DDL into TiDB-compatible DDL — unsupported clauses become `TISHIFT-REMOVED` comments (nothing is deleted), and every RAPID/FULLTEXT table gets an inline `ALTER TABLE ... SET TIFLASH REPLICA` | `tishift-heatwave convert` |
| 5. Load | Export data from HeatWave (Dumpling) and import into TiDB via the tier-appropriate path (`ticloud` import, direct load, or Lightning) | **Not automated — intentionally manual.** See [`docs/load-guide.md`](docs/load-guide.md) |
| 6. Validate | Compare row counts, column structure, and checksums between source and target; confirm TiFlash replicas report `AVAILABLE=1` | Manual or the AI skill |
| 7. Continue-replication sync & cutover *(optional — Essential/Dedicated)* | Grant DM users, run the valid-index precheck, create a DM task in the TiDB Cloud Console off the HeatWave binlog, monitor lag to zero | Manual (Console + prechecks); **cutover itself — stopping writes and repointing the application — is always your decision, never automated** |

Load and cutover are the two highest-stakes, least-reversible steps in any
migration, so this tool deliberately keeps a human in the loop for both
rather than scripting them.

## Prerequisites — prepare these before you start

- **Network path to the HeatWave DB System.** Public-accessibility DB Systems
  connect directly over TLS (your client IP must be in the allowed range);
  VCN-private DB Systems need an SSH tunnel through an OCI Bastion session, a
  compute jump host in the same VCN, or a site-to-site VPN.
- **The HeatWave instance CA certificate.** TLS is mandatory on HeatWave, not
  optional. Download it from OCI Console → DB System → Connect, or extract it
  with `openssl s_client -connect <host>:3306 -starttls mysql -showcerts`.
- **A source MySQL user** with `SELECT` on the schemas to migrate, plus read
  access to `information_schema` and `performance_schema` (needed to detect
  RAPID offload). Add `REPLICATION SLAVE, REPLICATION CLIENT` if
  continue-replication sync (Phase 7) is planned.
- **A target TiDB Cloud cluster (or self-hosted TiDB) and a tier decision** —
  Starter (free, cutover-only), Essential (autoscaling + DM continue
  replication), or Dedicated (full HTAP, Lightning, DM, PCI-DSS/SOC 2). Set it
  once as `target.tier` in your config file; it drives the load strategy,
  whether Phase 7 is available, and the tier `convert` targets by default.
- **If continue-replication (Phase 7) is planned**, the source also needs:
  `log_bin=ON`, `binlog_format=ROW`, `binlog_row_image=FULL`,
  `binlog_expire_logs_seconds ≥ 86400` (604800 recommended),
  `binlog_transaction_compression=OFF`, and `binlog_row_value_options=''`
  (not `PARTIAL_JSON`). `scan --continue-replication` checks all of these for
  you — see [`docs/sync-guide.md`](docs/sync-guide.md).
- **Python 3.10+** for the CLI toolkit, and `tiup` (Dumpling) for the manual
  load phase.

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

### DDL cleanup rules (convert phase)

| Rule | Trigger | Action |
|---|---|---|
| HW-DDL-1 | `SECONDARY_ENGINE=RAPID` table option | Comment out; emit a TiFlash replica ALTER |
| HW-DDL-2 | `SECONDARY_LOAD=...` option / standalone `ALTER ... SECONDARY_LOAD\|UNLOAD` | Comment out — TiFlash replication is automatic once the replica exists |
| HW-DDL-3 | `CLUSTERING BY (...)` | Comment out + a `TISHIFT-REVIEW` alternative (secondary index, or clustered PK) |
| HW-DDL-4 | `COMMENT 'RAPID_COLUMN=...'` column comment | Kept as-is — harmless on TiDB |
| HW-DDL-5 | RAPID_COLUMN hints with **no** SECONDARY_ENGINE clause (dumps often strip table options) | Emit a TiFlash replica ALTER + `TISHIFT-REVIEW`, flagged to confirm RAPID offload status on the live system |
| HW-DDL-6 | `FULLTEXT KEY/INDEX` (WARNING-2: parse-only outside Starter) | Emit a TiFlash replica ALTER + `TISHIFT-REVIEW` — columnar scans accelerate `LIKE`/`REGEXP` filtering; `MATCH ... AGAINST` still needs an application-side rewrite |

Every removed clause becomes a plain `/* TISHIFT-REMOVED [rule-id]: ... */` or
`-- TISHIFT-REMOVED [rule-id]: ...` comment — nothing is deleted, and the
conversion is idempotent (re-running `convert` on its own output is a no-op).
See [`references/compatibility-rules.md`](references/compatibility-rules.md)
for the full BLOCKER-\*/WARNING-\*/HW-\* rule set applied by `scan`.

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
# Edit with your HeatWave and TiDB credentials, and set target.tier to the
# TiDB Cloud tier you're migrating to (essential by default — see config comments).
# Public-endpoint DB Systems connect directly over TLS; VCN-private ones
# need an SSH tunnel or OCI Bastion session (see config comments).

# Scan and assess — pass --continue-replication if DM sync (Phase 7) is planned
tishift-heatwave scan --config tishift-heatwave.yaml --continue-replication --format cli --format json --format md

# Convert schema — HeatWave-only clauses become TISHIFT-REMOVED comments
# (auditable, nothing deleted); every RAPID table (explicit SECONDARY_ENGINE,
# RAPID_COLUMN comment hints, or a FULLTEXT index) gets an inline
# ALTER TABLE ... SET TIFLASH REPLICA right after its CREATE TABLE.
# --tier defaults to target.tier from --config; pass --tier to override it.
tishift-heatwave convert --config tishift-heatwave.yaml --ddl-file schema.sql

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
tishift-heatwave convert --config tishift-heatwave.yaml --ddl-file schema.sql
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
│   ├── core/scan/              Schema collectors, HeatWave detection, analyzers, reporters — implemented
│   ├── core/convert/           DDL transform, TiFlash emission, code stubs — implemented
│   ├── core/load/              Scope docstring only — CLI stub exits non-zero, see docs/load-guide.md
│   ├── core/check/             Scope docstring only — CLI stub exits non-zero, see docs/check-guide.md
│   ├── core/sync/              Scope docstring only — CLI stub exits non-zero, see docs/sync-guide.md
│   └── rules/                  Type mapping, compatibility rules, DDL cleanup rules, scoring
└── tests/                      Unit tests (offline, fixture-driven)
```

## Tests

```bash
pytest tests -q
```
