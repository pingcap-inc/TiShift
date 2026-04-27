# Check Guide

The check command validates data integrity between source (Cloud Spanner) and target (TiDB).

## What It Validates

1. **Row count comparison** — per-table counts on both sides
2. **Column structure diff** — column names, mapped types, nullability
3. **Primary key consistency** — PK-ordered row comparison (configurable batch size)
4. **Optional checksum** — hash per PK range

## Cross-Protocol Validation

Source queries use `google-cloud-spanner` (gRPC). Target queries use `PyMySQL` (MySQL protocol). The comparison logic normalizes type differences:
- Spanner `TRUE`/`FALSE` ↔ TiDB `1`/`0`
- Spanner `ARRAY<T>` ↔ TiDB `JSON` array
- Spanner `NUMERIC` ↔ TiDB `DECIMAL(38,9)`
- Spanner `TIMESTAMP` (nanosecond) ↔ TiDB `DATETIME(6)` (microsecond)

## Alternative: Google DVT

Google's Data Validation Tool (DVT) supports Spanner as source and MySQL as target. Consider using DVT as a complement to TiShift check.

## Usage

```bash
tishift-spanner check --config tishift-spanner.yaml
tishift-spanner check --config tishift-spanner.yaml --checksum
tishift-spanner check --config tishift-spanner.yaml --output json
```
