# Readiness Scoring — OceanBase → TiDB

Dual-mode scoring. Weights depend on OceanBase compatibility mode.

## MySQL Mode (25/15/20/20/20)

| Category | Max |
|---|---|
| Schema Compatibility | 25 |
| Procedural Code | 15 |
| Query Compatibility | 20 |
| Data Complexity | 20 |
| Operational Readiness | 20 |

Ops is weighted highest (20) because CDC unavailability and OB-extension stripping dominate the MySQL-mode migration effort.

## Oracle Mode (20/30/20/20/10)

| Category | Max |
|---|---|
| Schema Compatibility | 20 |
| Procedural Code | 30 |
| Query Compatibility | 20 |
| Data Complexity | 20 |
| Operational Readiness | 10 |

Procedural Code dominates (30) because PL/SQL is the #1 blocker.

Detailed deduction pseudocode is applied per category during the scoring phase.

## Score Interpretation

| Score | Rating |
|---|---|
| 90–100 | Excellent |
| 75–89 | Good |
| 50–74 | Moderate |
| 25–49 | Challenging |
| 0–24 | Difficult |
