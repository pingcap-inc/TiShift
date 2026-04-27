# Scan Guide — OceanBase to TiDB

## Mode Detection

First step: `SHOW VARIABLES LIKE 'ob_compatibility_mode'` → MYSQL or ORACLE. This branches the entire pipeline.

## MySQL Mode Scan

Uses standard `information_schema` queries (same as Aurora). Additionally detects OB extensions via `SHOW CREATE TABLE` output: TABLEGROUP, PRIMARY_ZONE, LOCALITY.

## Oracle Mode Scan

Uses DBA_* views where available, plus `information_schema`. Detects PL/SQL, sequences, CONNECT BY, ROWNUM (same as Oracle variant).

## Key OB-Specific Detections

- **TABLEGROUP** — appears in almost every OB schema
- **PRIMARY_ZONE / LOCALITY** — replica placement DDL
- **Resource units** — multi-tenant resource isolation DDL
- **CDC availability** — OB does NOT produce MySQL binlog
