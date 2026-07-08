"""Tests for the readiness scoring engine (pure, fixture-driven)."""

from tishift_heatwave.core.scan.analyzers.binlog_check import evaluate_binlog_config
from tishift_heatwave.core.scan.analyzers.scoring import ScoringContext, compute_readiness_score
from tishift_heatwave.models import (
    ColumnInfo,
    ConstraintInfo,
    HeatWaveMetadata,
    IndexInfo,
    QueryLogSignals,
    RoutineInfo,
    SchemaInventory,
    TableInfo,
    ViewInfo,
)
from tishift_heatwave.rules.compatibility import CompatibilityContext

CLEAN_BINLOG_VARS = {
    "log_bin": "ON",
    "server_id": "1",
    "binlog_format": "ROW",
    "binlog_row_image": "FULL",
    "binlog_expire_logs_seconds": "604800",
    "expire_logs_days": "0",
    "binlog_transaction_compression": "OFF",
}


def category(score, name):
    return next(c for c in score.categories if c.name == name)


def clean_context(**overrides) -> ScoringContext:
    compat_kwargs = dict(
        inventory=SchemaInventory(),
        metadata=HeatWaveMetadata(gtid_mode="ON"),
        binlog=evaluate_binlog_config(CLEAN_BINLOG_VARS),
        tier="dedicated",
        continue_replication_planned=False,
        query_log=QueryLogSignals(),
    )
    for key in list(overrides):
        if key in compat_kwargs:
            compat_kwargs[key] = overrides.pop(key)
    return ScoringContext(compat=CompatibilityContext(**compat_kwargs), **overrides)


class TestCleanSourceScoresPerfectly:
    def test_overall_100_and_ready(self):
        score = compute_readiness_score(clean_context())
        assert score.overall == 100
        assert score.rating == "READY"
        assert all(c.deductions == [] for c in score.categories)

    def test_category_maxima_sum_to_100(self):
        score = compute_readiness_score(clean_context())
        assert sum(c.max_points for c in score.categories) == 100


class TestSchemaCompatibility:
    def test_spatial_columns_deduct_5_per_table(self):
        inv = SchemaInventory()
        inv.columns = [
            ColumnInfo("myapp", "stores", "location", 1, "point", "point", True),
            ColumnInfo("myapp", "regions", "shape", 1, "geometry", "geometry", True),
        ]
        ctx = clean_context(inventory=inv)
        cat = category(compute_readiness_score(ctx), "Schema compatibility")
        assert cat.score == 30 - 10  # 2 tables * 5

    def test_foreign_keys_never_deduct(self):
        # Target is TiDB Cloud v8.5 — FK enforcement is native (since v6.6),
        # so foreign keys neither warn nor deduct.
        inv = SchemaInventory()
        inv.constraints = [ConstraintInfo("myapp", "orders", "fk1", "FOREIGN KEY", foreign_table="c")]

        cat = category(compute_readiness_score(clean_context(inventory=inv)), "Schema compatibility")
        assert cat.score == 30
        assert cat.deductions == []

    def test_0900_collation_noted_but_never_deducts(self):
        # utf8mb4_0900_* maps 1:1 to the target (native since TiDB v7.4) —
        # recorded as a -0 note, no scoring impact.
        inv = SchemaInventory()
        inv.columns = [
            ColumnInfo(
                "myapp", "orders", "note", 1, "varchar", "varchar(64)", True,
                collation="utf8mb4_0900_ai_ci",
            )
        ]
        cat = category(compute_readiness_score(clean_context(inventory=inv)), "Schema compatibility")
        assert cat.score == 30
        assert any(d.startswith("-0:") and "utf8mb4_0900" in d for d in cat.deductions)

    def test_score_floors_at_zero_not_negative(self):
        inv = SchemaInventory()
        inv.columns = [
            ColumnInfo("myapp", f"t{i}", "loc", 1, "point", "point", True) for i in range(20)
        ]
        cat = category(compute_readiness_score(clean_context(inventory=inv)), "Schema compatibility")
        assert cat.score == 0

    def test_unsupported_charset_deducts_5_per_table(self):
        inv = SchemaInventory()
        inv.columns = [
            ColumnInfo("myapp", "legacy", "notes", 1, "varchar", "varchar(99)", True, charset="cp1250"),
        ]
        cat = category(compute_readiness_score(clean_context(inventory=inv)), "Schema compatibility")
        assert cat.score == 30 - 5

    def test_case_colliding_table_names_deduct_5_per_group(self):
        inv = SchemaInventory()
        inv.tables = [
            TableInfo("myapp", "Users", "InnoDB", 10, 100, 10),
            TableInfo("myapp", "users", "InnoDB", 5, 50, 5),
        ]
        ctx = clean_context(inventory=inv, metadata=HeatWaveMetadata(lower_case_table_names=0))
        cat = category(compute_readiness_score(ctx), "Schema compatibility")
        # -5 for the BLOCKER-9 collision, -2 for the WARNING-8 mismatch itself
        assert cat.score == 30 - 5 - 2

    def test_fulltext_deducts_2_per_index_outside_starter(self):
        inv = SchemaInventory()
        inv.indexes = [
            IndexInfo("myapp", "articles", "idx_body", "FULLTEXT", is_unique=False, columns=["title"])
        ]
        # clean_context defaults tier="dedicated" — real index support is Starter-only.
        cat = category(compute_readiness_score(clean_context(inventory=inv)), "Schema compatibility")
        assert cat.score == 30 - 2

    def test_fulltext_does_not_deduct_on_starter(self):
        inv = SchemaInventory()
        inv.indexes = [
            IndexInfo("myapp", "articles", "idx_body", "FULLTEXT", is_unique=False, columns=["title"])
        ]
        ctx = clean_context(inventory=inv, tier="starter")
        cat = category(compute_readiness_score(ctx), "Schema compatibility")
        assert cat.score == 30

    def test_lower_case_table_names_mismatch_deducts_2_flat(self):
        ctx = clean_context(metadata=HeatWaveMetadata(lower_case_table_names=0))
        cat = category(compute_readiness_score(ctx), "Schema compatibility")
        assert cat.score == 30 - 2

    def test_updatable_views_deduct_1_per_view(self):
        inv = SchemaInventory()
        inv.views = [
            ViewInfo("myapp", "active_orders", is_updatable=True),
            ViewInfo("myapp", "customer_summary", is_updatable=False),
        ]
        cat = category(compute_readiness_score(clean_context(inventory=inv)), "Schema compatibility")
        assert cat.score == 30 - 1


class TestProgrammableObjects:
    def test_stored_procedures_batched_by_ten(self):
        inv = SchemaInventory()
        inv.routines = [
            RoutineInfo(schema_name="myapp", routine_name=f"p{i}", kind="PROCEDURE", definition="")
            for i in range(11)
        ]
        cat = category(compute_readiness_score(clean_context(inventory=inv)), "Programmable objects")
        assert cat.score == 25 - 10  # ceil(11/10)=2 batches * 5

    def test_nine_procedures_is_one_batch(self):
        inv = SchemaInventory()
        inv.routines = [
            RoutineInfo(schema_name="myapp", routine_name=f"p{i}", kind="PROCEDURE", definition="")
            for i in range(9)
        ]
        cat = category(compute_readiness_score(clean_context(inventory=inv)), "Programmable objects")
        assert cat.score == 25 - 5

    def test_udfs_present_flat_deduction(self):
        ctx = clean_context(query_log=QueryLogSignals(udf_count=3))
        cat = category(compute_readiness_score(ctx), "Programmable objects")
        assert cat.score == 25 - 5  # flat, not per-UDF


class TestHeatWaveSurface:
    def test_lakehouse_present_deducts_20(self):
        inv = SchemaInventory()
        inv.lakehouse_tables = ["myapp.raw"]
        cat = category(compute_readiness_score(clean_context(inventory=inv)), "HeatWave surface")
        assert cat.score == 0  # 20 - 20

    def test_automl_present_deducts_10(self):
        inv = SchemaInventory()
        inv.automl_schemas = ["ML_SCHEMA_x"]
        cat = category(compute_readiness_score(clean_context(inventory=inv)), "HeatWave surface")
        assert cat.score == 10

    def test_rapid_offload_costs_nothing(self):
        inv = SchemaInventory()
        inv.rapid_tables = ["orders", "line_items"]
        cat = category(compute_readiness_score(clean_context(inventory=inv)), "HeatWave surface")
        assert cat.score == 20
        assert any("no penalty" in d for d in cat.deductions)

    def test_vector_columns_deduct_3_per_table(self):
        inv = SchemaInventory()
        inv.columns = [
            ColumnInfo("myapp", "articles", "embedding", 1, "vector", "vector(1536)", True, is_vector=True),
        ]
        cat = category(compute_readiness_score(clean_context(inventory=inv)), "HeatWave surface")
        assert cat.score == 17


class TestDataAndLoadFeasibility:
    def test_size_within_starter_capacity_no_deduction(self):
        ctx = clean_context(tier="starter", total_size_bytes=10 * 1024**3)
        cat = category(compute_readiness_score(ctx), "Data & load feasibility")
        assert cat.score == 15

    def test_size_exceeds_starter_capacity_deducts_5(self):
        ctx = clean_context(tier="starter", total_size_bytes=30 * 1024**3)
        cat = category(compute_readiness_score(ctx), "Data & load feasibility")
        assert cat.score == 10

    def test_unmeasured_size_skips_the_check(self):
        ctx = clean_context(tier="starter", total_size_bytes=None)
        cat = category(compute_readiness_score(ctx), "Data & load feasibility")
        assert cat.score == 15

    def test_dedicated_tier_has_no_modeled_capacity_cap(self):
        ctx = clean_context(tier="dedicated", total_size_bytes=10 * 1024**4)
        cat = category(compute_readiness_score(ctx), "Data & load feasibility")
        assert cat.score == 15

    def test_no_network_path_deducts_5(self):
        ctx = clean_context(network_path_confirmed=False)
        cat = category(compute_readiness_score(ctx), "Data & load feasibility")
        assert cat.score == 10

    def test_xa_detected_deducts_3(self):
        ctx = clean_context(query_log=QueryLogSignals(xa_detected=True))
        cat = category(compute_readiness_score(ctx), "Data & load feasibility")
        assert cat.score == 12


class TestCutoverAndCdc:
    def test_no_continue_replication_planned_is_clean_even_with_bad_binlog(self):
        bad_vars = {**CLEAN_BINLOG_VARS, "log_bin": "OFF"}
        ctx = clean_context(binlog=evaluate_binlog_config(bad_vars), continue_replication_planned=False)
        cat = category(compute_readiness_score(ctx), "Cutover & continue replication")
        assert cat.score == 10

    def test_continue_replication_planned_on_starter_deducts_5(self):
        ctx = clean_context(tier="starter", continue_replication_planned=True)
        cat = category(compute_readiness_score(ctx), "Cutover & continue replication")
        assert cat.score == 5

    def test_log_bin_off_deducts_5_when_continue_replication_planned(self):
        bad_vars = {**CLEAN_BINLOG_VARS, "log_bin": "OFF"}
        ctx = clean_context(binlog=evaluate_binlog_config(bad_vars), continue_replication_planned=True)
        cat = category(compute_readiness_score(ctx), "Cutover & continue replication")
        assert cat.score == 5

    def test_gtid_mode_off_deducts_3_when_continue_replication_planned(self):
        ctx = clean_context(metadata=HeatWaveMetadata(gtid_mode="OFF"), continue_replication_planned=True)
        cat = category(compute_readiness_score(ctx), "Cutover & continue replication")
        assert cat.score == 7

    def test_binlog_row_value_options_deducts_2_when_continue_replication_planned(self):
        ctx = clean_context(
            metadata=HeatWaveMetadata(gtid_mode="ON", binlog_row_value_options="PARTIAL_JSON"),
            continue_replication_planned=True,
        )
        cat = category(compute_readiness_score(ctx), "Cutover & continue replication")
        assert cat.score == 8

    def test_tables_without_valid_index_deduct_2_each_only_when_continue_replication_planned(self):
        not_planned = clean_context(continue_replication_planned=False, tables_without_valid_index=3)
        planned = clean_context(continue_replication_planned=True, tables_without_valid_index=3)

        assert category(compute_readiness_score(not_planned), "Cutover & continue replication").score == 10
        assert category(compute_readiness_score(planned), "Cutover & continue replication").score == 4

    def test_score_floors_at_zero(self):
        bad_vars = {
            "log_bin": "OFF",
            "server_id": "0",
            "binlog_format": "STATEMENT",
            "binlog_row_image": "MINIMAL",
            "binlog_expire_logs_seconds": "0",
            "expire_logs_days": "0",
            "binlog_transaction_compression": "ON",
        }
        ctx = clean_context(
            tier="starter",
            continue_replication_planned=True,
            binlog=evaluate_binlog_config(bad_vars),
            metadata=HeatWaveMetadata(gtid_mode="OFF", binlog_row_value_options="PARTIAL_JSON"),
            tables_without_valid_index=50,
        )
        cat = category(compute_readiness_score(ctx), "Cutover & continue replication")
        assert cat.score == 0


class TestOverallRatingBands:
    def test_perfect_score_is_ready(self):
        assert compute_readiness_score(clean_context()).rating == "READY"

    def test_lakehouse_present_alone_drops_below_ready(self):
        inv = SchemaInventory()
        inv.lakehouse_tables = ["myapp.raw"]
        score = compute_readiness_score(clean_context(inventory=inv))
        assert score.overall == 80
        assert score.rating == "READY WITH WORK"
