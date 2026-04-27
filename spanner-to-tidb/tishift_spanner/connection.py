"""Connection management for Cloud Spanner (source) and TiDB (target)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from google.cloud.spanner_v1.database import Database
    import pymysql

from tishift_spanner.config import SourceConfig, TargetConfig

logger = logging.getLogger(__name__)


def connect_source(config: SourceConfig) -> "Database":
    """Connect to a Cloud Spanner source database.

    Returns a Spanner Database object. All reads use database.snapshot()
    which is inherently read-only — no additional enforcement needed.

    Authentication: uses GOOGLE_APPLICATION_CREDENTIALS env var
    or Application Default Credentials (ADC).
    """
    from google.cloud import spanner

    if config.credentials_file:
        client = spanner.Client(
            project=config.project_id,
            credentials=_load_credentials(config.credentials_file),
        )
    else:
        client = spanner.Client(project=config.project_id)

    instance = client.instance(config.instance_id)
    database = instance.database(config.database_id)

    logger.info(
        "Connected to Spanner: project=%s, instance=%s, database=%s",
        config.project_id,
        config.instance_id,
        config.database_id,
    )
    return database


def _load_credentials(credentials_file: str):
    """Load service account credentials from a JSON key file."""
    from google.oauth2 import service_account

    return service_account.Credentials.from_service_account_file(credentials_file)


def connect_target(config: TargetConfig) -> "pymysql.Connection":
    """Connect to a TiDB target database."""
    import pymysql

    ssl = {"ssl": {"ca": ""}} if config.tls else {}

    conn = pymysql.connect(
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password,
        database=config.database,
        charset="utf8mb4",
        connect_timeout=10,
        **ssl,
    )
    return conn
