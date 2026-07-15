# Sync Guide

**Status: `tishift-heatwave sync` is not implemented yet.** It currently
prints a pointer to this guide and exits non-zero (2) — see
`_not_implemented` in `tishift_heatwave/cli.py`. Run the SQL prechecks below
manually (or via the AI skill) until the command is automated.

Continue replication from HeatWave to TiDB runs on **TiDB DM**, configured and executed as a
migration task in the **TiDB Cloud console** — not by this tool. Available on
Essential/Dedicated targets only; Starter is cutover-only.

`tishift-heatwave sync` (and this guide) will only ever cover the
**prechecks**: the grants, binlog settings, and schema checks that must be
verified on the source and target *before* creating the DM task in the
console, plus the values to enter when configuring that task
(`block-allow-list`, scope). It will not create, start, stop, or monitor the
DM task itself — do that in the TiDB Cloud console, which has its own task
lifecycle, lag monitoring, and precheck UI. Treat everything below as inputs
to that console workflow, not as a substitute for it.

## Preflight

### Binlog configuration precheck

Run once against the source:

```sql
SHOW VARIABLES WHERE Variable_name IN
('log_bin','server_id','binlog_format','binlog_row_image',
'binlog_expire_logs_seconds','expire_logs_days','binlog_transaction_compression',
'binlog_row_value_options');
```

| Configuration | Required value | Why |
|---|---|---|
| `log_bin` | ON | Enables binary logging, which DM uses to replicate changes to TiDB |
| `binlog_format` | ROW | Captures all data changes accurately (other formats miss edge cases) |
| `binlog_row_image` | FULL | Includes all column values in events for safe conflict resolution |
| `binlog_expire_logs_seconds` | ≥ 86400 (1 day, hard minimum), 604800 (7 days, recommended) | Ensures DM can access consecutive logs during migration |
| `binlog_transaction_compression` | OFF | DM does not support transaction compression |
| `binlog_row_value_options` | `''` (empty, not PARTIAL_JSON) | DM cannot parse partial-JSON binlog rows — silent replication corruption on JSON columns. Clear with `SET GLOBAL binlog_row_value_options = '';` (invalidates previously captured binlog positions) |

`server_id` and `expire_logs_days` are returned by the same query but have no
required value: confirm `server_id` is non-zero (0 silently disables binary
logging rather than failing cleanly), and treat `expire_logs_days` as
informational — it's the legacy pre-8.0 retention setting, superseded by
`binlog_expire_logs_seconds` on MySQL 8.0+/HeatWave.

This precheck is implemented and unit-tested — not just documentation:
`tishift_heatwave/core/scan/analyzers/binlog_check.py` (rule IDs
HW-WARNING-4, HW-WARNING-6..9), collector in
`tishift_heatwave/core/scan/collectors/binlog.py`, tests in `tests/test_scan/`.

- `gtid_mode = ON`
- `binlog_row_value_options` must be **empty**. HeatWave DB Systems can default
  this to `PARTIAL_JSON`, which DM cannot parse — leaving it set causes silent
  replication corruption on JSON columns rather than a clean failure. Disable
  it before starting sync, and re-check afterward:
  ```sql
  SET GLOBAL binlog_row_value_options = '';
  SELECT @@binlog_row_value_options;  -- must return empty
  ```
  **This frequently fails on OCI-managed HeatWave** — even migration accounts
  with broad DDL/DML grants typically lack `SUPER`/`SYSTEM_VARIABLES_ADMIN`,
  so the `SET GLOBAL` above (and the equivalent for
  `binlog_expire_logs_seconds`) can return `ERROR 1227 (42000): Access
  denied; you need (at least one of) the SUPER or SYSTEM_VARIABLES_ADMIN
  privilege(s)`. When that happens, these are DB System configuration
  parameters, not SQL-settable from a client connection — fix them via **OCI
  Console → DB System → Configuration** instead, then re-run the query above
  (or `tishift-heatwave scan --continue-replication`) to confirm the change
  took effect.
- Migration user holds `REPLICATION SLAVE, REPLICATION CLIENT` plus `SELECT`
  on each business schema (see below)
- Source TLS is mandatory — DM's connection to HeatWave requires the instance
  CA certificate, same as scan/load
- DM workers (or the TiDB Cloud DM service) can reach the DB System through
  the same tunnel/VPN as scan/load

## Migration user privileges

DM's precheck validates replication access, schema read access on the
source, and DDL/DML access on the target — all three are checked
independently and any one being wrong fails the precheck.

### Source (HeatWave)

Replication grants are instance-wide (binlog access is not schema-scoped in
MySQL); `SELECT` must be granted per business schema, repeated for each
schema in the migration scope:

```sql
GRANT REPLICATION SLAVE, REPLICATION CLIENT ON *.* TO '$DM_USER'@'%';
GRANT SELECT ON `$DB`.* TO '$DM_USER'@'%';
-- repeat the SELECT grant for every additional business schema in scope
```

Missing the `SELECT` grant on a business schema is a common cause of DM
precheck failures that look unrelated (e.g. reported as a generic permission
or table-access error rather than naming the missing grant directly).

### Target (TiDB)

DM needs to create/alter tables and apply row changes on the target, so the
target user needs both DDL and DML privileges:

```sql
GRANT CREATE, SELECT, INSERT, UPDATE, DELETE, ALTER, DROP, INDEX ON *.* TO 'dm_target_user'@'%';
```

## Valid indexes precheck

Implemented as code: `tishift_heatwave/core/scan/collectors/valid_indexes.py`
(`fetch_tables_without_valid_index`), tested in
`tests/test_scan/test_valid_indexes_collector.py`; its result count feeds the
Cutover & continue replication scoring category (`references/scoring.md`).

DM needs a primary key or unique index on every table to apply row changes
deterministically. Tables without one can replicate incorrectly or fail
outright, so check for them before starting sync — and re-run this after any
schema change during the migration window:

```sql
SELECT
    t.table_name,
    t.table_schema
FROM
    information_schema.tables AS t
WHERE
    (t.table_schema, t.table_name) NOT IN (
        SELECT
            s.table_schema,
            s.table_name
        FROM
            information_schema.statistics AS s
        WHERE
            s.NON_UNIQUE = 0
        GROUP BY
            s.table_schema,
            s.table_name
    )
    AND t.table_schema NOT IN (
        'mysql', 'performance_schema', 'information_schema', 'sys',
        'mysql_autopilot', 'mysql_audit', 'mysql_tasks'
    )
    AND t.table_schema NOT LIKE 'ML\_SCHEMA\_%'
    AND t.table_type = 'BASE TABLE';
```

The schema exclusion list must cover **every non-business database on the
HeatWave instance** — extend the `NOT IN` list (and the `NOT LIKE` pattern)
to match the actual system/management schemas present on your DB System; the
values above (`mysql_autopilot`, `mysql_audit`, `mysql_tasks`, `ML_SCHEMA_%`)
are the ones this module already knows about, not an exhaustive list for
every environment. Any row returned is a business table missing a PK/UNIQUE
index — add one, or explicitly exclude the table from the DM task and
document why that's safe.

## Scope the task to business schemas

When configuring the DM task **in the TiDB Cloud console**, do **not** select
"All Objects." Use an explicit `block-allow-list` (`do-dbs` / `ignore-dbs`) so
only business schemas replicate and HeatWave/MySQL system and management
schemas are excluded:

```yaml
block-allow-list:
  instance:
    do-dbs: ["business_db", "test_db"]
    ignore-dbs: ["mysql_autopilot", "mysql_audit", "mysql_tasks"]
```

- `do-dbs` — the business schema(s) being migrated (the `$DB` used throughout scan/convert/load)
- `ignore-dbs` — HeatWave-managed schemas that must never replicate:
  `mysql_autopilot`, `mysql_audit`, `mysql_tasks`, plus standard MySQL system
  schemas (`mysql`, `sys`, `information_schema`, `performance_schema`) and any
  `ML_SCHEMA_%` AutoML schema (HW-BLOCKER-2 — no TiDB equivalent)

Selecting "All Objects" instead of an explicit list either fails the task
outright on these schemas or pulls in objects that have no place on the target.

**This scoping is database-level only.** `do-dbs`/`ignore-dbs` cannot exclude
a single table within an in-scope database. If the convert phase deliberately
left a table out of migration scope (e.g. a smoke-test table), DM will still
replicate it alongside everything else in that database once the task
starts, auto-creating it on the target with TiDB-native DDL. Usually harmless
if the table is empty or irrelevant, but it's schema drift the tool didn't
originate — `tishift-heatwave check` (or a manual diff) won't catch it unless
you compare the **full** table list on both sides, not just the tables that
were actually converted, once after the DM task starts syncing.

**DM task creation is console-only for Essential/Dedicated — there is no CLI
path.** The `ticloud` CLI only manages Serverless clusters
(`ticloud serverless ...`); it has no Essential/Dedicated DM task commands.
Everything in this section produces values to paste into the console's
task-creation form, not something scriptable end-to-end.

## Validating a DM task before trusting it for cutover (optional)

Once the task is running and shows lag approaching zero, don't take that as
sufficient proof it's replicating correctly — verify with real data moving
through it. Insert a small batch of clearly-tagged synthetic rows into the
source in FK-safe order (parents before children — e.g. reference/lookup
tables, then top-level entities, then their dependents), using a prefix like
`TISHIFT_TEST_` on name columns and `TT-*` on unique codes so they're
trivially identifiable. Then re-run the row-count and checksum queries from
`tishift-heatwave check` (or `docs/check-guide.md`) on both sides — matching
row counts alone isn't sufficient proof of correct replication, checksums
confirm content, not just totals. Delete the tagged rows from both sides once
satisfied; never leave synthetic data in place through a real cutover.

## Foreign keys: precheck warnings are expected

TiDB Cloud DM's precheck reports FK-related warnings against HeatWave
sources. In practice, migrations proceed and replicate successfully with
these warnings present — the warning itself is not the risk. Before
dismissing it, confirm every item on the:

### FK Pre-upgrade Checklist

- [ ] All FK-related parent and child tables are included in the task
- [ ] Any tables excluded from the task are confirmed not part of a required FK relationship
- [ ] Target TiDB schemas, tables, FK constraints, charset, and collation are already prepared and match source
- [ ] No PK/UK updates are expected on the source during replication
- [ ] No DDL or FK constraint changes are expected on the source during replication

If any item is unchecked, resolve it first — an unmet checklist item, not the
FK warning, is what causes replication problems.

**Notify PingCAP in advance of the planned cutover window** so the relevant
team is aligned and available if support or rollback assistance is needed.

## Running the prechecks

```bash
tishift-heatwave sync --config tishift-heatwave.yaml
```

Today this prints the "not implemented yet" notice above — run the binlog
precheck (`tishift-heatwave scan --continue-replication`, which already
covers HW-WARNING-4/6..9) and the valid-indexes SQL from this guide by hand
instead. Once automated, `sync` will run the grant, binlog, and
valid-indexes checks above against the source/target and print a pass/fail
summary — it will not create, start, stop, or otherwise touch a DM task.
Once every check passes, create the actual migration task in the **TiDB
Cloud console**: point it at the HeatWave source, apply the
`block-allow-list` from above, and use the console's own precheck step
(which is where the FK warnings in the previous section will show up), then
its lag monitor and task controls to run and observe replication. There is
nothing further to run from this CLI for the sync itself.

## Cutover

1. In the TiDB Cloud console, monitor DM replication lag until it approaches zero
2. Stop writes on HeatWave (application maintenance window)
3. Wait for lag = 0, verify with `tishift-heatwave check`
4. Repoint the application to TiDB
5. Keep HeatWave read-only for the agreed rollback window
6. Stop/remove the DM task in the console once cutover is confirmed and the rollback window has passed

**Executing this is a decision for the user (or their TiDB account team), not
this tool or the AI skill.** The steps above are reference, not something to
run or walk through live — the skill's job ends at a created, verified,
healthy DM task (grants confirmed, valid-indexes precheck passed, FK
checklist confirmed, sync spot-checked per "Validating a DM task" above).
Same posture as the load phase: high-stakes, deliberately left to the user
to perform and confirm independently.

## Preflight checklist (before creating the DM task in the console)

- [ ] Binlog configuration precheck passes: `log_bin=ON`, `binlog_format=ROW`,
  `binlog_row_image=FULL`, `binlog_transaction_compression=OFF`,
  `binlog_expire_logs_seconds ≥ 86400` (604800 recommended)
- [ ] Source and target users granted per "Migration user privileges" above
- [ ] Valid-indexes precheck returns no rows (or all flagged tables are explicitly excluded and documented)
- [ ] `block-allow-list` values ready to enter in the console (`do-dbs` / `ignore-dbs`), not "All Objects"
- [ ] `binlog_row_value_options` empty, `gtid_mode=ON`, source TLS configured
- [ ] FK Pre-upgrade Checklist items all checked
- [ ] PingCAP notified of the cutover window
