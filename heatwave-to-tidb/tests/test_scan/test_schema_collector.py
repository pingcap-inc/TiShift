"""Tests for collect_schema_inventory against a scripted fake connection."""

from tests.test_scan.fake_connection import ScriptedConnection

from tishift_heatwave.core.scan.collectors.schema import collect_schema_inventory

# Ordered so no substring is an accidental prefix-match of another entry above it.
BASE_RESPONSES = [
    (
        "FROM information_schema.TABLES t",
        [
            {
                "TABLE_NAME": "orders",
                "ENGINE": "InnoDB",
                "TABLE_ROWS": 1000,
                "DATA_LENGTH": 65536,
                "INDEX_LENGTH": 16384,
                "TABLE_COLLATION": "utf8mb4_0900_ai_ci",
                "CREATE_OPTIONS": 'SECONDARY_ENGINE="RAPID"',
                "AUTO_INCREMENT": 1001,
                "CHARACTER_SET_NAME": "utf8mb4",
            },
            {
                "TABLE_NAME": "customers",
                "ENGINE": "InnoDB",
                "TABLE_ROWS": 500,
                "DATA_LENGTH": 32768,
                "INDEX_LENGTH": 8192,
                "TABLE_COLLATION": "utf8mb4_general_ci",
                "CREATE_OPTIONS": "",
                "AUTO_INCREMENT": 501,
                "CHARACTER_SET_NAME": "utf8mb4",
            },
        ],
    ),
    (
        "FROM information_schema.PARTITIONS",
        [{"TABLE_NAME": "orders", "PARTITION_METHOD": "RANGE"}],
    ),
    (
        "FROM information_schema.COLUMNS",
        [
            {
                "TABLE_NAME": "orders",
                "COLUMN_NAME": "id",
                "ORDINAL_POSITION": 1,
                "DATA_TYPE": "bigint",
                "COLUMN_TYPE": "bigint unsigned",
                "IS_NULLABLE": "NO",
                "COLUMN_DEFAULT": None,
                "CHARACTER_MAXIMUM_LENGTH": None,
                "NUMERIC_PRECISION": 20,
                "NUMERIC_SCALE": 0,
                "CHARACTER_SET_NAME": None,
                "COLLATION_NAME": None,
                "EXTRA": "auto_increment",
            },
            {
                "TABLE_NAME": "orders",
                "COLUMN_NAME": "region",
                "ORDINAL_POSITION": 2,
                "DATA_TYPE": "varchar",
                "COLUMN_TYPE": "varchar(16)",
                "IS_NULLABLE": "YES",
                "COLUMN_DEFAULT": None,
                "CHARACTER_MAXIMUM_LENGTH": 16,
                "NUMERIC_PRECISION": None,
                "NUMERIC_SCALE": None,
                "CHARACTER_SET_NAME": "utf8mb4",
                "COLLATION_NAME": "utf8mb4_0900_ai_ci",
                "EXTRA": "",
            },
            {
                "TABLE_NAME": "orders",
                "COLUMN_NAME": "embedding",
                "ORDINAL_POSITION": 3,
                "DATA_TYPE": "vector",
                "COLUMN_TYPE": "vector(1536)",
                "IS_NULLABLE": "YES",
                "COLUMN_DEFAULT": None,
                "CHARACTER_MAXIMUM_LENGTH": None,
                "NUMERIC_PRECISION": None,
                "NUMERIC_SCALE": None,
                "CHARACTER_SET_NAME": None,
                "COLLATION_NAME": None,
                "EXTRA": "",
            },
        ],
    ),
    (
        "FROM information_schema.STATISTICS",
        [
            {
                "TABLE_NAME": "orders",
                "INDEX_NAME": "PRIMARY",
                "INDEX_TYPE": "BTREE",
                "NON_UNIQUE": 0,
                "COLUMN_NAME": "id",
                "SEQ_IN_INDEX": 1,
            },
            {
                "TABLE_NAME": "articles",
                "INDEX_NAME": "idx_body",
                "INDEX_TYPE": "FULLTEXT",
                "NON_UNIQUE": 1,
                "COLUMN_NAME": "title",
                "SEQ_IN_INDEX": 1,
            },
            {
                "TABLE_NAME": "articles",
                "INDEX_NAME": "idx_body",
                "INDEX_TYPE": "FULLTEXT",
                "NON_UNIQUE": 1,
                "COLUMN_NAME": "body",
                "SEQ_IN_INDEX": 2,
            },
        ],
    ),
    (
        "FROM information_schema.TABLE_CONSTRAINTS",
        [
            {
                "TABLE_NAME": "orders",
                "CONSTRAINT_NAME": "fk_orders_customer",
                "CONSTRAINT_TYPE": "FOREIGN KEY",
                "REFERENCED_TABLE_NAME": "customers",
            },
            {
                "TABLE_NAME": "orders",
                "CONSTRAINT_NAME": "PRIMARY",
                "CONSTRAINT_TYPE": "PRIMARY KEY",
                "REFERENCED_TABLE_NAME": None,
            },
        ],
    ),
    (
        "FROM information_schema.ROUTINES",
        [
            {
                "ROUTINE_NAME": "settle_order",
                "ROUTINE_TYPE": "PROCEDURE",
                "EXTERNAL_LANGUAGE": "SQL",
                "ROUTINE_DEFINITION": "UPDATE orders SET status='paid'",
                "IS_DETERMINISTIC": "NO",
            },
            {
                "ROUTINE_NAME": "score_customer",
                "ROUTINE_TYPE": "FUNCTION",
                "EXTERNAL_LANGUAGE": "JAVASCRIPT",
                "ROUTINE_DEFINITION": "return 1;",
                "IS_DETERMINISTIC": "YES",
            },
        ],
    ),
    (
        "FROM information_schema.TRIGGERS",
        [
            {
                "TRIGGER_NAME": "trg_orders_audit",
                "EVENT_MANIPULATION": "UPDATE",
                "EVENT_OBJECT_TABLE": "orders",
                "ACTION_TIMING": "AFTER",
                "ACTION_STATEMENT": "INSERT INTO order_audit ...",
            }
        ],
    ),
    (
        "FROM information_schema.EVENTS",
        [
            {
                "EVENT_NAME": "ev_purge_audit",
                "EVENT_DEFINITION": "DELETE FROM order_audit ...",
                "INTERVAL_VALUE": "1",
                "INTERVAL_FIELD": "DAY",
                "EXECUTE_AT": None,
            }
        ],
    ),
    (
        "FROM information_schema.VIEWS",
        [
            {"TABLE_NAME": "customer_summary", "IS_UPDATABLE": "NO"},
            {"TABLE_NAME": "active_orders", "IS_UPDATABLE": "YES"},
        ],
    ),
    (
        "ENGINE = 'Lakehouse'",
        [{"TABLE_SCHEMA": "myapp", "TABLE_NAME": "raw_events"}],
    ),
    (
        "information_schema.SCHEMATA",
        [{"SCHEMA_NAME": "ML_SCHEMA_admin"}],
    ),
]


def build_inventory():
    conn = ScriptedConnection(BASE_RESPONSES)
    return collect_schema_inventory(conn, "myapp")


class TestTables:
    def test_tables_collected_with_flags(self):
        inv = build_inventory()
        by_name = {t.table_name: t for t in inv.tables}

        assert by_name["orders"].is_rapid_loaded is True
        assert by_name["orders"].row_estimate == 1000
        assert by_name["orders"].data_bytes == 65536
        assert by_name["orders"].charset == "utf8mb4"
        assert by_name["orders"].partition_method == "RANGE"
        assert by_name["customers"].is_rapid_loaded is False
        assert by_name["customers"].partition_method is None

    def test_rapid_tables_list(self):
        inv = build_inventory()
        assert inv.rapid_tables == ["orders"]


class TestColumns:
    def test_columns_attached_to_owning_table(self):
        inv = build_inventory()
        orders = next(t for t in inv.tables if t.table_name == "orders")
        assert [c.column_name for c in orders.columns] == ["id", "region", "embedding"]

    def test_flat_columns_list_populated(self):
        inv = build_inventory()
        assert len(inv.columns) == 3

    def test_vector_column_detected(self):
        inv = build_inventory()
        embedding = next(c for c in inv.columns if c.column_name == "embedding")
        assert embedding.is_vector is True
        assert inv.vector_columns == ["orders.embedding"]

    def test_non_vector_column_not_flagged(self):
        inv = build_inventory()
        region = next(c for c in inv.columns if c.column_name == "region")
        assert region.is_vector is False

    def test_unsupported_collation_detected(self):
        inv = build_inventory()
        assert inv.unsupported_collations == ["orders.region: utf8mb4_0900_ai_ci"]


class TestIndexes:
    def test_index_columns_grouped_in_seq_order(self):
        inv = build_inventory()
        idx_body = next(i for i in inv.indexes if i.index_name == "idx_body")
        assert idx_body.columns == ["title", "body"]
        assert idx_body.index_type == "FULLTEXT"
        assert idx_body.is_unique is False

    def test_unique_primary_key_index(self):
        inv = build_inventory()
        pk = next(i for i in inv.indexes if i.table_name == "orders" and i.index_name == "PRIMARY")
        assert pk.is_unique is True


class TestConstraints:
    def test_foreign_key_and_primary_key_both_collected(self):
        inv = build_inventory()
        types = {c.constraint_name: c.constraint_type for c in inv.constraints}
        assert types["fk_orders_customer"] == "FOREIGN KEY"
        assert types["PRIMARY"] == "PRIMARY KEY"

    def test_foreign_table_captured(self):
        inv = build_inventory()
        fk = next(c for c in inv.constraints if c.constraint_name == "fk_orders_customer")
        assert fk.foreign_table == "customers"

    def test_fk_count_derivable(self):
        inv = build_inventory()
        fk_count = sum(1 for c in inv.constraints if c.constraint_type == "FOREIGN KEY")
        assert fk_count == 1


class TestRoutinesTriggersEvents:
    def test_js_routine_detected(self):
        inv = build_inventory()
        assert inv.js_routines == ["myapp.score_customer"]

    def test_sql_routine_not_flagged_as_js(self):
        inv = build_inventory()
        assert "myapp.settle_order" not in inv.js_routines

    def test_trigger_collected(self):
        inv = build_inventory()
        assert len(inv.triggers) == 1
        assert inv.triggers[0].table_name == "orders"
        assert inv.triggers[0].timing == "AFTER"

    def test_event_schedule_from_interval(self):
        inv = build_inventory()
        assert inv.events[0].schedule == "EVERY 1 DAY"


class TestViews:
    def test_views_collected(self):
        inv = build_inventory()
        assert {v.view_name for v in inv.views} == {"customer_summary", "active_orders"}

    def test_is_updatable_parsed(self):
        inv = build_inventory()
        by_name = {v.view_name: v for v in inv.views}
        assert by_name["customer_summary"].is_updatable is False
        assert by_name["active_orders"].is_updatable is True


class TestHeatWaveInstanceWideChecks:
    def test_lakehouse_tables_detected(self):
        inv = build_inventory()
        assert inv.lakehouse_tables == ["myapp.raw_events"]

    def test_automl_schemas_detected(self):
        inv = build_inventory()
        assert inv.automl_schemas == ["ML_SCHEMA_admin"]


class TestParameterization:
    def test_schema_never_interpolated_into_sql_text(self):
        conn = ScriptedConnection(BASE_RESPONSES)
        collect_schema_inventory(conn, "myapp")

        assert conn.executed, "expected queries to have been executed"
        for sql, _params in conn.executed:
            assert "myapp" not in sql, f"schema name leaked into SQL text: {sql}"

    def test_schema_scoped_queries_bind_the_schema_as_a_parameter(self):
        conn = ScriptedConnection(BASE_RESPONSES)
        collect_schema_inventory(conn, "myapp")

        scope_columns = ("TABLE_SCHEMA", "ROUTINE_SCHEMA", "TRIGGER_SCHEMA", "EVENT_SCHEMA")
        scoped = [
            (sql, params)
            for sql, params in conn.executed
            if any(f"{col} = %s" in sql for col in scope_columns)
        ]
        # tables, partitions, columns, indexes, constraints, routines, triggers, events, views
        assert len(scoped) == 9
        assert all(params == ("myapp",) for _, params in scoped)

    def test_instance_wide_queries_are_not_schema_scoped(self):
        conn = ScriptedConnection(BASE_RESPONSES)
        collect_schema_inventory(conn, "myapp")

        instance_wide = [
            (sql, params)
            for sql, params in conn.executed
            if "Lakehouse" in sql or "information_schema.SCHEMATA" in sql
        ]
        assert len(instance_wide) == 2
        # Instance-wide queries never bind the business schema. The AutoML
        # check binds only its LIKE pattern — a literal % in the SQL text
        # would be parsed by pymysql as a format directive and crash.
        # Parameterless queries must pass None (not ()) so pymysql skips
        # %-interpolation entirely.
        assert all(not params or "myapp" not in params for _, params in instance_wide)
        lakehouse = [params for sql, params in instance_wide if "Lakehouse" in sql]
        assert lakehouse == [None]
        automl = [params for sql, params in instance_wide if "SCHEMATA" in sql]
        assert automl == [(r"ML\_SCHEMA\_%",)]
