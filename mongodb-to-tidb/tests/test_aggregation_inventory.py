"""Tests for aggregation pipeline complexity scoring."""

from __future__ import annotations

from tishift_mongodb.core.scan.aggregation_inventory import (
    aggregate_complexity,
    complexity_of_pipeline,
    complexity_of_stage,
    inventory_from_user_file,
    stage_names,
)


def test_simple_stage_complexity():
    assert complexity_of_stage({"$match": {}}) == 1
    assert complexity_of_stage({"$sort": {}}) == 1
    assert complexity_of_stage({"$group": {"_id": "$x"}}) == 3
    assert complexity_of_stage({"$lookup": {}}) == 5
    assert complexity_of_stage({"$graphLookup": {}}) == 8
    assert complexity_of_stage({"$facet": {}}) == 8
    assert complexity_of_stage({"$out": "x"}) == 10
    assert complexity_of_stage({"$merge": "x"}) == 10


def test_array_op_adds_complexity():
    stage = {"$project": {"items": {"$filter": {"input": "$arr", "as": "i", "cond": {}}}}}
    # $project base 1 + $filter array op +4
    assert complexity_of_stage(stage) == 5


def test_pipeline_complexity_sum():
    pipeline = [
        {"$match": {}},
        {"$group": {"_id": "$x"}},
        {"$sort": {}},
    ]
    assert complexity_of_pipeline(pipeline) == 1 + 3 + 1


def test_stage_names():
    pipeline = [{"$match": {}}, {"$group": {}}, {"$lookup": {}}]
    assert stage_names(pipeline) == ["$match", "$group", "$lookup"]


def test_inventory_from_user_file():
    user_input = [
        {"id": "p1", "collection": "orders",
         "pipeline": [{"$match": {}}, {"$group": {"_id": "$s"}}, {"$sort": {}}]},
        {"id": "p2", "collection": "users",
         "pipeline": [{"$lookup": {"from": "orders"}}, {"$unwind": "$o"}]},
    ]
    inv = inventory_from_user_file(user_input)
    assert len(inv) == 2
    assert inv[0].collection == "orders"
    assert inv[0].complexity == 1 + 3 + 1
    assert inv[1].complexity == 5 + 5
    assert aggregate_complexity(inv) == (1 + 3 + 1) + (5 + 5)
