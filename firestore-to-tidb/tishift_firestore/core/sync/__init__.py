"""Sync phase: CDC via the firestore-bigquery-export Firebase Extension bridge.

Import from submodules directly. cutover.py is pure logic; bq_bridge.py
requires apache-beam[gcp] for the streaming Dataflow job.

The streaming Dataflow pipeline pulls TiDB credentials from the customer's
secret store at runtime (Workload Identity-bound Secret Manager access),
NOT from any on-disk TiShift artifact. Build the Flex Template so that the
sink reads `TIDB_PASSWORD` from Secret Manager directly.
"""
