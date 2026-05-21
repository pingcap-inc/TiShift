"""Load phase: bulk transfer from Firestore to TiDB.

All submodules require GCP / apache-beam / pymysql. Import directly:

    from tishift_firestore.core.load.dataflow_runner import submit_dataflow_jobs
    from tishift_firestore.core.load.lightning import build_lightning_config
"""
