---
name: spanner-to-tidb-migration
description: Migrate Cloud Spanner databases to TiDB — assess readiness, convert schema, load data, and validate. Use this skill whenever someone mentions migrating from Cloud Spanner or Google Spanner to TiDB, wants to assess Spanner compatibility with TiDB, needs to convert GoogleSQL schema to MySQL/TiDB DDL, or is planning any Spanner to TiDB migration project.
metadata:
  version: 0.1.0
---

# Cloud Spanner to TiDB Migration

This skill walks you through a complete Cloud Spanner → TiDB migration, one step at a time. The user runs each command and pastes the output back; you interpret the results and move to the next step.

## How to use this skill

When the user provides their Spanner project/instance/database details, start Phase 1 immediately. Output one command, say "Run this and paste the output," and wait.

**Authentication:** Cloud Spanner uses GCP IAM, not username/password. Before starting, verify the user has authenticated:
```
gcloud auth application-default login
```
Or has a service account key file set:
```
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/key.json"
```

**Command format for Spanner (GoogleSQL):**
```
gcloud spanner databases execute-sql $DATABASE_ID \
  --instance=$INSTANCE_ID \
  --project=$PROJECT_ID \
  --sql="SQL"
```

**Command format for TiDB (MySQL protocol):**
```
mysql -h $HOST -P $PORT -u $USER -e "SQL"
```

Substitute the user's actual values. Output one command per step — never combine queries.

**Key difference from other TiShift variants:** Spanner has no stored procedures, triggers, or UDFs. There is no procedural code to convert. The migration is purely schema + data — the cleanest migration path in TiShift.

---

## Phase 1: Connect

Verify access to both source (Cloud Spanner) and target (TiDB Cloud).

Before connecting, ask the user:
1. Which TiDB Cloud tier they're targeting (Starter/Essential/Dedicated)
2. Their GCP project ID, Spanner instance ID, and database ID
3. Whether they have a GCS bucket available for data export

**Step 1.1 — Test source:**
```
gcloud spanner databases execute-sql $DATABASE_ID \
  --instance=$INSTANCE_ID \
  --project=$PROJECT_ID \
  --sql="SELECT 1 AS connected"
```

**Step 1.2 — Get database dialect:**
```
gcloud spanner databases describe $DATABASE_ID \
  --instance=$INSTANCE_ID \
  --project=$PROJECT_ID \
  --format="value(databaseDialect)"
```

Note: If dialect is `POSTGRESQL`, the information_schema queries differ. This skill assumes GoogleSQL dialect. For PostgreSQL-dialect Spanner, adapt queries accordingly and add an ops score penalty (WARNING — adds complexity).

**Step 1.3 — Test target:**

For TiDB Cloud Starter/Essential (TLS required):
```
mysql --ssl-mode=VERIFY_IDENTITY -h $TARGET_HOST -P 4000 -u $TARGET_USER -e "SELECT VERSION()"
```

**Gate:** Both must succeed. Source returns `1`. Target shows TiDB version.

---

## Phase 2: Scan

Collect schema inventory from Cloud Spanner. Run all steps — each as a single command.

**Step 2.1 — Tables (including interleaved relationships):**
```
gcloud spanner databases execute-sql $DATABASE_ID \
  --instance=$INSTANCE_ID --project=$PROJECT_ID \
  --sql="SELECT TABLE_NAME, PARENT_TABLE_NAME, ON_DELETE_ACTION,
         ROW_DELETION_POLICY_EXPRESSION
         FROM INFORMATION_SCHEMA.TABLES
         WHERE TABLE_SCHEMA = '' AND TABLE_TYPE = 'BASE TABLE'"
```

**Step 2.2 — Columns:**
```
gcloud spanner databases execute-sql $DATABASE_ID \
  --instance=$INSTANCE_ID --project=$PROJECT_ID \
  --sql="SELECT TABLE_NAME, COLUMN_NAME, ORDINAL_POSITION,
         SPANNER_TYPE, IS_NULLABLE, COLUMN_DEFAULT,
         IS_GENERATED, GENERATION_EXPRESSION
         FROM INFORMATION_SCHEMA.COLUMNS
         WHERE TABLE_SCHEMA = ''
         ORDER BY TABLE_NAME, ORDINAL_POSITION"
```

**Step 2.3 — Commit timestamp columns:**
```
gcloud spanner databases execute-sql $DATABASE_ID \
  --instance=$INSTANCE_ID --project=$PROJECT_ID \
  --sql="SELECT TABLE_NAME, COLUMN_NAME
         FROM INFORMATION_SCHEMA.COLUMN_OPTIONS
         WHERE OPTION_NAME = 'allow_commit_timestamp'
           AND OPTION_VALUE = 'TRUE'
           AND TABLE_SCHEMA = ''"
```

**Step 2.4 — Indexes:**
```
gcloud spanner databases execute-sql $DATABASE_ID \
  --instance=$INSTANCE_ID --project=$PROJECT_ID \
  --sql="SELECT TABLE_NAME, INDEX_NAME, INDEX_TYPE, IS_UNIQUE,
         IS_NULL_FILTERED, PARENT_TABLE_NAME
         FROM INFORMATION_SCHEMA.INDEXES
         WHERE TABLE_SCHEMA = ''
           AND SPANNER_IS_MANAGED = FALSE"
```

**Step 2.5 — Index columns:**
```
gcloud spanner databases execute-sql $DATABASE_ID \
  --instance=$INSTANCE_ID --project=$PROJECT_ID \
  --sql="SELECT TABLE_NAME, INDEX_NAME, COLUMN_NAME,
         ORDINAL_POSITION, COLUMN_ORDERING
         FROM INFORMATION_SCHEMA.INDEX_COLUMNS
         WHERE TABLE_SCHEMA = ''
         ORDER BY TABLE_NAME, INDEX_NAME, ORDINAL_POSITION"
```

**Step 2.6 — Primary keys:**
```
gcloud spanner databases execute-sql $DATABASE_ID \
  --instance=$INSTANCE_ID --project=$PROJECT_ID \
  --sql="SELECT tc.TABLE_NAME, kcu.COLUMN_NAME, kcu.ORDINAL_POSITION
         FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
         JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu
           ON tc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME
         WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
           AND tc.TABLE_SCHEMA = ''
         ORDER BY tc.TABLE_NAME, kcu.ORDINAL_POSITION"
```

**Step 2.7 — Foreign keys:**
```
gcloud spanner databases execute-sql $DATABASE_ID \
  --instance=$INSTANCE_ID --project=$PROJECT_ID \
  --sql="SELECT rc.CONSTRAINT_NAME,
         kcu.TABLE_NAME AS child_table,
         kcu.COLUMN_NAME AS child_column,
         ccu.TABLE_NAME AS parent_table,
         ccu.COLUMN_NAME AS parent_column,
         rc.DELETE_RULE
         FROM INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS rc
         JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu
           ON rc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME
         JOIN INFORMATION_SCHEMA.CONSTRAINT_COLUMN_USAGE ccu
           ON rc.UNIQUE_CONSTRAINT_NAME = ccu.CONSTRAINT_NAME
         WHERE kcu.TABLE_SCHEMA = ''"
```

**Step 2.8 — Views:**
```
gcloud spanner databases execute-sql $DATABASE_ID \
  --instance=$INSTANCE_ID --project=$PROJECT_ID \
  --sql="SELECT TABLE_NAME, VIEW_DEFINITION
         FROM INFORMATION_SCHEMA.VIEWS
         WHERE TABLE_SCHEMA = ''"
```

**Step 2.9 — Change streams:**
```
gcloud spanner databases execute-sql $DATABASE_ID \
  --instance=$INSTANCE_ID --project=$PROJECT_ID \
  --sql="SELECT CHANGE_STREAM_NAME, ALL
         FROM INFORMATION_SCHEMA.CHANGE_STREAMS"
```

**Step 2.10 — Sequences:**
```
gcloud spanner databases execute-sql $DATABASE_ID \
  --instance=$INSTANCE_ID --project=$PROJECT_ID \
  --sql="SELECT NAME, DATA_TYPE, KIND
         FROM INFORMATION_SCHEMA.SEQUENCES
         WHERE SCHEMA = ''"
```

**Step 2.11 — Database options:**
```
gcloud spanner databases execute-sql $DATABASE_ID \
  --instance=$INSTANCE_ID --project=$PROJECT_ID \
  --sql="SELECT OPTION_NAME, OPTION_VALUE
         FROM INFORMATION_SCHEMA.DATABASE_OPTIONS"
```

**Step 2.12 — Data profile (table sizes):**
```
gcloud spanner databases execute-sql $DATABASE_ID \
  --instance=$INSTANCE_ID --project=$PROJECT_ID \
  --sql="SELECT TABLE_NAME, ROW_COUNT, TOTAL_BYTES
         FROM SPANNER_SYS.TABLE_SIZES_STATS_1MINUTE
         ORDER BY TOTAL_BYTES DESC"
```

**Gate:** All steps must succeed. Step 2.1 must return at least 1 table.

**Error recovery:**
- **Permission denied on INFORMATION_SCHEMA:** User needs `roles/spanner.databaseReader` or `roles/spanner.viewer` IAM role. Output the specific `gcloud projects add-iam-policy-binding` command.
- **Permission denied on SPANNER_SYS:** Statistics tables require `roles/spanner.databaseReader`. Non-critical — estimate sizes from column types if unavailable.
- **Database not found:** Verify project ID, instance ID, and database ID. Use `gcloud spanner databases list --instance=$INSTANCE_ID` to confirm.

---

## Phase 2.5: Build the Checklist

Extract structured counts from the scan output. Fill in every field.

```
table_count, view_count
interleaved_table_count, interleaved_index_count
array_column_count, bytes_column_count, json_column_count
proto_column_count, proto_enum_count, tokenlist_column_count
commit_timestamp_count, generated_column_count
sequence_count, foreign_key_count, check_constraint_count
row_deletion_policy_count, change_stream_count
struct_in_views (boolean — scan view definitions for STRUCT)
total_data_mb, largest_table_mb
database_dialect (GOOGLE_STANDARD_SQL or POSTGRESQL)
```

**Gate:** Every field has a concrete value. `table_count > 0`.

---

## Phase 3: Assess Compatibility

Classify findings as BLOCKER, WARNING, or COMPATIBLE using the checklist. Read `references/compatibility-rules.md` for the complete rule set.

The key distinction: **blockers** are features TiDB fundamentally cannot do (interleaved tables, ARRAY columns, PROTO types, TOKENLIST, graph schema, STRUCT in queries). **Warnings** are features that work differently (commit timestamps, sequences, row deletion policies, generated columns, interleaved indexes, NUMERIC precision, BOOL mapping).

**Important:** Unlike other TiShift variants, there are **no stored procedure or trigger blockers**. Spanner has no procedural code.

**Tier-specific constraints** — same as other variants:

| Constraint | Starter | Essential | Dedicated |
|---|---|---|---|
| Storage limit | 25 GiB free | No cap | No cap |
| Import method | `ticloud serverless import start` | Direct / DMS | Direct / Lightning |
| CDC sync | Not available | Changefeeds | Changefeeds / DM |

Output a JSON assessment with blockers, warnings, and compatible features.

---

## Phase 4: Score

Calculate a readiness score from 0-100 using 4 weighted categories (procedural code eliminated). Read `references/scoring.md` for the exact pseudocode.

| Category | Max | What It Measures |
|---|---|---|
| Schema Compatibility | 30 | Interleaved tables, ARRAY columns, PROTO types, TOKENLIST, graph schema, STRUCT |
| Data Complexity | 25 | Total volume, largest table, BYTES columns, table count, ARRAY export handling |
| Query Compatibility | 20 | STRUCT queries, ARRAY functions, PENDING_COMMIT_TIMESTAMP, stale reads, Spanner-specific functions |
| Operational Readiness | 25 | GCS bucket, Dataflow permissions, change stream config, multi-region, IAM auth, Data Boost |

**Rating:** >= 90 excellent, 75-89 good, 50-74 moderate, 25-49 challenging, < 25 difficult.

---

## *** USER GATE — DO NOT PROCEED WITHOUT EXPLICIT APPROVAL ***

**STOP HERE.** Present the full assessment and score. Ask explicitly: **"Do you want to proceed with schema conversion?"**

Do NOT continue to Phase 5 until the user explicitly approves.

---

## Phase 5: Convert Schema

Generate TiDB-compatible DDL. Read `references/type-mapping.md` for the complete type mapping and `references/function-mapping.md` for function translations.

**Key conversion rules:**
- `INT64` → `BIGINT`
- `FLOAT64` → `DOUBLE`, `FLOAT32` → `FLOAT`
- `STRING(N)` → `VARCHAR(N)` (if N ≤ 16383) or `TEXT` (if N > 16383 or MAX)
- `BYTES(N)` → `VARBINARY(N)` or `LONGBLOB` (for MAX)
- `NUMERIC` → `DECIMAL(38,9)`
- `BOOL` → `TINYINT(1)`
- `TIMESTAMP` → `DATETIME(6)`
- `ARRAY<T>` → `JSON` with comment
- `INTERLEAVE IN PARENT` → `FOREIGN KEY ... REFERENCES parent(pk)`
- `allow_commit_timestamp` → `DEFAULT CURRENT_TIMESTAMP(6)`
- Row deletion policies → TiDB `TTL` attribute or comment
- All tables: `ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci`

**Output files:**
- `01-create-tables.sql` — CREATE TABLE with type mappings and FK replacing interleave
- `02-create-indexes.sql` — secondary indexes (drop before load, recreate after)
- `03-create-views.sql` — views with function translations
- `04-foreign-keys.sql` — additional FK constraints
- `05-conversion-notes.md` — ARRAY columns, PROTO types, and other items requiring review

**Gate:** No Spanner types remain in output. Every `INTERLEAVE IN PARENT` replaced with FK.

---

## Phase 6: Load Data

Transfer data from Spanner to TiDB. **Important:** Spanner has no dump CLI. All data extraction goes through Dataflow or the Spanner client API.

| Tier | Data Size | Strategy | Method |
|---|---|---|---|
| **Starter** | ≤ 25 GiB | Dataflow CSV | Dataflow template → GCS CSV → `ticloud serverless import start` |
| **Essential** | < 50 GB | Dataflow CSV | Dataflow template → GCS CSV → `LOAD DATA LOCAL INFILE` |
| **Essential** | 50-500 GB | Dataflow CSV | Dataflow template (Data Boost) → GCS CSV → `LOAD DATA LOCAL INFILE` |
| **Dedicated** | < 50 GB | Dataflow CSV | Dataflow template → GCS CSV → `LOAD DATA LOCAL INFILE` |
| **Dedicated** | > 500 GB | Dataflow + Lightning | Dataflow → GCS CSV → download → TiDB Lightning |

**Export command (per table):**
```
gcloud dataflow jobs run tishift-export-$TABLE \
  --gcs-location gs://dataflow-templates/latest/Cloud_Spanner_to_GCS_Text \
  --region $REGION \
  --parameters \
    instanceId=$INSTANCE_ID,\
    databaseId=$DATABASE_ID,\
    outputDir=gs://$BUCKET/tishift-export/$TABLE/,\
    spannerTable=$TABLE
```

**Download from GCS:**
```
gsutil -m cp -r gs://$BUCKET/tishift-export/$TABLE/ ./$TABLE/
```

**Load steps:**
1. Apply schema: `mysql ... $DB < 01-create-tables.sql`
2. Export each table via Dataflow (above)
3. Download CSV from GCS
4. Load per table: `mysql ... -e "LOAD DATA LOCAL INFILE '$TABLE.csv' INTO TABLE ..."`
5. Recreate indexes: `mysql ... $DB < 02-create-indexes.sql`
6. Apply foreign keys: `mysql ... $DB < 04-foreign-keys.sql`

**Gate:** Get user confirmation before loading. Schema must apply cleanly. All Dataflow jobs must succeed.

---

## Phase 7: Validate

Compare source and target.

**Step 7.1 — Source row counts:**
```
gcloud spanner databases execute-sql $DATABASE_ID \
  --instance=$INSTANCE_ID --project=$PROJECT_ID \
  --sql="SELECT TABLE_NAME, ROW_COUNT
         FROM SPANNER_SYS.TABLE_SIZES_STATS_1MINUTE
         ORDER BY TABLE_NAME"
```

**Step 7.2 — Target row counts:**
```
mysql ... -e "SELECT table_name, table_rows
              FROM information_schema.tables
              WHERE table_schema = '$DB'
              ORDER BY table_name"
```

Compare. Flag any difference > 1%.

**Step 7.3-7.4 — Column structure:** Compare column names and mapped types between source and target.

**Gate:** Zero mismatches = migration verified.

---

## Decision Points

- If blockers exist: address before loading data
- If `interleaved_table_count > 0`: verify that flattened FK relationships preserve query performance
- If `array_column_count > 0`: confirm JSON representation works for application queries
- If `tier == "starter" AND total_data_mb > 25600`: recommend Essential or Dedicated
- If `tier == "starter"`: skip sync — cutover only
- If `change_stream_count == 0 AND sync_planned`: user must create a change stream first

---

## Reference files

- `references/type-mapping.md` — Complete Spanner → TiDB type mapping
- `references/compatibility-rules.md` — All blocker and warning rules with detection patterns
- `references/function-mapping.md` — GoogleSQL → MySQL function translations, array function rewrites
- `references/scoring.md` — Scoring pseudocode for all 4 categories
