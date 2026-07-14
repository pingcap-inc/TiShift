# Getting Started — HeatWave to TiDB

## Prerequisites

- Network path to the HeatWave DB System (SSH tunnel via OCI Bastion, compute
  jump host in the VCN, or site-to-site VPN) — DB Systems have no public endpoint
- A source MySQL user with `SELECT` on the schemas to migrate plus read access
  to `information_schema` and `performance_schema` (for RAPID detection);
  add `REPLICATION SLAVE, REPLICATION CLIENT` if continue-replication sync is planned — see
  [sync-guide.md](sync-guide.md#migration-user-privileges) for the exact grants
- A TiDB Cloud cluster (free Starter tier works for assessment)
- Python 3.10+ for the CLI toolkit; `tiup` (Dumpling) for the load phase

## Establish the tunnel

```bash
ssh -f -N -L 3306:<db-system-private-ip>:3306 opc@<bastion-host>
# then use host: 127.0.0.1, port: 3306 in tishift-heatwave.yaml
```

## Two ways to run

**AI skill (recommended):** open the repo in an AI coding assistant and run
`/heatwave-to-tidb`. The skill walks you through every phase one command at a time.

**CLI toolkit:**

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
cp config/tishift-heatwave.example.yaml tishift-heatwave.yaml
# edit credentials, then:
tishift-heatwave scan --config tishift-heatwave.yaml --format cli --format json
```

## Phase guides

1. [Scan](scan-guide.md) — inventory schema + HeatWave feature usage
2. [Convert](convert-guide.md) — TiDB DDL, TiFlash replicas, code stubs
3. [Load](load-guide.md) — Dumpling export, tier-appropriate import
4. [Check](check-guide.md) — row counts, structure, checksums
5. [Sync](sync-guide.md) — optional continue replication via TiDB DM

See [checklist.md](checklist.md) for every compatibility rule, DDL cleanup
rule, and precheck/attention tip across all phases collected in one place.
