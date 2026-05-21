"""Connection management for Firestore (source) and TiDB (target)."""

from __future__ import annotations

import logging
import ssl
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

from tishift_firestore.config import SourceConfig, TargetConfig


if TYPE_CHECKING:
    import pymysql  # type: ignore[import-not-found]
    from google.cloud import firestore  # type: ignore[import-not-found]
    from google.cloud.firestore_admin_v1 import FirestoreAdminClient  # type: ignore[import-not-found]


log = logging.getLogger(__name__)


class TLSConfigurationError(RuntimeError):
    """Raised when the requested TLS configuration cannot be honored safely."""


def _build_tidb_ssl_args(target: TargetConfig) -> dict[str, object]:
    """Construct the ssl kwargs for pymysql.connect from TargetConfig.

    Posture matrix:
      tls=False                                       → plaintext  (allowed; warned)
      tls=True, tls_insecure_skip_verify=True         → encrypted but not verified
                                                        (explicit dev opt-in only;
                                                        emits a WARNING)
      tls=True, tls_ca=""  (system bundle)            → verified against system CAs
      tls=True, tls_ca="/path/to/ca.pem"              → verified against pinned CA

    PyMySQL accepts an SSLContext via ssl_kwargs={"ssl": ctx} or a dict of
    keyword args. We build an explicit SSLContext so the verify behavior is
    unambiguous across pymysql versions.
    """
    if not target.tls:
        log.warning("TiDB connection configured WITHOUT TLS — "
                    "credentials and data are transmitted in cleartext.")
        return {}

    if target.tls_insecure_skip_verify:
        # ssl.create_default_context with verify_mode=NONE disables both
        # hostname checking and CA validation. Explicit, auditable bypass.
        log.warning("TiDB TLS verification is DISABLED "
                    "(tls_insecure_skip_verify=True). Use only for local dev.")
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return {"ssl": ctx}

    if target.tls_ca:
        ca_path = Path(target.tls_ca)
        if not ca_path.is_file():
            raise TLSConfigurationError(
                f"tls_ca points to a path that is not a regular file: {ca_path}"
            )
        ctx = ssl.create_default_context(cafile=str(ca_path))
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED
        log.debug("TiDB TLS pinned to CA bundle %s", ca_path)
        return {"ssl": ctx}

    # System default trust store with verification on.
    ctx = ssl.create_default_context()
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    log.debug("TiDB TLS using system default trust store with hostname verification")
    return {"ssl": ctx}


def _firestore_credentials(source: SourceConfig):
    """Resolve credentials in precedence order: explicit SA key path > ADC."""
    from google.auth import default as adc_default
    from google.oauth2 import service_account

    if source.service_account_key:
        log.debug("Using explicit service-account key from %s", source.service_account_key)
        return service_account.Credentials.from_service_account_file(
            source.service_account_key
        )
    log.debug("Using Application Default Credentials")
    creds, _ = adc_default()
    return creds


def firestore_client(source: SourceConfig):
    """Build a Firestore Client for read-only operations.

    IAM enforcement of read-only-ness is the caller's responsibility: bind the
    service account only to roles/datastore.viewer (and roles/datastore.indexAdmin
    for index reads). TiShift code itself only calls read methods.
    """
    from google.cloud import firestore as gfirestore

    creds = _firestore_credentials(source)
    if source.database_id == "(default)":
        return gfirestore.Client(project=source.project_id, credentials=creds)
    return gfirestore.Client(
        project=source.project_id,
        credentials=creds,
        database=source.database_id,
    )


def firestore_admin_client(source: SourceConfig):
    """Build a Firestore Admin Client for listing databases and composite indexes."""
    from google.cloud.firestore_admin_v1 import FirestoreAdminClient as _Admin

    creds = _firestore_credentials(source)
    return _Admin(credentials=creds)


@contextmanager
def tidb_connection(target: TargetConfig, *, read_only: bool = False) -> Iterator["pymysql.Connection"]:
    """Yield a PyMySQL connection to TiDB. Caller is responsible for closing.

    When read_only=True, the connection is set to READ ONLY at the session level
    — this is used by the check phase to verify counts and structure without
    risking accidental writes.
    """
    import pymysql as _pymysql
    import pymysql.cursors as _cursors

    ssl_args = _build_tidb_ssl_args(target)

    conn = _pymysql.connect(
        host=target.host,
        port=target.port,
        user=target.user,
        password=target.password.get_secret_value(),
        database=target.database,
        charset="utf8mb4",
        cursorclass=_cursors.DictCursor,
        autocommit=False,
        **ssl_args,
    )
    try:
        if read_only:
            with conn.cursor() as cur:
                cur.execute("SET SESSION TRANSACTION READ ONLY")
        yield conn
    finally:
        conn.close()
