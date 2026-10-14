# AI-gitops-pipeline — CI Pipeline for the FoodRush Delay Predictor
 
A GitHub Actions pipeline that trains an ML model, blocks bad models with an
accuracy gate, builds a container image, pushes it to Amazon ECR, and updates the
Kubernetes manifest with the new image tag — with no long-lived AWS keys.
 
Part of a 12-week AI-in-DevOps learning project (Week 4). Sibling repo:
`ai-devops-platform` (Bedrock log analyzer, MLflow tracking, FastAPI serving,
EKS Terraform).
 
## Status
 
| Stage | State |
|-------|-------|
| CI: train, accuracy gate, build, push, manifest update | Working (verified end to end) |
| CD: ArgoCD auto-sync to EKS | Next (Week 5) |
 
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
(Week 5) ArgoCD watches k8s/ and deploys the new tag to EKS
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
 
## Repository Structure
 
```
AI-gitops-pipeline/
├── .github/workflows/ml-pipeline.yml   # the pipeline
├── app/                                # FastAPI inference service
│   ├── main.py                         #   /predict, /health, /ready, /model-info
│   ├── model.py                        #   loads model.pkl (S3 / fallback if absent)
│   └── requirements.txt
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
 
## Issues Hit and How They Were Fixed
 
| Issue | Cause | Fix |
|-------|-------|-----|
| Workflow never triggered | `paths` filter used the repo name as a folder; paths are relative to repo root | Listed real paths: `app/**`, `scripts/**`, `Dockerfile`, workflow file |
| `Not authorized to perform sts:AssumeRoleWithWebIdentity` (wrong role name) | Workflow pointed at a role that did not exist; AWS returns the same error as a trust mismatch | Corrected the role ARN |
| Same error, correct role | GitHub's `sub` claim embeds numeric owner and repo IDs, so the trust pattern never matched | Printed the real claims from the runner, then pinned the IDs in the trust policy (also safer against repo-name reuse) |
| Bot `git push` rejected | `main` moved while the job ran (or a re-run replayed an old commit) | `git pull --rebase origin main` before the bot pushes |
| Workflow steps deleted by a `sed` edit | Range delete ran to end of file when no blank line followed | Restored the file from the last good commit; bounded the range using line numbers |
 
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
 
## Next: Week 5
 
ArgoCD on EKS watches `k8s/` in this repo and deploys each new image tag
automatically, completing the push-to-production GitOps loop.
