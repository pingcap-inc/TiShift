# Firestore → TiDB Scoring Engine

Loaded by `SKILL.md` Phase 4 (Score). Produces a 0–100 readiness score from
the Phase 2.5 checklist. Every deduction is traceable to a condition; no
hidden penalties.

## Category weights

Firestore uses **25 / 20 / 25 / 20 / 10**, different from SQL sources. The
weighting reflects that Firestore has no procedural code (so the SQL-source
"Procedural Code" slot is repurposed as "Application Coupling") and that the
biggest migration risks come from schema inferability and application
coupling, not from query translation or stored-procedure rewrites.

| Category | Weight | What it measures |
|---|---|---|
| Schema Inferability | 25 | Can a clean target schema be inferred from sampling? Polymorphic fields, sparse data, and deep nesting reduce this. |
| Data Complexity | 20 | Bulk size, BLOB usage, GeoPoint usage, subcollection topology. |
| Query/Index Coverage | 25 | Can the customer's query patterns be preserved? Composite index parity is the key signal. |
| Application Coupling | 20 | Realtime listeners, security rules complexity, sentinel-write usage. Replaces "Procedural Code" from SQL sources. |
| Operational Readiness | 10 | IAM/Workload Identity, BigQuery presence, network topology, cutover plan, BYOC project alignment. |

## Per-category deductions

```
// Category 1: Schema Inferability (25 points max)
SET schema_score = 25
IF polymorphic_field_count > 5 THEN schema_score -= 5
IF polymorphic_field_count > 20 THEN schema_score -= 5      // additional
IF sparse_field_ratio > 0.30 THEN schema_score -= 3
IF subcollection_max_depth > 5 THEN schema_score -= 3
IF mode == "datastore" THEN schema_score -= 5               // less feature-rich inference
IF mode == "mongo-api" THEN schema_score = 0                // automatic 0 → user was redirected
IF schema_score < 0 THEN schema_score = 0

// Category 2: Data Complexity (20 points max)
SET data_score = 20
IF total_data_gb_estimate > 1000 THEN data_score -= 4       // >1 TB
IF total_data_gb_estimate > 5000 THEN data_score -= 4       // >5 TB (additional)
IF bytes_field_max_size_mb > 5 AND bytes_field_count > 100 THEN data_score -= 3
IF subcollection_count > 50 THEN data_score -= 3
IF largest_collection_doc_count > 1_000_000_000 THEN data_score -= 3
IF data_score < 0 THEN data_score = 0

// Category 3: Query/Index Coverage (25 points max)
SET query_score = 25
IF composite_index_count == 0 THEN query_score -= 0         // no parity work — neutral
IF composite_index_count > 100 THEN query_score -= 4        // a lot to recreate
IF polymorphic_field_in_indexed_path == true THEN query_score -= 8
IF security_rules_complexity == "complex" THEN query_score -= 5   // rules gate queries
IF query_score < 0 THEN query_score = 0

// Category 4: Application Coupling (20 points max)
SET coupling_score = 20
IF has_realtime_listeners == true THEN coupling_score -= 10
IF security_rules_complexity == "complex" THEN coupling_score -= 5
IF security_rules_complexity == "moderate" THEN coupling_score -= 3
IF server_timestamp_sentinel_detected == true THEN coupling_score -= 1
IF array_union_remove_sentinel_detected == true THEN coupling_score -= 1
IF transaction_block_count > 50 THEN coupling_score -= 2
IF coupling_score < 0 THEN coupling_score = 0

// Category 5: Operational Readiness (10 points max)
SET ops_score = 10
IF target_tier == "byoc" AND byoc_in_same_gcp_project THEN ops_score -= 0   // ideal
IF target_tier == "byoc" AND byoc_in_different_gcp_project THEN ops_score -= 2
IF target_not_gcp THEN ops_score -= 5
IF firestore_bigquery_export_present == false AND cutover_tolerance == "minutes" THEN ops_score -= 2
IF workload_identity_unavailable THEN ops_score -= 1
IF ops_score < 0 THEN ops_score = 0

// Final
SET overall_score = schema_score + data_score + query_score + coupling_score + ops_score
```

## Rating thresholds

| Score | Rating | Action |
|---|---|---|
| 85–100 | EXCELLENT | Migration is straightforward; proceed. |
| 70–84 | GOOD | Migration is feasible; address warnings before convert. |
| 55–69 | MODERATE | Migration possible but application changes required; review blockers carefully. |
| 40–54 | DIFFICULT | Significant application rewrite needed; consider phased migration or scope reduction. |
| 0–39 | NOT RECOMMENDED | Re-evaluate: either too tightly coupled to Firestore primitives, or wrong-shape data for a relational target. |

## Worked example

Suppose the Phase 2.5 checklist returns:

```
mode = native
total_data_gb_estimate = 7000
composite_index_count = 87
polymorphic_field_count = 8
polymorphic_field_in_indexed_path = false
sparse_field_ratio = 0.18
subcollection_count = 23
subcollection_max_depth = 3
has_realtime_listeners = true
security_rules_complexity = moderate
server_timestamp_sentinel_detected = true
cutover_tolerance = weekend
target_tier = byoc
byoc_in_same_gcp_project = true
firestore_bigquery_export_present = true
```

Computation:

- Schema Inferability: 25 − 5 (poly>5) = **20**
- Data Complexity: 20 − 4 (>1TB) − 4 (>5TB) = **12**
- Query/Index Coverage: 25 − 3 (>100? no, but moderate rules) — actually,
  `composite_index_count == 87` is below 100, no deduction;
  `polymorphic_field_in_indexed_path == false`, no deduction;
  rules `moderate` doesn't trigger the rule-gated-query deduction (which keys
  off `complex`). **25**
- Application Coupling: 20 − 10 (listeners) − 3 (moderate rules) − 1 (server
  ts sentinel) = **6**
- Operational Readiness: 10 (BYOC same project, BQ extension installed). **10**

Total: 20 + 12 + 25 + 6 + 10 = **73 / 100 → GOOD**

Interpretation: the migration is feasible; the listener rewrite is the
dominant remaining work. If the listener question were resolved (no listeners
in critical paths), the score rises to 83 (still GOOD, near EXCELLENT).
