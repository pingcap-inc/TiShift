# Integration tests

These run against a real Supabase project (sandbox) and a real TiDB instance (or TiDB Cloud Starter). They require credentials in environment variables and are skipped by default in CI unless those variables are set.

Environment variables:

```
TISHIFT_INTEGRATION_SUPABASE_HOST
TISHIFT_INTEGRATION_SUPABASE_USER
TISHIFT_INTEGRATION_SUPABASE_PASSWORD
TISHIFT_INTEGRATION_TIDB_HOST
TISHIFT_INTEGRATION_TIDB_USER
TISHIFT_INTEGRATION_TIDB_PASSWORD
```

Run with:

```
pytest tests/integration -q -m integration
```

Skip in CI unless the above are set:

```
pytest tests -q -m "not integration"
```

The fixture project is loaded from `sql/sample-schema.sql`.
