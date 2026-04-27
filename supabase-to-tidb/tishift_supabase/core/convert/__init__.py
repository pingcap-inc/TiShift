"""Convert: TiDB DDL + RLS rewrite checklist + external-work plan.

Pipeline (run in order):

  1. Supabase-specific pre-passes:
     - strip CREATE POLICY and ALTER TABLE ... ENABLE/DISABLE/FORCE ROW LEVEL SECURITY
       (emit to 05-rls-rewrite-checklist.md)
     - strip CREATE PUBLICATION / SUBSCRIPTION / REPLICATION SLOT
     - strip the `extensions.` qualifier from function calls
     - flag auth.uid / auth.jwt / auth.role / auth.email call sites in function
       bodies and view definitions (emit to 05-rls-rewrite-checklist.md)
     - detect net.http_*, vault.*, cron.schedule(), graphql.resolve() call sites
       (emit to 07-external-work-plan.md)
     - drop DDL referencing Supabase-internal schemas

  2. sqlglot transform (read="postgres", write="mysql") for the remaining DDL
     and view definitions.

  3. Type mapping per rules.type_mapping for column type adjustments sqlglot
     doesn't handle (UUID choice, JSONB → JSON, array → JSON comment, ENUM
     inlining, timestamptz warnings).

  4. Emit 7 output files (see convert-guide.md).
"""

from __future__ import annotations

from pathlib import Path


def run_convert(
    scan_report: Path,
    output_dir: Path,
    dry_run: bool,
    uuid_type: str,
) -> None:
    """Entry point for `tishift-supabase convert`."""
    raise NotImplementedError("convert implementation pending — see build spec §Convert")
