---
name: oceanbase-to-tidb-migration
description: >
  Migrate from OceanBase to TiDB — assess readiness, convert schema, load data,
  validate. Use when someone mentions migrating from OceanBase to TiDB, assessing
  OceanBase compatibility, or planning an OceanBase to TiDB migration.
metadata:
  version: 0.1.0
---

# OceanBase to TiDB Migration

Step-by-step instructions to execute. One command at a time.

## Execution Rules

- **One command per step.** Output a single command, wait for output.
- **OceanBase uses MySQL protocol.** Connect via: `mysql -h $OB_HOST -P 2881 -u $OB_USER -D $DB -e "SQL"`
- **TiDB uses MySQL protocol.** Connect via: `mysql -h $HOST -P $PORT -u $USER -e "SQL"`
- **Port 2881** is OBProxy default (not 3306).
- **Tenant-qualified usernames**: `user@tenant_name` — the `@tenant` suffix is required for multi-tenant OceanBase.
- **Never put passwords on the command line.** Use `MYSQL_PWD` env var instead:
  ```
  export OB_USER="admin@sys"
  export MYSQL_PWD="ob_password"    # mysql client reads this automatically
  ```
  For TiDB target, set `MYSQL_PWD` before running target commands (or use separate env var and switch).

---

## Phase 0: Prerequisites

1. **MySQL client** installed (connects to both OceanBase and TiDB)
2. **TiDB Cloud tier** — Starter / Essential / Dedicated
3. **OceanBase credentials** — host, port (2881), user, tenant, password

---

## Phase 1: Connect & Detect Mode

**Step 1.1 — Test source + detect mode:**
```
mysql -h $OB_HOST -P 2881 -u $OB_USER  -e "SELECT ob_version(); SHOW VARIABLES LIKE 'ob_compatibility_mode'"
```
WAIT for output. Record:
- `$OB_VERSION` from `ob_version()`
- `$OB_MODE` from `ob_compatibility_mode` (MYSQL or ORACLE)

**Step 1.2 — Test target:**
```
mysql -h $TARGET_HOST -P $TARGET_PORT -u $TARGET_USER -e "SELECT VERSION()"
```

### STOP AND CHECK — Phase 1
- [ ] Source shows OceanBase version
- [ ] Mode detected: MYSQL or ORACLE
- [ ] Target shows TiDB version
- **If ORACLE mode**: warn that this requires full Oracle dialect conversion (type mapping, PL/SQL rewrite, CONNECT BY, ROWNUM). Significantly more effort than MySQL mode.

---

## Phase 2: Scan

### MySQL Mode Steps

**Step 2.1–2.10**: Standard MySQL `information_schema` queries (same as Aurora variant):
- 2.1: Tables, 2.2: Columns, 2.3: Indexes, 2.4: FKs, 2.5: Procedures, 2.6: Triggers, 2.7: Views, 2.8: Charset/collation, 2.9: Data profile, 2.10: Server metadata

**Step 2.11 — OceanBase-specific extensions:**
```
mysql -h $OB_HOST -P 2881 -u $OB_USER  -D $DB -e "SHOW CREATE TABLE $TABLE"
```
Run for each table. Parse output for:
- `TABLEGROUP = '...'`
- `PRIMARY_ZONE = '...'`
- `LOCALITY = '...'`

### Oracle Mode Steps

Use Oracle-compatible queries against `information_schema` or `DBA_*` views (same pattern as Oracle variant Phase 2).

### STOP AND CHECK — Phase 2
- [ ] All steps executed
- [ ] At least 1 table found
- [ ] OB-specific extensions detected and noted

---

## Phase 2.5: Checklist

Build the checklist from scan output. Key OB-specific fields:

```
CHECKLIST:
  ob_mode                = <MYSQL or ORACLE>
  ob_version             = <from Phase 1>
  table_count            = ...
  has_tablegroups        = <TRUE if any TABLEGROUP found>
  has_primary_zone       = <TRUE if any PRIMARY_ZONE found>
  has_locality           = <TRUE if any LOCALITY found>
  has_resource_units     = <TRUE if resource DDL found>
  has_global_indexes     = <TRUE if global index found>
  cdc_not_available      = <TRUE — OB does not produce MySQL binlog>
  collation_mismatch     = <TRUE if OB collation differs from TiDB target>
  // ... standard fields (table_count, proc_count, etc.)
  // Oracle-mode additional: package_count, has_connect_by, has_rownum, etc.
```

---

## Phase 3: Assess Compatibility

Load `references/compatibility-rules.md`. Apply rules based on `ob_mode`.

---

## Phase 4: Score

Load `references/scoring.md`. Use mode-appropriate weights:
- **MySQL mode**: Schema 25, Proc 15, Query 20, Data 20, Ops 20
- **Oracle mode**: Schema 20, Proc 30, Query 20, Data 20, Ops 10

### Output

```
═══════════════════════════════════════════════════════════
  TiShift — Migration Readiness Report
═══════════════════════════════════════════════════════════

  Source: <host>:2881/<database>
  OceanBase Version: <version>
  Compatibility Mode: <MYSQL | ORACLE>
  Tables: N | Total Size: N.N GB

  READINESS SCORE
  ─────────────────────────────────────────────────────────
  Category                Score
  Schema Compatibility    NN/<25|20>
  Procedural Code         NN/<15|30>
  Query Compatibility     NN/20
  Data Complexity         NN/20
  Operational             NN/<20|10>
  ─────────────────────────────────────────────────────────
  Overall                 NN/100  (<rating>)

  WHAT NEEDS WORK
  ─────────────────────────────────────────────────────────
  <category name> (NN/MM):
    * <finding 1> — <action>
    * <finding 2> — <action>

  WHAT'S READY
  ─────────────────────────────────────────────────────────
  * <category>: NN/MM — <why it's ready>

  AUTOMATION COVERAGE
  ─────────────────────────────────────────────────────────
  Automated:    NN% — <what's automated>
  AI-assisted:  NN% — <what needs review>
  Manual:       NN% — <what requires human design>
═══════════════════════════════════════════════════════════
```

### STOP AND ASK — Continue?

Do NOT proceed without explicit user confirmation.

---

## Phase 5: Convert Schema

### MySQL Mode
1. **Strip OB extensions**: TABLEGROUP, PRIMARY_ZONE, LOCALITY, resource unit clauses, OB hints
2. **Types pass through** — near-1:1
3. **Verify**: ENGINE=InnoDB, CHARSET=utf8mb4, collation match

### Oracle Mode
Full Oracle conversion pipeline: type mapping (NUMBER→DECIMAL, VARCHAR2→VARCHAR, DATE→DATETIME), function mapping (NVL→COALESCE, DECODE→CASE, etc.), CONNECT BY→WITH RECURSIVE, ROWNUM→LIMIT, PL/SQL→app code stubs.

### Output Files
- `01-create-tables.sql`, `02-create-indexes.sql`, `03-create-views.sql`, `04-foreign-keys.sql`
- Oracle mode adds: `05-create-sequences.sql`, `06-conversion-notes.md`

---

## Phase 6: Load Data

**Small**: `mysqldump -h $OB_HOST -P 2881 -u $OB_USER -p dbname > dump.sql` then load into TiDB.
**Large**: OBDUMPER `--csv` parallel export → TiDB Lightning.
**No DMS** — AWS DMS does not support OceanBase.

---

## Phase 7: Validate

Standard MySQL protocol comparison on both sides. For Oracle mode, additionally verify DATE→DATETIME and NUMBER precision.

---

## Reference files

- `references/compatibility-rules.md`
- `references/scoring.md`
- `references/type-mapping.md` (MySQL mode)
- `references/type-mapping-oracle.md` (Oracle mode)
- `references/function-mapping.md` (Oracle mode)
