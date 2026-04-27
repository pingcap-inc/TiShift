"""Postgres / Supabase function → TiDB function mapping.

Spec: references/function-mapping.md. Runtime equivalent lives here.
"""

from __future__ import annotations

# Auth helpers — always BLOCKER-3. No DB-side equivalent in TiDB.
AUTH_HELPERS: frozenset[str] = frozenset(
    {"auth.uid", "auth.jwt", "auth.role", "auth.email"}
)

# Platform function call sites — each drives a specific BLOCKER / WARNING.
PLATFORM_FUNCTIONS: dict[str, str] = {
    "net.http_get": "BLOCKER-7",
    "net.http_post": "BLOCKER-7",
    "net.http_put": "BLOCKER-7",
    "net.http_delete": "BLOCKER-7",
    "vault.create_secret": "BLOCKER-5",
    "vault.decrypted_secrets": "BLOCKER-5",
    "cron.schedule": "WARNING-5",
    "graphql.resolve": "WARNING-4",
}

# `extensions.` qualifier — common cases and their TiDB equivalents.
EXTENSIONS_QUALIFIED_MAP: dict[str, str] = {
    "extensions.gen_random_uuid": "UUID()",
    "extensions.uuid_generate_v4": "UUID()",
    # extensions.crypt / digest / encode / decode are flagged — no TiDB equivalent
}
