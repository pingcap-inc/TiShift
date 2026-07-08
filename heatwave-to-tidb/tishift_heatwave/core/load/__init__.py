"""Load phase — data transfer strategies.

Export uses Dumpling over the MySQL protocol (through an SSH tunnel or jump
host, since HeatWave DB Systems are VCN-private). Import depends on the
target tier: ticloud serverless import (Starter), direct load (Essential),
TiDB Lightning (Dedicated). MySQL Shell dumpSchemas to Object Storage is
documented as an alternative export path in references/load-strategies.md.
"""
