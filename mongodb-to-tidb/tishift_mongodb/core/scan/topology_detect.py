"""Detect MongoDB deployment topology: standalone / replica set / sharded."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TopologyResult:
    topology: str          # standalone | replica_set | sharded
    mongo_version: str
    replica_set_name: str  # empty if not a replica set
    shards: list[str]      # empty unless sharded


def detect_topology_from_hello(hello: dict, build_info: dict) -> TopologyResult:
    """Pure: classify topology given hello + buildInfo responses.

    Separated from the live client call so it can be tested directly.
    """
    if hello.get("msg") == "isdbgrid":
        topology = "sharded"
        rs_name = ""
    elif hello.get("setName"):
        topology = "replica_set"
        rs_name = hello["setName"]
    else:
        topology = "standalone"
        rs_name = ""

    mongo_version = build_info.get("version", "unknown")
    return TopologyResult(
        topology=topology,
        mongo_version=mongo_version,
        replica_set_name=rs_name,
        shards=[],  # populated separately when sharded via listShards
    )


def detect_topology(client) -> TopologyResult:
    """Live: call admin commands on the given PyMongo client."""
    hello = client.admin.command("hello")
    build_info = client.admin.command("buildInfo")
    result = detect_topology_from_hello(hello, build_info)
    if result.topology == "sharded":
        shards_doc = client.admin.command("listShards")
        shards = [s["host"] for s in shards_doc.get("shards", [])]
        return TopologyResult(
            topology="sharded",
            mongo_version=result.mongo_version,
            replica_set_name="",
            shards=shards,
        )
    return result
