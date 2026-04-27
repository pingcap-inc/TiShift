# OceanBase to TiDB Migration

AI-assisted migration toolkit for moving OceanBase databases to [TiDB Cloud](https://www.pingcap.com/tidb-cloud/).

## What It Does

TiShift OB scans your OceanBase cluster, detects the compatibility mode (MySQL or Oracle), assesses TiDB compatibility, strips OceanBase-specific extensions (TABLEGROUP, LOCALITY, PRIMARY_ZONE), converts schema, loads data, and validates results.

**Dual-mode support**: MySQL-mode is near-trivial (types are 1:1, same protocol). Oracle-mode adds full dialect conversion.

## Getting Started

### Prerequisites

- MySQL client (connects to both OceanBase and TiDB)
- Network access to OceanBase (default port: **2881** via OBProxy)
- A TiDB Cloud cluster (a free [Starter](https://tidbcloud.com/) tier works)

### Run the skill

```
/oceanbase-to-tidb
```

See [SKILL.md](SKILL.md) for the full guide.

## Migration Phases

1. **Connect & Detect Mode** — verify connectivity, detect MySQL or Oracle mode
2. **Scan** — schema inventory + OceanBase extension detection (TABLEGROUP, LOCALITY, PRIMARY_ZONE)
3. **Assess & Score** — mode-aware scoring (MySQL: 25/15/20/20/20, Oracle: 20/30/20/20/10)
4. **Convert** — strip OB extensions, convert types (MySQL mode: near-1:1, Oracle mode: full mapping)
5. **Load** — mysqldump or OBDUMPER CSV → TiDB Lightning / LOAD DATA
6. **Validate** — row counts, structure, collation verification

## Optional: CLI Toolkit

```bash
cd oceanbase-to-tidb
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'

cp config/tishift-ob.example.yaml tishift-ob.yaml
tishift-ob scan --config tishift-ob.yaml --format cli --format json
```

## Reference Documentation

- [Compatibility Rules](references/compatibility-rules.md) — 7 blockers, 12 warnings
- [Scoring Engine](references/scoring.md) — dual-mode weights
- [Type Mapping (MySQL)](references/type-mapping.md) — near-1:1
- [Type Mapping (Oracle)](references/type-mapping-oracle.md) — full Oracle mapping
- [Function Mapping](references/function-mapping.md)

## License

[Apache 2.0](../LICENSE)
