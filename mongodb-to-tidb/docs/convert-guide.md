# Convert Guide

How `tishift-mongodb convert` turns a scan report into TiDB DDL.

## What convert does

1. Loads the scan report.
2. For each collection, runs the schema-policy decision (see [schema-policy.md](../references/schema-policy.md)).
3. For each policy decision, emits typed columns / merged JSON column / child tables per [type-mapping.md](../references/type-mapping.md).
4. Writes SQL files in `tishift-output/`:
   - `01-create-tables.sql` — applied **before** load
   - `02-create-indexes.sql` — applied **after** load
   - `03-foreign-keys.sql` — applied **after** load (DBRef → FK when target in scope)
   - `04-multi-valued-indexes.sql` — applied **last**
5. Writes `convert-plan.json` (per-collection policy decisions).
6. Writes `convert-advisor.md` (human-readable mapping with flags).
7. If aggregation advisor enabled, writes `aggregation-rewrite.md` (SQL rewrite suggestions per pipeline).

## Running it

```bash
# Dry-run — produces SQL files but doesn't execute
tishift-mongodb convert --config tishift-mongodb.yaml \
    --scan-report tishift-reports/mongodb-scan-report.json --dry-run

# Apply — connects to TiDB and runs 01-create-tables.sql
tishift-mongodb convert --config tishift-mongodb.yaml \
    --scan-report tishift-reports/mongodb-scan-report.json --apply
```

**Always run `--dry-run` first.** Read the advisor and the aggregation
rewrites. Resolve flagged polymorphic fields before applying.

## The convert advisor

Per-collection report. Example for `products`:

```markdown
## `products` (policy: hybrid)

Rationale: 2 composite indexes present; 1 polymorphic field outside indexed paths.

Typed columns:
  - id            VARCHAR(24) PRIMARY KEY
  - sku           VARCHAR(64) NOT NULL
  - name          VARCHAR(512) NOT NULL
  - category_ref  VARCHAR(1500) NOT NULL    -- DBRef to categories
  - active        TINYINT(1) NOT NULL

JSON columns:
  - doc           JSON                    -- merged JSON: holds price, attributes, ...

Child tables:
  (none)

Flagged for review:
  - price (WARNING-8) — polymorphic field outside indexed paths.
      Sampled types: Int32 (180), Object (18), null (2)
      Default: lands in `doc` JSON column.
```

The user must resolve any **BLOCKER-** flagged fields before `--apply` will run.

## Hybrid policy: ONE merged JSON column

Under Hybrid, **non-indexed fields collapse into a single `doc JSON` column**,
not into individual JSON columns. This is the corrected behavior (the
Firestore variant initially had a bug here that produced a column per field).

Resulting table for a `users` collection with composite index on
`(country_code, tier, created_at)`:

```sql
CREATE TABLE `users` (
  `id` VARCHAR(24) NOT NULL,
  `country_code` VARCHAR(2) NOT NULL,    -- typed: in composite index
  `tier` VARCHAR(16) NOT NULL,           -- typed: in composite index
  `created_at` DATETIME(6) NOT NULL,     -- typed: in composite index
  `doc` JSON,                            -- single merged JSON: email, name, age, etc.
  PRIMARY KEY (`id`)
) ENGINE=InnoDB ...
```

To query a field inside `doc`, use `JSON_EXTRACT`:

```sql
SELECT id, JSON_EXTRACT(doc, '$.email') AS email
FROM users
WHERE country_code = 'US' AND tier = 'gold';
```

For frequently-queried JSON paths, add functional indexes:

```sql
ALTER TABLE users ADD INDEX idx_doc_email ((CAST(JSON_EXTRACT(doc, '$.email') AS CHAR(256))));
```

The convert phase suggests functional-index DDL for paths that the
aggregation inventory shows are accessed frequently.

## Schema policy choices per collection

Default is `auto`. Override in the config:

```yaml
convert:
  schema_policy_default: auto         # auto | json-mostly | hybrid | normalized
  per_collection:
    users:
      policy: normalized              # force all fields typed
    audit_logs:
      policy: json-mostly             # force entire doc into one JSON column
    products:
      policy: hybrid
      flatten_columns: [price, sku, name]    # force these to typed cols
      json_columns: [attributes, metadata]   # force these to merged JSON
      poly_fields:
        price:
          decision: json              # coerce | json | skip
```

## DBRef handling

A DBRef field (`{$ref, $id, $db}`) becomes:

- A `VARCHAR(1500)` column storing the full path
- An indexed column (`KEY idx_<field>`)
- A `FOREIGN KEY` constraint to the target collection's PK — **only if** the
  target collection is in the scan scope

For cross-database references or out-of-scope targets, the FK is omitted and
WARNING-10 fires.

To turn off FK creation entirely (faster initial load):

```yaml
convert:
  emit_foreign_keys: false
```

## Aggregation rewrites

If `convert.aggregation_advisor.enabled: true` AND a `completion_fn` callable
is injected, the convert phase produces `tishift-output/aggregation-rewrite.md`
with SQL rewrite suggestions per pipeline.

**Provider-agnostic** — the operator chooses the LLM provider:

```python
from tishift_mongodb.core.convert.aggregation_advisor import suggest_rewrite

def my_completion(prompt: str) -> str:
    # Any LLM provider — caller chooses the provider and owns credentials
    ...

# At convert time, wire it up via the config + entry point
```

See [aggregation-rewrite.md](../references/aggregation-rewrite.md) for the
full rewrite mapping and privacy contract.

## What convert does NOT do

- **Doesn't migrate data.** That's the load phase.
- **Doesn't generate `CREATE PROCEDURE` / `CREATE TRIGGER`.** Mongo has no procedural code.
- **Doesn't translate driver method chains to SQL.** Application-side rewrite.
- **Doesn't auto-apply aggregation rewrites.** Output is suggestions only.
- **Doesn't deploy any third-party connector.** Adapters (DMS, Datastream, Debezium) emit configs the customer applies.
