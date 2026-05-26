# MongoDB → TiDB Scoring Engine

Loaded by SKILL.md Phase 4. Produces a 0–100 readiness score from the
Phase 2.5 checklist. Every deduction is traceable; no hidden penalties.

## Category weights

MongoDB uses **20 / 20 / 20 / 25 / 15** — Application Coupling weighted higher
than other variants because the aggregation pipeline is the dominant migration
risk and is application code, not data. Operational Readiness weighted higher
because there are more cloud-environment and topology decisions.

| Category | Weight | What it measures |
|---|---|---|
| Schema Inferability | 20 | Can a clean target schema be inferred? Polymorphic fields, sparse data, polymorphic `_id`, deep nesting all reduce this. |
| Data Complexity | 20 | Bulk size, BLOB/binary usage, GridFS, subdocument depth. |
| Query/Index Coverage | 20 | Can the customer's query patterns be preserved? Geospatial, text, wildcard, partial indexes all reduce this. |
| Application Coupling | 25 | Aggregation pipeline count + complexity, CSFLE usage, GridFS, capped collections, transaction count. |
| Operational Readiness | 15 | Topology (standalone is bad), Mongo version, CDC provider availability, cloud topology, sync needed. |

## Per-category deductions

```
// Category 1: Schema Inferability (20 points max)
SET schema_score = 20
IF polymorphic_field_count > 5 THEN schema_score -= 4
IF polymorphic_field_count > 20 THEN schema_score -= 4   // additional
IF sparse_field_ratio > 0.30 THEN schema_score -= 3
IF subdocument_max_depth > 5 THEN schema_score -= 3
IF has_polymorphic_id THEN schema_score -= 6
IF schema_score < 0 THEN schema_score = 0

// Category 2: Data Complexity (20 points max)
SET data_score = 20
IF total_data_gb > 1000 THEN data_score -= 4
IF total_data_gb > 5000 THEN data_score -= 4   // additional
IF has_gridfs THEN data_score -= 4
IF binary_field_total_gb > 100 THEN data_score -= 2
IF largest_collection_doc_count > 1_000_000_000 THEN data_score -= 3
IF data_score < 0 THEN data_score = 0

// Category 3: Query/Index Coverage (20 points max)
SET query_score = 20
IF geospatial_index_count > 0 THEN query_score -= 4
IF text_index_count > 0 AND target_tier IN ("starter","essential") THEN query_score -= 3
IF text_index_count > 0 AND target_tier IN ("dedicated","byoc") THEN query_score -= 1
IF wildcard_index_count > 0 THEN query_score -= 3
IF polymorphic_field_in_indexed_path THEN query_score -= 6
IF composite_index_count > 200 THEN query_score -= 3
IF query_score < 0 THEN query_score = 0

// Category 4: Application Coupling (25 points max) — the big one for Mongo
SET coupling_score = 25
IF aggregation_complexity_total > 200 THEN coupling_score -= 10
ELIF aggregation_complexity_total > 50 THEN coupling_score -= 6
ELIF aggregation_complexity_total > 10 THEN coupling_score -= 3
IF csfle_field_count > 0 THEN coupling_score -= 5
IF has_gridfs THEN coupling_score -= 3
IF has_capped_collections THEN coupling_score -= 2
IF transaction_block_count > 50 THEN coupling_score -= 2
IF coupling_score < 0 THEN coupling_score = 0

// Category 5: Operational Readiness (15 points max)
SET ops_score = 15
IF topology == "standalone" THEN ops_score -= 6   // no CDC, hurts most cutovers
IF topology == "sharded" AND load_strategy NOT IN ("aws-dms","datastream-lightning","mongodump-lightning") THEN ops_score -= 3
IF cutover_tolerance IN ("minutes","hours") AND topology == "standalone" THEN ops_score -= 4
IF mongo_version < "4.2" THEN ops_score -= 2
IF mongo_version < "4.0" THEN ops_score -= 2   // additional
IF ops_score < 0 THEN ops_score = 0

// Final
SET overall_score = schema_score + data_score + query_score + coupling_score + ops_score
```

## Rating thresholds

| Score | Rating | Action |
|---|---|---|
| 85–100 | EXCELLENT | Migration is straightforward; proceed. |
| 70–84 | GOOD | Migration is feasible; address warnings before convert. |
| 55–69 | MODERATE | Migration possible but application changes required. |
| 40–54 | DIFFICULT | Significant application rewrite needed; consider phased migration. |
| 0–39 | NOT RECOMMENDED | Re-evaluate; possibly stay on Mongo + use TiDB as a downstream system. |

## Worked example

```
topology = replica_set
mongo_version = 7.0.4
total_data_gb = 800
composite_index_count = 45
geospatial_index_count = 2
text_index_count = 0
wildcard_index_count = 0
polymorphic_field_count = 6
polymorphic_field_in_indexed_path = false
has_polymorphic_id = false
sparse_field_ratio = 0.18
subdocument_max_depth = 4
has_gridfs = false
csfle_field_count = 0
has_capped_collections = false
aggregation_pipeline_count = 12
aggregation_complexity_total = 75
transaction_block_count = 0
cutover_tolerance = weekend
target_tier = byoc
```

Computation:

- Schema Inferability: 20 − 4 (poly>5) = **16**
- Data Complexity: 20 − 0 (size < 1TB) = **20**
- Query/Index Coverage: 20 − 4 (geospatial) = **16**
- Application Coupling: 25 − 6 (agg > 50) = **19**
- Operational Readiness: 15 − 0 (replica set, 4.2+, weekend) = **15**

Total: 16 + 20 + 16 + 19 + 15 = **86 / 100 → EXCELLENT**

Interpretation: minor surface area to address (6 polymorphic fields, 2
geospatial indexes, 12 aggregations with moderate complexity). The geospatial
queries need app-side or external geo handling; the aggregations need rewrite
suggestions reviewed; the polymorphic fields probably land in JSON columns
under the Hybrid policy. No BLOCKERs.
