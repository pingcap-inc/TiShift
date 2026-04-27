"""Scan: read-only assessment.

Collectors:
  collector_1_inventory       tables, columns, indexes, constraints, functions,
                              triggers, views, sequences, custom types, extensions,
                              partitioned tables — with Supabase schema filter applied
  collector_2_rls             every CREATE POLICY as a structured RLSPolicyFinding;
                              tables with relrowsecurity=true but no policy
  collector_3_platform        Supabase schema presence, Realtime slot, pg_cron jobs,
                              pg_net call sites, wrappers foreign tables, auth user
                              count, storage object count
  collector_4_data_profile    per-table size, row estimates, LOB columns
  collector_5_feature_usage   JSONB operator usage, array columns, UUID, tsvector,
                              range types, auth.* call sites in user objects,
                              extensions.*-qualified call sites
  collector_6_procedural      per-function complexity analysis (lines, cursor,
                              dynamic SQL, exception handling, auth.* references,
                              SECURITY DEFINER). Optional --ai sends definitions to
                              the AI for semantic classification.
"""

from __future__ import annotations

from pathlib import Path


def run_scan(config_path: Path, formats: list[str], ai: bool) -> None:
    """Entry point for `tishift-supabase scan`.

    Loads config, opens source read-only, runs collectors, classifies findings
    using rules in tishift_supabase.rules.compatibility, computes the 5-category
    score, writes reports in the requested formats.
    """
    raise NotImplementedError("scan implementation pending — see build spec §Scan Collectors")
