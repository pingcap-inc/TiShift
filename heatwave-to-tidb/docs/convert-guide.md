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
| HW-DDL-1 | `SECONDARY_ENGINE=RAPID` | 🔵 info | `/* TISHIFT-REMOVED ... */` + TiFlash replica emitted (TiFlash fully replaces the RAPID offload) | ✅ yes |
| HW-DDL-2 | `SECONDARY_LOAD=...` (option or `ALTER ... SECONDARY_LOAD` statement) | 🔵 info | commented out in place / whole statement to `--` line comment (TiFlash replication is automatic) | ✅ yes |
| HW-DDL-3 | `CLUSTERING BY (...)` | 🟠 needs assessment | commented out + `/* TISHIFT-REVIEW ... */` suggestion; listed in the manual-review section | ⚠️ partial |
| HW-DDL-4 | `COMMENT 'RAPID_COLUMN=...'` | 🟢 harmless | kept as-is, reported only | ❌ not needed |
| HW-DDL-5 | RAPID_COLUMN hints with **no** SECONDARY_ENGINE clause (dumps often strip table options) | 🟠 needs assessment | TiFlash replica emitted + `/* TISHIFT-REVIEW ... */` — likely RAPID-offloaded, verify on the live system | ⚠️ partial |
| HW-DDL-6 | `FULLTEXT KEY/INDEX` (WARNING-2: parse-only outside Starter) | 🟠 needs assessment | FULLTEXT clause kept as-is; TiFlash replica emitted + `/* TISHIFT-REVIEW ... */` — columnar scans accelerate `LIKE`/`REGEXP` filtering in place of the missing index; `MATCH ... AGAINST` still needs rewriting | ⚠️ partial |

Only plain `/* */` and `--` comments are emitted (never `/*! */` or `/*T! */`).
If a removed clause contains `*/`, the engine degrades to a `--` line comment.
The cleanup is idempotent — re-running on converted output changes nothing.

Every modified statement is re-parsed (sqlglot, MySQL dialect) to verify the
cleanup left valid syntax; failures are reported and the command exits non-zero.

## TiFlash replicas (inline)

Three independent triggers each emit `ALTER TABLE ... SET TIFLASH REPLICA n`
placed **immediately after the table's `CREATE TABLE`** in
`converted-schema.sql` (`--tiflash-replicas`, default 2) — a table hit by more
than one still gets exactly one ALTER, with a review comment per rule that fired:

1. **HW-DDL-1** — explicit `SECONDARY_ENGINE=RAPID`
2. **HW-DDL-5** — RAPID_COLUMN comment hints with no SECONDARY_ENGINE clause (likely RAPID-offloaded; dumps often strip table options)
3. **HW-DDL-6** — a `FULLTEXT` index (WARNING-2: parse-only outside Starter; the replica lets TiFlash accelerate scan-based full-text filtering in its place)

Replica statements are emitted on every tier — TiDB Cloud Starter/Serverless
supports TiFlash replicas too. Only `--tiflash-replicas 0` downgrades every
ALTER to an informational comment.

Trade-off: the replica exists before data load, so TiFlash replicates during
the import, which slows large loads. If import speed matters, move the ALTERs
after the load window.

## Outputs

- `converted-schema.sql` — cleaned DDL with TISHIFT-REMOVED comments and inline TiFlash statements
- `ddl-cleanup-report.json` / `ddl-cleanup-report.md` — per-table findings, manual-review checklist, parse errors

Display rule for the rule-summary table (Markdown report and CLI output):
rules with zero hits are hidden while at least one rule matched; when nothing
matched at all, every rule is shown with 0 hits as evidence of what was
checked. The JSON report always contains the full rule set.

## Planned (not yet implemented)

Spatial→JSON conversion, VECTOR index rewriting, unsupported-charset
conversion (BLOCKER-8), case-colliding table renames (BLOCKER-9), column-level
`NOT SECONDARY` stripping, and code stubs for stored procedures / triggers /
events / MLE routines — see `references/type-mapping.md` for the target
behavior. Do these manually (or via the AI skill) until they land in the CLI.

**`NOT SECONDARY` will currently break `convert`.** It's not valid
standalone MySQL/TiDB column syntax, and the DDL cleaner does not strip it
yet — a `CREATE TABLE` carrying it fails the post-cleanup sqlglot re-parse
and the command exits non-zero (see the parse-errors section of the report).
Remove it from the DDL by hand before running convert.
