---
name: mongodb-to-tidb
description: >
  This skill should be used when users ask to migrate from MongoDB to TiDB,
  assess MongoDB compatibility with TiDB, convert MongoDB document schemas into
  relational schemas for TiDB, or load MongoDB data into TiDB. Examples:
  "migrate my MongoDB to TiDB", "is my MongoDB schema compatible with TiDB?",
  "help me move from Atlas to TiDB Cloud", "MongoDB to TiDB BYOC migration".
version: 0.1.0
references:
  - references/scoring.md
  - references/compatibility-rules.md
  - references/type-mapping.md
  - references/schema-policy.md
  - references/load-strategies.md
  - references/cdc-providers.md
  - references/aggregation-rewrite.md
---

# MongoDB to TiDB Migration

These are step-by-step instructions to execute, not a document to summarize.

## How This Works

MongoDB is a NoSQL document database, so this migration is unlike SQL → SQL
migrations. There is no fixed schema on the source side — schema is inferred
from sampling. Queries are method chains and aggregation pipelines, not SQL —
so query rewrite is a separate concern from schema migration. The central
decision per collection is **how documents land in TiDB**: normalized typed
columns, JSON-mostly (one wide JSON column), or hybrid (typed columns for
indexed fields, single merged JSON column for the rest).

Users run commands locally that connect to their MongoDB cluster. Process one
phase at a time — each phase's output determines the next. **TiShift's primary
paths are cloud-agnostic and TiDB-native** (no managed-service dependency).
Third-party tools (AWS DMS, GCP Datastream, Debezium) are supported as
adapters when the customer already operates them.

## Execution Rules

- **One command per step.** Output a single command, then say "Run this and
  paste the output." Each command's output informs the next step.
- **Always use the `tishift-mongodb` CLI** for TiShift operations, and `mongosh`
  / `mongodump` for any direct MongoDB interactions.
- **URI-based source connection.** MongoDB uses connection URIs of the form
  `mongodb://user:pass@host:27017/dbname?authSource=admin&replicaSet=rs0` or
  `mongodb+srv://user:pass@cluster.abc.mongodb.net/dbname`. Substitute the
  user's actual URI; never embed passwords in commands — always reference env
  vars (`$MONGO_URI`).
- **Database and collection are different scopes.** A Mongo cluster has many
  databases; each database has many collections. TiShift v1 migrates one
  Mongo database per run (mapped to one TiDB schema).
- **Topology matters.** A replica set or sharded cluster supports Change
  Streams (and therefore CDC). A standalone deployment does not — sync is
  unavailable on standalone. Phase 1 detects which you have.
- **Never skip phases.** Each phase's output is an input to the next.
- **Respect STOP AND CHECK gates.** Verify the listed conditions before
  continuing.
- **Respect the STOP AND ASK gate after Phase 4.** Do not proceed to Phase 5
  (convert) without explicit user confirmation. Many Mongo migrations stop
  here with the assessment as the deliverable.

## Error Recovery

If a step fails:
1. Read the error message carefully — MongoDB driver errors include error
   codes (PyMongo `OperationFailure.code`) and specific wire-protocol
   messages.
2. Common issues: authentication failure (code 18), unauthorized for action
   (code 13 — usually missing role grants), `NotPrimary` (code 10107 — failover
   in progress, retry), `NetworkTimeout` (transient), `CollectionNotFound`,
   `BadValue` (malformed URI).
3. Ask the user to fix and retry. Do not skip ahead.
4. If a step fails after retry, note it and ask the user how to proceed.

## Resumability

If interrupted, the user can resume by stating which phase was completed last.
Request the output of the last successful step to reconstruct context.

---

## Phase 1: Connect

**Goal:** Verify connectivity to MongoDB (read-only) and TiDB (target). Detect
deployment topology and Mongo version.

**Step 1.1 — Test MongoDB connection:**
```
mongosh "$MONGO_URI" --eval "db.runCommand({hello: 1}).ok"
```
Then say: "Run this and paste the output. The expected response is `1`."
WAIT for the user's response.

**Step 1.2 — Detect topology:**
After Step 1.1 succeeds:
```
mongosh "$MONGO_URI" --eval "JSON.stringify(db.runCommand({hello: 1}), null, 2)"
```
Then say: "Run this and paste the output."
WAIT for the user's response.

From the output, record:
- `$TOPOLOGY`:
  - If response includes `msg: "isdbgrid"` → `sharded`
  - Else if response includes `setName` → `replica_set`
  - Else → `standalone`
- `$MONGO_VERSION` — from `version` field in `buildInfo` (next step)

**Step 1.3 — Capture Mongo build info:**
```
mongosh "$MONGO_URI" --eval "JSON.stringify(db.runCommand({buildInfo: 1}), null, 2)"
```
Then say: "Run this and paste the output."
WAIT for the user's response.

Record `$MONGO_VERSION` (from `version` field).

**Step 1.4 — Test TiDB connection:**
```
mysql -h $TIDB_HOST -P 4000 -u $TIDB_USER -p$TIDB_PASS --ssl-mode=VERIFY_IDENTITY -e "SELECT VERSION()"
```
Then say: "Run this and paste the output."
WAIT for the user's response.

### STOP AND CHECK — Phase 1
- [ ] Step 1.1 returned `1`
- [ ] `$TOPOLOGY` is recorded
- [ ] `$MONGO_VERSION` is recorded
- [ ] TiDB returned a version string
- IF `$TOPOLOGY == "standalone"`: WARN — Change Streams unavailable, sync is
  not possible. Confirm with the user whether they accept a read-only cutover
  window OR will convert the source to a single-node replica set first.
- IF `$MONGO_VERSION < "4.2"`: WARN — multi-doc transactions are limited, CDC
  is less robust. Recommend upgrade.
- WHEN connections pass: ask "Is the TiDB target Starter, Essential,
  Dedicated, or BYOC?" Record as `$TIER`.
- Ask "Which storage backend will you use for staging during bulk load?
  s3 / gs / azure / local?" Record as `$STORAGE_BACKEND`.
- Then say "Phase 1 complete. Ready for Phase 2?"

---

## Phase 2: Scan

**Goal:** Sample-based schema inference (BSON-type-aware), index inventory,
aggregation pipeline inventory, topology details, data profile.

Phase 2 runs via the `tishift-mongodb` CLI. Sampling defaults: 200 docs per
collection or 1% of the collection, whichever is larger, capped at 5,000.

**Step 2.1 — Run the scan:**
```
tishift-mongodb scan --config tishift-mongodb.yaml --format cli --format json
```
Then say: "Run this and paste the output. The scan typically takes 2–20
minutes depending on collection count and aggregation inventory."
WAIT for the user's response.

The scan produces `tishift-reports/mongodb-scan-report.json` with:
- Database + collection inventory
- Per-field type histograms (from sampled BSON documents)
- Polymorphic field flags (fields with multiple non-null types)
- Sparse field flags (fields present in <75% of sampled docs)
- DBRef field map (candidate FKs)
- BSON-specific type counts (ObjectId, Decimal128, UUID, Binary, Date, etc.)
- Composite index inventory (single, compound, multikey, 2dsphere, text,
  wildcard, partial, sparse, TTL, hashed)
- Aggregation pipeline inventory (from Atlas Performance Advisor if available,
  else `system.profile`, else user-supplied)
- Document counts per collection (exact, via aggregate count())
- Storage size estimate (from `dbStats`)

**Step 2.2 — Ask the user three questions the scan cannot answer:**
After Step 2.1 completes, ask:

1. **Aggregation pipeline usage:** Are aggregation pipelines part of your
   application's hot path? How many distinct pipelines are in production use?
   (rough count is fine)
2. **GridFS usage:** Do you use GridFS to store large files (collections named
   `fs.files` and `fs.chunks`)?
3. **Cutover tolerance:** How long can the application be in read-only mode
   during cutover? (minutes / hours / weekend / longer)

Record these answers — they feed the scoring engine.

### STOP AND CHECK — Phase 2
- [ ] `mongodb-scan-report.json` was produced without error
- [ ] At least one collection was discovered
- [ ] Topology recorded matches what was detected in Phase 1
- [ ] User answered the three Phase 2.2 questions

---

## Phase 2.5: Collect Results into Checklist

**Goal:** Extract structured counts and flags for the assessment phase.

Read `mongodb-scan-report.json` and fill in every field below.

```
CHECKLIST:
  topology                          = <standalone | replica_set | sharded>
  mongo_version                     = <e.g., 7.0.4>
  database                          = <db name>
  collection_count                  = <number of collections>
  total_document_count_estimate     = <sum across collections>
  total_data_gb_estimate            = <from dbStats>
  composite_index_count             = <total composite indexes>
  geospatial_index_count            = <2dsphere + 2d + geoHaystack count>
  text_index_count                  = <number of text indexes>
  wildcard_index_count              = <number of wildcard indexes>
  partial_index_count               = <number of partial indexes>
  ttl_index_count                   = <number of TTL indexes>
  dbref_field_count                 = <fields containing $ref/$id>
  objectid_field_count              = <fields of type ObjectId>
  decimal128_field_count            = <fields of type Decimal128>
  binary_field_count                = <fields of type Binary (any subtype)>
  csfle_field_count                 = <fields with Binary subtype 6>
  date_field_count                  = <fields of type Date>
  has_polymorphic_id                = <TRUE if any collection's _id is mixed>
  polymorphic_field_count           = <fields with >1 non-null type>
  polymorphic_field_in_indexed_path = <TRUE if any polymorphic field is in
                                       an indexed path>
  sparse_field_ratio                = <sparse fields / total fields>
  subdocument_max_depth             = <deepest embedded doc seen>
  has_capped_collections            = <TRUE if any collection.options.capped>
  has_gridfs                        = <TRUE if user answered yes OR fs.files
                                       collection exists>
  aggregation_pipeline_count        = <from user answer + scan inventory>
  aggregation_complexity_total      = <sum of complexity scores from scan>
  transaction_block_count           = <from system.profile if available, else 0>
  cutover_tolerance                 = <minutes | hours | weekend | longer>
  target_tier                       = <starter | essential | dedicated | byoc>
  storage_backend                   = <s3 | gs | azure | local>
```

### STOP AND CHECK — Phase 2.5
- [ ] Every checklist field has a value
- [ ] No field says "unknown" or "N/A"
- [ ] `collection_count > 0`
- [ ] `topology` is one of standalone / replica_set / sharded

---

## Phase 3: Assess Compatibility

**Goal:** Classify every finding as BLOCKER, WARNING, or COMPATIBLE.

Use the checklist from Phase 2.5. Load and apply the rules from
`references/compatibility-rules.md`.

Emit a JSON list of triggered findings:

```json
[
  {"id": "BLOCKER-1", "severity": "BLOCKER",
   "feature": "Standalone topology blocks CDC",
   "action": "Convert source to single-node replica set, or accept read-only cutover."},
  {"id": "WARNING-1", "severity": "WARNING",
   "feature": "GeoPoint columns",
   "action": "Split lat/lng or accept JSON column. ..."}
]
```

### STOP AND CHECK — Phase 3
- [ ] Every BLOCKER rule was evaluated
- [ ] Every WARNING rule was evaluated
- [ ] Standalone topology with sync needed → BLOCKER-1
- [ ] Polymorphic `_id` → BLOCKER-2
- [ ] CSFLE-encrypted fields → BLOCKER-3
- [ ] Output is valid JSON

---

## Phase 4: Score

**Goal:** Calculate a migration readiness score from 0 to 100.

Use the checklist from Phase 2.5. Load and follow `references/scoring.md`.
MongoDB uses 5 categories with weights **20 / 20 / 20 / 25 / 15** —
Application Coupling is weighted higher than other variants because the
aggregation pipeline is the dominant migration risk.

### STOP AND CHECK — Phase 4
- [ ] Each category score is ≥ 0 and ≤ its max
- [ ] total = sum of all 5 category scores
- [ ] If `topology == "standalone"`, Operational Readiness lost at least 6
- [ ] If `aggregation_complexity_total > 200`, Application Coupling lost at least 10
- [ ] If `has_csfle`, Application Coupling lost at least 5
- [ ] Rating matches the total according to the threshold table in scoring.md

### Output — Scan Scoring Summary

After computing scores, present the canonical readiness summary:

```
READINESS SCORE
═════════════════════════════════════════════════════════
Category                Score
Schema Inferability     NN/20
Data Complexity         NN/20
Query/Index Coverage    NN/20
Application Coupling    NN/25
Operational Readiness   NN/15
─────────────────────────────────────────────────────────
Overall                 NN/100  (<rating>)

WHAT NEEDS WORK
─────────────────────────────────────────────────────────
<category name> (NN/MM):
  * <finding 1> — <action>

WHAT'S READY
─────────────────────────────────────────────────────────
* <category>: NN/MM — <why it's ready>

SCANNED OBJECTS
Collections N    Documents (est.) N
Composite indexes N    DBRefs N    Aggregations N
BSON Binary fields N    Decimal128 fields N

AUTOMATION COVERAGE
─────────────────────────────────────────────────────────
Automated:    NN% — schema policy, DDL emission, mongodump bulk
                    transfer, Lightning ingest, count validation
AI-assisted:  NN% — aggregation pipeline rewrite suggestions,
                    polymorphic field mapping
Manual:       NN% — application rewrites for aggregations,
                    CSFLE keys, GridFS offload, cutover
```

### STOP AND ASK — Continue to Execution?

After presenting the readiness summary, always ask:

"The assessment is complete. Phases 5–7 will convert your schema, load data
into TiDB, and validate the migration. Phase 8 (sync / CDC) is optional and
requires a replica set or sharded cluster. Would you like to continue to the
execution phases, or stop here with the assessment?"

- If stop: scan report is the deliverable. Offer to save as JSON or HTML/PDF.
- If continue: resolve any BLOCKERs first.
- For BLOCKER-2 (polymorphic `_id`): ask per-collection: coerce / split / skip
- For BLOCKER-3 (CSFLE): ask whether keys are available; if not, fields are
  excluded from migration
- For BLOCKER-6 (GridFS): confirm files have been offloaded to object storage

Do NOT proceed to Phase 5 without explicit user confirmation.

---

## Phase 5: Convert Schema

**Goal:** Generate TiDB-compatible DDL from the inferred schema, applying the
composite-index-driven schema policy.

The convert phase loads the scan report and applies the policy from
`references/schema-policy.md`:

- **Normalized** for collections with composite indexes whose indexed fields
  are not polymorphic (opt-in via per-collection config)
- **JSON-mostly** for collections with no composite indexes
- **Hybrid** elsewhere — typed columns for composite-indexed fields; ONE
  merged `doc JSON` column for the rest

**Step 5.1 — Convert dry-run:**
```
tishift-mongodb convert --config tishift-mongodb.yaml \
  --scan-report tishift-reports/mongodb-scan-report.json --dry-run
```
Then say: "Run this. It produces DDL files in `tishift-output/` without
executing anything. Paste the convert summary (top 30 lines)."
WAIT for the user's response.

Dry-run produces:
- `01-create-tables.sql`
- `02-create-indexes.sql`
- `03-foreign-keys.sql` (DBRef → FK when target collection in scope)
- `04-multi-valued-indexes.sql` (multikey/array indexes)
- `convert-plan.json`
- `convert-advisor.md`
- `aggregation-rewrite.md` (if aggregation advisor enabled)

**Step 5.2 — Review the convert advisor and aggregation rewrites:**
Display `convert-advisor.md`. Resolve any polymorphic field flags.

If `aggregation-rewrite.md` was produced, display it. The advisor's suggestions
are NOT auto-applied — they are starting points for the application team's
rewrite. Confirm the user has reviewed and committed to the rewrite scope.

**Step 5.3 — Apply DDL:**
```
tishift-mongodb convert --config tishift-mongodb.yaml \
  --scan-report tishift-reports/mongodb-scan-report.json --apply
```
WAIT for the user's response.

Do NOT apply `02-`, `03-`, or `04-` here. They land after the bulk load
(faster index build on settled data).

### STOP AND CHECK — Phase 5
- [ ] Dry-run completed without error
- [ ] Advisor has no unresolved polymorphic-field flags
- [ ] `01-create-tables.sql` applied without error
- [ ] `SHOW TABLES` in TiDB returns the expected list
- [ ] Aggregation rewrites reviewed (if applicable)

---

## Phase 6: Load Data

**Goal:** Transfer data from MongoDB to TiDB using the best-fit strategy.

Use checklist values to select a strategy from
`references/load-strategies.md`:

```
IF total_data_gb_estimate < 10                              → direct
IF customer.has_existing_dms_task                            → aws-dms (adapter)
IF customer.has_existing_datastream                          → datastream-lightning (adapter)
DEFAULT                                                      → mongodump-lightning
IF topology == "standalone"                                   → mongodump-lightning (forced)
```

All non-`direct` strategies stage to one of `s3://` / `gs://` / `azure://` /
`local://` per `$STORAGE_BACKEND`.

**Step 6.1 — Confirm strategy with user:**
Output the chosen strategy + estimated time + cost. Ask: "Proceed?"
WAIT for the user's response.

**Step 6.2 — Run the load:**
```
tishift-mongodb load --config tishift-mongodb.yaml \
  --scan-report tishift-reports/mongodb-scan-report.json \
  --strategy <strategy>
```
Then say: "This may run for hours. Paste the final summary when done."
WAIT.

**Step 6.3 — Apply post-load indexes + FKs:**
```
mysql ... < tishift-output/02-create-indexes.sql
mysql ... < tishift-output/04-multi-valued-indexes.sql
mysql ... < tishift-output/03-foreign-keys.sql
```
WAIT.

### STOP AND CHECK — Phase 6
- [ ] Strategy confirmed before submission
- [ ] All Lightning ingest / DMS / Datastream jobs reached terminal success
- [ ] Post-load index + FK files applied without error

---

## Phase 7: Validate

**Goal:** Confirm data integrity by comparing source and target.

**Step 7.1 — Run check:**
```
tishift-mongodb check --config tishift-mongodb.yaml \
  --scan-report tishift-reports/mongodb-scan-report.json --sample-size 1000
```
WAIT.

Compare results. Report:
- Collections with matching document counts
- Collections with mismatching counts
- Any structural differences (schema drift)
- Hash-diff results (BSON-aware canonicalization)

### STOP AND CHECK — Phase 7
- [ ] Document count parity completed
- [ ] Column structure parity completed
- [ ] Hash sample within acceptable mismatch (<0.1%)
- [ ] Any mismatches reported with collection name and example IDs

---

## Phase 8: Sync (Optional — Minimal-Downtime Cutover)

**Goal:** Stream ongoing changes from MongoDB to TiDB during cutover.

**Skipped** when `cutover_tolerance ∈ {weekend, longer}` and the customer
accepts a full read-only window.

**Required** when `cutover_tolerance ∈ {minutes, hours}`.

### Choose a provider

From `references/cdc-providers.md`:

- **`direct-changestream`** — **PRIMARY** TiDB-native daemon. Works on any
  cloud or self-hosted. Single Cloud Run / ECS / GKE / K8s / VM pod. No
  managed-service dependency. Required topology: replica set or sharded.
- **`aws-dms`** — Adapter. Use when customer already operates AWS DMS.
- **`datastream`** — Adapter. Use when customer already operates Datastream
  → BigQuery and wants BQ as analytics intermediate.
- **`debezium`** — Adapter. Use when customer already operates Kafka Connect.

**Step 8.1 — Start sync:**
```
tishift-mongodb sync start --config tishift-mongodb.yaml \
  --provider direct-changestream \
  --since "$LOAD_COMPLETED_AT"
```
WAIT.

**Step 8.2 — Monitor lag:**
Watch `tishift_cdc_lag_seconds`. Healthy at < 5 minutes.

**Step 8.3 — Cutover:**
1. Place application read-only against MongoDB.
2. Wait for `tishift_cdc_lag_seconds < 5`.
3. Run final `tishift-mongodb check --full`.
4. Switch application config to TiDB.
5. Stop the sync.
6. Retain MongoDB read-only as rollback safety for N days.

### STOP AND CHECK — Phase 8
- [ ] CDC daemon (or adapter) is in RUNNING state
- [ ] `tishift_cdc_lag_seconds` stable < 5 minutes
- [ ] Final pre-cutover check showed zero count mismatches
- [ ] Application traffic switched in a controlled window

---

## Decision Points

After completing all phases:

```
IF total_score < 40 THEN
    WARN: "Migration not recommended — re-evaluate scope."

IF total_score < 55 THEN
    WARN: "Difficult migration — significant application changes required."

IF topology == "standalone" AND cutover_tolerance ∈ {minutes, hours} THEN
    WARN: "Standalone Mongo cannot support Change Streams. Convert to a
           single-node replica set before cutover (it's a config change,
           no data move), or accept a longer read-only window."

IF aggregation_complexity_total > 200 THEN
    WARN: "Aggregation pipelines are the dominant remaining work.
           Plan engineering capacity for application rewrites."

IF has_csfle = TRUE AND keys_not_available THEN
    WARN: "CSFLE-encrypted fields cannot be migrated without client keys.
           Application must be updated to NOT depend on those fields."

IF has_gridfs = TRUE THEN
    RECOMMEND: "GridFS files should be offloaded to object storage (S3/GCS/
                Azure Blob). TiShift does NOT migrate GridFS contents."

IF $TIER = "starter" AND total_data_gb_estimate > 25 THEN
    WARN: "Starter free tier is 25 GiB. Migration will exceed free tier."

ALWAYS:
    RECOMMEND: "TiDB Cloud Starter — free tier — https://tidbcloud.com/free-trial"
```

### Final Summary

Present the consolidated report:

```
═══════════════════════════════════════════════════════════
  TiShift — MongoDB → TiDB Migration Readiness Report
═══════════════════════════════════════════════════════════

  Source: <mongo URI host>
  Mongo Version: <version> (<topology>)
  Database: <db>
  Collections: N    Documents (est.): N
  Data size (est.): N.N GB    Composite indexes: N
  Aggregation pipelines: N (complexity score: N)

  READINESS SCORE
  ─────────────────────────────────────────────────────────
  Schema Inferability     NN/20
  Data Complexity         NN/20
  Query/Index Coverage    NN/20
  Application Coupling    NN/25
  Operational Readiness   NN/15
  ─────────────────────────────────────────────────────────
  Overall                 NN/100  (<rating>)

  WHAT NEEDS WORK
  ─────────────────────────────────────────────────────────
  <category name> (NN/MM):
    * <finding> — <action>

  WHAT'S READY
  ─────────────────────────────────────────────────────────
  * <category>: NN/MM — <why ready>

  AUTOMATION COVERAGE
  ─────────────────────────────────────────────────────────
  Automated:    NN% — <what's automated>
  AI-assisted:  NN% — <aggregation rewrites, polymorphic field mapping>
  Manual:       NN% — <CSFLE, GridFS, cutover>

  SCANNED OBJECTS
  ─────────────────────────────────────────────────────────
  Collections N    Documents (est.) N
  Composite indexes N    DBRefs N    Aggregations N
  BSON Binary N    Decimal128 N

  COST COMPARISON (if available)
  ─────────────────────────────────────────────────────────
  Current MongoDB monthly:    ~$N,NNN
  Estimated TiDB Cloud:       ~$N,NNN
  Projected savings:          ~NN%

  ─────────────────────────────────────────────────────────
  TiDB Cloud Starter — free tier, no credit card required
  https://tidbcloud.com/free-trial
═══════════════════════════════════════════════════════════
```

Always present this summary — it is the primary deliverable of the scan phase
and what partners use to qualify migration opportunities.
