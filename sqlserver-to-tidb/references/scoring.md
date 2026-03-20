# Readiness Scoring Methodology

5-category weighted model. Maximum score: 100.

## Category 1: Schema Compatibility (25 points max)

Start at 25, deduct for unsupported or problematic schema features.

```
SET schema_score = 25

IF has_image_columns OR has_ntext_columns THEN schema_score -= 3
IF has_hierarchyid_columns THEN schema_score -= 4
IF has_spatial_columns THEN schema_score -= 4
IF has_sql_variant_columns THEN schema_score -= 2
IF has_temporal_tables THEN schema_score -= 3
IF has_memory_optimized THEN schema_score -= 2
IF filestream_column_count > 0 THEN schema_score -= 2

computed_deduction = MIN(computed_column_count, 3)
schema_score -= computed_deduction

non_dbo_schema_count = count of distinct schemas that are not 'dbo'
schema_score -= MIN(non_dbo_schema_count * 3, 3)

schema_score = MAX(schema_score, 0)
```

## Category 2: Procedural Code (25 points max)

Start at 25, deduct for procedural code that must be rewritten.

```
SET code_score = 25

FOR EACH stored procedure:
    Count lines in definition
    Check for: CURSOR, sp_executesql, EXEC(@sql), temp tables (#), nested CALL

    IF has dynamic SQL (sp_executesql or EXEC(@sql)) or nested CALL:
        IF lines > 100: deduct 5 (requires_redesign)
        ELSE: deduct 4 (complex)
    ELSE IF lines < 10 AND no CURSOR:
        deduct 1 (trivial)
    ELSE IF lines < 30 AND no CURSOR:
        deduct 2 (simple)
    ELSE IF has CURSOR or temp tables or lines >= 100:
        deduct 3 (moderate)
    ELSE:
        deduct 2 (simple)

trigger_deduction = MIN(trigger_count * 2, 8)
code_score -= trigger_deduction

assembly_deduction = MIN(assembly_count * 3, 9)
code_score -= assembly_deduction

job_deduction = MIN(agent_job_count, 3)
code_score -= job_deduction

IF has_ssis THEN code_score -= 5

code_score = MAX(code_score, 0)
```

## Category 3: Query Compatibility (20 points max)

Evaluates T-SQL features found in routine/trigger/view definitions.

```
IF no routine/trigger/view definitions available THEN
    query_score = 16
    NOTE: "Assumed 16/20 — no definitions to analyze"
ELSE
    SET query_score = 20

    Count T-SQL pattern occurrences in all definitions:
    IF MERGE found:       query_score -= MIN(merge_count * 4, 4)
    IF FOR XML/OPENXML:   query_score -= MIN(forxml_count * 4, 4)
    IF OPENQUERY/OPENROWSET: query_score -= MIN(openquery_count * 3, 3)
    IF CURSOR found:      query_score -= MIN(cursor_count * 2, 2)
    IF sp_executesql:     query_score -= 2
    IF CROSS APPLY/UNPIVOT: query_score -= MIN(apply_count, 2)

query_score = MAX(query_score, 0)
```

## Category 4: Data Complexity (20 points max)

Evaluates data volume and structural complexity.

```
SET data_score = 20
total_data_gb = total_data_mb / 1024

IF total_data_gb > 5000: data_score -= 10
ELSE IF total_data_gb > 1000: data_score -= 5
ELSE IF total_data_gb > 500: data_score -= 2

largest_table_gb = largest_table_mb / 1024
IF largest_table_gb > 100: data_score -= 2

IF table_count > 1000: data_score -= 2
IF non_standard_collation_count > 0: data_score -= 2

data_score = MAX(data_score, 0)
```

## Category 5: Operational Readiness (10 points max)

Evaluates infrastructure readiness for migration.

```
SET ops_score = 10

IF is_cdc_enabled = 0: ops_score -= 3
IF windows_auth_only = 1: ops_score -= 2

ops_score = MAX(ops_score, 0)
```

## Rating Thresholds

```
total = schema_score + code_score + query_score + data_score + ops_score

>= 85: EXCELLENT  — straightforward migration, mostly automated
70-84: GOOD       — manageable with some manual work
50-69: MODERATE   — significant conversion effort needed
25-49: CHALLENGING — major redesign for several components
< 25:  DIFFICULT  — extensive manual work, consider phased approach
```

## Important Scoring Rules

- IDENTITY columns (AUTO_INCREMENT) cause NO deduction. They are a behavioral warning, not a compatibility issue.
- CDC not enabled is operational (affects sync phase), not a schema blocker.
- Each category floor is 0 — never go negative.
- When no query definitions are available, default to 16/20 (assume minor issues likely).

## Tier-Specific Scoring Adjustments

When the target tier is TiDB Cloud Starter or Essential, the following adjustments apply on top of the base scoring rules.

### Starter Tier

**Data Complexity adjustments:**
```
IF tier == "starter":
    IF total_data_gb > 25: data_score -= 8   # Exceeds free tier
    ELSE IF total_data_gb > 20: data_score -= 3  # Approaching limit
```

**Operational Readiness adjustments:**
```
IF tier == "starter":
    ops_score -= 2  # No zero-downtime cutover path (no Changefeeds/DM)
    IF is_cdc_enabled:
        ops_score -= 2  # CDC enabled but Starter can't use it
    # Note: the standard "CDC not enabled" deduction does NOT apply for Starter
    # because Starter can't use CDC regardless
```

### Essential Tier

**Data Complexity adjustments:**
```
IF tier == "essential":
    IF total_data_gb > 500: data_score -= 3  # Lightning unavailable; recommend Dedicated
```

### Dedicated / Self-Hosted

No tier-specific adjustments — use the base scoring rules as-is.
