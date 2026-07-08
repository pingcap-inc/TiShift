"""Sync phase — prechecks for continue replication via TiDB DM over HeatWave outbound binlog replication.

This module only verifies preconditions; it does not create, start, stop, or
monitor the DM task. That happens as a migration task configured directly in
the TiDB Cloud console, which owns the task lifecycle, precheck UI, and lag
monitor. Preflight requirements checked here: binlog_format=ROW, gtid_mode=ON,
sufficient binlog_expire_logs_seconds retention, binlog_row_value_options
empty (HeatWave can default it to PARTIAL_JSON, which DM cannot parse),
REPLICATION SLAVE/REPLICATION CLIENT + per-schema SELECT grants on the source
migration user, DDL/DML grants on the target user, TLS to the source, and a
PK/unique index on every business table. Starter tier is cutover-only (no
continue replication). The console's own precheck reports FK warnings that are expected and
safe once the FK Pre-upgrade Checklist in docs/sync-guide.md is satisfied.
"""
