# Convert Guide

The convert command transforms Postgres DDL into TiDB-compatible MySQL DDL.

## What It Converts

- **Types**: Postgres types → MySQL/TiDB equivalents (see `references/type-mapping.md`)
- **Functions**: Postgres functions → MySQL equivalents (see `references/function-mapping.md`)
- **Sequences**: `CREATE SEQUENCE` + `nextval()` → `AUTO_INCREMENT`
- **ENUMs**: Named `CREATE TYPE ... AS ENUM` → inline `ENUM(...)` in column definition
- **Views**: SQL dialect translation via sqlglot
- **Indexes**: Syntax normalization; GIN/GiST indexes flagged for review

## What It Cannot Auto-Convert

- **PL/pgSQL functions/procedures**: Generated as code stubs with AI-assisted rewrite (requires `--ai` flag)
- **Triggers**: Flagged with recommended application-layer alternatives
- **Arrays**: Flagged; manual decision needed (JSON column vs normalized table)
- **JSONB operators**: Flagged with MySQL JSON function equivalents
- **Extensions** (PostGIS, pgvector, etc.): Flagged with infrastructure alternatives

## Usage

```bash
# Dry run — show what would be generated
tishift-neon convert --scan-report ./tishift-reports/tishift-neon-report.json --dry-run

# Generate DDL files
tishift-neon convert --scan-report ./tishift-reports/tishift-neon-report.json

# With AI-assisted PL/pgSQL conversion
tishift-neon convert --scan-report ./tishift-reports/tishift-neon-report.json --ai
```

## Output Files

- `01-create-tables.sql` — CREATE TABLE statements
- `02-create-indexes.sql` — Secondary indexes (apply after data load)
- `03-create-views.sql` — View definitions
- `04-foreign-keys.sql` — Foreign key constraints
- `05-conversion-notes.md` — Items requiring manual review
