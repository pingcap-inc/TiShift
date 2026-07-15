"""Tests for the comment-preserving DDL cleanup engine (HW-DDL rules)."""

import re

from tishift_heatwave.core.convert.ddl_cleaner import (
    clean_statement,
    mask_sql,
    split_statements,
)


def active_sql(sql: str) -> str:
    """SQL with all comments/literals blanked — 'what would actually execute'."""
    return mask_sql(sql)


class TestHwDdl1SecondaryEngine:
    def test_commented_out_and_flagged_rapid(self):
        stmt = "CREATE TABLE orders (id BIGINT PRIMARY KEY) ENGINE=InnoDB SECONDARY_ENGINE=RAPID;"
        new_stmt, findings, is_rapid, table = clean_statement(stmt)

        assert "/* TISHIFT-REMOVED [HW-DDL-1]: SECONDARY_ENGINE=RAPID */" in new_stmt
        assert "SECONDARY_ENGINE" not in active_sql(new_stmt)
        assert is_rapid is True
        assert table == "orders"
        assert [f.rule_id for f in findings] == ["HW-DDL-1"]
        assert findings[0].action_taken == "commented_out"
        assert findings[0].risk == "info"

    def test_quoted_lowercase_variant(self):
        stmt = 'CREATE TABLE t (id INT) secondary_engine = "RAPID";'
        new_stmt, findings, is_rapid, _ = clean_statement(stmt)
        assert "TISHIFT-REMOVED [HW-DDL-1]" in new_stmt
        assert is_rapid is True

    def test_null_value_commented_but_not_rapid(self):
        stmt = "CREATE TABLE t (id INT) SECONDARY_ENGINE=NULL;"
        new_stmt, findings, is_rapid, _ = clean_statement(stmt)
        assert "TISHIFT-REMOVED [HW-DDL-1]" in new_stmt
        assert is_rapid is False

    def test_preceding_comma_consumed(self):
        stmt = "CREATE TABLE t (id INT) ENGINE=InnoDB, SECONDARY_ENGINE=RAPID;"
        new_stmt, _, _, _ = clean_statement(stmt)
        # no dangling comma left before the comment / statement end
        assert re.search(r"InnoDB\s*/\* TISHIFT-REMOVED", new_stmt)
        assert "," not in active_sql(new_stmt).split(")")[-1]


class TestHwDdl2SecondaryLoad:
    def test_option_form_commented(self):
        stmt = "CREATE TABLE t (id INT) SECONDARY_LOAD='auto';"
        new_stmt, findings, _, _ = clean_statement(stmt)
        assert "/* TISHIFT-REMOVED [HW-DDL-2]: SECONDARY_LOAD='auto' */" in new_stmt
        assert "SECONDARY_LOAD" not in active_sql(new_stmt)

    def test_statement_form_becomes_line_comment(self):
        stmt = "ALTER TABLE orders SECONDARY_LOAD;"
        new_stmt, findings, is_rapid, table = clean_statement(stmt)
        assert new_stmt.strip() == "-- TISHIFT-REMOVED [HW-DDL-2]: ALTER TABLE orders SECONDARY_LOAD;"
        assert findings[0].action_taken == "statement_commented_out"
        assert table == "orders"

    def test_unload_statement_form(self):
        stmt = "\nALTER TABLE `db`.`orders` SECONDARY_UNLOAD;"
        new_stmt, findings, _, _ = clean_statement(stmt)
        assert "-- TISHIFT-REMOVED [HW-DDL-2]:" in new_stmt
        assert "SECONDARY_UNLOAD" not in active_sql(new_stmt)

    def test_star_slash_in_value_degrades_to_line_comment(self):
        stmt = "CREATE TABLE t (id INT) SECONDARY_LOAD='a*/b';"
        new_stmt, _, _, _ = clean_statement(stmt)
        assert "-- TISHIFT-REMOVED [HW-DDL-2]: SECONDARY_LOAD='a*/b'" in new_stmt
        # the block-comment form must not appear (it would close early)
        assert "/* TISHIFT-REMOVED [HW-DDL-2]" not in new_stmt


class TestHwDdl3ClusteringBy:
    def test_commented_with_suggestion(self):
        stmt = (
            "CREATE TABLE orders (id BIGINT PRIMARY KEY, region VARCHAR(16), created_at DATETIME) "
            "ENGINE=InnoDB CLUSTERING BY (region, created_at);"
        )
        new_stmt, findings, _, _ = clean_statement(stmt)
        assert "/* TISHIFT-REMOVED [HW-DDL-3]: CLUSTERING BY (region, created_at) */" in new_stmt
        assert "TISHIFT-REVIEW [HW-DDL-3]" in new_stmt
        assert "CLUSTERING" not in active_sql(new_stmt)
        f = findings[0]
        assert f.action_taken == "commented_out_with_suggestion"
        assert f.risk == "assess"
        assert "secondary index on (region, created_at)" in f.suggestion

    def test_pk_prefix_suggests_clustered_pk(self):
        stmt = (
            "CREATE TABLE events (tenant_id BIGINT, ts DATETIME, payload JSON, "
            "PRIMARY KEY (tenant_id, ts)) CLUSTERING BY (tenant_id);"
        )
        _, findings, _, _ = clean_statement(stmt)
        assert "primary key" in findings[0].suggestion.lower()
        assert "CLUSTERED" in findings[0].suggestion

    def test_suggestion_safe_inside_block_comment(self):
        stmt = "CREATE TABLE t (a INT, b INT, PRIMARY KEY (a)) CLUSTERING BY (a);"
        _, findings, _, _ = clean_statement(stmt)
        assert "*/" not in findings[0].suggestion


class TestHwDdl4RapidColumnComment:
    def test_kept_unchanged_and_reported(self):
        stmt = (
            "CREATE TABLE t (region VARCHAR(16) COMMENT 'RAPID_COLUMN=DICTIONARY', id INT);"
        )
        new_stmt, findings, _, _ = clean_statement(stmt)
        assert new_stmt == stmt
        assert [f.rule_id for f in findings] == ["HW-DDL-4"]
        assert findings[0].action_taken == "kept"
        assert findings[0].risk == "harmless"


class TestSafety:
    def test_syntax_inside_string_literal_untouched(self):
        stmt = "CREATE TABLE t (note VARCHAR(99) COMMENT 'set SECONDARY_ENGINE=RAPID for speed');"
        new_stmt, findings, is_rapid, _ = clean_statement(stmt)
        assert new_stmt == stmt
        assert findings == []
        assert is_rapid is False

    def test_split_statements_ignores_semicolons_in_literals(self):
        sql = "INSERT INTO t VALUES ('a;b');\nCREATE TABLE u (id INT);"
        assert len(split_statements(sql)) == 2

    def test_idempotent(self):
        stmt = (
            "CREATE TABLE orders (id BIGINT PRIMARY KEY) "
            "ENGINE=InnoDB SECONDARY_ENGINE=RAPID CLUSTERING BY (id);"
        )
        once, findings_once, _, _ = clean_statement(stmt)
        twice, findings_twice, is_rapid_twice, _ = clean_statement(once)
        assert twice == once
        assert is_rapid_twice is False
        assert [f for f in findings_twice if f.action_taken != "kept"] == []
