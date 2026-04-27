# Sync Guide — CockroachDB to TiDB

## Overview

CDC from CockroachDB uses **Changefeeds** — built-in streaming that emits row changes to Kafka, webhooks, or cloud storage. AWS DMS is NOT supported (CRDB lacks streaming replication slots).

## Architecture

```
CockroachDB → Changefeed → Kafka → Consumer → TiDB
```

## Setup

### 1. Create Kafka topic

```bash
kafka-topics --create --topic crdb-cdc --bootstrap-server broker:9092
```

### 2. Create changefeed

```sql
CREATE CHANGEFEED FOR TABLE users, orders, products
INTO 'kafka://broker:9092?topic_prefix=crdb_'
WITH updated, resolved='10s', format=json;
```

### 3. Deploy consumer

A consumer reads from Kafka and writes to TiDB. Options:
- Custom Python consumer (using `confluent-kafka` + `pymysql`)
- Custom Go consumer (using `sarama` + `go-sql-driver`)
- Apache Flink CDC connector

### 4. Monitor

```sql
-- Check changefeed status
SHOW CHANGEFEED JOBS;
```

## Cutover

1. Wait for changefeed lag → 0
2. Quiesce application writes to CockroachDB
3. Verify final row counts match
4. Switch application connection strings to TiDB
5. Cancel changefeed: `CANCEL CHANGEFEED JOB <id>`

## Notes

- Changefeeds emit at-least-once delivery — consumer must handle idempotency (upsert pattern)
- `resolved` timestamps enable consumer-side watermarking for exactly-once semantics
- Enterprise changefeeds require a CockroachDB Enterprise license; Core changefeeds have limitations (no schema changes, no initial scan in older versions)
