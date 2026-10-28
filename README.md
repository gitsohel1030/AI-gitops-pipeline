# AI-gitops-pipeline — CI/CD for the FoodRush Delay Predictor
 
A GitHub Actions pipeline that trains an ML model, blocks bad models with an
accuracy gate, builds a container image, pushes it to Amazon ECR, and updates the
Kubernetes manifest with the new image tag — with no long-lived AWS keys.
ArgoCD then deploys that tag to an EKS cluster straight from Git.
 
Part of a 12-week AI-in-DevOps learning project (Weeks 4 and 5). Sibling repo:
`ai-devops-platform` (Bedrock log analyzer, MLflow tracking, FastAPI serving,
EKS Terraform).
 
## Status
 
| Stage | State |
|-------|-------|
| CI: train, accuracy gate, build, push, manifest update | Working (verified end to end) |
| CD: ArgoCD auto-sync to EKS | Working (Application Synced and Healthy on EKS) |
| Model monitoring (Prometheus + Grafana) | Next (Week 6) |
 
## Pipeline Flow
 
```
git push (app/, scripts/, Dockerfile or the workflow file)
        |
        v
GitHub Actions runner (ubuntu-latest)
        |
        +-- 1. Train model (scikit-learn RandomForest)
        +-- 2. ACCURACY GATE: exit 1 if accuracy < 0.90  --> pipeline stops
        +-- 3. Assume AWS role via OIDC (short-lived token, no stored keys)
        +-- 4. Build Docker image (model.pkl baked in)
        +-- 5. Push to ECR tagged with commit SHA (and latest)
        +-- 6. Update k8s/deployment.yaml with the new SHA tag
        +-- 7. Bot commits the manifest back to main ([skip ci])
        |
        v
ArgoCD (on EKS) polls k8s/ on main
        |
        +-- 8. Detects the new image tag
        +-- 9. Syncs the Deployment in namespace ml-models (rolling update)
```
 
## Why Each Design Choice
 
| Choice | Reason |
|--------|--------|
| Accuracy gate | Model quality is a build requirement, like tests blocking a bad deploy |
| Image tagged with commit SHA | Any running image can be traced to the exact commit that built it |
| OIDC instead of access keys | GitHub issues a short-lived token per run; nothing to leak or rotate |
| Model baked into the image | Fast startup, no S3 call at boot, immutable artifact per commit |
| `[skip ci]` on the bot commit | Stops the manifest update from re-triggering the pipeline |
| `paths` filter | Pipeline runs only when model/app files change, not on README edits |
| ArgoCD automated sync (prune + selfHeal) | Git is the single source of truth; manual cluster edits are reverted |
| Manifests in the same repo as CI | Simplest for one service; the bot needs no cross-repo token |
 
## Repository Structure
 
```
AI-gitops-pipeline/
├── .github/workflows/ml-pipeline.yml   # the CI pipeline
├── app/                                # FastAPI inference service
│   ├── main.py                         #   /predict, /health, /ready, /model-info
│   ├── model.py                        #   loads model.pkl (S3 / fallback if absent)
│   └── requirements.txt
├── argocd/
│   └── application.yaml                # ArgoCD Application (applied once to bootstrap)
├── scripts/
│   ├── train_and_validate.py           # trains model + accuracy gate
│   └── requirements.txt
├── k8s/                                # manifests (updated by the pipeline)
│   ├── namespace.yaml
│   ├── deployment.yaml
│   └── service.yaml
├── iam/                                # reference IAM policies for the CI role
├── Dockerfile
└── .gitignore
```
 
## GitOps Deployment (ArgoCD)
 
`argocd/application.yaml` tells ArgoCD what to watch and where to deploy it. It is
the only manual `kubectl apply` in the workflow; after that, Git drives everything.
 
```bash
kubectl apply -f argocd/application.yaml
kubectl get applications -n argocd
```
 
| Field | Value | Meaning |
|-------|-------|---------|
| `source.repoURL` / `targetRevision` | this repo, `main` | What ArgoCD watches |
| `source.path` | `k8s` | Only this folder is deployed |
| `destination.namespace` | `ml-models` | Where the model service runs |
| `syncPolicy.automated.prune` | true | Resources deleted from Git are deleted from the cluster |
| `syncPolicy.automated.selfHeal` | true | Manual cluster edits are reverted to match Git |
| finalizer | `resources-finalizer.argocd.argoproj.io` | Deleting the Application also deletes what it deployed |
 
ArgoCD checks Git about every 3 minutes. To skip the wait after a pipeline run:
 
```bash
kubectl annotate application delay-predictor -n argocd argocd.argoproj.io/refresh=hard --overwrite
```
 
## Results
 
| Metric | Value |
|--------|-------|
| Accuracy | 0.9400 |
| F1 score | 0.9268 |
| Minimum accuracy to ship | 0.90 |
| Model | RandomForest, 100 trees, max depth 10 |
 
The model predicts whether a food delivery order will be delayed, using distance,
item count, order hour, weather, restaurant rating and day of week. Training data
is synthetic (2,000 samples, fixed seed), generated to mimic FoodRush orders.
 
## AWS Setup
 
- ECR repository: `foodrush-delay-predictor` (scan on push enabled)
- OIDC identity provider: `token.actions.githubusercontent.com`
- IAM role: `github-actions-ai-devops-platform`, allowed to push to ECR and
  read/write the MLflow artifact bucket
- Trust policy condition on the `sub` claim, in this format:
 
```
repo:<owner>@<owner-id>/<repo>@<repo-id>:*
```
 
- EKS cluster `ai-platform-cluster` is provisioned with Terraform in the
  `ai-devops-platform` repo (`eks-cluster/`), with ArgoCD, Prometheus and Loki. It
  is created for working sessions and destroyed afterwards to control cost.
 
Reference policies are in `iam/`. Replace `<ACCOUNT_ID>` with your own.
 
## Run the Training Step Locally
 
```bash
python3.10 -m venv venv
source venv/bin/activate
pip install -r scripts/requirements.txt
python3 scripts/train_and_validate.py
```
 
Expected output: accuracy 0.94, F1 0.9268, "PASSED", and `model.pkl` written.
 
## Verify a Pipeline Run
 
```bash
git pull --rebase
grep "image:" k8s/deployment.yaml
aws ecr describe-images --repository-name foodrush-delay-predictor \
  --region ap-south-1 --query 'imageDetails[*].imageTags' --output json
```
 
The tag in `deployment.yaml` should appear in the ECR tag list.
 
## Verify the Deployment (cluster running)
 
```bash
kubectl get applications -n argocd
kubectl get pods -n ml-models
kubectl get deployment delay-predictor -n ml-models \
  -o jsonpath='{.spec.template.spec.containers[0].image}'; echo
```
 
The application should be `Synced` and `Healthy`, two pods `1/1 Running`, and the
image tag should match the one in `k8s/deployment.yaml`.
 
## Issues Hit and How They Were Fixed
 
| Issue | Cause | Fix |
|-------|-------|-----|
| Workflow never triggered | `paths` filter used the repo name as a folder; paths are relative to repo root | Listed real paths: `app/**`, `scripts/**`, `Dockerfile`, workflow file |
| `Not authorized to perform sts:AssumeRoleWithWebIdentity` (wrong role name) | Workflow pointed at a role that did not exist; AWS returns the same error as a trust mismatch | Corrected the role ARN |
| Same error, correct role | GitHub's `sub` claim embeds numeric owner and repo IDs, so the trust pattern never matched | Printed the real claims from the runner, then pinned the IDs in the trust policy (also safer against repo-name reuse) |
| Bot `git push` rejected | `main` moved while the job ran (or a re-run replayed an old commit) | `git pull --rebase origin main` before the bot pushes |
| Workflow steps deleted by a `sed` edit | Range delete ran to end of file when no blank line followed | Restored the file from the last good commit; bounded the range using line numbers |
| ArgoCD app `Synced` but `Degraded` | Synced only means the cluster matches Git; health is separate, and the pods were failing to start | Read pod events (`kubectl get events -n ml-models`) instead of the ArgoCD status |
| Pods in `ErrImagePull` ("not found") | The manifest referenced an image tag that ECR did not have | Rebuilt the image with the workflow's manual trigger, then forced an ArgoCD refresh |
 
## Known Limitations
 
- CI training does not log to MLflow (the tracking server runs on a private EC2 the
  runner cannot reach). Experiment lineage lives in the Week 2 MLflow setup.
- Training data is synthetic, so accuracy figures demonstrate the pipeline, not
  real-world model quality.
- The CI role grants ECR push on all repositories; scope it to one repository ARN
  for production use.
- `app/` also exists in the `ai-devops-platform` repo (`model-serving`). This repo
  is the source of truth going forward.
- ECR keeps every image; a lifecycle policy should expire old SHA tags.
- ArgoCD polls Git roughly every 3 minutes; a webhook would make deploys near-instant.
- During demos the ArgoCD UI was exposed through a public LoadBalancer, removed with
  the cluster. Production would use an internal ingress with SSO.
- The model service is not monitored yet (no metrics endpoint, dashboard or alerts).
 
## Week 6 — Model Monitoring (Prometheus + Grafana)

Verified on EKS 1.35 (AL2023 nodes) on 2026-10-28; cluster destroyed afterwards.

### What was added
- `/metrics` endpoint (`prometheus-client`): prediction counter by outcome, inference
  latency histogram, confidence histogram, error counter. Covered by unit tests (`tests/`).
- Named Service port + Service label, `ServiceMonitor` (`release: prometheus`).
- `PrometheusRule` with 4 alerts: target down, p95 latency > 100 ms, prediction errors,
  average confidence < 0.7 (simple drift signal).
- Grafana dashboard as code (ConfigMap, picked up by the Grafana sidecar), deployed by ArgoCD.

### Verified results
| Check | Result |
|---|---|
| ArgoCD application | Synced / Healthy |
| `/predict` on cluster | DELAYED, confidence 0.9989 |
| Prometheus targets | 2/2 pods `up` |
| Alert rules loaded | 4/4 |
| Dashboard | Populated with synthetic load (~2 req/s through one port-forward) |
| GitOps rollout | Commit `000f847` (MODEL_VERSION v2 → v3) → ArgoCD sync → new pods → API reports `v3`; image unchanged |

### Supply-chain hardening
- CI builds with `--provenance=false --sbom=false` so ECR can scan the image
  (attestations made the tag an OCI index, which ECR basic scanning rejects).
- ECR basic scan-on-push (OS packages only). Latest image: 0 CRITICAL, 3 HIGH, 9 MEDIUM, 3 LOW.
- Accepted risk: the 3 HIGH findings (CVE-2026-19499, CVE-2026-5435 in glibc; CVE-2026-85091
  in zlib) come from the Debian 13 base image. No fixed package was available at scan time
  (2026-10-28). They are rechecked on every build.

### Known limitations
- `/model-info` still hardcodes accuracy/F1.
- Load was generated through a single port-forward, so it is not a load-balanced load test.
- The data is synthetic.
