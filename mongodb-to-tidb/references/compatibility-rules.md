# MongoDB → TiDB Compatibility Rules

Loaded by SKILL.md Phase 3. Every rule has an ID, a condition expressed
against the Phase 2.5 checklist, the affected MongoDB feature, and the
action the user must take.

## Blockers

| ID | Condition | Feature | Action |
|---|---|---|---|
| BLOCKER-1 | `topology == "standalone"` AND `cutover_tolerance ∈ {minutes, hours}` | Standalone deployment cannot support Change Streams | Convert source to a single-node replica set (config change, no data move) before cutover, OR accept a longer read-only window. |
| BLOCKER-2 | `has_polymorphic_id == true` | `_id` field has mixed types across docs in a collection | TiDB PK must have one type. Per collection, choose: coerce all `_id` to string, split into per-type child tables, or skip the collection. |
| BLOCKER-3 | `csfle_field_count > 0` | Client-Side Field-Level Encryption (Binary subtype 6) | Encrypted fields are opaque without the original CSFLE client keys. If keys are unavailable, those fields must be excluded from migration and the application must be updated to not depend on them. |
| BLOCKER-4 | `aggregation_complexity_total > 100` AND aggregation advisor disabled | Heavy aggregation usage without rewrite guidance | Enable the aggregation advisor in `tishift-mongodb.yaml` (`convert.aggregation_advisor.enabled: true`) or commit to manual rewrite for every pipeline before proceeding to Phase 5. |
| BLOCKER-5 | `polymorphic_field_in_indexed_path == true` | Polymorphic field in a composite-indexed path | A composite index requires a single type per field. Per field: coerce in application, accept JSON column with degraded index parity, or skip. |
| BLOCKER-6 | `has_gridfs == true` | GridFS file storage | GridFS shards large files across `fs.files` + `fs.chunks` collections. TiDB has no equivalent. Offload files to object storage (S3/GCS/Azure Blob) BEFORE running TiShift. Application must be updated. |
| BLOCKER-7 | `mongo_version < "4.2"` AND `transaction_block_count > 0` | Pre-4.2 multi-doc transactions | TiDB transactions are stricter than pre-4.2 Mongo's. Upgrade Mongo to 4.2+ before migration, or accept that some atomic-multi-doc sequences may not behave identically. |

## Warnings

| ID | Condition | Feature | Action |
|---|---|---|---|
| WARNING-1 | `geospatial_index_count > 0` | 2dsphere / 2d / geoHaystack indexes | TiDB has limited spatial support. Either accept app-side proximity math, integrate an external geo service (PostGIS, Elasticsearch geo), or drop the queries. |
| WARNING-2 | `text_index_count > 0` AND `target_tier ∈ {starter, essential, dedicated}` | MongoDB text indexes | TiDB Cloud has FULLTEXT in some tiers; self-hosted lacks parity. Move to TiDB Cloud with FTS enabled, or integrate Elasticsearch / OpenSearch externally. |
| WARNING-3 | `wildcard_index_count > 0` | Wildcard indexes (indexing unknown / dynamic field names) | No TiDB equivalent. Wildcard indexes typically pair with JSON-mostly schema policy. Use per-path functional indexes on the JSON column where you know the dynamic key. |
| WARNING-4 | `partial_index_count > 0` | Partial indexes | Approximate via functional indexes on generated columns with the same filter predicate. Partial indexes proper arrive in TiDB v8.x. |
| WARNING-5 | `ttl_index_count > 0` | TTL indexes | Direct map to TiDB `TTL` clause on tables (v6.5+). Convert will emit. |
| WARNING-6 | `has_capped_collections == true` | Capped collections | No direct equivalent. Approximate via TTL + size-bounded delete job. Insertion-order guarantees are weaker. |
| WARNING-7 | `aggregation_pipeline_count > 0` AND aggregation advisor enabled | Aggregation pipelines present, advisor will produce rewrite suggestions | Advisor output is SUGGESTIONS, not guarantees. Every rewrite needs human review before production use. |
| WARNING-8 | `polymorphic_field_count > 0` AND NOT `polymorphic_field_in_indexed_path` | Polymorphic fields outside indexed paths | Default mapping: JSON column. Safe but lossy for downstream queries. |
| WARNING-9 | `topology == "sharded"` | Sharded cluster | Bulk load via `mongodump` against `mongos` is slow. TiShift orchestrates per-shard mongodump in parallel for faster loads. |
| WARNING-10 | `dbref_field_count > 0` | DBRef-style references | TiDB has no native cross-collection reference type. Map to VARCHAR FK with the target document path; FK constraint emitted when target collection in scope. |
| WARNING-11 | `decimal128_field_count > 0` | Decimal128 fields | Map to DECIMAL(38,11). Verify no values exceed 34-digit significand precision. |
| WARNING-12 | `total_data_gb_estimate > 1000` | Bulk size > 1 TB | `direct` strategy not viable. Use `mongodump-lightning` (TiDB-native, primary) or an adapter if available. Multi-day load expected. |
| WARNING-13 | `sparse_field_ratio > 0.30` | Many sparse fields | Indicates polymorphic schema across docs. JSON-mostly policy is likely the right fit. |
| WARNING-14 | `binary_field_count > 0` AND any Binary value > 5 MB | Large Binary fields | TiDB `LONGBLOB` supports up to 4 GiB but bloats rows. Recommend offloading values > 5 MB to object storage with a path column. |
| WARNING-15 | `mongo_version < "4.0"` | Pre-4.0 Mongo | No Change Streams. Recommend upgrade before any CDC-based cutover. |
| WARNING-16 | `topology == "standalone"` AND `cutover_tolerance == "weekend"` | Standalone with weekend cutover (acceptable) | No CDC needed. Bulk load via `mongodump` during the read-only window. Documented as informational only. |

## Compatible patterns

Patterns that map cleanly with no special handling:

- Int32 (→ `INT`), Int64 (→ `BIGINT`), Double (→ `DOUBLE`), Boolean (→ `TINYINT(1)`), Null (column nullable)
- Date (→ `DATETIME(6)` — Mongo's millisecond precision over-fits to microsecond cleanly)
- ObjectId (→ `VARCHAR(24)` hex form — preserves DBRef compatibility)
- Decimal128 (→ `DECIMAL(38,11)` — covers 34-digit significand)
- UUID Binary subtype 4 (→ `BINARY(16)`)
- Shallow stable-shape subdocuments → flattened columns
- Arrays of scalars → JSON column with optional multi-valued index
- Multi-doc transactions (Mongo 4.2+) → TiDB transactions (full ACID)
- TTL field policies → TiDB `TTL` clause on tables (v6.5+)
- Multikey indexes (array fields) → TiDB multi-valued indexes
- Aggregate `count()` (Mongo) → `SELECT COUNT(*)` (TiDB)
- Composite secondary indexes → standard MySQL composite indexes
- 16 MiB document size limit → TiDB JSON column ceiling is far higher
- Foreign-key semantics → TiDB v6.6+ enforces FKs (strict improvement)

## Non-issues that other migrations face

Absent in MongoDB:

- **Stored procedures, triggers, UDFs, views** — Mongo has none. No procedural-code conversion phase.
- **Engine selection** — managed by WiredTiger; not applicable.
- **Character set / collation defaults** — Mongo is UTF-8; map to `utf8mb4_bin` for TiDB columns.

This is why MongoDB's scoring engine weights "Application Coupling" at 25
(higher than other variants) — the equivalent migration risk lives in
aggregation pipelines, not stored procedures.
