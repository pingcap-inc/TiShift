"""Tests for the binlog/CDC-readiness precheck (rules + analyzer)."""

from tishift_heatwave.core.scan.analyzers.binlog_check import evaluate_binlog_config
from tishift_heatwave.rules.binlog_check import QUERY

ALL_GOOD = {
    "log_bin": "ON",
    "server_id": "1",
    "binlog_format": "ROW",
    "binlog_row_image": "FULL",
    "binlog_expire_logs_seconds": "604800",
    "expire_logs_days": "0",
    "binlog_transaction_compression": "OFF",
    "binlog_row_value_options": "",
}


def by_variable(result, name):
    return next(c for c in result.checks if c.variable == name)


class TestQuery:
    def test_query_matches_spec(self):
        assert QUERY == (
            "SHOW VARIABLES WHERE Variable_name IN "
            "('log_bin','server_id','binlog_format','binlog_row_image',"
            "'binlog_expire_logs_seconds','expire_logs_days',"
            "'binlog_transaction_compression','binlog_row_value_options')"
        )


class TestAllGood:
    def test_continue_replication_ready_when_everything_passes(self):
        result = evaluate_binlog_config(ALL_GOOD)
        assert result.continue_replication_ready is True
        assert all(c.status in ("pass", "info") for c in result.checks)

    def test_eight_checks_returned(self):
        result = evaluate_binlog_config(ALL_GOOD)
        assert len(result.checks) == 8  # 6 gated + server_id + expire_logs_days


class TestLogBin:
    def test_off_fails_and_blocks_cdc(self):
        variables = {**ALL_GOOD, "log_bin": "OFF"}
        result = evaluate_binlog_config(variables)
        check = by_variable(result, "log_bin")
        assert check.status == "fail"
        assert check.rule_id == "HW-WARNING-6"
        assert result.continue_replication_ready is False

    def test_missing_fails(self):
        variables = {k: v for k, v in ALL_GOOD.items() if k != "log_bin"}
        result = evaluate_binlog_config(variables)
        assert by_variable(result, "log_bin").status == "fail"

    def test_case_insensitive(self):
        variables = {**ALL_GOOD, "log_bin": "on"}
        result = evaluate_binlog_config(variables)
        assert by_variable(result, "log_bin").status == "pass"


class TestBinlogFormat:
    def test_mixed_fails(self):
        variables = {**ALL_GOOD, "binlog_format": "MIXED"}
        result = evaluate_binlog_config(variables)
        check = by_variable(result, "binlog_format")
        assert check.status == "fail"
        assert check.rule_id == "HW-WARNING-7"
        assert result.continue_replication_ready is False

    def test_statement_fails(self):
        variables = {**ALL_GOOD, "binlog_format": "STATEMENT"}
        result = evaluate_binlog_config(variables)
        assert by_variable(result, "binlog_format").status == "fail"


class TestBinlogRowImage:
    def test_minimal_fails(self):
        variables = {**ALL_GOOD, "binlog_row_image": "MINIMAL"}
        result = evaluate_binlog_config(variables)
        check = by_variable(result, "binlog_row_image")
        assert check.status == "fail"
        assert check.rule_id == "HW-WARNING-8"
        assert result.continue_replication_ready is False


class TestBinlogExpireLogsSeconds:
    def test_below_hard_floor_fails(self):
        variables = {**ALL_GOOD, "binlog_expire_logs_seconds": "3600"}
        result = evaluate_binlog_config(variables)
        check = by_variable(result, "binlog_expire_logs_seconds")
        assert check.status == "fail"
        assert check.rule_id == "HW-WARNING-4"
        assert result.continue_replication_ready is False

    def test_exactly_one_day_passes_but_below_recommended_warns(self):
        variables = {**ALL_GOOD, "binlog_expire_logs_seconds": "86400"}
        result = evaluate_binlog_config(variables)
        check = by_variable(result, "binlog_expire_logs_seconds")
        assert check.status == "warn"
        assert result.continue_replication_ready is True  # warn does not block CDC, only fail does

    def test_at_or_above_recommended_passes_clean(self):
        variables = {**ALL_GOOD, "binlog_expire_logs_seconds": "604800"}
        result = evaluate_binlog_config(variables)
        assert by_variable(result, "binlog_expire_logs_seconds").status == "pass"

    def test_non_numeric_fails(self):
        variables = {**ALL_GOOD, "binlog_expire_logs_seconds": "not-a-number"}
        result = evaluate_binlog_config(variables)
        assert by_variable(result, "binlog_expire_logs_seconds").status == "fail"


class TestBinlogTransactionCompression:
    def test_on_fails(self):
        variables = {**ALL_GOOD, "binlog_transaction_compression": "ON"}
        result = evaluate_binlog_config(variables)
        check = by_variable(result, "binlog_transaction_compression")
        assert check.status == "fail"
        assert check.rule_id == "HW-WARNING-9"
        assert result.continue_replication_ready is False


class TestBinlogRowValueOptions:
    def test_partial_json_fails_and_blocks(self):
        variables = {**ALL_GOOD, "binlog_row_value_options": "PARTIAL_JSON"}
        result = evaluate_binlog_config(variables)
        check = by_variable(result, "binlog_row_value_options")
        assert check.status == "fail"
        assert check.rule_id == "HW-WARNING-5"
        assert result.continue_replication_ready is False

    def test_empty_passes(self):
        result = evaluate_binlog_config(ALL_GOOD)
        assert by_variable(result, "binlog_row_value_options").status == "pass"

    def test_missing_fails(self):
        variables = {k: v for k, v in ALL_GOOD.items() if k != "binlog_row_value_options"}
        result = evaluate_binlog_config(variables)
        assert by_variable(result, "binlog_row_value_options").status == "fail"


class TestInformationalVariables:
    def test_server_id_zero_warns_but_does_not_block_cdc(self):
        variables = {**ALL_GOOD, "server_id": "0"}
        result = evaluate_binlog_config(variables)
        check = by_variable(result, "server_id")
        assert check.status == "warn"
        assert check.rule_id is None
        assert result.continue_replication_ready is True  # informational only, never gates CDC

    def test_server_id_nonzero_is_info(self):
        result = evaluate_binlog_config(ALL_GOOD)
        assert by_variable(result, "server_id").status == "info"

    def test_expire_logs_days_always_info(self):
        variables = {**ALL_GOOD, "expire_logs_days": "30"}
        result = evaluate_binlog_config(variables)
        check = by_variable(result, "expire_logs_days")
        assert check.status == "info"
        assert check.rule_id is None
        assert result.continue_replication_ready is True


class TestMultipleFailures:
    def test_all_bad_reports_every_failure(self):
        variables = {
            "log_bin": "OFF",
            "server_id": "0",
            "binlog_format": "STATEMENT",
            "binlog_row_image": "MINIMAL",
            "binlog_expire_logs_seconds": "0",
            "expire_logs_days": "0",
            "binlog_transaction_compression": "ON",
            "binlog_row_value_options": "PARTIAL_JSON",
        }
        result = evaluate_binlog_config(variables)
        assert result.continue_replication_ready is False
        failed_rule_ids = {c.rule_id for c in result.checks if c.status == "fail"}
        assert failed_rule_ids == {
            "HW-WARNING-4",
            "HW-WARNING-5",
            "HW-WARNING-6",
            "HW-WARNING-7",
            "HW-WARNING-8",
            "HW-WARNING-9",
        }
