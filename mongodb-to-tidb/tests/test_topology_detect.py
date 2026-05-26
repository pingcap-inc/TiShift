"""Tests for topology classification (pure function, no Mongo needed)."""

from __future__ import annotations

from tishift_mongodb.core.scan.topology_detect import detect_topology_from_hello


def test_standalone():
    hello = {"ok": 1, "isWritablePrimary": True}
    build_info = {"version": "7.0.4"}
    r = detect_topology_from_hello(hello, build_info)
    assert r.topology == "standalone"
    assert r.mongo_version == "7.0.4"
    assert r.replica_set_name == ""


def test_replica_set():
    hello = {"ok": 1, "setName": "rs0", "hosts": ["a", "b", "c"]}
    build_info = {"version": "6.0.10"}
    r = detect_topology_from_hello(hello, build_info)
    assert r.topology == "replica_set"
    assert r.replica_set_name == "rs0"
    assert r.mongo_version == "6.0.10"


def test_sharded():
    hello = {"ok": 1, "msg": "isdbgrid"}
    build_info = {"version": "7.0.4"}
    r = detect_topology_from_hello(hello, build_info)
    assert r.topology == "sharded"


def test_missing_version_handled():
    r = detect_topology_from_hello({"setName": "rs0"}, {})
    assert r.mongo_version == "unknown"
