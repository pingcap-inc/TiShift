"""Integration test for run_scan — wires all collectors + analyzers together
over one scripted fake connection. Individual collector/analyzer behavior is
already covered by their own unit tests; this just proves the wiring works
end-to-end and that continue_replication_planned correctly gates the valid-indexes precheck.
"""

from tests.test_scan.fake_connection import ScriptedConnection
from tests.test_scan.test_metadata_collector import FULL_RESPONSES as METADATA_RESPONSES
from tests.test_scan.test_schema_collector import BASE_RESPONSES as SCHEMA_RESPONSES

from tishift_heatwave.core.scan.orchestrator import run_scan

BINLOG_RESPONSES = [
    (
        "Variable_name IN",
        [
            {"Variable_name": "log_bin", "Value": "ON"},
            {"Variable_name": "server_id", "Value": "1"},
            {"Variable_name": "binlog_format", "Value": "ROW"},
            {"Variable_name": "binlog_row_image", "Value": "FULL"},
            {"Variable_name": "binlog_expire_logs_seconds", "Value": "604800"},
            {"Variable_name": "expire_logs_days", "Value": "0"},
            {"Variable_name": "binlog_transaction_compression", "Value": "OFF"},
            {"Variable_name": "binlog_row_value_options", "Value": ""},
        ],
    )
]

VALID_INDEX_RESPONSES = [
    (
        "information_schema.tables",  # lowercase — distinct from schema.py's "TABLES"
        [{"table_name": "audit_log", "table_schema": "myapp"}],
    )
]

# Order matters: the valid-indexes query and schema.py's AutoML-schema query
# both contain the literal substring "ML\_SCHEMA\_%", so VALID_INDEX_RESPONSES
# (matched via the more specific "information_schema.tables" — lowercase,
# unlike schema.py's "TABLES") must be checked before SCHEMA_RESPONSES.
ALL_RESPONSES = [*VALID_INDEX_RESPONSES, *METADATA_RESPONSES, *BINLOG_RESPONSES, *SCHEMA_RESPONSES]


def test_run_scan_wires_everything_together_without_cdc():
    conn = ScriptedConnection(ALL_RESPONSES)

    result = run_scan(conn, "myapp", tier="essential", continue_replication_planned=False)

    assert result.schema == "myapp"
    assert result.metadata.mysql_version == "8.0.32-cloud"
    assert len(result.inventory.tables) == 2  # orders, customers
    assert result.binlog.continue_replication_ready is True
    assert result.tables_without_valid_index == []  # not run — continue_replication_planned is False
    assert result.total_size_bytes == (65536 + 16384) + (32768 + 8192)
    assert result.score.overall > 0
    # RAPID offload + FK + VECTOR + 0900 collation + lower_case_table_names=0 +
    # one updatable view all present in the fixture
    warning_ids = {f.rule_id for f in result.assessment.warnings}
    assert "HW-WARNING-1" in warning_ids  # RAPID
    assert "WARNING-1" not in warning_ids  # foreign keys are compatible (target TiDB Cloud v8.5)
    assert "HW-WARNING-2" in warning_ids  # VECTOR
    assert "WARNING-4" in warning_ids  # 0900 collation (informational, no deduction)
    assert "WARNING-8" in warning_ids  # lower_case_table_names=0 != TiDB's required 2
    assert "WARNING-9" in warning_ids  # active_orders view is updatable
    assert "BLOCKER-8" not in {f.rule_id for f in result.assessment.blockers}  # no bad charsets
    assert "BLOCKER-9" not in {f.rule_id for f in result.assessment.blockers}  # no name collisions
    # programmable-object blockers from the fixture (trigger, event, JS routine)
    blocker_ids = {f.rule_id for f in result.assessment.blockers}
    assert "BLOCKER-2" in blocker_ids  # trigger
    assert "BLOCKER-3" in blocker_ids  # event
    assert "HW-BLOCKER-3" in blocker_ids  # JS routine


def test_valid_index_precheck_only_runs_when_continue_replication_planned():
    conn = ScriptedConnection(ALL_RESPONSES)

    result = run_scan(conn, "myapp", tier="essential", continue_replication_planned=True)

    assert result.tables_without_valid_index == [("myapp", "audit_log")]
    cutover = next(c for c in result.score.categories if c.name == "Cutover & continue replication")
    assert any("PK/UNIQUE index" in d for d in cutover.deductions)


def test_fk_and_collation_do_not_deduct():
    conn = ScriptedConnection(ALL_RESPONSES)

    result = run_scan(conn, "myapp", tier="essential")

    schema_cat = next(c for c in result.score.categories if c.name == "Schema compatibility")
    assert not any("foreign key" in d.lower() for d in schema_cat.deductions)
    assert not any(d.startswith("-") and "0900" in d and not d.startswith("-0:") for d in schema_cat.deductions)
