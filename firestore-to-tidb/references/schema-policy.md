# Schema Policy Engine

How TiShift decides whether each Firestore collection lands in TiDB as
**normalized**, **JSON-mostly**, or **hybrid**.

## The three policies

### Normalized

Top-level scalar fields become typed columns; subcollections become child
tables; arrays of objects become child tables; shallow maps flatten to
columns; deeper maps land in JSON columns. DocumentReferences become FK
columns where the target collection is in scope.

Best for: collections that participate in composite indexes, have stable
shape across documents, and will be queried by indexed field paths in TiDB.

Trade-off: most engineering work upfront; best post-migration query
performance and TiDB-native experience.

### JSON-mostly

A primary-key column plus a single `doc JSON` column holding the entire
document body. Subcollections still become child tables (so they remain
queryable independently), but the parent document body stays denormalized.

Best for: collections with no composite indexes, polymorphic schemas, or
truly key-value usage patterns (audit logs, raw events, session blobs).

Trade-off: minimal engineering work; query performance via JSON_EXTRACT and
optional functional indexes; less natural for downstream relational tooling.

### Hybrid

Typed columns for the fields that appear in composite indexes; a `doc JSON`
column for everything else. The default policy when a collection has
composite indexes but most of its fields are not indexed.

Best for: most real-world collections. Preserves the customer's existing
query patterns (indexed fields are first-class columns) while not forcing
typed-column engineering on every field.

Trade-off: writes touch two surfaces (typed cols + JSON). At Firestore's
size scale this is invisible; at TiDB's, the row size is larger than pure
normalized.

## Decision algorithm

The default policy is **auto**, which runs this algorithm per collection:

```
FOR each collection c:
    indexed_field_paths = {fields appearing in any composite index for c}
    polymorphic_field_paths = {fields with >1 non-null type in samples}

    IF len(indexed_field_paths) == 0 AND polymorphic_field_ratio(c) > 0.30:
        policy(c) = JSON-mostly
    ELIF len(indexed_field_paths) == 0:
        policy(c) = JSON-mostly        // no query parity needed; keep simple
    ELIF len(indexed_field_paths ∩ polymorphic_field_paths) > 0:
        policy(c) = Hybrid             // flagged-for-review fields
    ELSE:
        policy(c) = Hybrid             // typed cols for indexed, JSON for rest
```

**Normalized is never chosen automatically.** It is opt-in only, per
collection, via config override. This is intentional: choosing Normalized for
a collection with surprise polymorphism causes the convert to fail loudly at
DDL time. Choosing Hybrid degrades gracefully.

## Configuration override

In `tishift-firestore.yaml`:

```yaml
convert:
  schema_policy_default: auto         # auto | json-mostly | hybrid | normalized
  per_collection:
    users:
      policy: normalized              # force normalized for this collection
    audit_logs:
      policy: json-mostly             # force JSON-mostly even if it has indexes
    products:
      policy: hybrid
      flatten_columns: [price, sku, name]      # force these into typed cols
      json_columns: [attributes, metadata]     # force these into JSON
      poly_fields:
        price:
          decision: coerce-to-double   # accept lossy coercion at convert time
```

## Per-collection report

The convert phase emits `convert-plan.json` with the policy decision and
rationale for every collection:

```json
{
  "collections": [
    {
      "name": "users",
      "policy": "hybrid",
      "rationale": "Composite indexes present (3); 1 polymorphic field outside indexed paths.",
      "typed_columns": ["id", "email", "age", "created_at"],
      "json_columns": ["preferences"],
      "child_tables": ["users_orders", "users_orders_items"],
      "flagged_for_review": []
    },
    {
      "name": "products",
      "policy": "hybrid",
      "rationale": "Composite indexes present; price field is polymorphic in indexed path.",
      "typed_columns": ["id", "sku", "name", "category_ref"],
      "json_columns": ["attributes", "price"],
      "child_tables": [],
      "flagged_for_review": ["price (BLOCKER-4 — choose coerce / json / skip)"]
    },
    {
      "name": "audit_logs",
      "policy": "json-mostly",
      "rationale": "No composite indexes; 41% sparse fields.",
      "typed_columns": ["id", "created_at"],
      "json_columns": ["doc"],
      "child_tables": [],
      "flagged_for_review": []
    }
  ]
}
```

## Indexes follow the policy

- Normalized: composite indexes apply to the typed columns directly.
- Hybrid: composite indexes apply to the typed columns directly; functional
  indexes on JSON paths are emitted only if a composite index references a
  field that ended up in the JSON column.
- JSON-mostly: composite indexes become functional indexes on JSON paths via
  generated columns. Multi-valued indexes for array fields use TiDB's
  `CAST(JSON_EXTRACT(...) AS UNSIGNED ARRAY)` pattern.

The convert phase emits four SQL files:

1. `01-create-tables.sql` — applied before load (DDL must exist for ingest)
2. `02-create-indexes.sql` — applied after load (5–10× faster than ingest-with-indexes)
3. `03-foreign-keys.sql` — applied after load
4. `04-multi-valued-indexes.sql` — applied last, after the data is settled

## When to override `auto`

- **You know the customer's query patterns better than their indexes.** Some
  Firestore customers query via SDK predicates that auto-create single-field
  indexes but never composite ones. The composite-index signal is empty;
  Hybrid is wrong. Set `policy: normalized` for those collections explicitly.
- **The collection is hot-path append-only.** Audit logs, event streams. Set
  `policy: json-mostly` even if there happen to be composite indexes, to
  avoid the schema-evolution headache as new event types appear.
- **The collection is a configuration store with hand-crafted documents.**
  Normalized is usually wrong because schema drifts deliberately; JSON-mostly
  is right.

## What this policy is NOT

This is not a query rewriter. It produces a target schema; the application
still has to issue TiDB queries by writing SQL. The policy's purpose is to
make those SQL queries possible with reasonable performance.

If the customer wants their existing Firestore SDK code to "just work" against
TiDB, they need a higher-level compatibility layer (out of scope for v1).
