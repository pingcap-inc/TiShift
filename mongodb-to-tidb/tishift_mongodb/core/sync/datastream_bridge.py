"""GCP Datastream sync adapter — orchestrates BQ → Dataflow streaming → TiDB.

When the customer's Datastream pipes Mongo changes into BigQuery, this
module emits / starts a Dataflow streaming job that reads BQ's `_raw`
tables and writes to TiDB. Same shape as the Firestore variant's BQ-bridge.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from tishift_mongodb.config import TiShiftConfig


log = logging.getLogger(__name__)


@dataclass
class DataflowStreamingJobSpec:
    dataset_id: str
    target_database: str
    region: str
    since_timestamp_iso: str


def emit_dataflow_job_spec(
    cfg: TiShiftConfig, *, since_timestamp_iso: str,
    output_path: str | Path = "tishift-output/datastream-sync-job.json",
) -> Path:
    """Emit a Dataflow streaming-job spec the customer can submit."""
    spec = {
        "displayName": f"tishift-mongo-sync-{cfg.source.database}",
        "parameters": {
            "bigqueryProject": cfg.sync.datastream.bigquery_dataset_id.split(".")[0]
                if "." in cfg.sync.datastream.bigquery_dataset_id else "",
            "bigqueryDataset": cfg.sync.datastream.bigquery_dataset_id,
            "tidbHost": cfg.target.host,
            "tidbPort": cfg.target.port,
            "tidbUser": cfg.target.user,
            "tidbDatabase": cfg.target.database,
            "sinceTimestamp": since_timestamp_iso,
        },
    }
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(spec, indent=2))
    log.info("Wrote Datastream sync job spec to %s", path)
    return path
