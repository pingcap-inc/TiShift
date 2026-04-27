# Check Guide

The check command validates data integrity between source (Neon/Postgres) and target (TiDB).

## What It Validates

1. **Row count comparison** — per-table `COUNT(*)` on both sides
2. **Column structure diff** — column names, mapped types, nullability
3. **Primary key consistency** — PK-ordered row comparison (configurable batch size)
4. **Optional checksum** — MD5 hash per primary-key range

## Cross-Protocol Validation

Source queries use `psycopg` (Postgres protocol). Target queries use `PyMySQL` (MySQL protocol). The comparison logic normalizes type differences:
- Postgres `TRUE`/`FALSE` ↔ TiDB `1`/`0`
- Postgres `UUID` ↔ TiDB `VARCHAR(36)` string comparison
- Postgres `TIMESTAMPTZ` ↔ TiDB `DATETIME` (normalized to UTC)

## Usage

```bash
# Row count and structure validation
tishift-neon check --config tishift-neon.yaml

# Include checksum validation
tishift-neon check --config tishift-neon.yaml --checksum

# Output as JSON
tishift-neon check --config tishift-neon.yaml --output json
```

## Output

- Per-table: row counts (source vs target), match status, discrepancies
- Column-level: type mapping verification
- Summary: total matched, mismatched, missing
