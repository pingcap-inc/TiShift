"""Core library. Interface-agnostic — no CLI or MCP imports.

Capabilities:
  scan    — read-only assessment, RLS extraction, scoring
  convert — DDL transform, RLS rewrite checklist, external-work plan
  load    — bulk data transfer (schema allow-list enforced)
  check   — row count + structure diff + optional checksum
  sync    — logical-replication CDC bridge (direct endpoint only)
"""
