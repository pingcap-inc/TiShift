# Check Guide

How `tishift-firestore check` validates the migration after load.

## What check does

Three layers of verification:

1. **Document count parity** — Firestore aggregate `count()` on each
   collection vs TiDB `SELECT COUNT(*)`. Both are exact, fast, and free of
   sampling error.
2. **Column structure parity** — the scan report's inferred schema vs the
   live `SHOW CREATE TABLE` on TiDB. Detects schema drift between convert
   time and check time.
3. **Per-document hash diff** — a random sample of N documents per
   collection: read from Firestore, reconstruct from TiDB rows,
   canonicalize both, SHA-256 compare. Surfaces actual data corruption.

## Running it

```bash
tishift-firestore check --config tishift-firestore.yaml \
    --scan-report tishift-reports/firestore-scan-report.json \
    --sample-size 1000
```

Output:
- `tishift-reports/firestore-check-report.json`
- CLI summary panel

## Sample sizing

The sample size is per-collection. 1,000 is a sensible default for most
prospects. For critical collections, increase:

```bash
tishift-firestore check ... --sample-size 10000 \
    --collection users --collection orders
```

For a quick smoke test:

```bash
tishift-firestore check ... --sample-size 100
```

Sampling cost: 1 Firestore read per sampled document, same as scan
(~$0.06 per 100k). A 1,000-doc-per-collection check on 50 collections is
~$0.03.

## Canonicalization

Hash comparison only works if both sides produce identical bytes. Rules:

- Top-level fields sorted alphabetically by key
- All timestamps in ISO 8601 UTC: `2026-05-15T03:14:15.123456Z`
- Floating-point numbers serialized with Python's `repr()` (round-trip exact)
- JSON column reads from TiDB are parsed back to Python dict before
  canonicalization (don't compare raw JSON strings — whitespace differs)
- DocumentReference compared by document path only (the SDK returns a
  client-side reference object; we extract `.path`)
- GeoPoint compared as (lat, lng) tuple rounded to 6 decimal places
- Bytes compared by SHA-256 of the binary content, not the base64
  representation

Canonicalization is implemented in `tishift_firestore.core.check.hash_diff`
and is tested separately. Any change to the canonicalization rules
invalidates prior hash baselines — bump the version field in the check
report so consumers can detect drift.

## Reading the report

```json
{
  "check_started_at": "2026-05-15T05:00:00Z",
  "check_completed_at": "2026-05-15T05:08:33Z",
  "canonicalization_version": 1,
  "collections": [
    {
      "name": "users",
      "count_source": 1234567,
      "count_target": 1234567,
      "count_delta": 0,
      "structure_match": true,
      "structure_diffs": [],
      "hash_sample_size": 1000,
      "hash_matches": 1000,
      "hash_mismatches": 0,
      "first_mismatching_ids": []
    },
    {
      "name": "orders",
      "count_source": 8901234,
      "count_target": 8901230,
      "count_delta": -4,
      "structure_match": true,
      "structure_diffs": [],
      "hash_sample_size": 1000,
      "hash_matches": 998,
      "hash_mismatches": 2,
      "first_mismatching_ids": ["abc123...", "def456..."]
    }
  ],
  "verdict": "MISMATCH",
  "summary": "1 of 2 collections has count delta; 2 of 2000 sampled docs hash-differ."
}
```

## Verdict semantics

- `MATCH` — all collections have zero count delta and zero hash mismatches
- `MATCH_WITH_SAMPLE_DIFFS` — counts match but some sample hashes differ;
  inspect the offending docs (often canonicalization edge cases, not real
  data corruption)
- `MISMATCH` — any count delta or any structure diff
- `INCONCLUSIVE` — at least one collection couldn't be read (auth, network);
  fix and re-run

## When counts differ

Most often: an ongoing write to Firestore between the load's `read_time`
snapshot and the check. Verify by:

1. Re-running scan with current `read_time` and comparing to load's `read_time`.
2. Filtering both sides to docs created before `read_time`.

If counts still differ, the load missed documents. Inspect Dataflow job logs
for failed shards.

## When sample hashes differ

Most often: a canonicalization edge case. Check the first mismatching ID:

```bash
tishift-firestore check inspect --collection orders --id abc123...
```

Outputs both canonicalized representations side by side. If they really
should hash identically and don't, file a canonicalization bug.

If a real data difference: load is corrupt for that doc. Inspect the Dataflow
worker logs for that specific document path.

## What check does NOT do

- **Does not check application semantics.** If Firestore `users.age` was a
  string `"42"` and convert mapped it to `BIGINT 42`, that's expected — the
  hash will mismatch unless canonicalization explicitly handles the cast.
  Bake any expected casts into the canonicalization rules before running.
- **Does not replay queries.** Verifying that the customer's existing
  queries produce equivalent results in TiDB is application-side work.
- **Does not verify performance.** Use TiDB's slow-query log and dashboard
  for that.

## In CI

Run check as a smoke test in CI by pointing it at the Firestore Emulator
and a TiDB Docker container:

```bash
tishift-firestore check --config tests/fixtures/ci-config.yaml \
    --scan-report tests/fixtures/scan-report.json --sample-size 50
```

A passing check + parity counts is a sufficient regression signal for the
convert and load pipelines.
