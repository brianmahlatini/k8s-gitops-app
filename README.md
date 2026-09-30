# k8s-gitops-app

An end-to-end container delivery pipeline: a small Python service built the way platforms expect (probes, metrics, JSON logs, graceful shutdown), packaged as a hardened non-root image, **scanned, SBOM'd and signed** in CI, deployed to a real Kubernetes cluster (kind) on every change, and released to environments through **GitOps with Argo CD** and Kustomize overlays.

```
 PR / push ──► test (ruff, pytest ≥85% cov) ─┬─► image: build → Trivy (fail on fixable HIGH/CRIT) → SBOM ─┐
                                             │                                                        │ main only
             manifests: kustomize → kubeconform → checkov ─► e2e: kind cluster, restricted PSS, smoke  │
                                                                                                       ▼
                                                        push ghcr.io …:sha-<commit>, cosign keyless sign by digest
                                                                                                       │
                                        bump-dev: commit new tag to deploy/overlays/dev ──► Argo CD auto-syncs dev
                                                                                                       │
                     promote (manual): cosign verify → PR editing deploy/overlays/prod ──► review, merge ──► Argo CD sync prod
```

## What's in the repo

| Path | Purpose |
|---|---|
| `app/` | FastAPI service: `/healthz` (liveness), `/readyz` (readiness, flips to 503 on shutdown), `/metrics` (Prometheus), request ids, JSON logs, demo `/api/items` with in-memory fake data |
| `Dockerfile` | Multi-stage build, venv copied into a slim runtime, OS patches applied, pip removed, runs as UID 10001 |
| `deploy/base` | Deployment, Service, HPA, PDB, default-deny NetworkPolicy + allow rules, ServiceAccount |
| `deploy/overlays/{dev,prod}` | Per-environment namespace (restricted Pod Security), replicas, resources, zone/host spread (prod), image tag |
| `argocd/` | AppProject scoped to this repo and two namespaces; dev auto-sync with prune + self-heal; prod manual sync |
| `.github/workflows/ci.yml` | Test, validate, build, scan, SBOM, sign, kind e2e, GitOps tag bump |
| `.github/workflows/promote.yml` | Verify signature → open prod promotion PR |

## Design decisions and trade-offs

- **Git is the deployment API.** CI never runs `kubectl apply` against a real environment. It writes the new image tag to Git and Argo CD reconciles. Every deploy is a commit, rollback is `git revert`, and drift is reverted automatically in dev.
- **Promote artifacts, don't rebuild them.** Prod runs the exact image that passed dev. The promote workflow first proves with `cosign verify` that the image was signed by *this repository's* CI on `main`, then opens a PR. The merge is the approval record.
- **Keyless signing.** Cosign uses the workflow's OIDC identity through Sigstore, so there's no signing key to store, rotate or leak.
- **Zero-downtime rollouts.** `maxUnavailable: 0` + readiness gating + a `preStop` sleep + readiness flipping to 503 on SIGTERM. Old pods stop getting traffic *before* they stop serving, which removes the 502s that commonly appear during deploys.
- **Liveness ≠ readiness.** Liveness never checks dependencies. Otherwise a database blip makes Kubernetes restart every replica at once and turns a partial outage into a full one. A startup probe gives slow boots up to 60s without loosening liveness.
- **No CPU limits, yes memory limits.** CPU requests reserve capacity; CPU limits add CFS throttling latency without protecting neighbours. Memory limits stay because memory isn't compressible. This is documented as a deliberate checkov skip.
- **Metric cardinality control.** Requests are labelled by route *template* (`/api/items/{item_id}`), never the raw path, so metrics stay bounded no matter what URLs clients send.
- **Least privilege at every layer.** Non-root UID, read-only root filesystem, all capabilities dropped, `seccompProfile: RuntimeDefault`, no service-account token mounted, namespaces enforcing the *restricted* Pod Security Standard (the kind e2e proves the pods are admitted), and default-deny networking with explicit ingress from ingress/monitoring and DNS-only egress.
- **Honest scanning gate.** CI fails on HIGH/CRITICAL vulnerabilities *that have a fix*. Failing on unfixable ones blocks every build without making anything safer.

## Run locally

```sh
make install test          # lint + unit tests
make run                   # http://localhost:8080/docs
make image                 # docker build
make manifests             # render + schema-validate both overlays
```

Deploy with Argo CD: `kubectl apply -n argocd -f argocd/`. All data is fake and no external services are called.

## License

MIT
