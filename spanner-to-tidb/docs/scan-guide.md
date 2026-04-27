# Scan Guide

The scan command connects read-only to your Cloud Spanner instance and collects:

1. **Schema inventory** — tables, columns, indexes, constraints, views, sequences, change streams
2. **Data profile** — database size, per-table row estimates and sizes
3. **Feature usage** — interleaved tables, ARRAY columns, commit timestamps, row deletion policies, PROTO/ENUM types, TOKENLIST columns
4. **Spanner-specific checks** — database dialect (GoogleSQL vs PostgreSQL), change stream configuration

## Usage

```bash
# Basic scan
tishift-spanner scan --config tishift-spanner.yaml

# JSON output only
tishift-spanner scan --config tishift-spanner.yaml --format json --quiet
```

## Output

The scan produces a readiness report with:
- Migration Readiness Score (0-100) across 4 categories (no procedural code category — Spanner has no SPs/triggers)
- Blocker list with recommended actions
- Warning list with mitigation strategies

## Important Notes

- **GCP IAM authentication required.** Set `GOOGLE_APPLICATION_CREDENTIALS` or use `gcloud auth application-default login`.
- **Source connection is always read-only.** Uses `database.snapshot()` which is inherently read-only.
- **No stored procedure analysis.** Spanner has no stored procedures, triggers, or UDFs.
