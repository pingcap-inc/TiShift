"""Sanity checks on the sample schema fixture.

These don't execute the SQL — they just confirm the fixture still exercises
every blocker/warning it's supposed to. If a future edit removes a test point,
the scan's rule coverage tests lose their source of truth.
"""

from __future__ import annotations


def test_sample_schema_has_rls_patterns(sample_schema_sql: str) -> None:
    sql = sample_schema_sql
    # User-owned pattern
    assert "users_self_select" in sql
    assert "(select auth.uid()) = id" in sql
    # Role-gated pattern
    assert "posts_public_read" in sql
    assert "TO anon, authenticated" in sql
    # Tenant-isolation pattern
    assert "invoices_tenant_isolation" in sql
    assert "(auth.jwt() ->> 'tenant_id')::uuid" in sql
    # Deny-all pattern (RLS enabled, no policies on public.comments)
    assert "ALTER TABLE public.comments ENABLE ROW LEVEL SECURITY" in sql


def test_sample_schema_exercises_blockers(sample_schema_sql: str) -> None:
    sql = sample_schema_sql
    assert "auth.uid()" in sql                       # BLOCKER-3
    assert "TEXT[]" in sql                           # BLOCKER-9
    assert "@>" in sql                               # BLOCKER-10
    assert "CREATE OR REPLACE FUNCTION" in sql       # BLOCKER-13
    assert "CREATE TRIGGER" in sql                   # BLOCKER-14


def test_sample_schema_exercises_warnings(sample_schema_sql: str) -> None:
    sql = sample_schema_sql
    assert "CREATE TYPE post_status AS ENUM" in sql  # WARNING-7
    assert "CREATE SEQUENCE" in sql                  # WARNING-8
    assert "RETURNING id INTO" in sql                # WARNING-9
    assert "gen_random_uuid()" in sql                # WARNING-10
    assert " SERIAL " in sql or "SERIAL PRIMARY KEY" in sql  # WARNING-11
    assert "extensions.gen_random_uuid()" in sql     # WARNING-19
    assert "SECURITY DEFINER" in sql                 # WARNING-20
    assert "TIMESTAMP WITH TIME ZONE" in sql         # WARNING-21


def test_sample_schema_grants_postgrest_roles(sample_schema_sql: str) -> None:
    """The GRANTs to anon/authenticated drive the PostgREST-likely-in-use heuristic."""
    sql = sample_schema_sql
    assert "GRANT SELECT, INSERT, UPDATE ON public.users TO authenticated;" in sql
    assert "GRANT SELECT ON public.users TO anon;" in sql
