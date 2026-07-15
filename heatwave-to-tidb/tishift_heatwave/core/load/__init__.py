"""Load phase — intentionally not automated.

Data loading is deliberately excluded from this tool: it is a high-stakes
step the user must perform independently. The manual path is documented in
docs/load-guide.md and references/load-strategies.md — Dumpling export over
the MySQL protocol (directly against a public TLS endpoint, or through an
SSH tunnel / jump host for VCN-private DB Systems), then tier-appropriate
import: ticloud serverless import (Starter), direct load (Essential),
TiDB Lightning (Dedicated).
"""
