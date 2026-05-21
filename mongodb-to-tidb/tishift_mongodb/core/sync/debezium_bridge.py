"""Debezium adapter — emit Kafka Connect connector configs for customer to apply.

TiShift produces JSON configs for:
1. MongoDbConnector (source) — Change Streams → Kafka topics
2. JdbcSinkConnector (sink) — Kafka topics → TiDB

The customer applies via Kafka Connect REST API. TiShift can optionally
poll status via the REST API.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from tishift_mongodb.config import TiShiftConfig


log = logging.getLogger(__name__)


def emit_source_connector_config(
    cfg: TiShiftConfig,
    *,
    output_path: str | Path = "tishift-output/debezium-mongodb-source.json",
) -> Path:
    """Debezium MongoDB source connector config."""
    config = {
        "name": cfg.sync.debezium.source_connector_name or f"tishift-mongo-{cfg.source.database}",
        "config": {
            "connector.class": "io.debezium.connector.mongodb.MongoDbConnector",
            "mongodb.connection.string": cfg.source.uri,
            "topic.prefix": f"tishift.{cfg.source.database}",
            "database.include.list": cfg.source.database,
            "capture.mode": "change_streams_update_full",
            "tasks.max": "1",
        },
    }
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2))
    log.info("Wrote Debezium MongoDB source config to %s", path)
    return path


def emit_jdbc_sink_connector_config(
    cfg: TiShiftConfig,
    *,
    output_path: str | Path = "tishift-output/debezium-jdbc-sink.json",
) -> Path:
    """Debezium JDBC sink (Kafka topics → TiDB) connector config.

    NOTE: the TiDB password is NOT embedded here — the customer must inject it
    via their Kafka Connect secrets store (e.g., FileConfigProvider).
    """
    config = {
        "name": cfg.sync.debezium.jdbc_sink_connector_name or f"tishift-tidb-sink-{cfg.target.database}",
        "config": {
            "connector.class": "io.debezium.connector.jdbc.JdbcSinkConnector",
            "connection.url": f"jdbc:mysql://{cfg.target.host}:{cfg.target.port}/{cfg.target.database}?useSSL=true",
            "connection.username": cfg.target.user,
            "connection.password": "${file:/etc/kafka/secrets/tidb-password.properties:tidb_password}",
            "topics.regex": f"tishift\\.{cfg.source.database}\\..*",
            "insert.mode": "upsert",
            "primary.key.mode": "record_key",
            "delete.enabled": "true",
            "auto.create": "false",
            "auto.evolve": "false",
        },
    }
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2))
    log.info("Wrote Debezium JDBC sink config to %s", path)
    log.info("Note: password injection via Kafka Connect secrets store, NOT inlined here")
    return path


def emit_both(cfg: TiShiftConfig, *, output_dir: str | Path = "tishift-output") -> tuple[Path, Path]:
    """Emit both connector configs."""
    src = emit_source_connector_config(cfg, output_path=Path(output_dir) / "debezium-mongodb-source.json")
    sink = emit_jdbc_sink_connector_config(cfg, output_path=Path(output_dir) / "debezium-jdbc-sink.json")
    return src, sink
