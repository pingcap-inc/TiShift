# Convert Guide

`tishift-heatwave convert` turns HeatWave DDL into TiDB-compatible DDL:

```bash
tishift-heatwave convert --ddl-file schema.sql --tier dedicated
tishift-heatwave convert --ddl-file schema.sql --dry-run   # diff only
```

## Comment-preserving cleanup (HW-DDL rules)

HeatWave-only syntax is never deleted — it is converted to plain MySQL
comments so the original text stays auditable in the output:

| Rule | Syntax | Risk | Handling | Auto |
|---|---|---|---|---|
| HW-DDL-1 | `SECONDARY_ENGINE=RAPID` | 🔴 blocker | `/* TISHIFT-REMOVED ... */` + TiFlash replica emitted | ✅ yes |
| HW-DDL-2 | `SECONDARY_LOAD=...` (option or `ALTER ... SECONDARY_LOAD` statement) | 🔴 blocker | commented out in place / whole statement to `--` line comment | ✅ yes |
| HW-DDL-3 | `CLUSTERING BY (...)` | 🟠 needs assessment | commented out + `/* TISHIFT-REVIEW ... */` suggestion; listed in the manual-review section | ⚠️ partial |
| HW-DDL-4 | `COMMENT 'RAPID_COLUMN=...'` | 🟢 harmless | kept as-is, reported only | ❌ not needed |

Only plain `/* */` and `--` comments are emitted (never `/*! */` or `/*T! */`).
If a removed clause contains `*/`, the engine degrades to a `--` line comment.
The cleanup is idempotent — re-running on converted output changes nothing.

Every modified statement is re-parsed (sqlglot, MySQL dialect) to verify the
cleanup left valid syntax; failures are reported and the command exits non-zero.

## TiFlash replicas (inline)

Each RAPID table gets `ALTER TABLE ... SET TIFLASH REPLICA n` placed
**immediately after its `CREATE TABLE`** in `converted-schema.sql`
(`--tiflash-replicas`, default 2). Replica statements are emitted on every
tier — TiDB Cloud Starter/Serverless supports TiFlash replicas too. Only
`--tiflash-replicas 0` downgrades the ALTER to an informational comment.

Trade-off: the replica exists before data load, so TiFlash replicates during
the import, which slows large loads. If import speed matters, move the ALTERs
after the load window.

## Outputs

- `converted-schema.sql` — cleaned DDL with TISHIFT-REMOVED comments and inline TiFlash statements
- `ddl-cleanup-report.json` / `ddl-cleanup-report.md` — per-table findings, manual-review checklist, parse errors

## Planned (not yet implemented)

Spatial→JSON conversion, VECTOR index rewriting, unsupported-charset
conversion (BLOCKER-8), case-colliding table renames (BLOCKER-9), and code
stubs for stored procedures / triggers / events / MLE routines — see
`references/type-mapping.md` for the target behavior. Do these manually
(or via the AI skill) until they land in the CLI.
