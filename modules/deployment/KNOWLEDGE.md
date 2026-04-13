# Module: Deployment — Production Infrastructure for FastAPI

> The LLM generates: single-stage Dockerfile, `kubectl apply`, no probes, no resource limits.
> The staff engineer knows: multi-stage non-root builds, 3-level probes, zero-downtime rolling updates, HPA tuning, PDB, k6 load gates, CI/CD with image scanning.

---

## 1. Dockerfile SOTA — Multi-Stage, Non-Root, Layer Cache

### WHY
A single-stage `FROM python:3.12` image is 1.1GB, runs as root, includes compilers/headers/pip cache, and rebuilds everything on any code change. In production: every MB is attack surface, every root process is a privilege escalation vector, and every minute waiting for image pull is downtime. Multi-stage builds give you a 150-200MB image with only what the runtime needs.

### HOW
```dockerfile
# --- Build stage: install deps with build tools ---
FROM python:3.12-slim AS builder

WORKDIR /build
# Copy ONLY requirements first — layer cache survives code changes
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# --- Runtime stage: minimal image ---
FROM python:3.12-slim

# Non-root user (UID 10001 avoids conflicts with system users)
RUN groupadd -r app && useradd -r -g app -d /app -s /sbin/nologin -u 10001 app

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local
# Copy application code LAST (changes most frequently)
COPY . .

RUN chown -R app:app /app
USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import httpx; httpx.get('http://localhost:8000/healthz').raise_for_status()"]

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

### GOTCHA
`COPY requirements.txt .` MUST come before `COPY . .` — Docker caches layers top-down. If requirements haven't changed, `pip install` is skipped entirely. Put this in the wrong order and every code change triggers a full reinstall. Also: `--no-cache-dir` on pip saves 100-200MB in the builder layer and prevents stale wheel reuse.

---

## 2. Docker Security — Secrets, Pinning, Scanning

### WHY
`ARG JWT_SECRET=changeme` bakes the secret into the image layer history — anyone with `docker history` can extract it. Image tags like `python:3.12-slim` are mutable — a compromised upstream tag silently replaces your base. Unscanned images ship known CVEs into production.

### HOW
```dockerfile
# NEVER: ARG DB_PASSWORD=secret (baked into layer history)
# NEVER: ENV API_KEY=sk-xxx (visible in image inspect)

# Use BuildKit secrets for build-time secrets (e.g., private PyPI):
RUN --mount=type=secret,id=pip_conf,target=/etc/pip.conf \
    pip install --no-cache-dir -r requirements.txt

# Pin base images with SHA256 digest (immutable):
FROM python:3.12-slim@sha256:abc123... AS builder

# Pin ALL dependency versions:
# requirements.txt (pip-compile or pip freeze)
fastapi==0.115.6
uvicorn[standard]==0.34.0
pydantic==2.10.3
```

### GOTCHA
`docker build --secret id=pip_conf,src=./pip.conf` passes the secret at build time without baking it into layers. But if you `RUN echo $SECRET > /tmp/debug`, the secret is in the layer even though the ARG isn't. Never echo/cat/print secrets during build. Also: always run `trivy image myapp:latest --severity CRITICAL,HIGH` in CI before pushing to registry.

---

## 3. Kubernetes Deployment — Zero-Downtime Rolling Updates

### WHY
Default `kubectl apply` with no strategy kills old pods before new ones are ready — users see 502/503 during every deploy. `maxUnavailable: 0` + `maxSurge: 1` ensures the new pod is READY before an old pod is terminated. Combined with `terminationGracePeriodSeconds` and a `preStop` hook, in-flight requests complete gracefully.

### HOW
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myapi
spec:
  replicas: 3
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1          # Create 1 extra pod during update
      maxUnavailable: 0    # NEVER have fewer than desired replicas
  template:
    spec:
      terminationGracePeriodSeconds: 45  # preStop(10s) + app drain(30s) + buffer(5s)
      containers:
      - name: myapi
        lifecycle:
          preStop:
            exec:
              command: ["sh", "-c", "sleep 10"]
              # Wait 10s for endpoints to deregister from Service/Ingress
              # Without this, traffic hits a pod that's already shutting down
```

### GOTCHA
`preStop` sleep MUST be shorter than `terminationGracePeriodSeconds` — otherwise Kubernetes SIGKILL's the container before the sleep finishes. The 10s sleep covers the typical time for kube-proxy / cloud load balancers to remove the pod from their endpoint lists. Without it, you get 502s for 5-15 seconds after every deploy. Cloud LBs (ALB, NLB) can take up to 30s to deregister targets.

---

## 4. Kubernetes 3-Level Probes — Liveness, Readiness, Startup

### WHY
A single health check (`/health`) that checks the database is a recipe for cascading failure: if the DB goes down, Kubernetes restarts ALL pods (liveness fails) — but restarting pods doesn't fix the DB, and now you have zero capacity when the DB recovers. Three separate probes solve three different failure modes with three different remediations.

### HOW
```yaml
containers:
- name: myapi
  livenessProbe:
    httpGet:
      path: /healthz       # Process alive? NEVER check deps
      port: 8000
    initialDelaySeconds: 0
    periodSeconds: 15
    failureThreshold: 3    # 3 failures = restart (45s tolerance)

  readinessProbe:
    httpGet:
      path: /readyz         # Can accept traffic? Check ALL deps
      port: 8000
    initialDelaySeconds: 5
    periodSeconds: 10
    failureThreshold: 2    # 2 failures = stop routing (20s)

  startupProbe:
    httpGet:
      path: /startupz      # Init complete? (models loading, migrations, warmup)
      port: 8000
    initialDelaySeconds: 0
    periodSeconds: 5
    failureThreshold: 30   # 30 * 5s = 150s max startup time
```

### GOTCHA
`startupProbe` disables liveness/readiness until it succeeds — this prevents Kubernetes from killing slow-starting containers (ML model loading, DB migrations). Once startup passes, it never runs again. Set `failureThreshold * periodSeconds` to your WORST-CASE startup time. If your app takes 60s to start, `failureThreshold: 12` with `periodSeconds: 5` gives you exactly that.

---

## 5. HPA — CPU Target 70%, Scale-Up/Down Policies

### WHY
Manual replica management means either over-provisioning (wasting money) or under-provisioning (dropped requests). HPA scales based on actual load. CPU target 70% (not 80%) leaves headroom for request spikes — by the time HPA sees 80% and provisions a new pod (30-60s), you've already hit 100% and dropped requests. Scale-down stabilization prevents flapping: a traffic dip shouldn't immediately kill pods that cost 60s to recreate.

### HOW
```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: myapi-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: myapi
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70   # Scale up when avg CPU > 70%
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80   # Memory is a secondary signal
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 60    # Wait 60s before scaling up again
      policies:
      - type: Pods
        value: 2                        # Add max 2 pods per scale event
        periodSeconds: 60
    scaleDown:
      stabilizationWindowSeconds: 300   # Wait 5min before scaling down
      policies:
      - type: Pods
        value: 1                        # Remove max 1 pod per scale event
        periodSeconds: 120
```

### GOTCHA
HPA uses `requests` (not `limits`) for CPU percentage calculation. If you set `requests: 100m` and `limits: 500m`, the pod can burst to 500m but HPA thinks it's at 100% when the pod uses 100m. Set requests close to actual baseline usage. Also: `minReplicas: 2` is CRITICAL — with `minReplicas: 1`, a single pod failure means zero capacity until HPA scales up.

---

## 6. PDB — Pod Disruption Budget During Node Drain

### WHY
`kubectl drain` evicts ALL pods from a node during upgrades/maintenance. Without PDB, Kubernetes can evict all 3 replicas of your API simultaneously — complete outage. PDB tells Kubernetes "you MUST keep at least N pods running during voluntary disruptions." Note: PDB only applies to voluntary disruptions (drain, upgrades), NOT to node crashes.

### HOW
```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: myapi-pdb
spec:
  minAvailable: 1    # At least 1 pod must remain during disruptions
  selector:
    matchLabels:
      app: myapi
```

### GOTCHA
NEVER set `minAvailable` equal to your replica count (e.g., `minAvailable: 3` with 3 replicas) — this blocks ALL voluntary evictions, making `kubectl drain` hang forever and node upgrades impossible. `maxUnavailable: 1` is the safe alternative — it means "at most 1 pod can be disrupted at a time." For 3 replicas, `minAvailable: 2` and `maxUnavailable: 1` are equivalent. Use percentages (`minAvailable: "50%"`) for deployments that scale dynamically.

---

## 7. Resource Limits — Requests vs Limits, OOMKilled

### WHY
Without resource `requests`, the Kubernetes scheduler places pods randomly — a pod might land on a node with 50MB free and get OOMKilled immediately. Without `limits`, a single pod can consume the entire node's memory, killing all other pods (noisy neighbor). The difference matters: `requests` is what the scheduler RESERVES, `limits` is the MAXIMUM the kernel allows.

### HOW
```yaml
containers:
- name: myapi
  resources:
    requests:
      cpu: "200m"       # Scheduler reserves 0.2 CPU cores
      memory: "256Mi"   # Scheduler reserves 256MB RAM
    limits:
      cpu: "500m"       # Max 0.5 CPU cores (throttled beyond this, NOT killed)
      memory: "512Mi"   # Max 512MB RAM (OOMKilled beyond this)
```

### GOTCHA
CPU limits THROTTLE (pod gets less CPU time). Memory limits KILL (pod gets OOMKilled and restarted). This asymmetry is why many teams set CPU limits high or omit them (let pods burst), but ALWAYS set memory limits — an unbound memory leak will consume the entire node. Set requests based on steady-state p50 usage, limits based on p99 + 50% headroom. Run `kubectl top pods` for actual usage data.

---

## 8. Zero-Downtime Deploy — The Full Sequence

### WHY
Zero-downtime deploys require 4 things working together: (1) readiness probe to gate traffic, (2) rolling update strategy to maintain capacity, (3) preStop hook to drain connections, (4) graceful shutdown in the application (SIGTERM handling). Missing ANY one of these causes brief 502/503 errors during deploys that appear intermittent and are hard to reproduce.

### HOW
```
Deploy sequence for zero-downtime:

1. New pod starts (image pull + init containers)
2. startupProbe runs until app is ready (prevents premature liveness check)
3. readinessProbe passes → pod added to Service endpoints → LB starts routing
4. Old pod receives SIGTERM:
   a. preStop hook runs: sleep 10  (LB deregistration propagation)
   b. After preStop: SIGTERM delivered to app process
   c. App stops accepting NEW connections
   d. App finishes in-flight requests (graceful shutdown)
   e. App exits cleanly
5. terminationGracePeriodSeconds timer expires → SIGKILL if still running

Timeline:
  0s   → preStop starts (sleep 10)
  10s  → SIGTERM delivered to app
  10-40s → App drains in-flight requests
  45s  → SIGKILL if app hasn't exited (terminationGracePeriodSeconds: 45)
```

Uvicorn handles SIGTERM natively — it stops accepting connections and waits for in-flight requests:
```bash
# In CMD / entrypoint:
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4 --timeout-graceful-shutdown 30
```

### GOTCHA
`--timeout-graceful-shutdown 30` tells Uvicorn to wait up to 30 seconds for in-flight requests after SIGTERM. Without it, Uvicorn's default timeout is 0 — it kills connections immediately. The sum `preStop(10) + graceful_shutdown(30) + buffer(5) = 45` MUST be `<= terminationGracePeriodSeconds`. If `terminationGracePeriodSeconds` is too short, Kubernetes SIGKILL's the container mid-drain.

---

## 9. k6 Load Testing — Stages, Thresholds, Per-Endpoint Checks

### WHY
"It works on my laptop" means nothing if it dies at 100 concurrent users. k6 provides reproducible load tests with pass/fail thresholds that run in CI. Without load testing gates, you deploy regressions that double p95 latency — and only discover it when users complain.

### HOW
```javascript
import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  stages: [
    { duration: '30s', target: 20 },   // Ramp to 20 VUs
    { duration: '1m',  target: 50 },   // Sustain at 50 VUs
    { duration: '15s', target: 0 },    // Ramp down
  ],
  thresholds: {
    http_req_duration: ['p(95)<500', 'p(99)<1000'],  // 95% < 500ms, 99% < 1s
    http_req_failed: ['rate<0.01'],                   // < 1% errors
    checks: ['rate>0.99'],                            // 99% checks pass
  },
};

export default function () {
  const res = http.get('http://localhost:8000/healthz');
  check(res, {
    'status is 200': (r) => r.status === 200,
    'duration < 200ms': (r) => r.timings.duration < 200,
  });
  sleep(1);
}

export function handleSummary(data) {
  return {
    'stdout': textSummary(data, { indent: ' ', enableColors: true }),
    'summary.json': JSON.stringify(data),
  };
}
```

### GOTCHA
`sleep(1)` between iterations is CRITICAL for realistic load simulation. Without it, k6 fires as fast as possible — your 50 VUs generate 50,000 req/s instead of a realistic 50 req/s. The `thresholds` block makes k6 exit with code 99 when thresholds are breached — use this in CI to block deploys that regress performance. `handleSummary` exports results to JSON for Grafana/Datadog integration.

---

## 10. CI/CD Pipeline — Test, Build, Scan, Deploy

### WHY
Manual deploys are slow, error-prone, and impossible to audit. A CI/CD pipeline enforces the quality gate chain: tests must pass, image must be scanned, container must build — BEFORE any deployment. Without automated gates, the fastest path to production skips security scanning because "it worked locally."

### HOW
```yaml
# .github/workflows/deploy.yml
name: Deploy
on:
  push:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-python@v5
      with: { python-version: "3.12" }
    - run: pip install -r requirements.txt -r requirements-dev.txt
    - run: pytest --cov --tb=short

  build-and-scan:
    needs: test
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4
    - uses: docker/build-push-action@v6
      with:
        push: false
        tags: myapp:${{ github.sha }}
        load: true
    - uses: aquasecurity/trivy-action@0.28.0
      with:
        image-ref: myapp:${{ github.sha }}
        severity: CRITICAL,HIGH
        exit-code: 1          # FAIL the build on critical/high CVEs
    - uses: docker/build-push-action@v6
      with:
        push: true
        tags: ghcr.io/org/myapp:${{ github.sha }}
```

### GOTCHA
`exit-code: 1` in the Trivy step makes the pipeline FAIL when critical/high CVEs are found. Without this, Trivy reports vulnerabilities but the build continues — security theater. Pin the Trivy action version (`@0.28.0`) to prevent supply chain attacks via compromised action tags. Never use `@master` or `@latest` for GitHub Actions.

---

## 11. ConfigMap and Secrets — Externalize Configuration

### WHY
Baking configuration into the Docker image (`ENV DATABASE_URL=...` in Dockerfile) means rebuilding and redeploying for every config change. In Kubernetes, ConfigMaps store non-sensitive config (feature flags, log levels) and Secrets store sensitive data (DB passwords, API keys). Both are injected at runtime — change config without rebuilding.

### HOW
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: myapi-config
data:
  LOG_LEVEL: "info"
  WORKERS: "4"
  CORS_ORIGINS: "https://app.example.com"

---
apiVersion: v1
kind: Secret
metadata:
  name: myapi-secrets
type: Opaque
data:
  DATABASE_URL: cG9zdGdyZXNxbCtsb2NhbGhvc3Q=   # base64 encoded
  JWT_SECRET: c3VwZXItc2VjcmV0LWtleQ==           # base64 encoded

---
# Reference in Deployment:
containers:
- name: myapi
  envFrom:
  - configMapRef:
      name: myapi-config
  - secretRef:
      name: myapi-secrets
```

### GOTCHA
Kubernetes Secrets are base64 encoded, NOT encrypted. Anyone with `kubectl get secret -o yaml` can decode them. For production: use External Secrets Operator (AWS Secrets Manager, Vault) or Sealed Secrets. Also: changing a ConfigMap does NOT automatically restart pods — use `kubectl rollout restart deployment/myapi` or add a checksum annotation that triggers rolling update on config change.

---

## 12. Container Image Scanning — Trivy in CI

### WHY
Your code may be secure, but your base image ships with 50+ known CVEs from system libraries. A single critical CVE in OpenSSL or glibc gives attackers a foothold BEFORE they even touch your application code. Automated scanning in CI reduces vulnerability exposure by up to 87% compared to manual approaches, and catches issues before they reach production.

### HOW
```bash
# Local scanning (dev workflow):
trivy image myapp:latest --severity CRITICAL,HIGH

# CI scanning (GitHub Actions):
- uses: aquasecurity/trivy-action@0.28.0
  with:
    image-ref: myapp:${{ github.sha }}
    format: 'sarif'
    output: 'trivy-results.sarif'
    severity: 'CRITICAL,HIGH'
    exit-code: '1'

# Upload to GitHub Security tab:
- uses: github/codeql-action/upload-sarif@v3
  with:
    sarif_file: 'trivy-results.sarif'
  if: always()   # Upload even if Trivy found vulns

# Kubernetes cluster scanning (ongoing):
trivy k8s --report summary cluster
```

### GOTCHA
Scan BEFORE pushing to registry — not after. Once a vulnerable image is in your registry, automated deployments may pull it before you notice. Rebuild base images weekly to pick up security patches: `python:3.12-slim` gets updated when Debian releases fixes. Pin with digest (`@sha256:...`) for reproducibility, but UPDATE the digest regularly. Stale pins are just as dangerous as no pins.

---

## Distroless vs Slim vs Alpine — Decision Tree

Not a standalone technique — it's a foundational choice that affects every Dockerfile:

```
Need a shell for debugging in production?
├─ Yes → python:3.12-slim (95% of teams)
│       - 130MB, Debian-based, glibc, all pip packages work
│       - Has bash, apt, curl for emergency debugging
│
└─ No → Distroless
        ├─ gcr.io/distroless/python3 (40MB)
        │   - No shell, no package manager, no debugging tools
        │   - Runs as nonroot (UID 65532) by default
        │   - Smallest attack surface, but debugging requires ephemeral containers
        │
        └─ NOT Alpine for Python (avoid musl/glibc pain)
            - Alpine uses musl libc → numpy, pandas, psycopg2 fail to build
            - Debugging musl compatibility takes hours, saves 20MB
            - Only use Alpine if you have ZERO C extension dependencies
```

For FastAPI production: **`python:3.12-slim`** is the correct default. Distroless only if you have a security compliance requirement AND your team can debug without a shell (using `kubectl debug`).

---

## Gunicorn + Uvicorn Workers — Container Sizing

Invariant for Kubernetes deployments where the container is the process manager:

```bash
# In Kubernetes: DON'T use Gunicorn. Uvicorn alone is correct.
# Kubernetes IS your process manager (replicas = workers).
# Gunicorn + Kubernetes = double process management = confused scaling.

# Single-worker Uvicorn per pod (K8s manages replicas):
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

# Multi-worker Uvicorn (non-K8s, single VM/container):
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]

# Formula for non-K8s: workers = 2 * CPU_CORES + 1
# Formula for K8s: workers = 1 per pod, scale via HPA
```

In Kubernetes, prefer 1 worker per pod with more replicas. This gives HPA accurate CPU metrics per pod and avoids confused scaling where Gunicorn's internal load balancing fights Kubernetes' external load balancing.
