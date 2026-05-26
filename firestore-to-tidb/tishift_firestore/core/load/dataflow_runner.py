"""Submit Dataflow jobs (one per collection), poll until complete, update state file."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from tishift_firestore.config import TiShiftConfig
from tishift_firestore.core.load.beam_pipeline import BeamPipelineOptions, build_pipeline


log = logging.getLogger(__name__)


JobStatus = Literal["pending", "running", "complete", "failed", "cancelled"]


@dataclass
class JobState:
    collection: str
    status: JobStatus
    job_id: str = ""
    gcs_path: str = ""
    row_count: int = 0
    submitted_at: str = ""
    completed_at: str = ""

    def to_dict(self) -> dict:
        return {
            "collection": self.collection,
            "status": self.status,
            "job_id": self.job_id,
            "gcs_path": self.gcs_path,
            "row_count": self.row_count,
            "submitted_at": self.submitted_at,
            "completed_at": self.completed_at,
        }


@dataclass
class LoadState:
    load_id: str
    read_time: str
    jobs: dict[str, JobState] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "load_id": self.load_id,
            "read_time": self.read_time,
            "jobs": {k: v.to_dict() for k, v in self.jobs.items()},
        }

    def save(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))


def submit_dataflow_jobs(
    cfg: TiShiftConfig,
    *,
    collections: list[str],
    state_path: str | Path = "tishift-output/.load-state.json",
    read_time_iso: str | None = None,
) -> LoadState:
    """Submit one Dataflow job per collection. Polls until all reach a terminal state.

    Skips collections already in 'complete' state in the state file (resume semantics).
    """
    state = _load_or_init_state(state_path, read_time_iso)

    options = BeamPipelineOptions(
        project_id=cfg.source.project_id,
        database_id=cfg.source.database_id,
        region=cfg.load.dataflow.region,
        machine_type=cfg.load.dataflow.machine_type,
        max_workers=cfg.load.dataflow.max_workers,
        autoscaling=cfg.load.dataflow.autoscaling,
        network=cfg.load.dataflow.network,
        subnetwork=cfg.load.dataflow.subnetwork,
        use_public_ips=cfg.load.dataflow.use_public_ips,
        staging_location=f"gs://{cfg.source.staging.gcs_bucket}/{cfg.source.staging.gcs_prefix}_dataflow/staging",
        temp_location=f"gs://{cfg.source.staging.gcs_bucket}/{cfg.source.staging.gcs_prefix}_dataflow/temp",
    )

    for col in collections:
        existing = state.jobs.get(col)
        if existing and existing.status == "complete":
            log.info("Skipping %s (already complete)", col)
            continue

        output_path = (
            f"gs://{cfg.source.staging.gcs_bucket}/{cfg.source.staging.gcs_prefix}{col}/part"
        )
        log.info("Submitting Beam job for %s → %s", col, output_path)

        p = build_pipeline(
            collection_path=col,
            output_path=output_path,
            options=options,
            read_time_iso=state.read_time,
        )
        result = p.run()
        job_id = getattr(result, "job_id", lambda: "")()

        state.jobs[col] = JobState(
            collection=col,
            status="running",
            job_id=job_id,
            gcs_path=output_path,
            submitted_at=datetime.now(timezone.utc).isoformat(),
        )
        state.save(state_path)

        # Block until this job finishes. Could parallelize across collections —
        # left sequential in v1 for simpler operational reasoning.
        _wait_for_job(result, state.jobs[col], state, state_path)

    return state


def _wait_for_job(beam_result, job_state: JobState, state: LoadState,
                  state_path: str | Path) -> None:
    """Poll a Beam pipeline result to a terminal state, updating state file as we go."""
    try:
        beam_result.wait_until_finish()
        final_state = str(beam_result.state)
        if final_state in ("DONE", "JOB_STATE_DONE"):
            job_state.status = "complete"
        elif final_state in ("CANCELLED", "JOB_STATE_CANCELLED"):
            job_state.status = "cancelled"
        else:
            job_state.status = "failed"
    except Exception as e:  # noqa: BLE001
        log.error("Dataflow job for %s failed: %s", job_state.collection, e)
        job_state.status = "failed"

    job_state.completed_at = datetime.now(timezone.utc).isoformat()
    state.save(state_path)


def _load_or_init_state(state_path: str | Path, read_time_iso: str | None) -> LoadState:
    path = Path(state_path)
    if path.exists():
        raw = json.loads(path.read_text())
        return LoadState(
            load_id=raw["load_id"],
            read_time=raw["read_time"],
            jobs={
                k: JobState(**v) for k, v in raw.get("jobs", {}).items()
            },
        )
    import uuid
    return LoadState(
        load_id=str(uuid.uuid4()),
        read_time=read_time_iso or datetime.now(timezone.utc).isoformat(),
    )


def poll_dataflow_state(
    cfg: TiShiftConfig, state: LoadState, *, interval_seconds: int = 60
) -> LoadState:
    """For external callers — poll running jobs to fresh terminal state.

    The Beam SDK's wait_until_finish handles the same thing inline; this exists
    for resume scenarios where a previous CLI session was interrupted.
    """
    from google.cloud import dataflow_v1beta3 as dataflow
    client = dataflow.JobsV1Beta3Client()

    pending = [j for j in state.jobs.values() if j.status == "running" and j.job_id]
    while pending:
        for job in list(pending):
            request = dataflow.GetJobRequest(
                project_id=cfg.source.project_id,
                location=cfg.load.dataflow.region,
                job_id=job.job_id,
            )
            resp = client.get_job(request=request)
            state_name = dataflow.JobState(resp.current_state).name
            if state_name == "JOB_STATE_DONE":
                job.status = "complete"
                pending.remove(job)
            elif state_name in ("JOB_STATE_CANCELLED", "JOB_STATE_CANCELLING"):
                job.status = "cancelled"
                pending.remove(job)
            elif state_name in ("JOB_STATE_FAILED", "JOB_STATE_DRAINED"):
                job.status = "failed"
                pending.remove(job)
        if pending:
            time.sleep(interval_seconds)

    return state
