"""GCP Datastream adapter for bulk load (full-load + initial-CDC).

Adapter only — TiShift emits Datastream stream config + BQ-to-GCS export
job; the customer's GCP project runs the actual jobs. Adapter requires
the `datastream` install extra (apache-beam + google-cloud-bigquery).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from tishift_mongodb.config import TiShiftConfig


log = logging.getLogger(__name__)


def emit_stream_config(
    cfg: TiShiftConfig, *, output_path: str | Path = "tishift-output/datastream-stream-config.json"
) -> Path:
    """Emit a Datastream stream-creation payload for the customer to apply."""
    if not cfg.load.datastream.region:
        raise ValueError("load.datastream.region is required for datastream strategy")

    payload = {
        "displayName": f"tishift-mongo-{cfg.source.database}",
        "labels": {"tishift": "mongodb-to-tidb"},
        "sourceConfig": {
            "sourceConnectionProfile": "MONGODB_PROFILE_ARN_HERE",
            "mongodbSourceConfig": {
                "includeObjects": {"databases": [{"database": cfg.source.database}]},
            },
        },
        "destinationConfig": {
            "destinationConnectionProfile": "BIGQUERY_PROFILE_ARN_HERE",
            "bigqueryDestinationConfig": {
                "singleTargetDataset": {
                    "datasetId": cfg.load.datastream.bigquery_dataset_id,
                },
                "appendOnly": {},
            },
        },
        "backfillAll": {},
    }

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))
    log.info("Wrote Datastream stream config to %s", path)
    log.info(
        "Apply via: gcloud datastream streams create %s --location=%s --json-file=%s",
        cfg.load.datastream.stream_id or "tishift-mongo-stream",
        cfg.load.datastream.region,
        path,
    )
    return path
