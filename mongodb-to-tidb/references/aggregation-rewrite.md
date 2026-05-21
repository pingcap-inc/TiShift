# Aggregation Pipeline → SQL Rewrite Guidance

How TiShift inventories MongoDB aggregation pipelines and produces
human-reviewable SQL rewrite suggestions.

## Why this is its own document

Aggregation pipelines are the dominant migration risk for non-trivial Mongo
apps. Unlike schema mapping (which the convert phase can largely automate),
pipeline rewrites involve **semantic translation between query models** —
something only the application team can ultimately validate.

TiShift inventories pipelines and produces rewrite suggestions. **The
application team rewrites and reviews.** TiShift's value-add is the
inventory + complexity scoring + AI-assisted starting point, not the
finished SQL.

## Pipeline inventory sources

The scan phase looks for pipelines in three places, in priority order:

1. **Atlas Performance Advisor** (if Atlas + Atlas Admin API access).
   Surfaces the actual production pipelines the cluster has executed.
2. **`system.profile` collection** (if profiling is enabled — level 1 or 2).
   Captures recent aggregation operations.
3. **User-supplied JSON file** — operator provides `aggregations.json` with
   representative pipelines.

When none of these are available, the inventory is empty and the advisor
runs in "user-supplied" mode only.

## Complexity scoring

Per pipeline, TiShift computes a complexity score:

| Stage | Points |
|---|---|
| `$match`, `$sort`, `$limit`, `$skip`, `$project` | 1 |
| `$group` | 3 |
| `$lookup`, `$unwind` | 5 |
| `$graphLookup`, `$facet`, `$bucket`, `$bucketAuto` | 8 |
| Array-element operators (`$elemMatch`, `$slice`, `$filter`, `$map`, `$reduce`) | 4 each |
| `$out` / `$merge` (writes) | 10 — separate concern: writes aren't `SELECT` rewrites |

Per-collection totals roll up into `aggregation_complexity_total` in the
checklist. This feeds Application Coupling scoring:

- ≤ 10 total: no deduction
- 11–50: -3
- 51–200: -6
- > 200: -10

## SQL equivalence map

| MongoDB stage | SQL equivalent | Notes |
|---|---|---|
| `$match: {field: value}` | `WHERE field = value` | Operators map: `$gt` → `>`, `$in` → `IN`, `$regex` → `LIKE` or `REGEXP`. |
| `$project: {field1: 1, field2: 1}` | `SELECT field1, field2` | Excluded fields → just omit from SELECT list. |
| `$sort: {field: 1}` | `ORDER BY field ASC` | Multi-field maps naturally. |
| `$limit: N` | `LIMIT N` | Direct. |
| `$skip: N` | `OFFSET N` | Direct. |
| `$group: {_id: "$f", sum: {$sum: "$v"}}` | `GROUP BY f` + aggregate functions | Mongo's aggregate operators map to SQL: `$sum` → `SUM()`, `$avg` → `AVG()`, `$min` → `MIN()`, `$push` → `JSON_ARRAYAGG()` (in TiDB v6.5+). |
| `$lookup: {from, localField, foreignField, as}` | `LEFT JOIN` with appropriate ON clause | The `as` field becomes a JSON array via `JSON_ARRAYAGG()`, or each match becomes a row depending on `$unwind` after. |
| `$unwind: "$arr"` | `JSON_TABLE(arr, '$[*]' COLUMNS (...))` | TiDB's `JSON_TABLE` (v8.x) is the closest equivalent. For older versions, a child-table approach (if the array was normalized at convert time) is cleaner. |
| `$graphLookup` | Recursive CTE (`WITH RECURSIVE`) | Direct conceptual equivalent. |
| `$facet: {pipeline1: [...], pipeline2: [...]}` | Multiple separate queries OR UNION ALL with discriminator | Cannot translate to a single SQL query — needs application-side fan-out. |
| `$bucket` / `$bucketAuto` | `CASE WHEN ... END` + `GROUP BY` | Direct but verbose. |
| `$addFields` / `$set` | Computed columns in SELECT or generated columns | Direct. |
| `$out: <collection>` | `INSERT INTO <table> SELECT ...` | Writes — application-layer change. |
| `$merge: <collection>` | `INSERT ... ON DUPLICATE KEY UPDATE` | Direct in TiDB. |

## AI-assisted rewriting

When `convert.aggregation_advisor.enabled: true` and a `completion_fn`
callable is injected by the operator, the convert phase produces
`tishift-output/aggregation-rewrite.md` with one rewrite suggestion per
pipeline:

```markdown
## Pipeline: orders.aggregate-monthly-by-status

Complexity: 14 (3 stages: $match + $group + $sort)

Original (Mongo):
```json
[
  {"$match": {"created_at": {"$gte": ISODate("2026-01-01")}}},
  {"$group": {"_id": {"month": {"$month": "$created_at"}, "status": "$status"}, "count": {"$sum": 1}}},
  {"$sort": {"_id.month": 1}}
]
```

Suggested SQL (TiDB):
```sql
SELECT
  MONTH(created_at) AS month,
  status,
  COUNT(*) AS count
FROM orders
WHERE created_at >= '2026-01-01'
GROUP BY MONTH(created_at), status
ORDER BY MONTH(created_at) ASC;
```

Rationale: $match → WHERE; $group with $month → GROUP BY MONTH();
$sum: 1 → COUNT(*); $sort on grouping key → ORDER BY same expression.

⚠ Review required:
- Verify the timezone handling matches Mongo's (Mongo uses UTC for $month)
- Confirm the index on (created_at, status) is in place — your composite
  index on (status, created_at) won't help this query
```

## Provider-agnostic injection

The advisor uses a `CompletionFn = Callable[[str], str]` injection point.
The operator chooses the LLM provider and credentials:

```python
from tishift_mongodb.core.convert.aggregation_advisor import suggest_rewrite

def my_llm_completion(prompt: str) -> str:
    # Your LLM call here — caller owns the provider choice and credentials
    ...
    return response_text

# At convert time:
suggestion = suggest_rewrite(pipeline_json, schema_context, complete=my_llm_completion)
```

**Privacy contract:** the prompt sent to the LLM contains:
- The pipeline JSON
- Field names and inferred types from the scan
- Schema-policy decisions for the involved collections

It does **NOT** contain document data or sample values. The advisor
explicitly redacts before transmission. Verified in tests.

## When to disable the advisor

- Customer cannot share pipeline JSON with an external LLM (compliance)
- Inventory-only mode is sufficient (customer rewrites pipelines internally)
- v1 deferral — skip advisor entirely, address aggregations in v1.1

```yaml
convert:
  aggregation_advisor:
    enabled: false
```

In this mode, the inventory still runs (so the scoring engine has its
complexity input), but no suggestions are produced.

## What the advisor doesn't do

- **Doesn't execute the SQL.** Suggestions are text — humans validate.
- **Doesn't guarantee semantic equivalence.** `$lookup` with subpipelines
  and `$facet` are the hardest cases; suggestions for these often need
  significant refinement.
- **Doesn't rewrite write-side stages (`$out`, `$merge`).** Those are
  application-layer changes, surfaced in the inventory but not in the
  rewrite output.
- **Doesn't auto-create the JSON helper expressions** for `$unwind` /
  `JSON_TABLE` cases. Suggested SQL uses placeholder `JSON_TABLE` calls
  the application team fills in.
