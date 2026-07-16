"""Tests for convert orchestration: TiFlash inlining, tiers, validation."""

import re

from tishift_heatwave.core.convert.ddl_cleaner import mask_sql
from tishift_heatwave.core.convert.schema_transformer import transform_schema

V2_EXAMPLE = """\
CREATE TABLE orders (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  region VARCHAR(16) COMMENT 'RAPID_COLUMN=DICTIONARY',
  created_at DATETIME NOT NULL
) ENGINE=InnoDB SECONDARY_ENGINE=RAPID CLUSTERING BY (region, created_at);
ALTER TABLE orders SECONDARY_LOAD;
"""


def test_v2_example_end_to_end():
    result = transform_schema(V2_EXAMPLE, tier="dedicated", tiflash_replicas=1)

    # all four rules fired
    assert {f.rule_id for f in result.findings} == {"HW-DDL-1", "HW-DDL-2", "HW-DDL-3", "HW-DDL-4"}
    # RAPID column comment untouched
    assert "COMMENT 'RAPID_COLUMN=DICTIONARY'" in result.sql
    # TiFlash ALTER placed after the CREATE TABLE, before the commented SECONDARY_LOAD line
    create_end = result.sql.index(");")
    tiflash_pos = result.sql.index("ALTER TABLE orders SET TIFLASH REPLICA 1;")
    load_comment_pos = result.sql.index("-- TISHIFT-REMOVED [HW-DDL-2]: ALTER TABLE orders SECONDARY_LOAD;")
    assert create_end < tiflash_pos < load_comment_pos
    assert result.rapid_tables == ["orders"]
    assert result.tiflash_statements == ["ALTER TABLE orders SET TIFLASH REPLICA 1;"]
    # nothing HeatWave-only remains executable
    active = mask_sql(result.sql)
    assert "SECONDARY_ENGINE" not in active
    assert "SECONDARY_LOAD" not in active
    assert "CLUSTERING" not in active
    # cleanup produced parseable SQL
    assert result.parse_errors == []


def test_starter_tier_emits_alter_like_every_tier():
    result = transform_schema(V2_EXAMPLE, tier="starter", tiflash_replicas=1)
    assert result.tiflash_statements == ["ALTER TABLE orders SET TIFLASH REPLICA 1;"]
    assert "ALTER TABLE orders SET TIFLASH REPLICA 1;" in result.sql
    assert "TISHIFT-INFO [HW-DDL-1]" not in result.sql


def test_default_replica_count_is_two():
    result = transform_schema(V2_EXAMPLE, tier="starter")
    assert result.tiflash_statements == ["ALTER TABLE orders SET TIFLASH REPLICA 2;"]


def test_replica_count_zero_disables_emission():
    result = transform_schema(V2_EXAMPLE, tier="dedicated", tiflash_replicas=0)
    assert result.tiflash_statements == []
    assert "TISHIFT-INFO [HW-DDL-1]" in result.sql


def test_replica_count_respected():
    result = transform_schema(V2_EXAMPLE, tier="essential", tiflash_replicas=2)
    assert "ALTER TABLE orders SET TIFLASH REPLICA 2;" in result.sql


def test_existing_tiflash_statement_not_duplicated():
    sql = V2_EXAMPLE + "\nALTER TABLE orders SET TIFLASH REPLICA 1;\n"
    result = transform_schema(sql, tier="dedicated", tiflash_replicas=1)
    assert result.sql.count("SET TIFLASH REPLICA") == 1


def test_idempotent_across_full_pipeline():
    once = transform_schema(V2_EXAMPLE, tier="dedicated", tiflash_replicas=1)
    twice = transform_schema(once.sql, tier="dedicated", tiflash_replicas=1)
    assert twice.sql == once.sql
    assert twice.tiflash_statements == []
    assert [f for f in twice.findings if f.action_taken != "kept"] == []


def test_untouched_schema_passes_through():
    sql = "CREATE TABLE plain (id INT PRIMARY KEY, name VARCHAR(50)) ENGINE=InnoDB;"
    result = transform_schema(sql, tier="dedicated")
    assert result.sql == sql
    assert result.findings == []
    assert result.rapid_tables == []


HINT_ONLY_EXAMPLE = """\
CREATE TABLE guests (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(191) COMMENT 'RAPID_COLUMN=ENCODING=VARLEN',
  email VARCHAR(191) COMMENT 'RAPID_COLUMN=ENCODING=VARLEN'
) ENGINE=InnoDB;
CREATE TABLE plain (id INT PRIMARY KEY, name VARCHAR(50)) ENGINE=InnoDB;
"""


def test_rapid_column_hint_emits_tiflash_replica():
    result = transform_schema(HINT_ONLY_EXAMPLE, tier="dedicated", tiflash_replicas=2)
    assert result.rapid_tables == []
    assert result.rapid_hint_tables == ["guests"]
    assert result.tiflash_statements == ["ALTER TABLE guests SET TIFLASH REPLICA 2;"]
    # ALTER placed after the CREATE TABLE, prefixed with a review comment
    assert "TISHIFT-REVIEW [HW-DDL-5]" in result.sql
    create_end = result.sql.index("ENGINE=InnoDB;")
    review_pos = result.sql.index("TISHIFT-REVIEW [HW-DDL-5]")
    alter_pos = result.sql.index("ALTER TABLE guests SET TIFLASH REPLICA 2;")
    assert create_end < review_pos < alter_pos
    assert "ALTER TABLE plain" not in result.sql
    # one table-level HW-DDL-5 finding, flagged for manual review
    hint_findings = [f for f in result.findings if f.rule_id == "HW-DDL-5"]
    assert len(hint_findings) == 1
    assert hint_findings[0].table == "guests"
    assert hint_findings[0].risk == "assess"
    assert hint_findings[0].action_taken == "tiflash_replica_emitted"
    # RAPID_COLUMN comments themselves stay untouched
    assert result.sql.count("COMMENT 'RAPID_COLUMN=ENCODING=VARLEN'") == 2
    assert result.parse_errors == []


def test_explicit_rapid_table_does_not_double_fire_hint_rule():
    result = transform_schema(V2_EXAMPLE, tier="dedicated", tiflash_replicas=1)
    assert [f for f in result.findings if f.rule_id == "HW-DDL-5"] == []
    assert result.rapid_hint_tables == []
    assert result.sql.count("SET TIFLASH REPLICA") == 1


def test_hint_with_replicas_zero_notes_only():
    result = transform_schema(HINT_ONLY_EXAMPLE, tier="dedicated", tiflash_replicas=0)
    assert result.tiflash_statements == []
    assert "TISHIFT-INFO [HW-DDL-5]" in result.sql
    assert "SET TIFLASH REPLICA" not in mask_sql(result.sql)
    hint_findings = [f for f in result.findings if f.rule_id == "HW-DDL-5"]
    assert len(hint_findings) == 1
    assert hint_findings[0].action_taken == "noted_only"


def test_hint_idempotent_across_full_pipeline():
    once = transform_schema(HINT_ONLY_EXAMPLE, tier="dedicated", tiflash_replicas=2)
    twice = transform_schema(once.sql, tier="dedicated", tiflash_replicas=2)
    assert twice.sql == once.sql
    assert twice.tiflash_statements == []
    assert [f for f in twice.findings if f.action_taken != "kept"] == []


def test_hint_idempotent_with_replicas_zero():
    once = transform_schema(HINT_ONLY_EXAMPLE, tier="dedicated", tiflash_replicas=0)
    twice = transform_schema(once.sql, tier="dedicated", tiflash_replicas=0)
    assert twice.sql == once.sql
    assert [f for f in twice.findings if f.action_taken != "kept"] == []


def test_hint_respects_existing_tiflash_statement():
    sql = HINT_ONLY_EXAMPLE + "\nALTER TABLE guests SET TIFLASH REPLICA 2;\n"
    result = transform_schema(sql, tier="dedicated", tiflash_replicas=2)
    assert result.sql.count("SET TIFLASH REPLICA") == 1
    assert [f for f in result.findings if f.rule_id == "HW-DDL-5"] == []


def test_multiple_rapid_tables_each_get_replica():
    sql = (
        "CREATE TABLE a (id INT PRIMARY KEY) SECONDARY_ENGINE=RAPID;\n"
        "CREATE TABLE b (id INT PRIMARY KEY) ENGINE=InnoDB;\n"
        "CREATE TABLE c (id INT PRIMARY KEY) SECONDARY_ENGINE=RAPID;\n"
    )
    result = transform_schema(sql, tier="dedicated", tiflash_replicas=1)
    assert result.rapid_tables == ["a", "c"]
    assert re.search(r"CREATE TABLE a .*?;\n\nALTER TABLE a SET TIFLASH REPLICA 1;", result.sql, re.S)
    assert "ALTER TABLE b" not in result.sql
    assert "ALTER TABLE c SET TIFLASH REPLICA 1;" in result.sql
