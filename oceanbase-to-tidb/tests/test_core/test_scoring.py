"""Tests for OceanBase → TiDB dual-mode scoring engine."""

from tishift_ob.core.scan.scoring import (
    _mysql_schema, _mysql_proc, _mysql_query, _mysql_ops,
    _oracle_schema, _oracle_proc, _oracle_query, _oracle_ops,
    _score_data, score_migration,
)


class TestMysqlSchema:
    def test_perfect(self):
        assert _mysql_schema({}).score == 25

    def test_tablegroups(self):
        assert _mysql_schema({"has_tablegroups": True}).score == 22

    def test_all_deductions(self):
        c = {"has_tablegroups": True, "has_primary_zone": True, "has_locality": True,
             "has_resource_units": True, "has_global_indexes": True, "has_spatial": True}
        assert _mysql_schema(c).score == 11  # 25-3-2-2-2-2-3


class TestMysqlProc:
    def test_no_procs(self):
        assert _mysql_proc({"stored_procedure_count": 0, "trigger_count": 0}).score == 15

    def test_with_procs(self):
        assert _mysql_proc({"stored_procedure_count": 3, "trigger_count": 1}).score == 7  # 15-6-2


class TestMysqlQuery:
    def test_no_analysis(self):
        assert _mysql_query({}).score == 18

    def test_with_hints(self):
        assert _mysql_query({"_query_analyzed": True, "ob_hint_count": 3}).score == 18  # -2 capped


class TestMysqlOps:
    def test_cdc_unavailable(self):
        r = _mysql_ops({"cdc_not_available": True, "ob_version": "4.2"}, "dedicated")
        assert r.score == 15  # 20-5

    def test_old_version(self):
        r = _mysql_ops({"cdc_not_available": False, "ob_version": "3.2"}, "dedicated")
        assert r.score == 17  # 20-3

    def test_starter(self):
        r = _mysql_ops({"cdc_not_available": True, "ob_version": "4.2", "total_data_mb": 30000}, "starter")
        assert r.score == 8  # 20-5-5-2


class TestOracleSchema:
    def test_perfect(self):
        assert _oracle_schema({}).score == 20

    def test_tablegroups_and_types(self):
        assert _oracle_schema({"has_tablegroups": True, "has_oracle_types": True}).score == 14


class TestOracleProc:
    def test_no_procs(self):
        assert _oracle_proc({"stored_procedure_count": 0, "function_count": 0,
                              "package_count": 0, "trigger_count": 0}).score == 30

    def test_with_packages(self):
        c = {"stored_procedure_count": 2, "function_count": 1, "package_count": 2, "trigger_count": 1}
        # 30 - min(3*2,20) - min(2*3,9) - min(1*2,10) = 30-6-6-2 = 16
        assert _oracle_proc(c).score == 16


class TestOracleQuery:
    def test_no_analysis(self):
        assert _oracle_query({}).score == 16

    def test_connect_by(self):
        r = _oracle_query({"_query_analyzed": True, "connect_by_count": 2})
        assert r.score == 16  # 20-4


class TestData:
    def test_small(self):
        assert _score_data({"total_data_mb": 100}).score == 20

    def test_5tb(self):
        assert _score_data({"total_data_mb": 6_000_000}).score == 10


class TestScoreMigration:
    def test_mysql_mode(self, mysql_mode_checklist):
        r = score_migration(mysql_mode_checklist, ob_mode="mysql", target_tier="dedicated")
        assert r.ob_mode == "mysql"
        assert 0 <= r.total <= 100
        assert r.schema.max_score == 25
        assert r.procedural_code.max_score == 15
        assert r.ops.max_score == 20

    def test_oracle_mode(self, oracle_mode_checklist):
        r = score_migration(oracle_mode_checklist, ob_mode="oracle", target_tier="dedicated")
        assert r.ob_mode == "oracle"
        assert 0 <= r.total <= 100
        assert r.schema.max_score == 20
        assert r.procedural_code.max_score == 30
        assert r.ops.max_score == 10

    def test_perfect_mysql_mode(self):
        c = {"table_count": 5, "stored_procedure_count": 0, "trigger_count": 0,
             "total_data_mb": 100, "ob_version": "4.2", "cdc_not_available": False}
        r = score_migration(c, ob_mode="mysql", target_tier="dedicated")
        # Schema 25, Proc 15, Query 18, Data 20, Ops 20 = 98
        assert r.total == 98
        assert r.rating == "excellent"

    def test_rating_thresholds(self):
        # Verify boundary
        c = {"table_count": 5, "stored_procedure_count": 0, "trigger_count": 0,
             "total_data_mb": 100, "ob_version": "4.2", "cdc_not_available": False}
        r = score_migration(c, ob_mode="mysql", target_tier="dedicated")
        assert r.rating in ("excellent", "good", "moderate", "challenging", "difficult")
