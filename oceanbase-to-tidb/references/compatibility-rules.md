# Compatibility Rules — OceanBase → TiDB

## Blockers

| ID | Condition | Feature | Action |
|---|---|---|---|
| BLOCKER-1 | `has_tablegroups` | TABLEGROUP | Strip from DDL. No TiDB equivalent. TiDB optimizer handles co-location. |
| BLOCKER-2 | `ob_mode == 'oracle' AND stored_procedure_count > 0` | PL/SQL (Oracle mode) | Rewrite as application code (AI-assisted). |
| BLOCKER-3 | `ob_mode == 'oracle' AND package_count > 0` | PL/SQL Packages (Oracle mode) | Decompose into application modules. |
| BLOCKER-4 | `trigger_count > 0` | Triggers | TiDB parses but does not execute. Rewrite as middleware. |
| BLOCKER-5 | `has_multi_tenancy_ddl` | Multi-tenancy DDL | Strip tenant/resource DDL. Deploy separate TiDB clusters or use Resource Control. |
| BLOCKER-6 | `ob_mode == 'oracle' AND has_oracle_types` | Oracle Types (NUMBER, VARCHAR2, ROWNUM) | Full type mapping required. |
| BLOCKER-7 | `ob_mode == 'mysql' AND stored_procedure_count > 0` | MySQL Stored Procedures | TiDB parses but does not execute. |

## Warnings

| ID | Condition | Feature | Action |
|---|---|---|---|
| WARNING-1 | `has_primary_zone` | PRIMARY_ZONE | Strip. Map to TiDB Placement Rules. |
| WARNING-2 | `has_locality` | LOCALITY | Strip. Map to TiDB Placement Rules. |
| WARNING-3 | `has_resource_units` | Resource Units/Pools | Strip. Map to TiDB Resource Control (v7.1+). |
| WARNING-4 | `has_global_indexes` | Global Indexes | TiDB supports GLOBAL INDEX (v6.5+). Verify target version. |
| WARNING-5 | `has_outlines` | Outline (Plan Binding) | Convert to TiDB `CREATE BINDING`. |
| WARNING-6 | `partition_count > 0` | Partitions | Mostly compatible. Verify composite partitions. |
| WARNING-7 | `has_auto_increment` | AUTO_INCREMENT | OB is globally unique (like TiDB). Minimal gap. |
| WARNING-8 | `ob_mode == 'oracle' AND sequence_count > 0` | Sequences | TiDB supports CREATE SEQUENCE (v4.0+). |
| WARNING-9 | `ob_mode == 'oracle' AND has_connect_by` | CONNECT BY | Rewrite as WITH RECURSIVE. |
| WARNING-10 | `ob_mode == 'oracle' AND has_rownum` | ROWNUM | Rewrite as LIMIT. |
| WARNING-11 | `collation_mismatch` | Collation | OB defaults utf8mb4_general_ci. TiDB may differ. Verify. |
| WARNING-12 | `cdc_not_available` | No MySQL-binlog CDC | OB does not produce MySQL binlog. CDC requires OMS or libobcdc. |

## Compatible (MySQL Mode)

All standard MySQL types, AUTO_INCREMENT, information_schema, RANGE/LIST/HASH/KEY partitioning, views, JSON, prepared statements, transactions, `LOAD DATA LOCAL INFILE`.

## JSON Output

```json
{
  "blockers": [{"id": "BLOCKER-1", "feature": "TABLEGROUP", "count": 5, "action": "Strip from DDL"}],
  "warnings": [{"id": "WARNING-1", "feature": "PRIMARY_ZONE", "count": 1, "action": "Strip, map to Placement Rules"}],
  "compatible": ["INT/BIGINT", "VARCHAR", "DATETIME", "JSON", "Partitioning", "Views"]
}
```
