"""Scan phase: topology detection, BSON-aware sampling, index + aggregation inventory.

Import from submodules directly to avoid pulling pymongo for pure-logic tests:

    from tishift_mongodb.core.scan.type_inferrer import FieldHistogram
    from tishift_mongodb.core.scan.sampler import plan_sample
"""
