# Check Guide

**Status: not implemented yet.** `tishift-heatwave check` currently prints a
pointer to this guide and exits non-zero (2) — see `_not_implemented` in
`tishift_heatwave/cli.py`. Run the checks below manually until the command
is automated.

Once implemented, `tishift-heatwave check` will validate the migrated data.

Checks, in order:

1. **Row counts** — `SELECT COUNT(*)` per table on both sides
2. **Column structure** — name/type/nullability diff from `information_schema.COLUMNS`;
   deliberate conversions (collation remaps, spatial→JSON) are whitelisted from
   the scan report so only unexpected drift is reported
3. **Checksums** (`--checksum`) — `BIT_XOR(CRC32(CONCAT_WS('#', ...)))` over
   matching PK ranges for tables with a numeric primary key
4. **TiFlash replicas** — every table from `tiflash-replicas.sql` reports
   `AVAILABLE = 1` in `information_schema.tiflash_replica`

Once automated, the exit code will be non-zero when any check fails, so the
command can gate a cutover pipeline.
