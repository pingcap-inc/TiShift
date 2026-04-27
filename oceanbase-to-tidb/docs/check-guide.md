# Check Guide — OceanBase to TiDB

## Validation

Both sides speak MySQL protocol — standard row count and structure comparison.

For Oracle mode, additionally verify:
- DATE → DATETIME mapping (OB Oracle DATE includes time)
- NUMBER precision
- Collation match (OB defaults may differ from TiDB)
