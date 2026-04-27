# Convert Guide

The convert command transforms GoogleSQL DDL into TiDB-compatible MySQL DDL.

## What It Converts

- **Types**: Spanner types → MySQL/TiDB equivalents (see `references/type-mapping.md`)
- **Functions**: GoogleSQL functions → MySQL equivalents (see `references/function-mapping.md`)
- **Interleaved tables**: `INTERLEAVE IN PARENT` → standard `FOREIGN KEY` constraints
- **Commit timestamps**: `OPTIONS(allow_commit_timestamp=true)` → `DEFAULT CURRENT_TIMESTAMP(6)`
- **Row deletion policies**: `ROW DELETION POLICY` → TiDB `TTL` attribute
- **Sequences/IDENTITY**: → `AUTO_RANDOM` or `AUTO_INCREMENT`
- **Views**: SQL dialect translation via sqlglot (bigquery→mysql)

## What It Cannot Auto-Convert

- **ARRAY columns**: Flagged; manual decision needed (JSON column vs normalized table)
- **PROTO columns**: Flagged; must decide JSON vs flattened columns
- **TOKENLIST columns**: Flagged; requires external search engine
- **STRUCT in queries**: Flagged; query rewriting needed
- **FARM_FINGERPRINT and other Spanner-specific functions**: Flagged with alternatives

## Usage

```bash
# Dry run
tishift-spanner convert --scan-report ./tishift-reports/tishift-spanner-report.json --dry-run

# Generate DDL files
tishift-spanner convert --scan-report ./tishift-reports/tishift-spanner-report.json
```

## Output Files

- `01-create-tables.sql` — CREATE TABLE statements with interleave flattened to FK
- `02-create-indexes.sql` — Secondary indexes (apply after data load)
- `03-create-views.sql` — View definitions with function translations
- `04-foreign-keys.sql` — Additional FK constraints
- `05-conversion-notes.md` — Items requiring manual review
