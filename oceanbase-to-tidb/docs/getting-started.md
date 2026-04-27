# Getting Started — OceanBase to TiDB

## Prerequisites

1. **MySQL client** — connects to both OceanBase (MySQL protocol) and TiDB
2. **OceanBase access** — host, port (**2881** via OBProxy), user, tenant, password
3. **TiDB Cloud cluster** — free [Starter](https://tidbcloud.com/) tier works

## Quick Start

```
/oceanbase-to-tidb
```

Or CLI: `pip install -e '.[dev]' && tishift-ob scan --config tishift-ob.yaml`

## Connection Notes

- OceanBase default port: **2881** (OBProxy), not 3306
- Tenant-qualified username: `user@tenant_name`
- Set credentials: `export OB_USER="admin@sys" OB_PASS="password"`
