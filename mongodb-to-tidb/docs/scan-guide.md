# Scan Guide

What `tishift-mongodb scan` does, how to tune it, how to read its output.

## What the scan does

MongoDB is schemaless. The scan infers schema by sampling documents — but
with one strict improvement over schemaless-source scans elsewhere: **BSON
types are read directly from the wire, not inferred from values.** This
gives strictly better type fidelity than what's possible with JSON-only
sources.

For each collection:

1. Detect topology (standalone / replica set / sharded).
2. Sample N documents — 200 by default, 1% of collection capped at 5,000.
3. For each sampled doc, walk every field path and record `(path, bson_type)`.
4. Aggregate into a type histogram per field:
   - 100% one type → that type, NOT NULL
   - ≥95% one type with rest null → that type, NULL
   - Multiple non-null types → **polymorphic**, flag for review
   - Field missing from >25% of docs → **sparse**, flag as nullable
5. Inventory composite indexes (single, compound, multikey, 2dsphere, text, wildcard, partial, sparse, TTL, hashed).
6. Inventory aggregation pipelines (Atlas Performance Advisor → `system.profile` → user file, in priority order).
7. Profile data size (`dbStats`).

Cost: ~1 Mongo read per sampled document. A 50-collection database scan at
defaults reads ~10,000 documents.

## Running it

```bash
tishift-mongodb scan --config tishift-mongodb.yaml --format cli --format json
```

Output:
- `tishift-reports/mongodb-scan-report.json` — machine-readable
- CLI panel — Rich-rendered summary

JSON report shape:

```json
{
  "scan_started_at": "2026-05-20T03:00:00Z",
  "scan_completed_at": "2026-05-20T03:08:42Z",
  "topology": "replica_set",
  "mongo_version": "7.0.4",
  "database": "myapp",
  "collections": [
    {
      "name": "users",
      "estimated_count": 1234567,
      "sampled_count": 200,
      "id_type": "ObjectId",
      "fields": {
        "email": {"types": {"String": 200}, "presence_ratio": 1.0},
        "age": {"types": {"Int32": 187, "null": 13}, "presence_ratio": 1.0},
        "location": {"types": {"Object": 198, "null": 2}, "presence_ratio": 1.0},
        "tags": {"types": {"Array": 142, "null": 58}, "presence_ratio": 1.0,
                 "array_element_type": "String"}
      },
      "indexes": [
        {"name": "_id_", "fields": [{"name": "_id", "direction": 1}], "unique": true},
        {"name": "email_1", "fields": [{"name": "email", "direction": 1}], "unique": true},
        {"name": "country_tier_created", "fields": [{"name": "country_code", "direction": 1},
                                                    {"name": "tier", "direction": 1},
                                                    {"name": "created_at", "direction": -1}]}
      ],
      "polymorphic_fields": [],
      "sparse_fields": []
    }
  ],
  "aggregation_pipelines": [
    {
      "id": "orders.monthly-by-status",
      "collection": "orders",
      "stages": ["$match", "$group", "$sort"],
      "complexity": 5,
      "source": "system.profile"
    }
  ],
  "data_profile": {
    "total_storage_gb": 0.85,
    "total_index_storage_gb": 0.12
  }
}
```

## Tuning

| Setting | Default | When to change |
|---|---|---|
| `scan.sample_size_per_collection` | 200 | Increase for noisier schemas; cost scales linearly. |
| `scan.full_scan_threshold_docs` | 5000 | Below this size, scan reads every doc (exact field-presence ratios). |
| `scan.subdocument_max_depth` | 10 | Cap recursion. Safety net for misconfigured-deep nesting. |
| `scan.inventory_aggregations` | true | Disable if you don't want Atlas API calls. |
| `scan.inventory_indexes` | true | Always leave on. |

## BSON type histograms

The histogram captures Mongo's actual wire types, not just Python class names:

```json
"price": {
  "types": {"Int32": 180, "Double": 18, "null": 2},
  "presence_ratio": 0.99,
  "is_polymorphic": true,
  "numeric_values_sample": [19, 24, 49, 999, ...]
}
```

This drives the convert phase's mapping decision: `Int32` + `Double` polymorphism
maps to `DOUBLE` (lossless promotion). Mixed `Int32` + `Object` would be a
BLOCKER-5 if the field is in a composite index.

## Reading the polymorphic and sparse flags

**Polymorphic** (multiple non-null types):

```json
{"price": {"types": {"Int32": 180, "Object": 18, "null": 2}, "is_polymorphic": true}}
```

→ Default JSON column. BLOCKER-5 if in composite index.

**Sparse** (presence < 75%):

```json
{"deprecated_legacy_id": {"types": {"String": 14, "null": 0}, "presence_ratio": 0.07}}
```

→ Nullable. Convert advisor recommends dropping if presence < 5%.

## Aggregation inventory

Three sources, in priority order:

1. **Atlas Performance Advisor** — Atlas-only. Requires Atlas Admin API access and the role `atlasAdmin` or specific project-level read.
2. **`system.profile`** — Self-hosted Mongo. Requires profiling enabled (level 1 or 2). Captures pipelines that ran in the last profile window.
3. **User-supplied** — Operator places `aggregations.json` in the config dir with a JSON array of representative pipelines:

```json
[
  {"id": "orders.monthly-by-status", "collection": "orders",
   "pipeline": [{"$match": {...}}, {"$group": {...}}]},
  {"id": "users.active-count", "collection": "users",
   "pipeline": [{"$match": {...}}, {"$count": "active"}]}
]
```

Inventoried pipelines drive Application Coupling scoring (via complexity totals)
and the aggregation rewrite advisor (in Phase 5).

## What scan does NOT detect

- **Aggregation pipelines never executed** — only what's in Performance Advisor or `system.profile`. Cold pipelines must be supplied manually.
- **Application-side query patterns from driver logs.** These would need source-code analysis (out of scope for v1).
- **CSFLE keys** — even if encrypted fields are detected, the keys are client-side and not visible to the scan.
- **GridFS usage** — usually detectable from `fs.files` / `fs.chunks` collection presence, but the user is also asked directly in Phase 2.2.

## Resumability

The scan writes intermediate state to `tishift-reports/.scan-state.json` every
10 collections. Restart with the same command — completed collections are
skipped.

To force a full re-scan:

```bash
tishift-mongodb scan --config tishift-mongodb.yaml --force-full
```
