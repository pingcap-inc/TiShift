"""Compatibility rule engine — applies BLOCKER-1..21 and WARNING-1..22.

Each rule is a pure function: (SchemaInventory) -> Finding | None.

The Markdown table in references/compatibility-rules.md is the spec. This
module is the runtime implementation. Keep them in sync: if a rule changes,
update both.
"""

from __future__ import annotations

# Rule IDs in order. See references/compatibility-rules.md for full descriptions.
BLOCKER_IDS: list[str] = [f"BLOCKER-{i}" for i in range(1, 22)]
WARNING_IDS: list[str] = [f"WARNING-{i}" for i in range(1, 23)]


def classify_all(inventory):  # type: ignore[no-untyped-def]
    """Return (blockers, warnings, compatible) for an inventory.

    Implementation pending — rules are enumerated in compatibility-rules.md.
    """
    raise NotImplementedError(
        "compatibility rule engine pending — see references/compatibility-rules.md"
    )
