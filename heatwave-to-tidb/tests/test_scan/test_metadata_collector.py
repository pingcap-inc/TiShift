"""Tests for collect_heatwave_metadata against a scripted fake connection."""

from tests.test_scan.fake_connection import RAISES_ERROR, ScriptedConnection

from tishift_heatwave.core.scan.collectors.metadata import collect_heatwave_metadata

FULL_RESPONSES = [
    # "@@version_comment" must be checked before the shorter "SELECT @@version"
    # pattern below — first-match-wins substring matching would otherwise let
    # "SELECT @@version" (a prefix of the version_comment query) match first.
    ("@@version_comment", [{"@@version_comment": "MySQL Enterprise - Cloud"}]),
    ("SELECT @@version", [{"@@version": "8.0.32-cloud"}]),
    ("rpd_nodes", [{"n": 3}]),
    ("@@binlog_row_value_options", [{"@@binlog_row_value_options": "PARTIAL_JSON"}]),
    ("@@gtid_mode", [{"@@gtid_mode": "ON"}]),
    ("@@character_set_server", [{"@@character_set_server": "utf8mb4"}]),
    ("@@collation_server", [{"@@collation_server": "utf8mb4_0900_ai_ci"}]),
    ("@@transaction_isolation", [{"@@transaction_isolation": "REPEATABLE-READ"}]),
    ("@@sql_mode", [{"@@sql_mode": "ONLY_FULL_GROUP_BY"}]),
    ("@@lower_case_table_names", [{"@@lower_case_table_names": "0"}]),
    ("@@max_connections", [{"@@max_connections": "5000"}]),
    ("@@read_only", [{"@@read_only": "0"}]),
    ("@@super_read_only", [{"@@super_read_only": "0"}]),
    ("SHOW REPLICA STATUS", []),
    (
        "SHOW REPLICAS",
        [
            {"Server_id": 101, "Host": "10.0.1.20", "Port": 3306},
            {"Server_id": 102, "Host": "10.0.1.21", "Port": 3306},
        ],
    ),
]


def test_collects_all_fields_from_a_heatwave_source():
    conn = ScriptedConnection(FULL_RESPONSES)

    meta = collect_heatwave_metadata(conn)

    assert meta.mysql_version == "8.0.32-cloud"
    assert meta.version_comment == "MySQL Enterprise - Cloud"
    assert meta.has_rapid_cluster is True
    assert meta.rapid_node_count == 3
    assert meta.binlog_row_value_options == "PARTIAL_JSON"
    assert meta.gtid_mode == "ON"
    assert meta.character_set_server == "utf8mb4"
    assert meta.collation_server == "utf8mb4_0900_ai_ci"
    assert meta.transaction_isolation == "REPEATABLE-READ"
    assert meta.sql_mode == "ONLY_FULL_GROUP_BY"
    assert meta.lower_case_table_names == 0
    assert meta.max_connections == 5000
    # topology: primary node with two attached read replicas
    assert meta.read_only is False
    assert meta.super_read_only is False
    assert meta.is_replica is False
    assert meta.replica_source_host is None
    assert meta.connected_replica_count == 2
    assert meta.connected_replica_hosts == ["10.0.1.20", "10.0.1.21"]


def test_degrades_gracefully_on_plain_mysql_without_rapid_cluster():
    responses = [
        ("rpd_nodes", RAISES_ERROR) if r[0] == "rpd_nodes" else r for r in FULL_RESPONSES
    ]
    conn = ScriptedConnection(responses)

    meta = collect_heatwave_metadata(conn)

    assert meta.has_rapid_cluster is False
    assert meta.rapid_node_count == 0
    # other fields still collected normally
    assert meta.mysql_version == "8.0.32-cloud"


def test_version_comment_missing_on_community_mysql():
    # Replace in place so "@@version_comment" still precedes the shorter
    # "SELECT @@version" pattern in match order.
    responses = [
        ("@@version_comment", RAISES_ERROR) if r[0] == "@@version_comment" else r
        for r in FULL_RESPONSES
    ]
    conn = ScriptedConnection(responses)

    meta = collect_heatwave_metadata(conn)

    assert meta.version_comment is None


class TestReplicationTopology:
    def test_replica_node_reports_source_host(self):
        responses = [
            ("@@read_only", [{"@@read_only": "1"}]) if r[0] == "@@read_only" else r
            for r in FULL_RESPONSES
        ]
        responses = [
            ("@@super_read_only", [{"@@super_read_only": "1"}])
            if r[0] == "@@super_read_only"
            else r
            for r in responses
        ]
        responses = [
            ("SHOW REPLICA STATUS", [{"Source_Host": "10.0.1.10"}])
            if r[0] == "SHOW REPLICA STATUS"
            else r
            for r in responses
        ]
        responses = [("SHOW REPLICAS", []) if r[0] == "SHOW REPLICAS" else r for r in responses]
        conn = ScriptedConnection(responses)

        meta = collect_heatwave_metadata(conn)

        assert meta.read_only is True
        assert meta.super_read_only is True
        assert meta.is_replica is True
        assert meta.replica_source_host == "10.0.1.10"
        assert meta.connected_replica_count == 0

    def test_degrades_without_replication_client_privilege(self):
        responses = [
            ("SHOW REPLICA STATUS", RAISES_ERROR) if r[0] == "SHOW REPLICA STATUS" else r
            for r in FULL_RESPONSES
        ]
        responses = [
            ("SHOW REPLICAS", RAISES_ERROR) if r[0] == "SHOW REPLICAS" else r for r in responses
        ]
        conn = ScriptedConnection(responses)

        meta = collect_heatwave_metadata(conn)

        assert meta.is_replica is False
        assert meta.replica_source_host is None
        assert meta.connected_replica_count == 0
        assert meta.connected_replica_hosts == []
        # other fields collected normally
        assert meta.mysql_version == "8.0.32-cloud"
