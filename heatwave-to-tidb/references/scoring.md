# Readiness Scoring — MySQL HeatWave → TiDB

Compute a 0-100 readiness score from the Phase 2 scan inventory. Start each
category at its maximum and subtract per finding; floor each category at 0.

**Implemented as code:** `tishift_heatwave/rules/scoring.py` (category
maxima, rating bands, per-unit point constants) and
`tishift_heatwave/core/scan/analyzers/scoring.py` (the actual formulas —
batching, tier/version gating), unit-tested in
`tests/test_scan/test_scoring_engine.py`. The scoring engine reuses the exact
same rule-check functions as the compatibility analyzer
(`rules/compatibility.py`), so a finding and its deduction can never
disagree about what they're counting.

## Categories

| Category | Max | Deductions |
|---|---|---|
| Schema compatibility | 30 | -5 per spatial column set (BLOCKER-4); -5 per table with an unsupported character set (BLOCKER-8); -5 per case-colliding table-name group (BLOCKER-9); -2 per FULLTEXT index outside Starter (WARNING-2); -2 flat if lower_case_table_names ≠ 2 (WARNING-8); -1 per updatable view (WARNING-9). utf8mb4_0900_* collations (WARNING-4) map 1:1 to the target (native since TiDB v7.4; target TiDB Cloud is v8.5) and are recorded as a -0 note; foreign keys are enforced natively (v6.6+) and neither warn nor deduct |
| Programmable objects | 25 | -5 per stored procedure batch of 10 (BLOCKER-1); -5 per trigger batch of 10 (BLOCKER-2); -3 per event (BLOCKER-3); -5 per JavaScript/MLE routine (HW-BLOCKER-3); -5 if UDFs present (BLOCKER-6) |
| HeatWave surface | 20 | -20 if Lakehouse external tables present (HW-BLOCKER-1); -10 if AutoML/GenAI schemas present (HW-BLOCKER-2); -0 for RAPID offload (maps to TiFlash, HW-WARNING-1); -3 per VECTOR column set needing index rework (HW-WARNING-2) |
| Data & load feasibility | 15 | -5 if total size exceeds tier capacity (e.g. > 25 GiB on Starter); -5 if no network path (no bastion/tunnel reachable); -3 if XA usage detected (BLOCKER-5) |
| Cutover & continue replication | 10 | -5 if continue replication required but tier is Starter; -5 if log_bin ≠ ON (HW-WARNING-6 — continue replication categorically impossible); -3 if binlog_format ≠ ROW (HW-WARNING-7) or binlog_row_image ≠ FULL (HW-WARNING-8) or gtid_mode ≠ ON; -2 if binlog retention < 86400s/1 day hard floor, or < 604800s/7 days recommended (HW-WARNING-4); -2 if binlog_row_value_options is not empty (HW-WARNING-5); -2 if binlog_transaction_compression ≠ OFF (HW-WARNING-9); -2 per business table without a PK/UNIQUE index when continue replication is planned (see sync-guide.md § Valid indexes precheck) |

## Rating bands

| Score | Rating | Guidance |
|---|---|---|
| 85-100 | READY | Proceed; standard runbook |
| 65-84 | READY WITH WORK | Proceed after converting flagged objects |
| 40-64 | SIGNIFICANT REWORK | Pilot a subset first; budget application changes |
| 0-39 | NOT RECOMMENDED YET | Resolve blockers (usually Lakehouse/AutoML coupling) before migrating |

## Output Format

```json
{
  "overall": 78,
  "rating": "READY WITH WORK",
  "categories": [
    {"name": "Schema compatibility", "max_points": 30, "score": 27, "deductions": ["..."]},
    {"name": "Programmable objects", "max_points": 25, "score": 15, "deductions": ["..."]},
    {"name": "HeatWave surface", "max_points": 20, "score": 20, "deductions": []},
    {"name": "Data & load feasibility", "max_points": 15, "score": 10, "deductions": ["..."]},
    {"name": "Cutover & continue replication", "max_points": 10, "score": 6, "deductions": ["..."]}
  ]
}
```
