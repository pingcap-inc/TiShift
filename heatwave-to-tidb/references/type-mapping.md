# Type Mapping — MySQL HeatWave → TiDB

HeatWave is MySQL under the hood and TiDB is MySQL-compatible, so nearly all
column types map 1:1. This file lists the identity mappings for completeness
and calls out the exceptions.

## Identity mappings (no change)

| HeatWave / MySQL | TiDB | Notes |
|---|---|---|
| TINYINT / SMALLINT / MEDIUMINT / INT / BIGINT (± UNSIGNED) | same | |
| DECIMAL(p,s), FLOAT, DOUBLE | same | |
| BIT(n) | same | |
| CHAR / VARCHAR | same | check collation, see below |
| TINYTEXT / TEXT / MEDIUMTEXT / LONGTEXT | same | |
| BINARY / VARBINARY / BLOB family | same | |
| DATE / TIME / DATETIME / TIMESTAMP / YEAR | same | TiDB TIMESTAMP range matches MySQL |
| ENUM / SET | same | |
| JSON | same | full JSON path support |
| Generated columns (VIRTUAL/STORED) | same | |

## Exceptions

| HeatWave / MySQL | TiDB | Rule |
|---|---|---|
| `VECTOR(n)` (MySQL 9) | `VECTOR(n)` on TiDB Cloud | Supported on Starter/Essential/Dedicated. Vector index syntax differs (`VECTOR INDEX ... USING HNSW`); distance functions must be re-verified. Self-hosted TiDB < v8.4: convert to `JSON` and flag |
| Spatial types (GEOMETRY, POINT, POLYGON, ...) | `JSON` + `COMMENT 'was: <type>'` | BLOCKER-4 — no spatial index support |
| Columns with `utf8mb4_0900_*` collation | Same collation, unchanged — `utf8mb4_0900_*` is supported natively on TiDB ≥ v7.4 (target TiDB Cloud is v8.5) | WARNING-4 — informational only, no readiness-score impact |
| Columns with a charset outside `ascii`/`latin1`/`binary`/`utf8`/`utf8mb4`/`gbk` | Convert to a supported charset (`utf8mb4` by default) — TiDB rejects the column outright, this isn't a degrade-gracefully case | BLOCKER-8 |
| `AUTO_INCREMENT` | `AUTO_INCREMENT` (non-sequential) or `AUTO_RANDOM` | WARNING-3 — AUTO_RANDOM recommended for high-insert PK-only tables; MySQL Compatibility Mode if strict sequential IDs are required |
| Updatable views (`IS_UPDATABLE='YES'`) | Views remain, but become read-only | WARNING-9 — redirect any write path through the view to the underlying table(s) |
| Table/database names differing only by case, when source `lower_case_table_names` ≠ 2 | Rename to remove the collision — TiDB Cloud is always `lower_case_table_names=2` | BLOCKER-9 (collision) / WARNING-8 (setting mismatch, no collision) |

## Table options

Removals are comment-preserving: the clause is converted to a plain
`/* TISHIFT-REMOVED [rule-id]: <original> */` (or `--` line) comment in the
output DDL so the original text stays auditable. See
`references/compatibility-rules.md` § DDL cleanup rules.

| HeatWave clause | TiDB action |
|---|---|
| `SECONDARY_ENGINE = RAPID` | HW-DDL-1 — comment out; emit `ALTER TABLE ... SET TIFLASH REPLICA n` immediately after the `CREATE TABLE` (Essential/Dedicated; informational comment on Starter) |
| `SECONDARY_LOAD=...` option / `SECONDARY_LOAD`/`SECONDARY_UNLOAD` statements | HW-DDL-2 — comment out (whole statement becomes a `--` line comment); TiFlash replication is automatic once the replica is set |
| `CLUSTERING BY (...)` | HW-DDL-3 — comment out + `TISHIFT-REVIEW` suggestion (secondary index, or clustered PK when columns are a PK prefix); needs human assessment |
| `COMMENT 'RAPID_COLUMN=...'` | HW-DDL-4 — keep as-is (inert comment on TiDB); reported only |
| Column-level `NOT SECONDARY` | Strip — TiFlash replicates whole tables; note excluded columns in the report |
| `ENGINE_ATTRIBUTE` / `SECONDARY_ENGINE_ATTRIBUTE` (Lakehouse) | HW-BLOCKER-1 — table data is external; materialize before export |
| `ENCRYPTION='Y'` | Strip — TiDB Cloud encrypts at rest by default |
