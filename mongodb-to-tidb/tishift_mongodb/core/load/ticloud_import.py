"""TiDB Cloud Serverless Import — for Starter/Essential tier customers.

Subprocess safety: args as list, no shell, value validation via regex
to prevent flag-injection.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass


log = logging.getLogger(__name__)

# Must start with alphanumeric/underscore to prevent argv flag-injection
# (a value like "--evil" must be rejected even though it only uses safe chars).
_CLUSTER_ID_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._\-]{0,63}$")


class InvalidCloudImportRequestError(ValueError):
    """Raised when a CloudImportRequest field fails validation."""


@dataclass
class CloudImportRequest:
    cluster_id: str
    source_type: str
    source_url: str
    file_pattern: str
    target_database: str

    def __post_init__(self) -> None:
        if not _CLUSTER_ID_RE.fullmatch(self.cluster_id):
            raise InvalidCloudImportRequestError(
                f"cluster_id {self.cluster_id!r} fails [A-Za-z0-9._\\-]{{1,64}}"
            )
        if not self.source_url.startswith(("s3://", "gs://", "azure://")):
            raise InvalidCloudImportRequestError(
                f"source_url must begin with s3:// gs:// or azure://, got {self.source_url!r}"
            )
        if self.source_type not in {"NDJSON", "CSV", "PARQUET", "SQL"}:
            raise InvalidCloudImportRequestError(
                f"source_type {self.source_type!r} not a known TiDB Cloud import type"
            )
        if not _CLUSTER_ID_RE.fullmatch(self.target_database):
            raise InvalidCloudImportRequestError(
                f"target_database {self.target_database!r} contains unsafe characters"
            )

    def to_cli_args(self) -> list[str]:
        return [
            "ticloud", "serverless", "import", "start",
            "--cluster-id", self.cluster_id,
            "--source-type", self.source_type,
            "--source-url", self.source_url,
            "--file-pattern", self.file_pattern,
            "--target-database", self.target_database,
        ]


def build_cloudimport_request(cfg, *, cluster_id: str) -> CloudImportRequest:
    return CloudImportRequest(
        cluster_id=cluster_id,
        source_type="NDJSON",
        source_url=cfg.load.staging.base_url,
        file_pattern="*/part-*.ndjson",
        target_database=cfg.target.database,
    )


def submit_cloudimport(req: CloudImportRequest) -> int:
    import subprocess
    log.info("Submitting Cloud Import: %s", " ".join(req.to_cli_args()))
    proc = subprocess.run(req.to_cli_args(), check=False)
    return proc.returncode
