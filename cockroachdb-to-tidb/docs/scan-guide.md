# Scan Guide — CockroachDB to TiDB

## What the Scan Collects

1. **Schema inventory** — tables, columns, indexes (including hash-sharded and inverted), constraints, views, sequences, enum types
2. **CRDB-specific features** — multi-region config, hash-sharded indexes, inverted indexes, row-level TTL, interleaved tables
3. **Data profile** — table sizes from `crdb_internal.tables`, JSONB and array column detection, UUID PK detection
4. **Procedural code** — stored procedures (v23.2+), triggers (v24.3+)
5. **Server metadata** — CockroachDB version

## Key CockroachDB-Specific Considerations

- **INT is 64-bit.** CRDB `INT` = `INT8` = 64 bits. The scan flags all INT columns for mapping to BIGINT.
- **`crdb_internal.tables`** provides table sizes, estimated row counts, and range counts. Falls back to `pg_stat_user_tables` if not accessible.
- **Hash-sharded indexes** detected via `crdb_internal.table_indexes` where `is_sharded = true`.
- **pg_dump does not work** against CockroachDB. DDL is extracted via `SHOW CREATE TABLE`.
