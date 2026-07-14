"""Schema inventory collector — SKILL.md Steps 2.2 through 2.6.

Queries information_schema for one business schema (the config's
source.database) plus two instance-wide checks that can't be scoped to a
single schema: Lakehouse external tables and ML_SCHEMA_% AutoML schemas
(Step 2.4). All schema-scoped queries are parameterized (TABLE_SCHEMA = %s);
nothing interpolates the schema name into SQL text.

Known limitation: information_schema.COLUMNS has no reliable signal for a
column-level ``NOT SECONDARY`` exclusion (it doesn't surface outside
SHOW CREATE TABLE), so ColumnInfo.excluded_from_rapid is always False here —
the convert-phase DDL cleaner reads it from the DDL text directly instead.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pymysql

from tishift_heatwave.models import (
    ColumnInfo,
    ConstraintInfo,
    EventInfo,
    IndexInfo,
    RoutineInfo,
    SchemaInventory,
    TableInfo,
    TriggerInfo,
    ViewInfo,
)

_UNSUPPORTED_COLLATION_PREFIX = "utf8mb4_0900"


def _query(cursor: Any, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    """Execute a query and return rows as dicts with lowercase keys.

    information_schema returns UPPERCASE column names regardless of the
    SELECT clause's case; normalize once here so every mapper below can use
    plain lowercase attribute access.

    Parameterless queries pass None (not an empty tuple) so pymysql skips
    %-interpolation entirely — a literal % in such SQL must never be treated
    as a format directive.
    """
    cursor.execute(sql, params if params else None)
    rows = cursor.fetchall()
    return [{k.lower(): v for k, v in row.items()} for row in rows]


def _collect_tables(cur: Any, schema: str) -> dict[str, TableInfo]:
    rows = _query(
        cur,
        """
        SELECT t.TABLE_NAME, t.ENGINE, t.TABLE_ROWS, t.DATA_LENGTH, t.INDEX_LENGTH,
               t.TABLE_COLLATION, t.CREATE_OPTIONS, t.AUTO_INCREMENT,
               c.CHARACTER_SET_NAME
        FROM information_schema.TABLES t
        LEFT JOIN information_schema.COLLATIONS c ON c.COLLATION_NAME = t.TABLE_COLLATION
        WHERE t.TABLE_SCHEMA = %s AND t.TABLE_TYPE = 'BASE TABLE'
        ORDER BY t.DATA_LENGTH DESC
        """,
        (schema,),
    )
    tables: dict[str, TableInfo] = {}
    for r in rows:
        create_options = r.get("create_options") or ""
        engine = r.get("engine") or ""
        tables[r["table_name"]] = TableInfo(
            schema_name=schema,
            table_name=r["table_name"],
            engine=engine,
            row_estimate=r.get("table_rows") or 0,
            data_bytes=r.get("data_length") or 0,
            index_bytes=r.get("index_length") or 0,
            create_options=create_options,
            charset=r.get("character_set_name"),
            collation=r.get("table_collation"),
            is_rapid_loaded="SECONDARY_ENGINE" in create_options.upper(),
            is_lakehouse=engine.lower() == "lakehouse",
            auto_increment=r.get("auto_increment"),
        )

    partitions = _query(
        cur,
        """
        SELECT TABLE_NAME, PARTITION_METHOD
        FROM information_schema.PARTITIONS
        WHERE TABLE_SCHEMA = %s AND PARTITION_NAME IS NOT NULL
        GROUP BY TABLE_NAME, PARTITION_METHOD
        """,
        (schema,),
    )
    for r in partitions:
        table = tables.get(r["table_name"])
        if table is not None:
            table.partition_method = r.get("partition_method")

    return tables


def _collect_columns(cur: Any, schema: str) -> list[ColumnInfo]:
    rows = _query(
        cur,
        """
        SELECT TABLE_NAME, COLUMN_NAME, ORDINAL_POSITION, DATA_TYPE, COLUMN_TYPE,
               IS_NULLABLE, COLUMN_DEFAULT, CHARACTER_MAXIMUM_LENGTH,
               NUMERIC_PRECISION, NUMERIC_SCALE, CHARACTER_SET_NAME,
               COLLATION_NAME, EXTRA
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = %s
        ORDER BY TABLE_NAME, ORDINAL_POSITION
        """,
        (schema,),
    )
    columns = []
    for r in rows:
        data_type = (r.get("data_type") or "").lower()
        columns.append(
            ColumnInfo(
                schema_name=schema,
                table_name=r["table_name"],
                column_name=r["column_name"],
                ordinal_position=r["ordinal_position"],
                data_type=data_type,
                column_type=r.get("column_type") or "",
                is_nullable=(r.get("is_nullable") == "YES"),
                column_default=r.get("column_default"),
                character_maximum_length=r.get("character_maximum_length"),
                numeric_precision=r.get("numeric_precision"),
                numeric_scale=r.get("numeric_scale"),
                charset=r.get("character_set_name"),
                collation=r.get("collation_name"),
                extra=r.get("extra") or "",
                is_vector=(data_type == "vector"),
            )
        )
    return columns


def _collect_indexes(cur: Any, schema: str) -> list[IndexInfo]:
    rows = _query(
        cur,
        """
        SELECT TABLE_NAME, INDEX_NAME, INDEX_TYPE, NON_UNIQUE, COLUMN_NAME, SEQ_IN_INDEX
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = %s
        ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX
        """,
        (schema,),
    )
    grouped: dict[tuple[str, str], IndexInfo] = {}
    for r in rows:
        key = (r["table_name"], r["index_name"])
        idx = grouped.get(key)
        if idx is None:
            idx = IndexInfo(
                schema_name=schema,
                table_name=r["table_name"],
                index_name=r["index_name"],
                index_type=r.get("index_type") or "BTREE",
                is_unique=(r.get("non_unique") == 0),
            )
            grouped[key] = idx
        idx.columns.append(r["column_name"])
    return list(grouped.values())


def _collect_constraints(cur: Any, schema: str) -> list[ConstraintInfo]:
    rows = _query(
        cur,
        """
        SELECT DISTINCT tc.TABLE_NAME, tc.CONSTRAINT_NAME, tc.CONSTRAINT_TYPE,
               kcu.REFERENCED_TABLE_NAME
        FROM information_schema.TABLE_CONSTRAINTS tc
        LEFT JOIN information_schema.KEY_COLUMN_USAGE kcu
          ON kcu.CONSTRAINT_SCHEMA = tc.CONSTRAINT_SCHEMA
         AND kcu.CONSTRAINT_NAME = tc.CONSTRAINT_NAME
         AND kcu.TABLE_NAME = tc.TABLE_NAME
        WHERE tc.TABLE_SCHEMA = %s
        """,
        (schema,),
    )
    return [
        ConstraintInfo(
            schema_name=schema,
            table_name=r["table_name"],
            constraint_name=r["constraint_name"],
            constraint_type=r["constraint_type"],
            foreign_table=r.get("referenced_table_name"),
        )
        for r in rows
    ]


def _collect_routines(cur: Any, schema: str) -> list[RoutineInfo]:
    rows = _query(
        cur,
        """
        SELECT ROUTINE_NAME, ROUTINE_TYPE, EXTERNAL_LANGUAGE, ROUTINE_DEFINITION,
               IS_DETERMINISTIC
        FROM information_schema.ROUTINES
        WHERE ROUTINE_SCHEMA = %s
        """,
        (schema,),
    )
    return [
        RoutineInfo(
            schema_name=schema,
            routine_name=r["routine_name"],
            kind=r.get("routine_type") or "",
            definition=r.get("routine_definition") or "",
            external_language=r.get("external_language") or "SQL",
            is_deterministic=(r.get("is_deterministic") == "YES"),
        )
        for r in rows
    ]


def _collect_triggers(cur: Any, schema: str) -> list[TriggerInfo]:
    rows = _query(
        cur,
        """
        SELECT TRIGGER_NAME, EVENT_MANIPULATION, EVENT_OBJECT_TABLE,
               ACTION_TIMING, ACTION_STATEMENT
        FROM information_schema.TRIGGERS
        WHERE TRIGGER_SCHEMA = %s
        """,
        (schema,),
    )
    return [
        TriggerInfo(
            schema_name=schema,
            table_name=r.get("event_object_table") or "",
            trigger_name=r["trigger_name"],
            timing=r.get("action_timing") or "",
            event=r.get("event_manipulation") or "",
            definition=r.get("action_statement") or "",
        )
        for r in rows
    ]


def _collect_events(cur: Any, schema: str) -> list[EventInfo]:
    rows = _query(
        cur,
        """
        SELECT EVENT_NAME, EVENT_DEFINITION, INTERVAL_VALUE, INTERVAL_FIELD, EXECUTE_AT
        FROM information_schema.EVENTS
        WHERE EVENT_SCHEMA = %s
        """,
        (schema,),
    )
    events = []
    for r in rows:
        if r.get("interval_value") is not None:
            schedule = f"EVERY {r['interval_value']} {r.get('interval_field') or ''}".strip()
        elif r.get("execute_at") is not None:
            schedule = f"AT {r['execute_at']}"
        else:
            schedule = ""
        events.append(
            EventInfo(
                schema_name=schema,
                event_name=r["event_name"],
                schedule=schedule,
                definition=r.get("event_definition") or "",
            )
        )
    return events


def _collect_views(cur: Any, schema: str) -> list[ViewInfo]:
    """TiDB views are always read-only (no UPDATE/INSERT/DELETE through a
    view); IS_UPDATABLE flags which source views rely on write-through
    behavior that won't carry over (WARNING-9)."""
    rows = _query(
        cur,
        "SELECT TABLE_NAME, IS_UPDATABLE FROM information_schema.VIEWS WHERE TABLE_SCHEMA = %s",
        (schema,),
    )
    return [
        ViewInfo(
            schema_name=schema,
            view_name=r["table_name"],
            is_updatable=(r.get("is_updatable") == "YES"),
        )
        for r in rows
    ]


def _collect_lakehouse_tables(cur: Any) -> list[str]:
    """Instance-wide — Lakehouse external tables can exist in any schema."""
    rows = _query(
        cur,
        "SELECT TABLE_SCHEMA, TABLE_NAME FROM information_schema.TABLES WHERE ENGINE = 'Lakehouse'",
    )
    return [f"{r['table_schema']}.{r['table_name']}" for r in rows]


def _collect_automl_schemas(cur: Any) -> list[str]:
    """Instance-wide — AutoML/GenAI model catalogs (HW-BLOCKER-2)."""
    rows = _query(
        cur,
        "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME LIKE %s",
        (r"ML\_SCHEMA\_%",),
    )
    return [r["schema_name"] for r in rows]


def collect_schema_inventory(conn: pymysql.Connection, schema: str) -> SchemaInventory:
    """Collect the full schema inventory for one business schema.

    ``schema`` is passed as a bind parameter everywhere except the two
    instance-wide checks (Lakehouse, AutoML), which by definition are not
    scoped to a single schema.
    """
    inv = SchemaInventory()

    with conn.cursor() as cur:
        tables = _collect_tables(cur, schema)
        columns = _collect_columns(cur, schema)
        inv.indexes = _collect_indexes(cur, schema)
        inv.constraints = _collect_constraints(cur, schema)
        inv.routines = _collect_routines(cur, schema)
        inv.triggers = _collect_triggers(cur, schema)
        inv.events = _collect_events(cur, schema)
        inv.views = _collect_views(cur, schema)
        inv.lakehouse_tables = _collect_lakehouse_tables(cur)
        inv.automl_schemas = _collect_automl_schemas(cur)

    for column in columns:
        table = tables.get(column.table_name)
        if table is not None:
            table.columns.append(column)
        if column.is_vector:
            inv.vector_columns.append(f"{column.table_name}.{column.column_name}")
        if (column.collation or "").lower().startswith(_UNSUPPORTED_COLLATION_PREFIX):
            inv.unsupported_collations.append(
                f"{column.table_name}.{column.column_name}: {column.collation}"
            )

    inv.tables = list(tables.values())
    inv.columns = columns
    inv.rapid_tables = [t.table_name for t in inv.tables if t.is_rapid_loaded]
    inv.js_routines = [
        f"{schema}.{r.routine_name}"
        for r in inv.routines
        if r.external_language.upper() == "JAVASCRIPT"
    ]

    return inv
