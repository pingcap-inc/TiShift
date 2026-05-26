"""TiDB Cloud Import (Serverless) integration for Starter / Essential tiers.

Subprocess invocation safety: every argument is passed as a discrete element
in argv (no shell=True, no string concatenation), so shell metacharacters
in arg values are not interpreted. As defense-in-depth we additionally
validate cluster_id against TiDB Cloud's documented identifier shape and
source_url against the gs:// prefix before constructing the command.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from tishift_firestore.config import TiShiftConfig
from tishift_firestore.core.load.dataflow_runner import LoadState


log = logging.getLogger(__name__)


_CLUSTER_ID_RE = re.compile(r"^[A-Za-z0-9._\-]{1,64}$")


class InvalidCloudImportRequestError(ValueError):
    """Raised when a CloudImportRequest field fails validation."""


@dataclass
class CloudImportRequest:
    """A serialized request to `ticloud serverless import start`.

    The actual import is submitted via the ticloud CLI or the TiDB Cloud REST
    API; this struct captures the shape so the CLI can show the user the
    exact request before submission.
    """

    cluster_id: str
    source_type: str
    source_url: str
    file_pattern: str
    target_database: str

    def __post_init__(self) -> None:
        # Validate against accidental flag-injection / malformed values
        # before the request can be turned into a subprocess argv.
        if not _CLUSTER_ID_RE.fullmatch(self.cluster_id):
            raise InvalidCloudImportRequestError(
                f"cluster_id {self.cluster_id!r} does not match "
                r"[A-Za-z0-9._\-]{1,64}"
            )
        if not self.source_url.startswith("gs://"):
            raise InvalidCloudImportRequestError(
                f"source_url must begin with gs://, got {self.source_url!r}"
            )
        if self.source_type not in {"NDJSON", "CSV", "PARQUET", "SQL"}:
            raise InvalidCloudImportRequestError(
                f"source_type {self.source_type!r} is not a known TiDB Cloud import type"
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


def build_cloudimport_request(
    cfg: TiShiftConfig, *, cluster_id: str, state: LoadState
) -> CloudImportRequest:
    """Build a single CloudImportRequest covering all completed Dataflow outputs."""
    source_url = (
        f"gs://{cfg.source.staging.gcs_bucket}/{cfg.source.staging.gcs_prefix}"
    )
    return CloudImportRequest(
        cluster_id=cluster_id,
        source_type="NDJSON",
        source_url=source_url,
        file_pattern="*/part-*.ndjson",
        target_database=cfg.target.database,
    )


def submit_cloudimport(req: CloudImportRequest) -> int:
    """Submit via the ticloud CLI. Caller must have ticloud configured."""
    import subprocess

    log.info("Submitting Cloud Import: %s", " ".join(req.to_cli_args()))
    proc = subprocess.run(req.to_cli_args(), check=False)
    return proc.returncode
