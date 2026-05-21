# MongoDB → TiDB Type Mapping

Loaded by the convert phase. Every BSON type has a default TiDB target;
some have configurable alternatives that the per-collection schema policy
can select.

## BSON scalar types

| BSON type | TiDB type (default) | Notes |
|---|---|---|
| `Int32` | `INT` | Direct. |
| `Int64` | `BIGINT` | Direct. |
| `Double` | `DOUBLE` | Direct. |
| `Decimal128` | `DECIMAL(38,11)` | Covers Mongo's 34-digit significand. TiDB supports up to 65 total digits. |
| `Boolean` | `TINYINT(1)` | Standard MySQL convention. |
| `String` | `VARCHAR(N)` or `TEXT` | N rounds to next power of 2 from observed max length. ≥10,000 chars → `TEXT`. Always `utf8mb4_bin`. |
| `Null` | (column nullable) | Influences nullability, not type. |

## Temporal types

| BSON type | TiDB type (default) | Notes |
|---|---|---|
| `Date` | `DATETIME(6)` | Mongo Date is ms; safe over-fit to TiDB microsecond. WARN if values outside year 1000–9999. |
| `Timestamp` (BSON internal) | `DATETIME(6)` | Internal type, rare in user data. Lossy: pack `(seconds, increment)` into one DATETIME(6). |

## Identifier types

| BSON type | TiDB type (default) | Alternative |
|---|---|---|
| `ObjectId` | `VARCHAR(24)` (hex form) | `BINARY(12)` if storage matters more than human-readability. Default preserves DBRef compatibility. |
| `Binary` subtype 4 (UUID standard) | `BINARY(16)` | Direct. |
| `Binary` subtype 3 (UUID legacy) | `BINARY(16)` | Driver byte-order varies; normalize on read. |

## Binary types

| BSON type | TiDB type (default) | Threshold |
|---|---|---|
| `Binary` subtype 0, 1, 2, 5, 7 (general) | `LONGBLOB` | Inline. |
| `Binary` (any subtype) max size > 5 MB | `VARCHAR(2048)` storing object-storage path | Recommend offload to S3/GCS/Azure Blob; surface in advisor. |
| `Binary` subtype 6 (CSFLE) | `LONGBLOB` (opaque) | BLOCKER-3 — cannot decrypt. Surface and decide per field. |

## Reference types

| BSON type | TiDB type (default) | Notes |
|---|---|---|
| `DBRef` ({$ref, $id, $db}) | `VARCHAR(1500)` storing the full reference path | If target collection in scope, emit FK constraint. |
| Field named like `*_ref` / `*_id` storing string ObjectId | `VARCHAR(24)` | Advisor can suggest as FK candidate. |

## Other BSON types

| BSON type | TiDB type (default) | Notes |
|---|---|---|
| `Regex` | `VARCHAR(...)` | Lossy. Store source pattern as text. |
| `Code` / `CodeWithScope` | `VARCHAR(...)` + SECURITY warning | Almost never used. If present, surface — never execute. |
| `Symbol` | `VARCHAR(...)` | Deprecated since Mongo 1.6. Lossy. |
| `MinKey` / `MaxKey` | `NULL` | Internal sort sentinels. Map to NULL with a WARNING. |

## Container types

| BSON type | TiDB type (default) | Alternative |
|---|---|---|
| Subdocument (embedded), shallow + stable shape | Flattened columns | One column per known sub-field. |
| Subdocument (deep / polymorphic) | `JSON` | When inference finds >5 keys or polymorphic value types. |
| `Array<scalar>` | `JSON` | Multi-valued index via generated column when in a composite index. |
| `Array<object>` | Child table (default) | Synthetic PK + `parent_doc_id` FK + columns for each object field. JSON alternative on user override. |

## Document `_id` type

| Observed type | Maps to | Notes |
|---|---|---|
| All `ObjectId` | `VARCHAR(24) PRIMARY KEY` | Preserve hex form. |
| All `String` | `VARCHAR(N) PRIMARY KEY` (N from observed max) | Application-supplied IDs. |
| All `Int64` | `BIGINT PRIMARY KEY` | Numeric IDs. |
| Mixed types | **BLOCKER-2** — cannot have one PK type | Coerce / split / skip per collection. |

## Polymorphic fields

When a field has multiple non-null types in the BSON-aware histogram:

| Default | When the field is composite-indexed | When user overrides |
|---|---|---|
| `JSON` column | BLOCKER-5 — user must choose: coerce in application, accept JSON with degraded index, or skip | Honor per-field override in `convert.per_collection.<col>.poly_fields.<field>` |

## Sample type-mapping for the demo schema

Given `users` collection with `email: string`, `age: int32`, `location: geopoint subdoc`, `avatar: Binary`, `created_at: Date`, `_id: ObjectId`:

```sql
CREATE TABLE `users` (
  `id` VARCHAR(24) NOT NULL,
  `email` VARCHAR(256) NOT NULL,
  `age` INT NULL,
  `location_lat` DECIMAL(9,6) NULL,
  `location_lng` DECIMAL(9,6) NULL,
  `avatar` LONGBLOB NULL,
  `created_at` DATETIME(6) NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
```

Given `users.orders` subcollection (mongoose-style embedded path, becomes a child table) with DBRef to `products`, `Array<Subdoc>` (items), `Decimal128` (total), `Date` (created_at):

```sql
CREATE TABLE `orders` (
  `id` VARCHAR(24) NOT NULL,
  `user_ref` VARCHAR(1500) NOT NULL,
  `product_ref` VARCHAR(1500) NOT NULL,
  `total` DECIMAL(38,11) NULL,
  `created_at` DATETIME(6) NULL,
  PRIMARY KEY (`id`),
  KEY `idx_user_ref` (`user_ref`(255)),
  KEY `idx_product_ref` (`product_ref`(255))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE `orders_items` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `parent_doc_id` VARCHAR(24) NOT NULL,
  `sku` VARCHAR(64) NULL,
  `qty` BIGINT NULL,
  `price` DECIMAL(38,11) NULL,
  PRIMARY KEY (`id`),
  KEY `idx_parent` (`parent_doc_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
```
