"""Scan phase: sample-based schema inference and feature detection.

Import from submodules directly to avoid pulling heavy GCP deps when only the
pure-logic modules are needed:

    from tishift_firestore.core.scan.type_inferrer import FieldHistogram
    from tishift_firestore.core.scan.sampler import plan_sample
    from tishift_firestore.core.scan.reporter import run_scan   # needs google-cloud-firestore
"""
