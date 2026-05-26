# Schema Policy Engine

How TiShift decides whether each MongoDB collection lands in TiDB as
**normalized**, **JSON-mostly**, or **hybrid**.

## The three policies

### Normalized

Top-level scalar fields become typed columns; embedded subdocuments become
flattened columns (shallow stable shape) or JSON (deeper); arrays of objects
become child tables; arrays of scalars become JSON with optional multi-valued
indexes. DBRefs become FK columns where the target collection is in scope.

Best for: collections that participate in composite indexes, have stable
shape across documents, and will be queried by indexed field paths in TiDB.

### JSON-mostly

A primary-key column plus a single `doc JSON` column holding the entire
document body. No flattening, no per-field typing.

Best for: collections with no composite indexes, polymorphic schemas, or
truly key-value-shaped data (audit logs, event streams, configuration blobs).

### Hybrid (default)

**Typed columns** for fields that appear in composite indexes; **one merged
`doc JSON` column** for everything else. This is the default for collections
that have composite indexes — preserves indexable query patterns without
forcing typed-column engineering on every field.

**Key correctness note** (lifted as a lesson from the Firestore variant):
non-indexed fields collapse into a single `doc JSON` column, NOT into
individual JSON columns per field. The latter is the worst of both worlds —
JSON storage cost per field without the indexability benefit of typed columns.
A typed table for `users` under Hybrid policy looks like:

```sql
CREATE TABLE `users` (
  `id` VARCHAR(24) NOT NULL,
  `country_code` VARCHAR(2) NOT NULL,    -- typed: in a composite index
  `tier` VARCHAR(16) NOT NULL,           -- typed: in a composite index
  `created_at` DATETIME(6) NOT NULL,     -- typed: in a composite index
  `doc` JSON,                            -- single merged JSON: everything else
  PRIMARY KEY (`id`)
) ENGINE=InnoDB ...
```

NOT this:

```sql
-- WRONG (Firestore variant's initial bug):
CREATE TABLE `users` (
  `id` VARCHAR(24),
  `country_code` VARCHAR(2),
  `tier` VARCHAR(16),
  `created_at` DATETIME(6),
  `email` JSON,                          -- WRONG: should be in `doc`
  `display_name` JSON,                   -- WRONG: should be in `doc`
  `preferences` JSON,                    -- WRONG: should be in `doc`
  ...
)
```

## Decision algorithm

The default policy is `auto`, which runs per collection:

```
FOR each collection c:
    indexed_field_paths = {fields appearing in any composite index for c}
    polymorphic_field_paths = {fields with >1 non-null type in BSON-aware samples}

    IF len(indexed_field_paths) == 0 AND polymorphic_field_ratio(c) > 0.30:
        policy(c) = JSON-mostly
    ELIF len(indexed_field_paths) == 0:
        policy(c) = JSON-mostly         // no query parity needed
    ELIF len(indexed_field_paths ∩ polymorphic_field_paths) > 0:
        policy(c) = Hybrid              // flagged-for-review fields
    ELSE:
        policy(c) = Hybrid              // typed cols for indexed, JSON for rest
```

**Normalized is never chosen automatically.** It is opt-in only, per
collection, via config override. Choosing Normalized for a collection with
surprise polymorphism causes the convert to fail loudly at DDL time. Choosing
Hybrid degrades gracefully.

## Configuration override

In `tishift-mongodb.yaml`:

```yaml
convert:
  schema_policy_default: auto         # auto | json-mostly | hybrid | normalized
  per_collection:
    users:
      policy: normalized
    audit_logs:
      policy: json-mostly
    products:
      policy: hybrid
      flatten_columns: [price, sku, name]    # force these into typed cols
      json_columns: [attributes, metadata]   # force these into the merged JSON
      poly_fields:
        price:
          decision: json              # coerce | json | skip
```

## Per-collection report

The convert phase emits `convert-plan.json` with the policy decision and
rationale for every collection. Same shape as the Firestore variant —
including `flagged_for_review` for polymorphic-in-indexed fields.

## When to override `auto`

- **You know the customer's query patterns better than their indexes.** Some
  Mongo customers query via driver-level filters that don't surface as
  composite indexes. The signal is empty; Hybrid is wrong. Set `normalized`
  explicitly.
- **The collection is hot-path append-only** (audit logs, event streams).
  Set `json-mostly` regardless of indexes to avoid schema-evolution churn.
- **The collection is a configuration store with hand-crafted documents.**
  Normalized is usually wrong; JSON-mostly is right.

## Indexes follow the policy

- **Normalized**: composite indexes apply to typed columns directly.
- **Hybrid**: composite indexes on typed columns; functional indexes on
  JSON paths emitted when an indexed field happens to land in the merged
  `doc JSON`.
- **JSON-mostly**: composite indexes become functional indexes on JSON paths
  via generated columns. Multikey-array indexes use TiDB's `CAST(JSON_EXTRACT(...))
  AS ... ARRAY)` pattern.

Convert emits four SQL files:

1. `01-create-tables.sql` — applied before load (DDL must exist for ingest)
2. `02-create-indexes.sql` — applied after load (5–10× faster)
3. `03-foreign-keys.sql` — applied after load
4. `04-multi-valued-indexes.sql` — applied last, on settled data
