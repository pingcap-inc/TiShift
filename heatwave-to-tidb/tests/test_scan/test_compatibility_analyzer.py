"""Tests for the compatibility analyzer (pure, fixture-driven)."""

from tishift_heatwave.core.scan.analyzers.binlog_check import evaluate_binlog_config
from tishift_heatwave.core.scan.analyzers.compatibility import assess_compatibility
from tishift_heatwave.models import (
    ColumnInfo,
    ConstraintInfo,
    EventInfo,
    HeatWaveMetadata,
    IndexInfo,
    QueryLogSignals,
    RoutineInfo,
    SchemaInventory,
    Severity,
    TableInfo,
    TriggerInfo,
    ViewInfo,
)

CLEAN_BINLOG_VARS = {
    "log_bin": "ON",
    "server_id": "1",
    "binlog_format": "ROW",
    "binlog_row_image": "FULL",
    "binlog_expire_logs_seconds": "604800",
    "expire_logs_days": "0",
    "binlog_transaction_compression": "OFF",
}


def empty_inventory() -> SchemaInventory:
    return SchemaInventory()


def by_id(findings, rule_id):
    return next((f for f in findings if f.rule_id == rule_id), None)


class TestEmptyInventoryIsClean:
    def test_no_blockers_no_warnings(self):
        result = assess_compatibility(
            empty_inventory(), HeatWaveMetadata(), evaluate_binlog_config(CLEAN_BINLOG_VARS)
        )
        assert result.blockers == []
        assert result.warnings == []
        assert len(result.compatible) > 0


class TestBlockers:
    def test_stored_procedures_trigger_blocker_1(self):
        inv = empty_inventory()
        inv.routines = [
            RoutineInfo(schema_name="myapp", routine_name="p1", kind="PROCEDURE", definition="")
        ]
        result = assess_compatibility(inv, HeatWaveMetadata(), evaluate_binlog_config(CLEAN_BINLOG_VARS))
        f = by_id(result.blockers, "BLOCKER-1")
        assert f is not None
        assert f.count == 1
        assert f.severity == Severity.BLOCKER

    def test_functions_do_not_trigger_blocker_1(self):
        inv = empty_inventory()
        inv.routines = [
            RoutineInfo(schema_name="myapp", routine_name="f1", kind="FUNCTION", definition="")
        ]
        result = assess_compatibility(inv, HeatWaveMetadata(), evaluate_binlog_config(CLEAN_BINLOG_VARS))
        assert by_id(result.blockers, "BLOCKER-1") is None

    def test_triggers_and_events_counted(self):
        inv = empty_inventory()
        inv.triggers = [
            TriggerInfo(schema_name="myapp", table_name="orders", trigger_name="t1", timing="AFTER", event="UPDATE")
        ]
        inv.events = [
            EventInfo(schema_name="myapp", event_name="e1", schedule="EVERY 1 DAY"),
            EventInfo(schema_name="myapp", event_name="e2", schedule="EVERY 1 DAY"),
        ]
        result = assess_compatibility(inv, HeatWaveMetadata(), evaluate_binlog_config(CLEAN_BINLOG_VARS))
        assert by_id(result.blockers, "BLOCKER-2").count == 1
        assert by_id(result.blockers, "BLOCKER-3").count == 2

    def test_spatial_columns_trigger_blocker_4_counted_per_table(self):
        inv = empty_inventory()
        inv.columns = [
            ColumnInfo("myapp", "stores", "location", 1, "point", "point", True),
            ColumnInfo("myapp", "stores", "boundary", 2, "polygon", "polygon", True),
            ColumnInfo("myapp", "regions", "shape", 1, "geometry", "geometry", True),
        ]
        result = assess_compatibility(inv, HeatWaveMetadata(), evaluate_binlog_config(CLEAN_BINLOG_VARS))
        f = by_id(result.blockers, "BLOCKER-4")
        assert f.count == 2  # distinct tables: stores, regions

    def test_lakehouse_tables_trigger_hw_blocker_1(self):
        inv = empty_inventory()
        inv.lakehouse_tables = ["myapp.raw_events"]
        result = assess_compatibility(inv, HeatWaveMetadata(), evaluate_binlog_config(CLEAN_BINLOG_VARS))
        assert by_id(result.blockers, "HW-BLOCKER-1").count == 1

    def test_automl_schemas_trigger_hw_blocker_2(self):
        inv = empty_inventory()
        inv.automl_schemas = ["ML_SCHEMA_admin"]
        result = assess_compatibility(inv, HeatWaveMetadata(), evaluate_binlog_config(CLEAN_BINLOG_VARS))
        assert by_id(result.blockers, "HW-BLOCKER-2").count == 1

    def test_js_routines_trigger_hw_blocker_3(self):
        inv = empty_inventory()
        inv.js_routines = ["myapp.score_customer"]
        result = assess_compatibility(inv, HeatWaveMetadata(), evaluate_binlog_config(CLEAN_BINLOG_VARS))
        assert by_id(result.blockers, "HW-BLOCKER-3").count == 1

    def test_query_log_signals_feed_blockers_5_6_7(self):
        inv = empty_inventory()
        signals = QueryLogSignals(xa_detected=True, udf_count=2, xml_function_detected=True)
        result = assess_compatibility(
            inv, HeatWaveMetadata(), evaluate_binlog_config(CLEAN_BINLOG_VARS), query_log=signals
        )
        assert by_id(result.blockers, "BLOCKER-5").count == 1
        assert by_id(result.blockers, "BLOCKER-6").count == 2
        assert by_id(result.blockers, "BLOCKER-7").count == 1

    def test_unsupported_charset_triggers_blocker_8(self):
        # TiDB only supports ascii/latin1/binary/utf8/utf8mb4/gbk.
        inv = empty_inventory()
        inv.columns = [
            ColumnInfo("myapp", "legacy", "notes", 1, "varchar", "varchar(99)", True, charset="cp1250"),
            ColumnInfo("myapp", "legacy", "extra", 2, "varchar", "varchar(99)", True, charset="cp1250"),
            ColumnInfo("myapp", "orders", "region", 1, "varchar", "varchar(16)", True, charset="utf8mb4"),
        ]
        result = assess_compatibility(inv, HeatWaveMetadata(), evaluate_binlog_config(CLEAN_BINLOG_VARS))
        assert by_id(result.blockers, "BLOCKER-8").count == 1  # only "legacy" affected

    def test_supported_charsets_do_not_trigger_blocker_8(self):
        inv = empty_inventory()
        inv.columns = [
            ColumnInfo("myapp", "orders", "region", 1, "varchar", "varchar(16)", True, charset="utf8mb4"),
            ColumnInfo("myapp", "orders", "code", 2, "char", "char(2)", True, charset="ascii"),
            ColumnInfo("myapp", "orders", "legacy_id", 3, "char", "char(8)", True, charset=None),
        ]
        result = assess_compatibility(inv, HeatWaveMetadata(), evaluate_binlog_config(CLEAN_BINLOG_VARS))
        assert by_id(result.blockers, "BLOCKER-8") is None

    def test_case_colliding_names_trigger_blocker_9_when_source_case_sensitive(self):
        inv = empty_inventory()
        inv.tables = [
            TableInfo("myapp", "Users", "InnoDB", 10, 100, 10),
            TableInfo("myapp", "users", "InnoDB", 5, 50, 5),
            TableInfo("myapp", "orders", "InnoDB", 20, 200, 20),
        ]
        meta = HeatWaveMetadata(lower_case_table_names=0)
        result = assess_compatibility(inv, meta, evaluate_binlog_config(CLEAN_BINLOG_VARS))
        assert by_id(result.blockers, "BLOCKER-9").count == 1  # one colliding group: Users/users

    def test_blocker_9_not_triggered_when_source_already_case_insensitive(self):
        # lower_case_table_names=2 already matches TiDB's required value, so
        # the source could not hold two such tables in the first place.
        inv = empty_inventory()
        inv.tables = [TableInfo("myapp", "orders", "InnoDB", 20, 200, 20)]
        meta = HeatWaveMetadata(lower_case_table_names=2)
        result = assess_compatibility(inv, meta, evaluate_binlog_config(CLEAN_BINLOG_VARS))
        assert by_id(result.blockers, "BLOCKER-9") is None

    def test_blocker_9_not_triggered_without_actual_collision(self):
        inv = empty_inventory()
        inv.tables = [
            TableInfo("myapp", "orders", "InnoDB", 20, 200, 20),
            TableInfo("myapp", "customers", "InnoDB", 10, 100, 10),
        ]
        meta = HeatWaveMetadata(lower_case_table_names=0)
        result = assess_compatibility(inv, meta, evaluate_binlog_config(CLEAN_BINLOG_VARS))
        assert by_id(result.blockers, "BLOCKER-9") is None


class TestWarnings:
    def test_foreign_keys_do_not_warn(self):
        # FK enforcement is native on the target (TiDB Cloud v8.5, enforced
        # since v6.6) — FKs are a compatible feature, not a warning.
        inv = empty_inventory()
        inv.constraints = [
            ConstraintInfo("myapp", "orders", "fk1", "FOREIGN KEY", foreign_table="customers")
        ]
        result = assess_compatibility(inv, HeatWaveMetadata(), evaluate_binlog_config(CLEAN_BINLOG_VARS))
        assert by_id(result.warnings, "WARNING-1") is None

    def test_fulltext_only_flagged_outside_starter(self):
        # Real FULLTEXT index support is TiDB Cloud Starter-only (and
        # region-limited); Essential/Dedicated/self-hosted only parse the
        # syntax without indexing — docs.pingcap.com/tidbcloud/mysql-compatibility.
        inv = empty_inventory()
        inv.indexes = [
            IndexInfo("myapp", "articles", "idx_body", "FULLTEXT", is_unique=False, columns=["title"])
        ]
        starter_result = assess_compatibility(
            inv, HeatWaveMetadata(), evaluate_binlog_config(CLEAN_BINLOG_VARS), tier="starter"
        )
        assert by_id(starter_result.warnings, "WARNING-2") is None
        for tier in ("essential", "dedicated", "self-hosted"):
            result = assess_compatibility(
                inv, HeatWaveMetadata(), evaluate_binlog_config(CLEAN_BINLOG_VARS), tier=tier
            )
            assert by_id(result.warnings, "WARNING-2").count == 1, f"tier={tier}"

    def test_auto_increment_tables_trigger_warning_3(self):
        inv = empty_inventory()
        inv.tables = [
            TableInfo("myapp", "orders", "InnoDB", 100, 1000, 100, auto_increment=101),
            TableInfo("myapp", "customers", "InnoDB", 50, 500, 50, auto_increment=None),
        ]
        result = assess_compatibility(inv, HeatWaveMetadata(), evaluate_binlog_config(CLEAN_BINLOG_VARS))
        assert by_id(result.warnings, "WARNING-3").count == 1

    def test_unsupported_collation_counted_per_table(self):
        inv = empty_inventory()
        inv.columns = [
            ColumnInfo("myapp", "orders", "region", 1, "varchar", "varchar(16)", True, collation="utf8mb4_0900_ai_ci"),
            ColumnInfo("myapp", "orders", "notes", 2, "varchar", "varchar(99)", True, collation="utf8mb4_0900_ai_ci"),
            ColumnInfo("myapp", "customers", "name", 1, "varchar", "varchar(99)", True, collation="utf8mb4_general_ci"),
        ]
        result = assess_compatibility(inv, HeatWaveMetadata(), evaluate_binlog_config(CLEAN_BINLOG_VARS))
        assert by_id(result.warnings, "WARNING-4").count == 1  # only "orders" affected

    def test_lower_case_table_names_mismatch_triggers_warning_8(self):
        inv = empty_inventory()
        for value in (0, 1):
            meta = HeatWaveMetadata(lower_case_table_names=value)
            result = assess_compatibility(inv, meta, evaluate_binlog_config(CLEAN_BINLOG_VARS))
            assert by_id(result.warnings, "WARNING-8").count == 1, f"value={value}"

    def test_lower_case_table_names_matching_tidb_does_not_warn(self):
        inv = empty_inventory()
        meta = HeatWaveMetadata(lower_case_table_names=2)
        result = assess_compatibility(inv, meta, evaluate_binlog_config(CLEAN_BINLOG_VARS))
        assert by_id(result.warnings, "WARNING-8") is None

    def test_lower_case_table_names_unknown_does_not_warn(self):
        # metadata collector failed to read it (permissions, older MySQL) —
        # don't warn on a value we never actually observed.
        inv = empty_inventory()
        meta = HeatWaveMetadata(lower_case_table_names=None)
        result = assess_compatibility(inv, meta, evaluate_binlog_config(CLEAN_BINLOG_VARS))
        assert by_id(result.warnings, "WARNING-8") is None

    def test_updatable_views_trigger_warning_9(self):
        inv = empty_inventory()
        inv.views = [
            ViewInfo("myapp", "customer_summary", is_updatable=False),
            ViewInfo("myapp", "active_orders", is_updatable=True),
        ]
        result = assess_compatibility(inv, HeatWaveMetadata(), evaluate_binlog_config(CLEAN_BINLOG_VARS))
        assert by_id(result.warnings, "WARNING-9").count == 1

    def test_read_only_views_do_not_trigger_warning_9(self):
        inv = empty_inventory()
        inv.views = [ViewInfo("myapp", "customer_summary", is_updatable=False)]
        result = assess_compatibility(inv, HeatWaveMetadata(), evaluate_binlog_config(CLEAN_BINLOG_VARS))
        assert by_id(result.warnings, "WARNING-9") is None

    def test_rapid_tables_trigger_hw_warning_1(self):
        inv = empty_inventory()
        inv.rapid_tables = ["orders"]
        result = assess_compatibility(inv, HeatWaveMetadata(), evaluate_binlog_config(CLEAN_BINLOG_VARS))
        assert by_id(result.warnings, "HW-WARNING-1").count == 1

    def test_vector_columns_counted_per_table(self):
        inv = empty_inventory()
        inv.columns = [
            ColumnInfo("myapp", "articles", "embedding", 1, "vector", "vector(1536)", True, is_vector=True),
        ]
        result = assess_compatibility(inv, HeatWaveMetadata(), evaluate_binlog_config(CLEAN_BINLOG_VARS))
        assert by_id(result.warnings, "HW-WARNING-2").count == 1

    def test_binlog_row_value_options_partial_json_only_flagged_when_continue_replication_planned(self):
        inv = empty_inventory()
        meta = HeatWaveMetadata(binlog_row_value_options="PARTIAL_JSON")
        binlog_result = evaluate_binlog_config(CLEAN_BINLOG_VARS)

        not_planned = assess_compatibility(inv, meta, binlog_result, continue_replication_planned=False)
        planned = assess_compatibility(inv, meta, binlog_result, continue_replication_planned=True)

        assert by_id(not_planned.warnings, "HW-WARNING-5") is None
        assert by_id(planned.warnings, "HW-WARNING-5").count == 1

    def test_binlog_failures_only_flagged_when_continue_replication_planned(self):
        inv = empty_inventory()
        bad_vars = {**CLEAN_BINLOG_VARS, "log_bin": "OFF", "binlog_format": "STATEMENT"}
        binlog_result = evaluate_binlog_config(bad_vars)

        not_planned = assess_compatibility(inv, HeatWaveMetadata(), binlog_result, continue_replication_planned=False)
        planned = assess_compatibility(inv, HeatWaveMetadata(), binlog_result, continue_replication_planned=True)

        assert by_id(not_planned.warnings, "HW-WARNING-6") is None
        assert by_id(not_planned.warnings, "HW-WARNING-7") is None
        assert by_id(planned.warnings, "HW-WARNING-6").count == 1
        assert by_id(planned.warnings, "HW-WARNING-7").count == 1


class TestCompatibleFeatures:
    def test_compatible_list_always_present(self):
        result = assess_compatibility(empty_inventory(), HeatWaveMetadata(), evaluate_binlog_config(CLEAN_BINLOG_VARS))
        assert "InnoDB engine (TiDB's only engine — always compatible)" in result.compatible
