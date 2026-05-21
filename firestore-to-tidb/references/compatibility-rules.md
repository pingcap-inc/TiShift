# Firestore → TiDB Compatibility Rules

Loaded by `SKILL.md` Phase 3 (Assess Compatibility). Every rule has an ID, a
condition expressed against the Phase 2.5 checklist, the affected Firestore
feature, and the action a user must take.

## Blockers

A blocker is a finding that prevents the migration from proceeding without
intervention. Some blockers (BLOCKER-1) cause an immediate abort and redirect.
Others (BLOCKER-2) require application-side changes that must be confirmed
complete before Phase 5.

| ID | Condition | Feature | Action |
|---|---|---|---|
| BLOCKER-1 | `mode == "mongo-api"` OR `edition == "enterprise"` AND MongoDB-compatibility API enabled | Firestore Enterprise with MongoDB-compatibility API | Abort this skill. The MongoDB API surface is best served by the `mongo-to-tidb` skill — different drivers, different scan strategy, different bulk-load tools. |
| BLOCKER-2 | `has_realtime_listeners == true` | App uses `onSnapshot` listeners | TiDB has no equivalent of realtime listeners. Application rewrite required: poll TiDB, use TiCDC → Kafka → application subscribers, or keep Firestore as a realtime tier alongside TiDB. Confirm app rewrite complete before Phase 5. |
| BLOCKER-3 | `security_rules_complexity == "complex"` AND rules contain cross-document references or function calls | Multi-doc / function-call security rules | Cannot auto-translate. Rewrite to application-layer authorization. The scan emits a rules listing for manual review. |
| BLOCKER-4 | `polymorphic_field_in_indexed_path == true` | Heterogeneous types in composite-indexed fields | A composite index requires a single type per field. Either coerce in application code (write a backfill job that normalizes all values to one type) or accept JSON-mostly mapping for that field with degraded index parity. Ask the user per field. |
| BLOCKER-5 | `multiple_databases_in_project == true` AND `cross_database_references == true` | Cross-database `DocumentReference` | TiShift v1 migrates one Firestore database per run. Cross-database references break. Plan a multi-pass migration with database ordering. |
| BLOCKER-6 | `mode == "datastore"` | Firestore in Datastore mode | v1 supports Datastore mode at limited fidelity (entity enumeration only, no subcollection semantics). Recommend the user confirm whether their workload fits the Datastore-mode subset or wait for v1.x full support. |

## Warnings

A warning is a finding the user should know about but that does not block the
migration. Warnings inform scoring, surface in the convert advisor, and shape
the per-collection schema policy.

| ID | Condition | Feature | Action |
|---|---|---|---|
| WARNING-1 | `geopoint_field_count > 0` | GeoPoint columns | Default mapping: each GeoPoint splits into `<field>_lat DECIMAL(9,6)` + `<field>_lng DECIMAL(9,6)`. TiDB has limited spatial indexing, so range queries work but proximity queries require application-side math. Alt mapping: store as `JSON {"lat":..., "lng":...}` if app uses GeoPoint as opaque payload. |
| WARNING-2 | `bytes_field_max_size_mb > 5` | Large binary documents | TiDB `LONGBLOB` supports up to 4 GiB but bloats rows. Recommend offloading values >5 MB to GCS with a path column instead. The convert advisor surfaces this per field. |
| WARNING-3 | `subcollection_count > 50` | Many subcollections | Each becomes a child table; operational complexity scales linearly. Consider collection-group flattening for high-cardinality subcollection names. |
| WARNING-4 | `timestamp_field_count > 0` | Nanosecond Timestamp precision | TiDB `DATETIME(6)` is microsecond. Three digits of precision lost. Acceptable for almost all applications. |
| WARNING-5 | `server_timestamp_sentinel_detected == true` | `FieldValue.serverTimestamp()` writes | Application writes must drop the sentinel; the column gets `DEFAULT CURRENT_TIMESTAMP(6)` server-side. Sample sentinel occurrences are noted in the convert advisor. |
| WARNING-6 | `composite_index_count > 100` | Heavy query workload | High value (the migration escapes Firestore's index sprawl) but the convert phase emits all parity indexes, which can take hours each to build at multi-TB scale. Plan the build order. |
| WARNING-7 | `polymorphic_field_count > 0` AND `polymorphic_field_in_indexed_path == false` | Polymorphic fields outside indexed paths | Default mapping = JSON column. Safe but lossy for downstream queries. |
| WARNING-8 | `total_data_gb_estimate > 5000` | Bulk size > 5 TB | Direct SDK strategy is not viable; Dataflow + Lightning is mandatory. Multi-day Dataflow jobs require checkpointing and per-collection retries. Surface time and cost estimate. |
| WARNING-9 | `document_reference_field_count > 0` AND any reference target is outside the scoped database | Dangling DocumentReference | The FK constraint cannot be created. Either expand scan scope to include the target collection or leave the column as unindexed `VARCHAR`. |
| WARNING-10 | `auto_id_generation_in_use == true` | Firestore auto-generated 20-char IDs | Default: preserve as `VARCHAR(20) PRIMARY KEY` to keep DocumentReference values intact. Switching to `AUTO_RANDOM` requires rewriting all FK columns and is opt-in only. |
| WARNING-11 | `firestore_bigquery_export_present == false` AND `cutover_tolerance == "minutes"` | CDC required, extension not installed | Customer must install `firestore-bigquery-export` per in-scope collection ≥7 days before cutover so change history accumulates. Convert phase emits the install manifest. |
| WARNING-12 | `cross_database_references == false` AND `multiple_databases_in_project == true` | Multi-database project, no cross-DB refs | The current scope migrates one database. Plan separate runs for siblings. Operational only — does not block. |
| WARNING-13 | `sparse_field_ratio > 0.30` | Many sparse fields | Indicates a polymorphic schema (different document shapes in the same collection). Most or all sparse fields end up nullable. Surface in advisor — user may prefer JSON-mostly for these collections. |

## Compatible patterns

Patterns that map cleanly with no special handling. Included here so the
assessment can give credit where credit is due, not just flag problems.

- Scalar string / number / boolean / null fields → typed MySQL columns
- Shallow stable-shape maps (≤2 levels, consistent keys) → flattened columns
- Arrays of scalars → JSON column with optional multi-valued index
- Multi-doc transactions → TiDB transactions (full ACID)
- TTL field policies → TiDB `TTL` clause on tables (v6.5+)
- Aggregate `count()` → `SELECT COUNT(*)`
- Composite secondary indexes → standard MySQL composite indexes
- Document size limits → TiDB JSON column far exceeds Firestore's 1 MiB
- Foreign-key semantics → TiDB v6.6+ enforces FKs (strict improvement over
  Firestore, which has no FK enforcement)

## Non-issues that other migrations face

These are absent in Firestore, which simplifies the migration relative to SQL
sources:

- **Stored procedures** — none in Firestore. No procedural-code phase.
- **Triggers** — none. Cloud Functions are application-layer and out of scope.
- **UDFs, sequences, views, check constraints** — none.
- **Engine selection / row format** — managed by Firestore; not applicable.
- **Character set / collation defaults** — Firestore is UTF-8 throughout; map
  to `utf8mb4_bin` for all TiDB columns.

This is why Firestore's scoring engine reweights the "Procedural Code" slot
(20 points in SQL sources) as "Application Coupling" — the equivalent
migration risk has moved from the database into the application layer.
