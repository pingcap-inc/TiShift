# BYOC Deployment

How to run TiShift end-to-end inside a customer's GCP project with TiDB Cloud
BYOC as the target. This is the canonical production deployment.

See also: [references/byoc-runbook.md](../references/byoc-runbook.md) for the
full architectural runbook.

## Quick deploy: Cloud Run

The simplest production deployment runs TiShift as a Cloud Run service in
the customer's GCP project, with a Workload Identity-bound service account.

### Build the container

```bash
cd firestore-to-tidb
gcloud builds submit --tag gcr.io/$PROJECT/tishift-firestore:0.1.0 .
```

The included `Dockerfile`:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .
COPY tishift_firestore ./tishift_firestore
ENTRYPOINT ["tishift-firestore"]
```

### Deploy

```bash
gcloud run deploy tishift-firestore \
    --image=gcr.io/$PROJECT/tishift-firestore:0.1.0 \
    --service-account=$SA \
    --project=$PROJECT \
    --region=us-central1 \
    --vpc-connector=$VPC_CONNECTOR \
    --vpc-egress=all-traffic \
    --no-allow-unauthenticated \
    --cpu=4 --memory=16Gi --timeout=3600 \
    --set-env-vars="TISHIFT_CONFIG_GCS=gs://tishift-config/tishift-firestore.yaml" \
    --set-env-vars="TISHIFT_TARGET_PASSWORD_SECRET=projects/$PROJECT/secrets/tidb-pass/versions/latest"
```

Note `--vpc-connector` and `--vpc-egress=all-traffic` — keeps all gRPC
traffic to Firestore and BigQuery on the customer's VPC and on Google's
backbone (via Private Google Access).

### Invoke

```bash
gcloud run services proxy tishift-firestore --region=us-central1 &
# Now tishift-firestore is reachable on localhost:8080 via the proxy
# Use the included `tishift-firestore-remote` CLI wrapper to invoke it
```

For one-shot invocations, prefer `gcloud run jobs` over `gcloud run deploy`:

```bash
gcloud run jobs create tishift-scan-once \
    --image=gcr.io/$PROJECT/tishift-firestore:0.1.0 \
    --args="scan,--config,gs://tishift-config/tishift-firestore.yaml" \
    --service-account=$SA \
    --region=us-central1 \
    --vpc-connector=$VPC_CONNECTOR

gcloud run jobs execute tishift-scan-once
```

## Alternative: GCE VM

For long-running loads (multi-day Dataflow polling), a GCE VM is more
appropriate than Cloud Run (which has a 60-minute max execution per
request). Recommended sizing:

| Phase | Machine type | Disk | Network |
|---|---|---|---|
| scan / convert / check | `e2-standard-2` (2 vCPU, 8 GB) | 50 GB SSD | default |
| load (orchestrator) | `e2-standard-4` (4 vCPU, 16 GB) | 100 GB SSD | default |
| Lightning runner | `n2-standard-32` (32 vCPU, 128 GB) | 2 TB local SSD | default |

The Lightning runner stays alive only during the load phase; spin it up,
run, and tear down.

## Network architecture

The full BYOC topology:

```
   ┌──── Customer GCP project ────────────────────────────────────────┐
   │                                                                  │
   │   ┌────────────────────┐         ┌────────────────────┐          │
   │   │  Cloud Firestore   │         │  TiDB Cloud BYOC   │          │
   │   │  (source DB)       │         │  (managed VPC)     │          │
   │   └────────┬───────────┘         └──────────▲─────────┘          │
   │            │                                │                    │
   │            │ gRPC via Private Google Access │ MySQL on port 4000 │
   │            │                                │ via VPC peering    │
   │            ▼                                │                    │
   │   ┌─────────────────────────────────────────┴───────────────┐    │
   │   │  Workload VPC (customer's)                              │    │
   │   │                                                         │    │
   │   │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐      │    │
   │   │  │  TiShift    │  │  Dataflow   │  │  Lightning  │      │    │
   │   │  │  Cloud Run  │  │  workers    │  │  GCE VM     │      │    │
   │   │  └─────────────┘  └─────────────┘  └─────────────┘      │    │
   │   │         │                │                │             │    │
   │   │         └────────────────┼────────────────┘             │    │
   │   │                          ▼                              │    │
   │   │                  ┌───────────────┐                      │    │
   │   │                  │  GCS staging  │                      │    │
   │   │                  │  bucket       │                      │    │
   │   │                  └───────────────┘                      │    │
   │   └─────────────────────────────────────────────────────────┘    │
   │                                                                  │
   └──────────────────────────────────────────────────────────────────┘
```

All arrows are intra-project. No public-internet traffic. No cross-cloud
egress.

## IAM: minimal grants

| SA | Role | On |
|---|---|---|
| `tishift-firestore@` | `roles/datastore.viewer` | source project |
| `tishift-firestore@` | `roles/datastore.indexAdmin` | source project |
| `tishift-firestore@` | `roles/storage.objectAdmin` | staging bucket |
| `tishift-firestore@` | `roles/bigquery.dataViewer` | `firestore_export` dataset |
| `tishift-firestore@` | `roles/dataflow.developer` | source project |
| `dataflow-worker@` | `roles/dataflow.worker` | source project |
| `dataflow-worker@` | `roles/storage.objectAdmin` | staging bucket |
| `dataflow-worker@` | `roles/datastore.viewer` | source project |

Do **not** grant `roles/datastore.user` or any write role on Firestore.
TiShift never writes the source.

## Verifying the deploy

After deploy:

```bash
gcloud run services proxy tishift-firestore --region=us-central1 &
curl -s http://localhost:8080/preflight | jq
```

Expected response:

```json
{
  "firestore_reachable": true,
  "firestore_databases_listed": ["(default)"],
  "gcs_bucket_writable": true,
  "tidb_reachable": true,
  "tidb_version": "v8.1.0",
  "dataflow_api_enabled": true,
  "bigquery_api_enabled": true,
  "private_google_access": true,
  "verdict": "READY"
}
```

A `READY` verdict is the prerequisite for any scan / convert / load run.

## Common pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| Firestore reads from Cloud Run land on public IP | Private Google Access disabled on subnet | Enable on the runtime subnet |
| TiDB connect refused | TiDB BYOC VPC not peered with workload VPC | Set up peering or move TiShift into TiDB BYOC's VPC |
| Dataflow workers can't read Firestore | `dataflow-worker@` SA missing `datastore.viewer` | Add the binding on the source project |
| Dataflow workers can't write GCS | `dataflow-worker@` SA missing `storage.objectAdmin` on the bucket | Bind it |
| Lightning ingest hangs | Lightning VM in different region from TiDB BYOC | Move the Lightning VM to the same region |
| Cross-region egress charges | Source region ≠ staging region ≠ target region | Align all three before running |
