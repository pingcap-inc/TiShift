# Type Mapping — OceanBase MySQL Mode → TiDB

OceanBase MySQL-mode types are near-1:1 with MySQL/TiDB types.

| OceanBase MySQL Type | TiDB Type | Notes |
|---|---|---|
| `INT` | `INT` | Direct. |
| `BIGINT` | `BIGINT` | Direct. |
| `SMALLINT` | `SMALLINT` | Direct. |
| `TINYINT` | `TINYINT` | Direct. |
| `FLOAT` | `FLOAT` | Direct. |
| `DOUBLE` | `DOUBLE` | Direct. |
| `DECIMAL(p,s)` | `DECIMAL(p,s)` | Direct. |
| `VARCHAR(n)` | `VARCHAR(n)` | Direct. |
| `CHAR(n)` | `CHAR(n)` | Direct. |
| `TEXT` | `TEXT` | Direct. |
| `LONGTEXT` | `LONGTEXT` | Direct. |
| `BLOB` | `BLOB` | Direct. |
| `LONGBLOB` | `LONGBLOB` | Direct. |
| `DATE` | `DATE` | Direct (MySQL-mode DATE is date-only). |
| `DATETIME` | `DATETIME` | Direct. |
| `TIMESTAMP` | `TIMESTAMP` | Direct. |
| `JSON` | `JSON` | Direct. |
| `ENUM(...)` | `ENUM(...)` | Direct. |
| `BIT(n)` | `BIT(n)` | Direct. |

**The focus for MySQL mode is DDL extension stripping, not type conversion.**

Strip from CREATE TABLE output:
- `TABLEGROUP = '...'`
- `PRIMARY_ZONE = '...'`
- `LOCALITY = '...'`
- `REPLICA_NUM = N`
- Resource-related clauses
