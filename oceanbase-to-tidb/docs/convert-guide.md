# Convert Guide — OceanBase to TiDB

## MySQL Mode (near-trivial)

1. Strip OB extensions from DDL: TABLEGROUP, PRIMARY_ZONE, LOCALITY, REPLICA_NUM, resource clauses, OB hints
2. Types pass through (near-1:1)
3. Verify ENGINE=InnoDB, CHARSET=utf8mb4

## Oracle Mode (full conversion)

1. Strip OB extensions (same as MySQL mode)
2. Type mapping: NUMBER→DECIMAL, VARCHAR2→VARCHAR, DATE→DATETIME
3. Function mapping: NVL→COALESCE, DECODE→CASE, TO_DATE→STR_TO_DATE
4. Query rewriting: CONNECT BY→WITH RECURSIVE, ROWNUM→LIMIT, (+)→ANSI JOIN
5. PL/SQL→application code stubs (AI-assisted)
