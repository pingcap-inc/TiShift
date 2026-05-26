# Scan Guide

What `tishift-firestore scan` does, how to tune it, and how to read its output.

## What the scan does

Firestore has no `information_schema`. The scan infers schema by sampling
documents. For each collection (and each subcollection it discovers
recursively):

1. Sample N documents — 200 by default, or 1% of the collection, capped at 5,000.
2. For each sampled document, walk every field path and record `(path, type)`.
3. Aggregate into a type histogram: `users/email: {string: 200, null: 0}`.
4. Apply inference rules:
   - 100% of values are one type → that type
   - ≥95% are one type with the rest null → that type, nullable
   - Multiple non-null types → **polymorphic**, flag for review
   - Field missing from >25% of docs → **sparse**, flag as nullable
5. For each document, list its subcollections (`doc.collections()`). Recurse.
6. Enumerate composite indexes via the Firestore Admin API.
7. Pull data-size metrics from Cloud Monitoring (`firestore.googleapis.com/document/storage_bytes`).

Cost: roughly 1 read operation per sampled document, charged by Firestore at
~$0.06 per 100,000. A 50-collection database scan at default settings costs
roughly $0.01.

## Running it

```bash
tishift-firestore scan --config tishift-firestore.yaml --format cli --format json
```

Output:
- `tishift-reports/firestore-scan-report.json` — machine-readable report
- CLI panel — Rich-rendered summary

The JSON report contains:

```json
{
  "scan_started_at": "2026-05-15T03:00:00Z",
  "scan_completed_at": "2026-05-15T03:11:42Z",
  "project_id": "...",
  "database_id": "(default)",
  "mode": "native",
  "edition": "standard",
  "collections": [
    {
      "name": "users",
      "estimated_count": 1234567,
      "sampled_count": 200,
      "fields": {
        "email": {"types": {"string": 200}, "presence_ratio": 1.0},
        "age": {"types": {"number": 187, "null": 13}, "presence_ratio": 1.0},
        "location": {"types": {"geopoint": 198, "null": 2}, "presence_ratio": 1.0},
        "preferences": {"types": {"map": 200}, "presence_ratio": 1.0, "map_keys": ["theme", "lang"]},
        "tags": {"types": {"array": 142, "null": 58}, "presence_ratio": 1.0, "array_element_type": "string"}
      },
      "subcollections": ["orders", "sessions"],
      "polymorphic_fields": [],
      "sparse_fields": []
    },
    ...
  ],
  "composite_indexes": [
    {"collection": "orders", "fields": [{"name": "status", "order": "ASC"}, {"name": "created_at", "order": "DESC"}], "scope": "COLLECTION"}
  ],
  "data_profile": {
    "total_storage_bytes": 7340032000000,
    "total_index_storage_bytes": 73400320000000
  }
}
```

## Tuning

| Setting | Default | When to change |
|---|---|---|
| `scan.sample_size_per_collection` | 200 | Increase for noisier schemas (e.g., 500–1000) when default samples miss rare field shapes. Cost scales linearly. |
| `scan.full_scan_threshold_docs` | 5000 | Below this size, the scan reads every document. Increase if you want exact field-presence ratios on slightly larger collections. |
| `scan.subcollection_max_depth` | 10 | Cap the recursion depth. Useful as a safety net if a misconfigured app has accidentally created deeper-than-expected nesting. |
| `scan.parent_sample_for_subcollections` | 100 | How many parent docs to descend into when looking for subcollections. Increase if your subcollection layout is non-uniform across parents. |

## Reading the polymorphic and sparse flags

A **polymorphic** field has multiple non-null types in samples:

```json
{"price": {"types": {"number": 180, "map": 18, "null": 2}, "presence_ratio": 0.99}}
```

Action: in the convert phase, this field will get the JSON policy by
default. If it appears in a composite index, BLOCKER-4 fires and the user
must choose: coerce, accept JSON, or skip.

A **sparse** field appears in less than 75% of sampled docs:

```json
{"deprecated_legacy_id": {"types": {"string": 14, "null": 0}, "presence_ratio": 0.07}}
```

Action: the field becomes nullable. If presence is below 5%, the convert
advisor recommends dropping it (the user can override).

## What the scan does NOT detect

- **Realtime listener usage in the app.** No way to detect from data. The
  SKILL flow asks the user directly.
- **Sentinel-write patterns in app code.** TiShift detects `serverTimestamp`
  sentinel values that landed in sampled documents, but not the original SDK
  call sites in the application. A separate code scan (out of scope for v1)
  could find these.
- **Security rule complexity.** Asked of the user as part of Phase 2.
- **Per-document write rate.** Firestore doesn't expose this directly. Cloud
  Monitoring has aggregate counters; per-doc hot spots aren't visible to
  scan.

## Resumability

The scan writes intermediate state to `tishift-reports/.scan-state.json`
every 10 collections. If interrupted, restart with the same command — it
will skip collections marked complete.

To force a full re-scan:

```bash
tishift-firestore scan --config tishift-firestore.yaml --force-full
```
