"""Tests for the Oracle → TiDB migration scoring engine."""

import pytest

from tishift_oracle.core.scan.scoring import (
    CategoryScore,
    ScoringResult,
    _classify_procedure,
    _score_data,
    _score_ops,
    _score_procedural_code,
    _score_query,
    _score_schema,
    score_migration,
)


class TestSchemaScoring:
    def test_perfect_schema(self):
        checklist = {"synonym_count": 0, "non_default_schema_count": 0}
        result = _score_schema(checklist)
        assert result.score == 20
        assert result.max_score == 20
        assert result.deductions == []

    def test_xmltype_deduction(self):
        checklist = {"has_xmltype_columns": True}
        result = _score_schema(checklist)
        assert result.score == 16

    def test_sdo_geometry_deduction(self):
        checklist = {"has_sdo_geometry": True}
        result = _score_schema(checklist)
        assert result.score == 16

    def test_multiple_deductions(self):
        checklist = {
            "has_xmltype_columns": True,    # -4
            "has_sdo_geometry": True,        # -4
            "has_object_types": True,        # -3
            "has_bfile_columns": True,       # -2
            "has_long_columns": True,        # -1
            "synonym_count": 5,              # -2 (capped)
        }
        result = _score_schema(checklist)
        # 20 - 4 - 4 - 3 - 2 - 1 - 2 = 4
        assert result.score == 4

    def test_floor_at_zero(self):
        checklist = {
            "has_xmltype_columns": True,
            "has_sdo_geometry": True,
            "has_object_types": True,
            "has_varrays": True,
            "has_bfile_columns": True,
            "has_long_columns": True,
            "synonym_count": 10,
            "non_default_schema_count": 5,
        }
        result = _score_schema(checklist)
        assert result.score == 0

    def test_synonym_cap(self):
        checklist = {"synonym_count": 100}
        result = _score_schema(checklist)
        # Only -2 deducted (capped at 2)
        assert result.score == 18


class TestProceduralCodeScoring:
    def test_no_procedures(self):
        checklist = {
            "stored_procedure_count": 0,
            "function_count": 0,
            "package_count": 0,
            "trigger_count": 0,
        }
        result = _score_procedural_code(checklist)
        assert result.score == 30

    def test_heuristic_scoring(self):
        checklist = {
            "stored_procedure_count": 5,
            "function_count": 2,
            "package_count": 1,
            "trigger_count": 3,
        }
        result = _score_procedural_code(checklist)
        # 30 - (7*2=14 proc heuristic) - (1*3=3 packages) - (3*2=6 triggers) = 7
        assert result.score == 7

    def test_detailed_procedure_scoring(self):
        checklist = {
            "stored_procedure_count": 2,
            "function_count": 0,
            "package_count": 0,
            "trigger_count": 0,
        }
        procedures = [
            {"name": "proc1", "lines": 5},      # trivial: -1
            {"name": "proc2", "lines": 50, "has_cursor": True},  # moderate: -3
        ]
        result = _score_procedural_code(checklist, procedures)
        assert result.score == 26  # 30 - 1 - 3

    def test_autonomous_tx_max_deduction(self):
        checklist = {
            "stored_procedure_count": 1,
            "function_count": 0,
            "package_count": 0,
            "trigger_count": 0,
        }
        procedures = [
            {"name": "proc1", "lines": 20, "has_autonomous_tx": True},  # -5
        ]
        result = _score_procedural_code(checklist, procedures)
        assert result.score == 25

    def test_trigger_cap(self):
        checklist = {
            "stored_procedure_count": 0,
            "function_count": 0,
            "package_count": 0,
            "trigger_count": 20,
        }
        result = _score_procedural_code(checklist)
        # 30 - min(20*2, 10) = 30 - 10 = 20
        assert result.score == 20

    def test_package_cap(self):
        checklist = {
            "stored_procedure_count": 0,
            "function_count": 0,
            "package_count": 10,
            "trigger_count": 0,
        }
        result = _score_procedural_code(checklist)
        # 30 - min(10*3, 9) = 30 - 9 = 21
        assert result.score == 21


class TestClassifyProcedure:
    def test_trivial(self):
        pts, label = _classify_procedure({"lines": 5})
        assert pts == 1
        assert label == "trivial"

    def test_simple(self):
        pts, label = _classify_procedure({"lines": 25})
        assert pts == 2
        assert label == "simple"

    def test_moderate_cursor(self):
        pts, label = _classify_procedure({"lines": 50, "has_cursor": True})
        assert pts == 3
        assert label == "moderate"

    def test_moderate_long(self):
        pts, label = _classify_procedure({"lines": 150})
        assert pts == 3
        assert label == "moderate"

    def test_complex_dynamic_sql(self):
        pts, label = _classify_procedure({"lines": 50, "has_dynamic_sql": True})
        assert pts == 4
        assert label == "complex"

    def test_requires_redesign_dynamic_sql_long(self):
        pts, label = _classify_procedure({"lines": 200, "has_dynamic_sql": True})
        assert pts == 5
        assert label == "requires_redesign"

    def test_requires_redesign_autonomous(self):
        pts, label = _classify_procedure({"lines": 10, "has_autonomous_tx": True})
        assert pts == 5
        assert label == "requires_redesign"

    def test_requires_redesign_pipelined(self):
        pts, label = _classify_procedure({"lines": 10, "has_pipe_row": True})
        assert pts == 4
        assert label == "requires_redesign"

    def test_bulk_collect(self):
        pts, label = _classify_procedure({"lines": 30, "has_bulk_collect": True})
        assert pts == 3
        assert label == "moderate"


class TestQueryScoring:
    def test_no_query_analysis(self):
        checklist = {}
        result = _score_query(checklist)
        assert result.score == 16
        assert "No query analysis" in result.deductions[0]

    def test_connect_by_deduction(self):
        checklist = {"has_connect_by": True, "connect_by_count": 3}
        result = _score_query(checklist)
        # 20 - min(3*2, 6) = 14
        assert result.score == 14

    def test_connect_by_cap(self):
        checklist = {"has_connect_by": True, "connect_by_count": 10}
        result = _score_query(checklist)
        # 20 - 6 (capped) = 14
        assert result.score == 14

    def test_multiple_query_deductions(self):
        checklist = {
            "has_connect_by": True,
            "connect_by_count": 2,       # -4
            "has_rownum_usage": True,
            "rownum_count": 3,            # -3
            "has_plus_join_syntax": True,
            "plus_join_count": 2,         # -2
            "has_listagg": True,
            "listagg_count": 1,           # -1
        }
        result = _score_query(checklist)
        assert result.score == 10  # 20 - 4 - 3 - 2 - 1

    def test_model_clause(self):
        checklist = {"has_model_clause": True}
        result = _score_query(checklist)
        assert result.score == 16  # 20 - 4


class TestDataScoring:
    def test_small_database(self):
        checklist = {"total_data_mb": 1000, "largest_table_mb": 500, "lob_column_count": 0, "table_count": 20}
        result = _score_data(checklist)
        assert result.score == 20

    def test_large_database_5tb(self):
        checklist = {"total_data_mb": 6_000_000}
        result = _score_data(checklist)
        assert result.score == 10  # -10

    def test_large_database_1tb(self):
        checklist = {"total_data_mb": 1_500_000}
        result = _score_data(checklist)
        assert result.score == 15  # -5

    def test_lob_deduction(self):
        checklist = {"lob_column_count": 8}
        result = _score_data(checklist)
        # min(8, 5) = -5
        assert result.score == 15

    def test_many_tables(self):
        checklist = {"table_count": 2000}
        result = _score_data(checklist)
        assert result.score == 18  # -2

    def test_long_columns(self):
        checklist = {"has_long_columns": True}
        result = _score_data(checklist)
        assert result.score == 19  # -1


class TestOpsScoring:
    def test_perfect_ops_dedicated(self):
        checklist = {
            "supplemental_logging_min": "YES",
            "oracle_version": "19.0.0.0.0",
            "nls_characterset": "AL32UTF8",
            "total_data_mb": 5000,
        }
        result = _score_ops(checklist, target_tier="dedicated")
        assert result.score == 10

    def test_no_supplemental_logging(self):
        checklist = {"supplemental_logging_min": "NO", "nls_characterset": "AL32UTF8", "oracle_version": "19"}
        result = _score_ops(checklist, target_tier="dedicated")
        assert result.score == 7  # -3

    def test_old_oracle_version(self):
        checklist = {"supplemental_logging_min": "YES", "nls_characterset": "AL32UTF8", "oracle_version": "11.2.0.4"}
        result = _score_ops(checklist, target_tier="dedicated")
        assert result.score == 8  # -2

    def test_non_utf8(self):
        checklist = {"supplemental_logging_min": "YES", "nls_characterset": "WE8MSWIN1252", "oracle_version": "19"}
        result = _score_ops(checklist, target_tier="dedicated")
        assert result.score == 8  # -2

    def test_us7ascii_double_deduction(self):
        checklist = {"supplemental_logging_min": "YES", "nls_characterset": "US7ASCII", "oracle_version": "19"}
        result = _score_ops(checklist, target_tier="dedicated")
        assert result.score == 7  # -2 (non-UTF8) - 1 (ASCII risk) = -3

    def test_starter_tier_penalties(self):
        checklist = {
            "supplemental_logging_min": "YES",
            "nls_characterset": "AL32UTF8",
            "oracle_version": "19",
            "total_data_mb": 5000,
        }
        result = _score_ops(checklist, target_tier="starter")
        # 10 - 2 (no CDC) = 8
        assert result.score == 8

    def test_starter_tier_large_data(self):
        checklist = {
            "supplemental_logging_min": "YES",
            "nls_characterset": "AL32UTF8",
            "oracle_version": "19",
            "total_data_mb": 30_000,
        }
        result = _score_ops(checklist, target_tier="starter")
        # 10 - 5 (> 25 GiB) - 2 (no CDC) = 3
        assert result.score == 3


class TestScoreMigration:
    def test_full_scoring_with_sample_checklist(self, sample_checklist):
        result = score_migration(sample_checklist, target_tier="dedicated")

        assert isinstance(result, ScoringResult)
        assert 0 <= result.schema.score <= 20
        assert 0 <= result.procedural_code.score <= 30
        assert 0 <= result.query.score <= 20
        assert 0 <= result.data.score <= 20
        assert 0 <= result.ops.score <= 10
        assert result.total == (
            result.schema.score
            + result.procedural_code.score
            + result.query.score
            + result.data.score
            + result.ops.score
        )
        assert result.rating in ("excellent", "good", "moderate", "challenging", "difficult")

    def test_perfect_database(self):
        checklist = {
            "table_count": 10,
            "stored_procedure_count": 0,
            "function_count": 0,
            "package_count": 0,
            "trigger_count": 0,
            "synonym_count": 0,
            "total_data_mb": 100,
            "largest_table_mb": 50,
            "lob_column_count": 0,
            "supplemental_logging_min": "YES",
            "oracle_version": "19.0.0.0.0",
            "nls_characterset": "AL32UTF8",
        }
        result = score_migration(checklist, target_tier="dedicated")
        # Schema: 20, Code: 30, Query: 16 (no analysis), Data: 20, Ops: 10 = 96
        assert result.total == 96
        assert result.rating == "excellent"

    def test_difficult_database(self):
        checklist = {
            "table_count": 2000,
            "stored_procedure_count": 50,
            "function_count": 20,
            "package_count": 10,
            "trigger_count": 30,
            "has_xmltype_columns": True,
            "has_sdo_geometry": True,
            "has_object_types": True,
            "has_varrays": True,
            "has_bfile_columns": True,
            "has_long_columns": True,
            "synonym_count": 50,
            "non_default_schema_count": 5,
            "lob_column_count": 20,
            "total_data_mb": 6_000_000,
            "largest_table_mb": 500_000,
            "has_connect_by": True,
            "connect_by_count": 10,
            "has_rownum_usage": True,
            "rownum_count": 20,
            "has_model_clause": True,
            "supplemental_logging_min": "NO",
            "oracle_version": "11.2",
            "nls_characterset": "WE8ISO8859P1",
        }
        result = score_migration(checklist, target_tier="dedicated")
        assert result.total < 25
        assert result.rating == "difficult"

    def test_rating_thresholds(self):
        """Verify rating thresholds by checking boundary values."""
        for total, expected in [(100, "excellent"), (90, "excellent"), (89, "good"),
                                (75, "good"), (74, "moderate"), (50, "moderate"),
                                (49, "challenging"), (25, "challenging"), (24, "difficult"),
                                (0, "difficult")]:
            result = ScoringResult(
                schema=CategoryScore("S", min(total, 20), 20, []),
                procedural_code=CategoryScore("P", min(max(total - 20, 0), 30), 30, []),
                query=CategoryScore("Q", min(max(total - 50, 0), 20), 20, []),
                data=CategoryScore("D", min(max(total - 70, 0), 20), 20, []),
                ops=CategoryScore("O", min(max(total - 90, 0), 10), 10, []),
            )
            assert result.rating == expected, f"total={total}, expected={expected}, got={result.rating}"
