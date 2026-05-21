"""Connection management for MongoDB (source) and TiDB (target).

Heavy imports (`pymongo`, `pymysql`, `google.*`) are deferred to function bodies
so that pure-logic modules can be imported without those packages installed.
"""

from __future__ import annotations

import logging
import ssl
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

from tishift_mongodb.config import SourceConfig, TargetConfig


if TYPE_CHECKING:
    import pymongo  # type: ignore[import-not-found]
    import pymysql  # type: ignore[import-not-found]


log = logging.getLogger(__name__)


class TLSConfigurationError(RuntimeError):
    """Raised when the requested TLS configuration cannot be honored safely."""


def _build_tidb_ssl_args(target: TargetConfig) -> dict[str, object]:
    """Construct the ssl kwargs for pymysql.connect from TargetConfig.

    Posture matrix:
      tls=False                                       → plaintext (allowed; warned)
      tls=True, tls_insecure_skip_verify=True         → encrypted but not verified
                                                        (explicit dev opt-in; WARN)
      tls=True, tls_ca=""                             → system trust store, verified
      tls=True, tls_ca="/path/to/ca.pem"              → pinned to CA bundle, verified
    """
    if not target.tls:
        log.warning(
            "TiDB connection configured WITHOUT TLS — "
            "credentials and data are transmitted in cleartext."
        )
        return {}

    if target.tls_insecure_skip_verify:
        log.warning(
            "TiDB TLS verification is DISABLED "
            "(tls_insecure_skip_verify=True). Use only for local dev."
        )
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

    ctx = ssl.create_default_context()
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    log.debug("TiDB TLS using system default trust store with hostname verification")
    return {"ssl": ctx}


def mongo_client(source: SourceConfig):
    """Build a PyMongo MongoClient from the SourceConfig URI.

    IAM-style read-only enforcement is the caller's responsibility: bind the
    Mongo user to the `read` role on the in-scope database. TiShift code itself
    only calls read methods (.find, .aggregate, .watch, .estimated_document_count).
    """
    from pymongo import MongoClient

    kwargs: dict[str, object] = {}
    if source.tls_ca_file:
        kwargs["tlsCAFile"] = source.tls_ca_file
    if source.tls_client_cert_key_file:
        kwargs["tlsCertificateKeyFile"] = source.tls_client_cert_key_file

    return MongoClient(source.uri, **kwargs)


@contextmanager
def tidb_connection(target: TargetConfig, *, read_only: bool = False) -> Iterator["pymysql.Connection"]:
    """Yield a PyMySQL connection to TiDB. Caller responsible for closing.

    read_only=True sets SESSION TRANSACTION READ ONLY — used by check phase to
    verify counts and structure without risking accidental writes.
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
