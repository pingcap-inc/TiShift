"""Tests for the CockroachDB → TiDB migration scoring engine."""

from tishift_crdb.core.scan.scoring import (
    _score_schema, _score_query, _score_procedural, _score_data, _score_ops,
    score_migration, ScoringResult,
)


class TestSchemaScoring:
    def test_perfect(self):
        result = _score_schema({})
        assert result.score == 25

    def test_arrays(self):
        result = _score_schema({"array_column_count": 3})
        assert result.score == 22

    def test_array_cap(self):
        result = _score_schema({"array_column_count": 100})
        assert result.score == 20  # capped at -5

    def test_custom_types(self):
        result = _score_schema({"has_custom_types": True})
        assert result.score == 21

    def test_hash_sharded(self):
        result = _score_schema({"hash_sharded_index_count": 2})
        assert result.score == 23

    def test_multi_region(self):
        result = _score_schema({"has_multi_region": True})
        assert result.score == 23

    def test_ttl_low_cost(self):
        result = _score_schema({"has_row_level_ttl": True})
        assert result.score == 24  # only -1

    def test_floor_at_zero(self):
        # Total deductions: 5+4+3+3+3+3+2+1 = 24, score = 1
        # Add more to force to zero
        result = _score_schema({
            "array_column_count": 10, "has_custom_types": True,
            "has_spatial_geography": True, "has_interleaved_tables": True,
            "hash_sharded_index_count": 10, "inverted_index_count": 10,
            "has_multi_region": True, "has_row_level_ttl": True,
        })
        assert result.score <= 1  # near floor
        # Force to actual zero with even more deductions not possible in this category
        # so just verify it doesn't go negative
        assert result.score >= 0


class TestQueryScoring:
    def test_no_analysis(self):
        result = _score_query({})
        assert result.score == 20

    def test_jsonb_operators(self):
        result = _score_query({"has_jsonb_operators": True, "jsonb_operator_count": 3})
        assert result.score == 19  # 25 - 6

    def test_writable_ctes(self):
        result = _score_query({"has_writable_ctes": True})
        assert result.score == 21

    def test_returning(self):
        result = _score_query({"has_returning_clause": True})
        assert result.score == 23

    def test_full_text(self):
        result = _score_query({"has_full_text_search": True})
        assert result.score == 22


class TestProceduralScoring:
    def test_no_procs(self):
        result = _score_procedural({"stored_procedure_count": 0, "trigger_count": 0})
        assert result.score == 15

    def test_with_procs(self):
        result = _score_procedural({"stored_procedure_count": 3, "trigger_count": 0})
        assert result.score == 9  # 15 - 6

    def test_with_triggers(self):
        result = _score_procedural({"stored_procedure_count": 0, "trigger_count": 5})
        assert result.score == 9  # 15 - 6 (capped)

    def test_trigger_cap(self):
        result = _score_procedural({"stored_procedure_count": 0, "trigger_count": 20})
        assert result.score == 9  # 15 - min(40, 6)


class TestDataScoring:
    def test_small(self):
        result = _score_data({"total_data_mb": 100, "jsonb_column_count": 0, "table_count": 10})
        assert result.score == 20

    def test_large_5tb(self):
        result = _score_data({"total_data_mb": 6_000_000})
        assert result.score == 10

    def test_jsonb_columns(self):
        result = _score_data({"jsonb_column_count": 6})
        assert result.score == 16  # -4 capped

    def test_many_tables(self):
        result = _score_data({"table_count": 2000})
        assert result.score == 18


class TestOpsScoring:
    def test_perfect_dedicated(self):
        result = _score_ops({"crdb_version": "24.1"}, target_tier="dedicated")
        assert result.score == 15

    def test_old_version(self):
        result = _score_ops({"crdb_version": "21.2"}, target_tier="dedicated")
        assert result.score == 11  # -2 (< 23) - 2 (< 22)

    def test_starter_penalties(self):
        result = _score_ops({"crdb_version": "24.1", "total_data_mb": 5000}, target_tier="starter")
        assert result.score == 13  # 15 - 2 (no CDC)

    def test_starter_large(self):
        result = _score_ops({"crdb_version": "24.1", "total_data_mb": 30_000}, target_tier="starter")
        assert result.score == 9  # 15 - 4 (> 25 GiB) - 2 (no CDC)


class TestScoreMigration:
    def test_full_with_sample(self, sample_checklist):
        result = score_migration(sample_checklist, target_tier="dedicated")
        assert isinstance(result, ScoringResult)
        assert 0 <= result.total <= 100
        assert result.rating in ("excellent", "good", "moderate", "challenging", "difficult")

    def test_perfect_database(self):
        checklist = {
            "table_count": 5,
            "stored_procedure_count": 0,
            "trigger_count": 0,
            "array_column_count": 0,
            "jsonb_column_count": 0,
            "hash_sharded_index_count": 0,
            "inverted_index_count": 0,
            "total_data_mb": 100,
            "largest_table_mb": 50,
            "crdb_version": "24.1",
        }
        result = score_migration(checklist, target_tier="dedicated")
        # Schema 25, Query 20 (no analysis), Proc 15, Data 20, Ops 15 = 95
        assert result.total == 95
        assert result.rating == "excellent"

    def test_difficult_database(self):
        checklist = {
            "table_count": 2000,
            "stored_procedure_count": 20,
            "trigger_count": 10,
            "array_column_count": 50,
            "jsonb_column_count": 30,
            "hash_sharded_index_count": 20,
            "inverted_index_count": 15,
            "has_custom_types": True,
            "has_spatial_geography": True,
            "has_interleaved_tables": True,
            "has_multi_region": True,
            "has_row_level_ttl": True,
            "has_jsonb_operators": True,
            "jsonb_operator_count": 20,
            "has_writable_ctes": True,
            "has_returning_clause": True,
            "has_full_text_search": True,
            "has_array_usage": True,
            "array_usage_count": 10,
            "total_data_mb": 6_000_000,
            "largest_table_mb": 500_000,
            "crdb_version": "21.1",
            "changefeeds_not_available": True,
        }
        result = score_migration(checklist, target_tier="dedicated")
        assert result.total < 25
        assert result.rating == "difficult"
