# Scan Guide

The scan command connects read-only to your Neon/Postgres instance and collects:

1. **Schema inventory** — tables, columns, indexes, constraints, functions, triggers, views, sequences, custom types, extensions
2. **Data profile** — database size, per-table row estimates and sizes, large column detection
3. **Feature usage** — arrays, JSONB operators, inheritance, RLS, full-text search, unlogged tables
4. **Neon-specific checks** — connection type (pooled vs direct), WAL level, statistics freshness, compute constraints

## Usage

```bash
# Basic scan
tishift-neon scan --config tishift-neon.yaml

# Scan with AI analysis of PL/pgSQL functions
tishift-neon scan --config tishift-neon.yaml --ai

# JSON output only
tishift-neon scan --config tishift-neon.yaml --format json --quiet
```

## Output

The scan produces a readiness report with:
- Migration Readiness Score (0-100) across 5 categories
- Blocker list with recommended actions
- Warning list with mitigation strategies
- Automation coverage estimate

## Important Notes

- **Use a direct (unpooled) connection string.** Pooled Neon connections will cause failures.
- **Run ANALYZE first** if the Neon compute was recently restarted — statistics may be stale.
- **Source connection is always read-only.** No data is modified on your Neon instance.
