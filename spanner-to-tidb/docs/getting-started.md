# Getting Started

1. Authenticate with GCP: `gcloud auth application-default login`
2. Create `tishift-spanner.yaml` from the example config.
3. Run `tishift-spanner scan` to assess your Spanner database.
4. Run `tishift-spanner convert` to generate TiDB-compatible DDL.
5. Run `tishift-spanner load` to transfer data via Dataflow/GCS.
6. Run `tishift-spanner check` to validate, then `tishift-spanner sync` for CDC.
