# Getting Started — Oracle to TiDB Migration

## Prerequisites

1. **Oracle access** — Read-only credentials to the source Oracle database. The user needs `SELECT` privileges on `ALL_TABLES`, `ALL_TAB_COLUMNS`, `ALL_INDEXES`, `ALL_CONSTRAINTS`, `ALL_SOURCE`, `ALL_OBJECTS`, `ALL_VIEWS`, `ALL_SEQUENCES`, `ALL_SYNONYMS`, `ALL_DB_LINKS`, `ALL_MVIEWS`, `ALL_TRIGGERS`, `ALL_PART_TABLES`, `ALL_TAB_PARTITIONS`, `ALL_LOBS`, `NLS_DATABASE_PARAMETERS`. Optional: `DBA_SEGMENTS` for accurate sizing, `V$VERSION` and `V$DATABASE` for server metadata.

2. **Oracle client tools** — Either `sqlplus` (included with Oracle Client) or Oracle SQLcl (lightweight, Java-based, no Oracle Client needed). Download SQLcl: https://www.oracle.com/database/sqldeveloper/technologies/sqlcl/

3. **TiDB Cloud cluster** — A free [Starter](https://tidbcloud.com/) tier works for assessment and small migrations. For production, use Essential or Dedicated.

4. **MySQL client** — For connecting to TiDB (`mysql` CLI).

## Quick Start

### Option 1: AI-assisted (recommended)

Open the project in your AI coding assistant and run:

```
/oracle-to-tidb
```

The skill guides you through every phase interactively.

### Option 2: CLI toolkit

```bash
cd oracle-to-tidb
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'

cp config/tishift-oracle.example.yaml tishift-oracle.yaml
# Edit with your credentials

tishift-oracle scan --config tishift-oracle.yaml
```

## Setting Up Credentials

Set environment variables so passwords don't appear in commands:

```bash
export TISHIFT_ORACLE_PASSWORD="your_oracle_password"
export TISHIFT_TARGET_PASSWORD="your_tidb_password"

# For AI-assisted PL/SQL conversion (optional):
export TISHIFT_AI_API_KEY="your-api-key"
```

## What Happens During a Migration

1. **Scan** — TiShift connects read-only to Oracle, queries the data dictionary (ALL_TABLES, ALL_SOURCE, etc.), and collects schema inventory, data sizes, and PL/SQL complexity.

2. **Assess & Score** — Findings are classified as blockers (PL/SQL packages, triggers, database links), warnings (sequences, CONNECT BY queries, ROWNUM), or compatible. A 0–100 readiness score is computed across 5 categories.

3. **Convert** — TiDB-compatible DDL is generated. Oracle types are mapped (DATE→DATETIME, NUMBER→DECIMAL, CLOB→LONGTEXT). Oracle SQL syntax is rewritten (CONNECT BY→WITH RECURSIVE, ROWNUM→LIMIT). PL/SQL is converted to application code stubs.

4. **Load** — Data is extracted from Oracle via CSV (SQLcl) and loaded into TiDB via LOAD DATA, Cloud Import, DMS, or Lightning depending on data size and target tier.

5. **Validate** — Row counts, column structures, NULL semantics, and sequence state are compared between source and target.

## Next Steps

- [Scan Guide](scan-guide.md) — Detailed scan phase walkthrough
- [Convert Guide](convert-guide.md) — Type mapping and DDL conversion details
- [Load Guide](load-guide.md) — Data extraction and loading strategies
