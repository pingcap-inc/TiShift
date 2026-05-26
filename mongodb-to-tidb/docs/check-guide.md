# Check Guide

How `tishift-mongodb check` validates the migration after load.

## What check does

Three layers:

1. **Document count parity** — Mongo `count_documents({})` vs TiDB `SELECT COUNT(*)`. Both exact, both fast, no sampling.
2. **Column structure parity** — scan report's inferred schema vs live `SHOW CREATE TABLE` on TiDB.
3. **Per-document hash diff** — random N docs per collection; canonicalize both sides with BSON-aware rules; SHA-256 compare.

## Running it

```bash
tishift-mongodb check --config tishift-mongodb.yaml \
    --scan-report tishift-reports/mongodb-scan-report.json \
    --sample-size 1000
```

Sample size is per-collection. 1,000 is the sensible default; 10,000 for
critical collections; 100 for smoke tests.

## BSON-aware canonicalization

Hashing only works if both sides produce identical bytes. Mongo has more
typed values than Firestore, so the canonicalization rules are extended:

```python
def canonicalize(value):
    if isinstance(value, ObjectId):       return {"$oid": str(value)}
    if isinstance(value, Decimal128):     return {"$dec": str(value)}
    if isinstance(value, UUID):           return {"$uuid": str(value)}
    if isinstance(value, Binary):
        return {"$bin": base64.b64encode(value).decode(), "$type": value.subtype}
    if isinstance(value, datetime):       return value.isoformat(timespec="microseconds")
    if isinstance(value, Regex):          return {"$regex": value.pattern, "$opts": value.flags}
    if isinstance(value, Code):           return {"$code": str(value)}
    if isinstance(value, Timestamp):      return {"$ts": (value.time, value.inc)}
    # Standard scalars, dicts, lists handled by base rules
```

When TiShift reads from the target side, it parses TiDB's JSON columns back to
Python dicts before canonicalizing — never compares raw JSON strings (whitespace
varies).

## Reading the report

```json
{
  "check_started_at": "2026-05-20T05:00:00Z",
  "check_completed_at": "2026-05-20T05:09:11Z",
  "canonicalization_version": 2,
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
      "hash_sample_size": 1000,
      "hash_matches": 998,
      "hash_mismatches": 2,
      "first_mismatching_ids": ["6479a...", "6479b..."]
    }
  ],
  "verdict": "MISMATCH"
}
```

## Verdict semantics

- `MATCH` — all counts equal, all hashes match
- `MATCH_WITH_SAMPLE_DIFFS` — counts match but some hashes differ (often canonicalization edge cases)
- `MISMATCH` — count or structure diff
- `INCONCLUSIVE` — at least one collection unreadable (auth, network); fix and retry

## When counts differ

Most common cause: ongoing writes between the load's `--oplog` cut-time and
the check. Verify by:

1. Compare load's `read_time` to current time
2. Check `oplog.rs` for events newer than load time
3. Filter both sides to docs created before load time

If counts still differ, the load missed documents. Inspect Lightning logs or
mongodump output for the affected collection.

## When sample hashes differ

Most common cause: a canonicalization edge case (timezone, UUID byte order,
Decimal128 trailing zeros). Inspect the first mismatching ID:

```bash
tishift-mongodb check inspect --collection orders --id 6479a...
```

Outputs both canonicalized representations side by side. If they're really
the same and don't hash identically → canonicalization bug; file an issue.

If they're actually different → load corrupted that doc. Inspect Lightning
logs for the specific document.

## What check does NOT do

- **Doesn't replay queries.** Verifying that the customer's existing queries produce equivalent results is application-side work.
- **Doesn't validate aggregation pipeline rewrites.** Those are SQL the application now runs, validated by application tests.
- **Doesn't verify performance.** Use TiDB's slow-query log + dashboard.
- **Doesn't reconcile CSFLE-encrypted fields.** They're opaque LONGBLOB on both sides.

## In CI

Run check as a smoke test in CI against the Docker Mongo + Docker TiDB:

```bash
tishift-mongodb check --config tests/fixtures/ci-config.yaml \
    --scan-report tests/fixtures/scan-report.json --sample-size 50
```

A passing check + count parity is a sufficient regression signal for the
convert and load pipelines.
