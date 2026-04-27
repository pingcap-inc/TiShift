# Readiness Scoring Methodology — Oracle → TiDB

5-category weighted model. Maximum score: 100.

Oracle's Procedural Code category is weighted at 30 (highest of any TiShift variant) because PL/SQL packages, autonomous transactions, and DBMS_* dependencies are the dominant migration blocker for Oracle databases.

## Category 1: Schema Compatibility (20 points max)

Start at 20, deduct for unsupported or problematic schema features.

```
SET schema_score = 20

IF has_xmltype_columns THEN schema_score -= 4
IF has_sdo_geometry THEN schema_score -= 4
IF has_object_types THEN schema_score -= 3
IF has_varrays OR has_nested_tables THEN schema_score -= 3
IF has_bfile_columns THEN schema_score -= 2
IF has_long_columns THEN schema_score -= 1

synonym_deduction = MIN(synonym_count, 2)
schema_score -= synonym_deduction

non_default_schema_count = count of schemas beyond the primary
schema_score -= MIN(non_default_schema_count, 3)

schema_score = MAX(schema_score, 0)
```

## Category 2: Procedural Code (30 points max)

Start at 30, deduct for PL/SQL that must be rewritten. This is the heaviest category because PL/SQL is the #1 migration blocker for Oracle.

```
SET code_score = 30

IF zero procedures, functions, packages, triggers → keep 30

FOR EACH stored procedure or function:
    Count lines in ALL_SOURCE
    Check for: CURSOR, EXECUTE IMMEDIATE, DBMS_*, UTL_*, BULK COLLECT,
               FORALL, PRAGMA AUTONOMOUS_TRANSACTION, PIPE ROW

    IF has PRAGMA AUTONOMOUS_TRANSACTION: deduct 5 (requires_redesign)
    ELSE IF has PIPE ROW (pipelined function): deduct 4 (requires_redesign)
    ELSE IF has EXECUTE IMMEDIATE or DBMS_SQL:
        IF lines > 100: deduct 5 (requires_redesign)
        ELSE: deduct 4 (complex)
    ELSE IF has BULK COLLECT or FORALL:
        deduct 3 (moderate)
    ELSE IF has CURSOR or lines >= 100:
        deduct 3 (moderate)
    ELSE IF lines < 10 AND no CURSOR:
        deduct 1 (trivial)
    ELSE IF lines < 30:
        deduct 2 (simple)
    ELSE:
        deduct 2 (simple)

package_deduction = MIN(package_count * 3, 9)
code_score -= package_deduction

trigger_deduction = MIN(trigger_count * 2, 10)
code_score -= trigger_deduction

code_score = MAX(code_score, 0)
```

## Category 3: Query Compatibility (20 points max)

Start at 20, deduct for Oracle SQL patterns that sqlglot cannot auto-convert.

```
SET query_score = 20

// Only scored if source code / view definitions are analyzed, otherwise assume 16/20

connect_by_count = count of objects using CONNECT BY
query_score -= MIN(connect_by_count * 2, 6)

rownum_count = count of objects using ROWNUM
query_score -= MIN(rownum_count, 3)

plus_join_count = count of objects using (+) syntax
query_score -= MIN(plus_join_count, 3)

listagg_count = count of objects using LISTAGG
query_score -= MIN(listagg_count, 2)

IF has_model_clause THEN query_score -= 4

xml_function_count = count of XML function usage (XMLELEMENT, XMLAGG, EXTRACTVALUE, etc.)
query_score -= MIN(xml_function_count * 2, 4)

query_score = MAX(query_score, 0)
```

## Category 4: Data Complexity (20 points max)

Start at 20, deduct for data volume and LOB complexity.

```
SET data_score = 20

IF total_data_mb > 5000000 THEN data_score -= 10    // > 5 TB
ELSE IF total_data_mb > 1000000 THEN data_score -= 5 // > 1 TB
ELSE IF total_data_mb > 500000 THEN data_score -= 2  // > 500 GB

IF largest_table_mb > 100000 THEN data_score -= 2    // > 100 GB

lob_deduction = MIN(lob_column_count, 5)
data_score -= lob_deduction

IF table_count > 1000 THEN data_score -= 2

IF has_long_columns THEN data_score -= 1  // LONG type complicates extraction

data_score = MAX(data_score, 0)
```

## Category 5: Operational Readiness (10 points max)

Start at 10, deduct for CDC readiness, version, and character set issues.

```
SET ops_score = 10

IF supplemental_logging_min != 'YES' THEN ops_score -= 3  // CDC not ready
IF oracle_version < 12 THEN ops_score -= 2                // 11g — approaching EOL
IF nls_characterset != 'AL32UTF8' THEN ops_score -= 2     // charset conversion needed
IF nls_characterset = 'US7ASCII' THEN ops_score -= 1      // additional risk — ASCII only

// Tier-specific adjustments
IF target_tier = 'starter':
    IF total_data_mb > 25000 THEN ops_score -= 5   // exceeds Starter 25 GiB limit
    ELSE IF total_data_mb > 20000 THEN ops_score -= 2
    ops_score -= 2  // Starter has no CDC support

ops_score = MAX(ops_score, 0)
```

## Final Score

```
SET overall_score = schema_score + code_score + query_score + data_score + ops_score
```

Every deduction must be traceable to a specific condition. No hidden penalties.

## Score Interpretation

| Score | Rating | Meaning |
|---|---|---|
| 90–100 | Excellent | Minimal PL/SQL, clean schema. Near drop-in migration. |
| 75–89 | Good | Some procedural code and query rewrites needed. Straightforward. |
| 50–74 | Moderate | Significant PL/SQL rewrite required. Feasible with AI assistance. |
| 25–49 | Challenging | Heavy PL/SQL, packages, autonomous transactions. Major application refactoring. |
| 0–24 | Difficult | Deeply embedded Oracle features. Requires architectural redesign. |
