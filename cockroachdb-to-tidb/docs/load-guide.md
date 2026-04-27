# Load Guide — CockroachDB to TiDB

## Data Extraction

Use CockroachDB's `EXPORT INTO CSV`. Do NOT use pg_dump (fails) or cockroach dump (deprecated).

### Local export (self-hosted CRDB)

```sql
EXPORT INTO CSV 'nodelocal:///tmp/export/users' FROM TABLE public.users;
```

### Cloud export (CockroachDB Cloud)

```sql
EXPORT INTO CSV 's3://my-bucket/tishift-export/users?AUTH=implicit' FROM TABLE public.users;
```

## Load Strategy

| Tier | Size | Method |
|---|---|---|
| Starter | ≤ 25 GiB | CSV → `ticloud serverless import start` |
| Essential | < 100 GB | CSV → `LOAD DATA LOCAL INFILE` |
| Essential | 100 GB–500 GB | CSV → S3 → TiDB Lightning |
| Dedicated | < 100 GB | CSV → `LOAD DATA LOCAL INFILE` |
| Dedicated | > 100 GB | CSV → S3 → TiDB Lightning physical mode |

**No DMS option** — AWS DMS does not support CockroachDB as a source.

## Performance Tips

- Drop secondary indexes before load, recreate after (3–5x faster)
- EXPORT produces one file per range — may result in many small files for large tables. Concatenate before LOAD DATA if needed.
- For UUID PK tables, LOAD DATA is efficient since UUIDs scatter naturally (no hotspot).
