# Convert Guide

How `tishift-firestore convert` turns a scan report into TiDB DDL.

## What convert does

1. Loads the scan report.
2. For each collection, runs the schema-policy decision algorithm — see
   [references/schema-policy.md](../references/schema-policy.md).
3. For each policy decision, emits typed columns / JSON columns / child
   tables per [references/type-mapping.md](../references/type-mapping.md).
4. Writes four SQL files in `tishift-output/`:
   - `01-create-tables.sql` — applied **before** load (DDL must exist)
   - `02-create-indexes.sql` — applied **after** load (5–10× faster)
   - `03-foreign-keys.sql` — applied **after** load
   - `04-multi-valued-indexes.sql` — applied **last**, on settled data
5. Writes `convert-plan.json` — machine-readable policy decisions
6. Writes `convert-advisor.md` — human-readable per-collection mapping with
   flagged fields requiring review

## Running it

```bash
# Dry-run — produces SQL files but does not execute anything
tishift-firestore convert --config tishift-firestore.yaml \
    --scan-report tishift-reports/firestore-scan-report.json --dry-run

# Apply — connects to TiDB and runs 01-create-tables.sql
tishift-firestore convert --config tishift-firestore.yaml \
    --scan-report tishift-reports/firestore-scan-report.json --apply
```

**Always run `--dry-run` first.** Read the advisor. Resolve any flagged
polymorphic fields before applying.

## The convert advisor

`tishift-output/convert-advisor.md` is a per-collection report:

```markdown
## users (policy: hybrid)

Rationale: 3 composite indexes present; 1 polymorphic field outside indexed paths.

Typed columns:
  - id            VARCHAR(20) PRIMARY KEY
  - email         VARCHAR(256) NOT NULL
  - age           BIGINT NULL
  - location_lat  DECIMAL(9,6) NULL
  - location_lng  DECIMAL(9,6) NULL
  - created_at    DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)

JSON columns:
  - preferences   JSON NULL    -- map type, stable but deep

Child tables:
  - users_orders        (subcollection)
  - users_orders_items  (Array<object> from orders.items)

Flagged for review:
  (none)


## products (policy: hybrid)

Rationale: composite indexes present; price field is polymorphic in indexed path.

Typed columns:
  - id            VARCHAR(20) PRIMARY KEY
  - sku           VARCHAR(64) NOT NULL
  - name          VARCHAR(512) NOT NULL
  - category_ref  VARCHAR(1500) NOT NULL    -- FK to categories.id

JSON columns:
  - attributes    JSON NULL
  - price         JSON NULL    -- POLYMORPHIC — choose handling below

Child tables:
  (none)

Flagged for review:
  - price (BLOCKER-4) — polymorphic field in composite-indexed path.
      Sampled types: number (180), map (18), null (2)
      Options:
        (a) coerce: convert all 'map' values to number (lossy — keeps index)
        (b) json:   accept JSON column, drop the composite index that uses 'price'
        (c) skip:   drop the field entirely
      Add the chosen action to tishift-firestore.yaml under
      convert.per_collection.products.poly_fields.price.decision
```

The user must resolve flagged-for-review fields before `--apply` will run.

## Schema policy choices per collection

The default policy is `auto`, which uses the algorithm in
[references/schema-policy.md](../references/schema-policy.md). Override
per-collection in the config:

```yaml
convert:
  schema_policy_default: auto         # auto | json-mostly | hybrid | normalized
  per_collection:
    users:
      policy: normalized              # force fully typed columns
    audit_logs:
      policy: json-mostly             # force single-JSON-column shape
    products:
      policy: hybrid
      flatten_columns: [price, sku, name]    # force these to typed cols
      json_columns: [attributes, metadata]   # force these to JSON
      poly_fields:
        price:
          decision: json              # coerce | json | skip
```

## DocumentReference handling

By default, a `DocumentReference` field becomes:

- A `VARCHAR(1500)` column storing the full document path.
- An indexed column (`KEY idx_<field>`).
- A `FOREIGN KEY` constraint to the target collection's PK, **only if** the
  target collection is in the scan scope.

For cross-database references or out-of-scope targets, the FK is omitted and
WARNING-9 fires.

To turn off FK creation entirely (useful during initial load to speed
ingest):

```yaml
convert:
  emit_foreign_keys: false
```

The `03-foreign-keys.sql` file is still produced — you can apply it
separately after the load.

## GeoPoint mapping per field

```yaml
convert:
  per_collection:
    users:
      geopoint_mapping:
        location: lat_lng_columns    # default — two DECIMAL(9,6) cols
    geo_zones:
      geopoint_mapping:
        boundary: json               # opaque payload — store as JSON
```

## What convert does NOT do

- **Does not migrate data.** Convert produces DDL. Data movement happens in
  the load phase.
- **Does not generate `CREATE PROCEDURE` / `CREATE TRIGGER`.** Firestore has
  no procedural code.
- **Does not translate Firestore queries to SQL.** That's an application-side
  rewrite the customer owns. TiShift v1 can advise on query patterns but
  does not rewrite SDK code.
- **Does not deploy the `firestore-bigquery-export` extension.** Convert
  emits the install manifest when sync is configured; the customer runs
  `firebase ext:install`.
