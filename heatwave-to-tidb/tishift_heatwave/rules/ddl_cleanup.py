"""DDL cleanup rule registry — HeatWave-only syntax handled by the convert phase.

Single source of truth for the HW-DDL rules; kept in lockstep with
references/compatibility-rules.md (§ DDL cleanup rules).

Patterns for clause rules are matched against a *masked* copy of the SQL
(string literals and comments blanked out) so a clause mentioned inside a
string or an existing TISHIFT-REMOVED comment is never re-matched. The
HW-DDL-4 pattern is the exception: it targets literal content and runs on the
original text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class CleanupRule:
    rule_id: str
    description: str
    risk: str  # info | assess | harmless
    action_taken: str  # commented_out | commented_out_with_suggestion | kept
    auto_cleanable: str  # yes | partial | no
    pattern: re.Pattern


# A table-option value: quoted string, backtick identifier, or bare word.
# Matched on masked text, so quoted forms appear as 'xxx' / "xxx" — the
# original value is recovered from the match span.
_VALUE = r"(?:\"[^\"]*\"|'[^']*'|`[^`]*`|\w+)"

# Clause-level rules, applied inside CREATE TABLE / ALTER TABLE statements.
# Each pattern optionally consumes a preceding comma so commenting the clause
# out never leaves a dangling separator.
CLAUSE_RULES: list[CleanupRule] = [
    CleanupRule(
        rule_id="HW-DDL-1",
        description="SECONDARY_ENGINE table option (RAPID analytics offload — replaced by TiFlash)",
        risk="info",
        action_taken="commented_out",
        auto_cleanable="yes",
        pattern=re.compile(rf"(?:,\s*)?\bSECONDARY_ENGINE\s*(?:=\s*)?{_VALUE}", re.I),
    ),
    CleanupRule(
        rule_id="HW-DDL-2",
        description="SECONDARY_LOAD table option (TiFlash replication is automatic once the replica is set)",
        risk="info",
        action_taken="commented_out",
        auto_cleanable="yes",
        pattern=re.compile(rf"(?:,\s*)?\bSECONDARY_LOAD\s*=\s*{_VALUE}", re.I),
    ),
    CleanupRule(
        rule_id="HW-DDL-3",
        description="CLUSTERING BY clause",
        risk="assess",
        action_taken="commented_out_with_suggestion",
        auto_cleanable="partial",
        pattern=re.compile(r"(?:,\s*)?\bCLUSTERING\s+BY\s*\([^)]*\)", re.I),
    ),
]

# Statement-level form of HW-DDL-2: standalone ALTER ... SECONDARY_LOAD/UNLOAD.
# The whole statement is converted to a `--` line comment.
ALTER_SECONDARY_STMT = re.compile(
    r"ALTER\s+TABLE\s+(?P<name>(?:`[^`]+`|\w+)(?:\s*\.\s*(?:`[^`]+`|\w+))?)"
    r"\s+SECONDARY_(?:LOAD|UNLOAD)\s*;?\s*$",
    re.I,
)

# Detection-only rule: RAPID column hints inside COMMENT literals are valid,
# inert comments on TiDB and are kept as-is.
RAPID_COLUMN_RULE = CleanupRule(
    rule_id="HW-DDL-4",
    description="COMMENT 'RAPID_COLUMN=...' column comment",
    risk="harmless",
    action_taken="kept",
    auto_cleanable="no",
    pattern=re.compile(
        r"\bCOMMENT\s*(?:=\s*)?(?P<q>['\"])(?P<val>[^'\"]*RAPID_COLUMN=[^'\"]*)(?P=q)", re.I
    ),
)

# Canonical rule list for report rendering (HW-DDL-2 listed once).
ALL_RULES: list[CleanupRule] = [*CLAUSE_RULES, RAPID_COLUMN_RULE]
