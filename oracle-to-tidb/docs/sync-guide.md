# Sync Guide — Oracle to TiDB

## Overview

The sync phase sets up Change Data Capture (CDC) to keep Oracle and TiDB in sync during the migration transition period. This enables near-zero-downtime cutover.

**Note:** TiDB Cloud Starter tier does not support CDC. Starter migrations require a cutover with scheduled downtime.

## CDC Options

### Option 1: AWS DMS (Recommended)

AWS Database Migration Service with Oracle source endpoint.

**Prerequisites:**
- Supplemental logging enabled on Oracle: `ALTER DATABASE ADD SUPPLEMENTAL LOG DATA`
- DMS replication instance created in the same region
- Source endpoint (Oracle, LogMiner mode) and target endpoint (TiDB, MySQL-compatible) configured

**CDC modes:**
| Mode | Pros | Cons |
|---|---|---|
| LogMiner | No OS access needed, no extra license | Slower, SQL-based redo log reading |
| Binary Reader | Faster, direct redo log parsing | Needs OS-level access to redo logs |

**Limitations:**
- DDL changes during CDC require DMS task restart
- LOB columns: full LOB mode (slow) vs limited LOB mode (truncation risk)
- Sequence values are NOT replicated

### Option 2: Debezium Oracle Connector

Open-source, self-managed CDC via Apache Kafka.

**Prerequisites:**
- Kafka cluster
- Debezium connector deployed
- Supplemental logging enabled on Oracle
- LogMiner access

**Architecture:**
```
Oracle → Debezium (LogMiner) → Kafka → Consumer → TiDB
```

Best for teams already running Kafka infrastructure.

## Cutover Procedure

1. Start DMS/Debezium CDC task (after full load is complete)
2. Monitor replication lag — wait for lag to approach zero
3. Quiesce application writes to Oracle (maintenance window)
4. Verify final replication lag = 0
5. Verify row counts match between Oracle and TiDB
6. Switch application connection strings to TiDB
7. Verify application health on TiDB
8. Stop CDC task
9. Decommission Oracle (after verification period)

## Important Notes

- Enable supplemental logging BEFORE starting CDC. Enabling it has 5–15% I/O overhead on the Oracle production database.
- DMS cannot replicate DDL changes during CDC. Plan all schema changes for the cutover window.
- Sequence values must be manually synced. After cutover, set TiDB sequence values to match Oracle's current state.
