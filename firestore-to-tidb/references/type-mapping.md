# Firestore → TiDB Type Mapping

Loaded by the convert phase. Every Firestore type has a default TiDB target;
some have configurable alternatives that the per-collection schema policy can
select.

## Scalar types

| Firestore type | TiDB type (default) | Notes |
|---|---|---|
| `string` | `VARCHAR(N)` or `TEXT` | N = round up to next power of 2 from observed `max(length)` in samples. ≥10,000 chars → `TEXT`. Always `utf8mb4_bin` collation. |
| `number` (integer-shaped, `|x| < 2^53`) | `BIGINT` | Firestore numbers are float64 internally; if samples show only integer values within the JS safe-int range, prefer `BIGINT`. |
| `number` (float-shaped) | `DOUBLE` | If any sampled value has decimals or exceeds the safe-int range. |
| `boolean` | `TINYINT(1)` | Standard MySQL convention. |
| `null` | (column nullable) | Influences `NOT NULL` decision, not a separate type. |

## Temporal types

| Firestore type | TiDB type (default) | Notes |
|---|---|---|
| `Timestamp` | `DATETIME(6)` | Microsecond precision. Three digits of precision lost from Firestore's nanosecond representation. |
| `Timestamp` (with `serverTimestamp()` sentinel use detected) | `DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6)` | Server-side default added. Application writes must drop the sentinel. |

## Reference types

| Firestore type | TiDB type (default) | Notes |
|---|---|---|
| `DocumentReference` (target collection in scope) | `VARCHAR(1500) NOT NULL` + `FOREIGN KEY` | Stores the full document path: `projects/p/databases/(default)/documents/users/abc`. FK enforces referential integrity (v6.6+). |
| `DocumentReference` (target collection not in scope or cross-database) | `VARCHAR(1500)` | Plain column, indexed. No FK constraint. Surface in WARNING-9. |

## Spatial types

| Firestore type | TiDB type (default) | Alternative |
|---|---|---|
| `GeoPoint` (default — used in spatial queries) | `<f>_lat DECIMAL(9,6)`, `<f>_lng DECIMAL(9,6)` (two columns) | Each component independently indexable. Range queries work; proximity queries require app-side math. |
| `GeoPoint` (opaque — never queried spatially) | `JSON` storing `{"lat":..., "lng":...}` | Lower storage cost when not queried. |

Selection is per-field in `convert.per_collection.<col>.geopoint_mapping`.

## Binary types

| Firestore type | TiDB type (default) | Threshold |
|---|---|---|
| `Bytes` ≤ 5 MiB observed | `LONGBLOB` | Inline storage. |
| `Bytes` > 5 MiB observed | `VARCHAR(2048)` storing GCS path | Recommend offloading. Convert advisor flags this. |

## Container types

| Firestore type | TiDB type (default) | Alternative |
|---|---|---|
| `Map` (shallow ≤ 2 levels, stable keys across docs) | Flattened columns (`address_street`, `address_city`, …) | `JSON` column if user prefers per-collection. |
| `Map` (deep > 2 levels or polymorphic) | `JSON` | No alternative — flattening is too brittle. |
| `Array<scalar>` | `JSON` | Multi-valued index via generated column when the field appears in a composite index. |
| `Array<object>` | Child table | Synthetic PK + `parent_doc_id` FK + columns for each object field. JSON alternative on user override. |

## Hierarchical types

| Firestore feature | TiDB representation | Notes |
|---|---|---|
| **Subcollection** | Child table named `{parent_collection}_{subcollection_name}` | `parent_doc_id VARCHAR(20)` FK to parent, synthetic PK, optional `_path VARCHAR(1500)` for collection-group queries. |
| **Document ID** (auto-generated, 20-char base62) | `VARCHAR(20) PRIMARY KEY` | Preserve original to keep DocumentReference values valid. |
| **Document ID** (user-supplied integer-like) | `BIGINT PRIMARY KEY` | Inference-based; convert advisor surfaces the choice. |
| **Document path** (`_path` denorm column) | `VARCHAR(1500)` | Optional; required only if collection-group queries are used. |

## Polymorphic fields

When a field has multiple non-null types in the sample histogram:

| Default | When the field is in a composite-indexed path | When user overrides |
|---|---|---|
| `JSON` column | Becomes BLOCKER-4 — user must choose: coerce in application, accept JSON with degraded index, or skip | Honor the per-field override in `convert.per_collection.<col>.poly_fields.<field>` |

## Sample type-mapping decisions for the demo schema

Given `users` collection with `email: string`, `age: number(int)`, `location: GeoPoint`, `avatar: bytes`, `created_at: Timestamp`:

```sql
CREATE TABLE users (
    id VARCHAR(20) NOT NULL,
    email VARCHAR(256) NOT NULL,
    age BIGINT NULL,
    location_lat DECIMAL(9,6) NULL,
    location_lng DECIMAL(9,6) NULL,
    avatar LONGBLOB NULL,
    created_at DATETIME(6) NULL,
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
```

Given the `orders` subcollection of `users` with `product_ref: DocumentReference`, `items: Array<object>`, `total: number(float)`, `created_at: Timestamp` (with server sentinel):

```sql
CREATE TABLE users_orders (
    id VARCHAR(20) NOT NULL,
    parent_doc_id VARCHAR(20) NOT NULL,
    product_ref VARCHAR(1500) NOT NULL,
    total DOUBLE NULL,
    created_at DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    KEY idx_parent (parent_doc_id),
    KEY idx_product_ref (product_ref(255))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE users_orders_items (
    id BIGINT NOT NULL AUTO_INCREMENT,
    parent_doc_id VARCHAR(20) NOT NULL,
    sku VARCHAR(64) NULL,
    qty BIGINT NULL,
    price DOUBLE NULL,
    PRIMARY KEY (id),
    KEY idx_parent (parent_doc_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
```

The `Array<object>` decomposes into the third table because the convert
advisor detected stable inner shape from the sample.
