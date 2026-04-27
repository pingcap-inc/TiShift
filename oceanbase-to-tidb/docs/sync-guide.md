# Sync Guide — OceanBase to TiDB

## CDC Limitation

OceanBase does **NOT** produce MySQL-compatible binlog. TiDB DM cannot consume OB's change logs.

## Options

1. **OMS (Enterprise)** — OceanBase Migration Service supports incremental sync to MySQL targets
2. **libobcdc + custom consumer** — OB's CDC library → custom bridge → TiDB
3. **DataX** — full load only, no incremental

## Community Edition

No CDC available. Migration requires **scheduled downtime cutover**.

## Cutover Procedure

1. Quiesce application writes to OceanBase
2. Final mysqldump or OBDUMPER export
3. Load into TiDB
4. Verify row counts
5. Switch connection strings
