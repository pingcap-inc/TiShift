"""OceanBase compatibility mode detection and branching."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


OBMode = Literal["mysql", "oracle"]


@dataclass(frozen=True)
class OBEnvironment:
    """Detected OceanBase environment metadata."""
    mode: OBMode
    version: str
    tenant: str

    @property
    def is_mysql_mode(self) -> bool:
        return self.mode == "mysql"

    @property
    def is_oracle_mode(self) -> bool:
        return self.mode == "oracle"

    @property
    def major_version(self) -> float:
        """Extract major.minor version as float (e.g., 4.2)."""
        try:
            parts = self.version.split(".")
            return float(f"{parts[0]}.{parts[1]}")
        except (ValueError, IndexError):
            return 0.0

    @property
    def sqlglot_dialect(self) -> str:
        """Return the sqlglot read dialect for this mode."""
        return "mysql" if self.is_mysql_mode else "oracle"
