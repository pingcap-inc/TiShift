"""Apache Beam pipeline definition for Firestore → GCS NDJSON extraction.

The pipeline is read-only on Firestore and stateless; one job per collection.
Pinned to a single `read_time` snapshot for cross-worker consistency.

Note: this module imports apache_beam lazily so that scan/convert/check work
even when the heavyweight Beam dependency stack isn't installed (CI, small
test loops).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BeamPipelineOptions:
    project_id: str
    database_id: str
    region: str
    machine_type: str
    max_workers: int
    autoscaling: str
    network: str
    subnetwork: str
    use_public_ips: bool
    staging_location: str
    temp_location: str
    num_shards: int = 100


def doc_to_ndjson(doc: Any) -> str:
    """Serialize one Firestore document (Beam-side) to a single NDJSON line."""
    body = _firestore_value_to_python(doc)
    body["_id"] = doc.id if hasattr(doc, "id") else body.get("_id", "")
    return json.dumps(body, separators=(",", ":"), default=str)


def _firestore_value_to_python(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, list):
        return [_firestore_value_to_python(v) for v in value]
    if isinstance(value, dict):
        return {k: _firestore_value_to_python(v) for k, v in value.items()}
    if hasattr(value, "to_dict"):
        return _firestore_value_to_python(value.to_dict())
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "latitude"):
        return {"lat": value.latitude, "lng": value.longitude}
    if hasattr(value, "path"):
        return {"$ref": value.path}
    if isinstance(value, bytes):
        import base64
        return {"$bytes": base64.b64encode(value).decode("ascii")}
    return str(value)


def build_pipeline_args(
    *,
    collection_path: str,
    output_path: str,
    options: BeamPipelineOptions,
    read_time_iso: str,
) -> list[str]:
    """Build the command-line argument list for `python -m apache_beam.examples...`-style runners.

    For real production use the inline Pipeline construction is preferred; this
    function exists so the CLI can show the user exactly what would be submitted.
    """
    return [
        "--runner=DataflowRunner",
        f"--project={options.project_id}",
        f"--region={options.region}",
        f"--machine_type={options.machine_type}",
        f"--max_num_workers={options.max_workers}",
        f"--autoscaling_algorithm={options.autoscaling}",
        f"--network={options.network}",
        *(["--subnetwork=" + options.subnetwork] if options.subnetwork else []),
        f"--use_public_ips={'true' if options.use_public_ips else 'false'}",
        f"--staging_location={options.staging_location}",
        f"--temp_location={options.temp_location}",
        # Application args:
        f"--firestore_database={options.database_id}",
        f"--firestore_collection={collection_path}",
        f"--read_time={read_time_iso}",
        f"--output_path={output_path}",
        f"--num_shards={options.num_shards}",
    ]


def build_pipeline(*, collection_path: str, output_path: str,
                   options: BeamPipelineOptions, read_time_iso: str):
    """Build a Beam Pipeline object. Requires apache-beam[gcp] installed."""
    import apache_beam as beam
    from apache_beam.io.gcp.firestore import ReadFromFirestore
    from apache_beam.options.pipeline_options import PipelineOptions

    pipeline_opts = PipelineOptions(
        flags=build_pipeline_args(
            collection_path=collection_path,
            output_path=output_path,
            options=options,
            read_time_iso=read_time_iso,
        )
    )

    p = beam.Pipeline(options=pipeline_opts)
    (
        p
        | "ReadFirestore"
        >> ReadFromFirestore(
            project=options.project_id,
            database=options.database_id,
            collection=collection_path,
            read_time=read_time_iso,
        )
        | "MapToNDJSON" >> beam.Map(doc_to_ndjson)
        | "WriteGCS"
        >> beam.io.WriteToText(
            file_path_prefix=output_path,
            file_name_suffix=".ndjson",
            num_shards=options.num_shards,
        )
    )
    return p
