"""Scan phase — schema collectors, HeatWave feature detection, analyzers, reporters.

Collectors gather the schema inventory plus HeatWave-specific signals:
RAPID-offloaded tables, Lakehouse external tables, AutoML schemas
(ML_SCHEMA_<user>), VECTOR columns, and JavaScript (MLE) stored programs.

Implemented so far:
- collectors/binlog.py + analyzers/binlog_check.py — binlog/continue-replication readiness
  precheck (Step 2.1a)
- collectors/metadata.py — server metadata incl. primary/secondary (HA)
  replication topology and RAPID cluster node count (Steps 1.1/1.2, 2.1b)
- collectors/schema.py — schema inventory: tables (size, engine, collation,
  partitioning), columns, indexes, constraints, routines, triggers, events,
  Lakehouse tables, AutoML schemas (Steps 2.2-2.6)
- collectors/valid_indexes.py — PK/UNIQUE index coverage precheck (Step 7.1)
- analyzers/compatibility.py — applies every rule in
  rules/compatibility.py (references/compatibility-rules.md) to produce an
  AssessmentResult
- analyzers/scoring.py — computes the 0-100 ReadinessScore
  (references/scoring.md), reusing the same rule checks as the compatibility
  analyzer so the two can never disagree about what they're counting
- orchestrator.py — run_scan() wires a live connection through every
  collector/analyzer above (thin by design; almost all behavior is already
  covered by their own unit tests)
- report.py — builds the report dict and renders it as CLI text / Markdown /
  JSON, wired into the `tishift-heatwave scan` CLI command

Not yet implemented: HTML/PDF reporters. A few compatibility rules (XA
transactions, UDFs, XML functions, GET_LOCK, SQL_CALC_FOUND_ROWS, SAVEPOINT,
MySQL Enterprise plugins) need query-log analysis this project doesn't
implement yet; they're wired up via QueryLogSignals and default to "not
detected" until such a collector exists.
"""
