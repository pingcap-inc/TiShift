# BYOC Deployment Runbook

How to run TiShift end-to-end inside a customer's GCP project with TiDB Cloud
BYOC (Bring Your Own Cloud) as the target. This is the canonical deployment
for production Firestore → TiDB migrations on GCP — data stays inside the
customer's tenancy, traffic stays on Google's backbone, and IAM is the
customer's existing service-account model.

## Architecture

```
  ┌──────────────────────────── Customer GCP project ───────────────────────────┐
  │                                                                              │
  │  ┌────────────────────┐         ┌────────────────────┐                       │
  │  │  Cloud Firestore   │         │  TiDB Cloud BYOC   │                       │
  │  │  (source DB)       │         │  (target cluster)  │                       │
  │  └────────┬───────────┘         └──────────▲─────────┘                       │
  │           │ gRPC                           │ MySQL protocol                  │
  │           │ (Admin SDK / Beam IO)          │ (Lightning / PyMySQL)           │
  │           ▼                                │                                 │
  │  ┌────────────────────────────────────────┴──────────────┐                   │
  │  │  TiShift workload (Cloud Run or GCE)                  │                   │
  │  │   - scan / convert / load / check / sync              │                   │
  │  │   - Dataflow job submitter                            │                   │
  │  └─────────┬──────────────────────────────┬──────────────┘                   │
  │            │                              │                                  │
  │            ▼                              ▼                                  │
  │  ┌────────────────┐              ┌─────────────────────┐                     │
  │  │   GCS staging  │  NDJSON      │   BigQuery dataset  │                     │
  │  │   bucket       │  ─────────►  │   firestore_export  │ (for CDC)           │
  │  └────────┬───────┘              └──────────┬──────────┘                     │
  │           │ gs:// reads                     │ BQ Storage API                 │
  │           │ (from Lightning)                │ (from sync Dataflow job)       │
  │           ▼                                 ▼                                │
  │       (target)                          (target)                             │
  │                                                                              │
  └──────────────────────────────────────────────────────────────────────────────┘
```

All arrows are intra-project. No public-internet traffic. No cross-cloud
egress. Private Google Access on the VPC means even gRPC calls to Firestore
stay on Google's backbone.

## Pre-flight checklist

Before running the first `tishift-firestore scan`, confirm:

1. **Single GCP project.** Firestore source, GCS staging bucket, BigQuery
   dataset (if doing CDC), and TiDB BYOC VPC are all in the same project. If
   they must span projects, see "Cross-project setup" below.
2. **Same region.** Firestore database region matches the GCS bucket region
   and the TiDB BYOC region. Cross-region transfer incurs egress and adds
   latency.
3. **Workload Identity (recommended).** TiShift runs on Cloud Run or GKE with
   a service account bound via Workload Identity, not with a service-account
   key file mounted in the container.
4. **VPC reachability.** TiDB BYOC and the TiShift workload sit in VPCs that
   can reach each other (same VPC, peered, or via Cloud VPN). Verify with
   `mysql -h $TIDB_HOST -P 4000 -e "SELECT 1"` from the TiShift workload.
5. **Private Google Access enabled** on the subnet where TiShift runs, so
   gRPC calls to Firestore and BigQuery don't egress to the public internet.

## IAM roles required

Bind these roles to the TiShift service account. Prefer custom roles in
production; the predefined roles below are the minimal set:

| Resource | Role | Why |
|---|---|---|
| Firestore source DB | `roles/datastore.viewer` | Read documents and metadata |
| Firestore source DB | `roles/datastore.indexAdmin` (READ side) | List composite indexes |
| GCS staging bucket | `roles/storage.objectAdmin` | Write NDJSON during load; lifecycle management |
| BigQuery dataset (if sync) | `roles/bigquery.dataViewer` | Read `_raw` changelog tables |
| Dataflow | `roles/dataflow.developer` | Submit Beam jobs |
| Dataflow worker SA | `roles/dataflow.worker` | Run worker VMs (on a separate SA per Dataflow best practice) |
| Cloud Monitoring | `roles/monitoring.viewer` | Read Firestore storage-byte metrics |
| TiDB BYOC | (network only, no GCP role) | MySQL auth credentials from `tishift-firestore.yaml` |

**Do not grant** `roles/datastore.user`, `roles/datastore.owner`, or any role
with `firestore.documents.*` write permissions. TiShift never writes to the
source.

## Service account setup

```bash
# Create the TiShift service account
gcloud iam service-accounts create tishift-firestore \
    --display-name="TiShift Firestore migration" \
    --project=$PROJECT

SA=tishift-firestore@$PROJECT.iam.gserviceaccount.com

# Bind required roles
for ROLE in datastore.viewer datastore.indexAdmin \
            storage.objectAdmin bigquery.dataViewer \
            dataflow.developer monitoring.viewer ; do
    gcloud projects add-iam-policy-binding $PROJECT \
        --member="serviceAccount:$SA" \
        --role="roles/$ROLE"
done

# Workload Identity binding (if running TiShift on GKE)
gcloud iam service-accounts add-iam-policy-binding $SA \
    --role roles/iam.workloadIdentityUser \
    --member "serviceAccount:$PROJECT.svc.id.goog[tishift-ns/tishift-sa]"
```

## Networking

### Same-VPC (simplest)

If TiDB BYOC is provisioned into the same VPC the TiShift workload runs in,
no extra setup is needed. The MySQL connection works on the private IP.

### Peered VPCs

If TiDB BYOC uses a managed VPC and the customer's workload VPC is separate,
set up VPC peering:

```bash
gcloud compute networks peerings create tishift-to-tidb \
    --network=$WORKLOAD_VPC \
    --peer-network=$TIDB_VPC \
    --auto-create-routes
```

### Private Google Access

Required for gRPC calls to Firestore from inside a VPC. Enable per-subnet:

```bash
gcloud compute networks subnets update $SUBNET \
    --region=$REGION --enable-private-ip-google-access
```

This is what keeps the 7 TB of Firestore reads from traversing public NAT.

## Storage sizing

| Resource | Sizing rule of thumb |
|---|---|
| GCS staging bucket | 1.2× the Firestore source data size (NDJSON is denser than Firestore's internal protobuf, but the extension fields add overhead) |
| Dataflow worker disks | 100 GB per worker for sort space (auto-sized by Dataflow most of the time) |
| TiDB Lightning sort dir | 1.5× the largest table size — Lightning needs scratch space during physical import |
| TiDB BYOC TiKV nodes | Source data × 3 (3 replicas) × 1.3 (overhead) — for 7 TB, plan ~30 TB raw TiKV storage |

## Cost model

For a representative 7 TB Firestore source:

| Item | Estimated cost (one-time) |
|---|---|
| Firestore reads (1 read per doc, ~7B docs) | ~$4,200 at $0.06/100k |
| Dataflow workers (200 × n2-standard-4 × 36h) | ~$2,500 |
| GCS staging (temporary, 8 TB for 7 days) | ~$140 |
| BigQuery storage (CDC, 7 days of changelog) | ~$50 |
| Network egress (intra-region) | $0 |
| Network egress (cross-region — avoid) | up to $5,000 if accidentally cross-region |

Confirm the source database region with `gcloud firestore databases describe`
before provisioning. The single biggest cost mistake is staging across
regions.

## Cross-project setup (if unavoidable)

If TiDB BYOC must live in a separate GCP project from Firestore:

1. **Shared VPC** the two projects to a common host project, OR set up a Cloud
   VPN tunnel between their VPCs.
2. **Workload Identity Federation** from the TiShift workload's project to
   the Firestore source project, with the same role bindings.
3. **GCS staging bucket** lives in the Firestore project (to keep the heavy
   Dataflow → GCS path intra-project), and TiDB reads it via cross-project
   IAM grant.
4. **BigQuery dataset** lives in the project where the
   `firestore-bigquery-export` extension was installed (the Firestore
   project), and the TiShift workload reads via cross-project grant.

Expect ~+1 week of IAM and networking setup for cross-project. The
single-project path is strongly preferred.

## Verification

After setup, run:

```bash
tishift-firestore preflight --config tishift-firestore.yaml
```

This validates:

- Service account can list Firestore databases
- Service account can read at least one document from each in-scope collection
- GCS staging bucket is writable
- TiDB target is reachable on port 4000 and credentials work
- Dataflow API is enabled
- BigQuery API is enabled (if sync is configured)
- Private Google Access is enabled on the runtime subnet (warning, not error,
  if disabled — works but traverses NAT)

A clean preflight is the prerequisite for any subsequent phase.
