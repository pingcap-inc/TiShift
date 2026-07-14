"""Convert phase — DDL transformation and code-stub generation.

Comment-preserving cleanup of HeatWave-only syntax (SECONDARY_ENGINE,
SECONDARY_LOAD, CLUSTERING BY — kept as TISHIFT-REMOVED comments), with
`ALTER TABLE ... SET TIFLASH REPLICA n` inlined after each RAPID table's
CREATE TABLE. Planned: collation remaps, spatial→JSON, and application-code
stubs for stored procedures, triggers, events, and JavaScript stored programs.
"""
