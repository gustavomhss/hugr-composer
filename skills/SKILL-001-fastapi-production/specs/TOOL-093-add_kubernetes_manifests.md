# TOOL-093: `fastapi_add_kubernetes_manifests`

**Skill:** SKILL-001-fastapi-production
**Category:** extend / infrastructure
**Source:** `adapt/extend/infrastructure/add_kubernetes_manifests.py`
**Test file:** `adapt/extend/infrastructure/test_add_kubernetes_manifests.py`
**MCP name:** `fastapi_add_kubernetes_manifests`

---

## 1. Overview

`fastapi_add_kubernetes_manifests` generates a complete, production-ready
Kubernetes manifest set for any FastAPI project. It creates a `k8s/`
directory containing exactly seven YAML files and patches one existing file:

| File | Kind | Purpose |
|---|---|---|
| `k8s/deployment.yaml` | `Deployment` | readiness/liveness probes, resource limits, env from ConfigMap + Secret, `runAsNonRoot: true` |
| `k8s/service.yaml` | `Service` (ClusterIP) | Internal DNS name, port 80 → 8000 |
| `k8s/hpa.yaml` | `HorizontalPodAutoscaler` | Scale 2–10 replicas on CPU ≥ 70% or memory ≥ 80% |
| `k8s/pdb.yaml` | `PodDisruptionBudget` | `minAvailable: 1` protects rolling updates |
| `k8s/configmap.yaml` | `ConfigMap` | Non-secret runtime config (environment, log level, DB URL, Redis URL) |
| `k8s/secret.yaml` | `Secret` (Opaque) | Placeholder template with `IMPORTANT` warning; operators must replace values |
| `k8s/ingress.yaml` | `Ingress` | nginx class, TLS termination, `proxy-body-size` annotation |
| `app/core/config.py` *(patch)* | — | Inserts `K8S_REPLICAS`, `K8S_CPU_LIMIT`, `K8S_MEMORY_LIMIT`, `K8S_NAMESPACE` inside `class Settings` |

The tool is **idempotent**: if `k8s/hpa.yaml` already exists and contains the
string `HorizontalPodAutoscaler`, the tool returns `status="no_op"` and writes
nothing.

---

## 2. Purpose & Problem Solved

Bootstrapping a Kubernetes deployment correctly requires knowledge of at least
seven distinct resource kinds. Developers routinely omit PodDisruptionBudgets
(causing downtime during node drains), skip resource limits (causing noisy-
neighbour evictions), or leave secrets as plaintext. This tool encodes SOTA
Kubernetes best practices in one idempotent call:

- **Availability:** `minReplicas: 2` in HPA and `minAvailable: 1` in PDB
  guarantee at least one pod is always running.
- **Autoscaling:** CPU (70%) and memory (80%) dual-metric HPA targeting
  `autoscaling/v2` API (Kubernetes 1.23+).
- **Security:** `securityContext: runAsNonRoot: true, runAsUser: 1000`
  in the Deployment; secrets are never hardcoded.
- **Operational safety:** `secret.yaml` ships with `<base64-encoded-…>`
  placeholders and an `IMPORTANT` warning comment to force operator action
  before `kubectl apply`.
- **Ingress:** nginx with TLS and `ssl-redirect: "true"` — no plaintext HTTP.

---

## 3. Performance SLOs

| Metric | Target |
|---|---|
| `execution_time_ms` | < 500 ms on cold filesystem |
| Files created | exactly 7 YAML manifests in `k8s/` |
| Files modified | 1 (`app/core/config.py`) |
| Config fields injected | 4 (`K8S_REPLICAS`, `K8S_CPU_LIMIT`, `K8S_MEMORY_LIMIT`, `K8S_NAMESPACE`) |
| Maximum function LOC (`app/`) | ≤ 50 |
| `no_op` detection cost | O(1) — single file existence + string check |

---

## 4. Code Examples

### 4.1 Before (minimal FastAPI project)

```
my_project/
├── app/
│   ├── main.py
│   └── core/
│       └── config.py          # class Settings: ... ; settings = Settings()
├── requirements.txt
└── (no k8s/ directory)
```

`app/core/config.py` before:

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://user:pass@localhost/db"
    SECRET_KEY: str = "change-me"

settings = Settings()
```

### 4.2 After (tool applied)

```
my_project/
├── app/
│   └── core/
│       └── config.py          # K8S_REPLICAS, K8S_CPU_LIMIT, K8S_MEMORY_LIMIT, K8S_NAMESPACE added
└── k8s/
    ├── deployment.yaml
    ├── service.yaml
    ├── hpa.yaml
    ├── pdb.yaml
    ├── configmap.yaml
    ├── secret.yaml
    └── ingress.yaml
```

`app/core/config.py` after (injected block):

```python
    K8S_REPLICAS: int = 2
    K8S_CPU_LIMIT: str = "1000m"
    K8S_MEMORY_LIMIT: str = "512Mi"
    K8S_NAMESPACE: str = "production"

settings = Settings()
```

### 4.3 `k8s/deployment.yaml` (key sections)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-project
  namespace: ${K8S_NAMESPACE:-production}
spec:
  replicas: ${K8S_REPLICAS:-2}
  template:
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
      containers:
        - name: my-project
          image: my-project:latest
          ports:
            - containerPort: 8000
          envFrom:
            - configMapRef:
                name: my-project-config
            - secretRef:
                name: my-project-secret
          resources:
            requests:
              cpu: "250m"
              memory: "256Mi"
            limits:
              cpu: "${K8S_CPU_LIMIT:-1000m}"
              memory: "${K8S_MEMORY_LIMIT:-512Mi}"
          readinessProbe:
            httpGet:
              path: /healthz
              port: 8000
            initialDelaySeconds: 10
            periodSeconds: 10
          livenessProbe:
            httpGet:
              path: /healthz
              port: 8000
            initialDelaySeconds: 30
            periodSeconds: 30
```

### 4.4 `k8s/hpa.yaml`

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: my-project
  namespace: ${K8S_NAMESPACE:-production}
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: my-project
  minReplicas: 2
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
    - type: Resource
      resource:
        name: memory
        target:
          type: Utilization
          averageUtilization: 80
```

### 4.5 `k8s/secret.yaml` (placeholder pattern)

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: my-project-secret
  namespace: ${K8S_NAMESPACE:-production}
type: Opaque
# IMPORTANT: Replace ALL placeholder values below with real base64-encoded secrets.
# Generate: echo -n 'mysecret' | base64
data:
  SECRET_KEY: <base64-encoded-secret-key>
  POSTGRES_PASSWORD: <base64-encoded-postgres-password>
```

### 4.6 `k8s/ingress.yaml` (nginx + TLS)

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: my-project
  namespace: ${K8S_NAMESPACE:-production}
  annotations:
    nginx.ingress.kubernetes.io/proxy-body-size: "10m"
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
spec:
  ingressClassName: nginx
  tls:
    - hosts:
        - your-app.example.com
      secretName: my-project-tls
  rules:
    - host: your-app.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: my-project
                port:
                  number: 80
```

### 4.7 `_patch_config` implementation

```python
def _patch_config(config_file: Path) -> None:
    content = config_file.read_text()
    fields_needed = [
        "    K8S_REPLICAS: int = 2",
        '    K8S_CPU_LIMIT: str = "1000m"',
        '    K8S_MEMORY_LIMIT: str = "512Mi"',
        '    K8S_NAMESPACE: str = "production"',
    ]
    new_lines = [line for line in fields_needed
                 if line.strip().split(":")[0] not in content]
    if not new_lines:
        return
    insertion = "\n".join(new_lines) + "\n"
    marker = "settings = Settings()"
    if marker in content:
        content = content.replace(marker, insertion + "\n" + marker, 1)
    else:
        if not content.endswith("\n"):
            content += "\n"
        content += "\n" + insertion
    config_file.write_text(content)
```

### 4.8 Idempotency guard and app name derivation

```python
# Idempotency check
hpa_file = project / "k8s" / "hpa.yaml"
if hpa_file.exists() and "HorizontalPodAutoscaler" in hpa_file.read_text():
    return ToolResult(status="no_op", ...)

# App name derived from directory
app_name = project.name.lower().replace("_", "-").replace(" ", "-") or "fastapi-app"
```

### 4.9 MCP descriptor

```python
MCP_TOOL = {
    "name": "fastapi_add_kubernetes_manifests",
    "description": (
        "Generate production-ready Kubernetes manifests: Deployment, Service, HPA, "
        "PDB, ConfigMap, Secret, and Ingress YAML files."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_kubernetes_manifests",
}
```

---

## 5. Quality Standards

| Standard | Requirement |
|---|---|
| Manifest count | Exactly 7 YAML files in `k8s/` |
| API versions | `autoscaling/v2` for HPA (Kubernetes ≥ 1.23); `policy/v1` for PDB (≥ 1.21) |
| Security context | `runAsNonRoot: true`, `runAsUser: 1000` in Deployment pod spec |
| Resource limits | CPU and memory `limits` and `requests` in Deployment |
| Secret safety | Placeholder values with `IMPORTANT` warning in `secret.yaml` |
| Probe coverage | Both `readinessProbe` and `livenessProbe` in Deployment |
| Ingress TLS | `tls:` block present in `ingress.yaml` |
| No new Python deps | YAML generated via `textwrap.dedent` — no yaml library required |
| Config hygiene | Fields 4-space indented inside `class Settings` body |
| Model/route isolation | `app/models/__init__.py` and `app/routes/__init__.py` untouched |

---

## 6. Completeness Criteria

| CC | Criterion | Verification | Test |
|---|---|---|---|
| CC-01 | `status="success"` on fresh project | `result.status == "success"` | `test_success_status` |
| CC-02 | Second run returns `no_op`, zero writes | `r2.status == "no_op"` and `not r2.files_created` | `test_idempotent` |
| CC-03 | `dry_run=True` returns `success` with zero writes | No files changed | `test_dry_run` |
| CC-04 | At least 7 YAML files in `files_created` | `len(yaml_files) >= 7` | `test_files_created_count` |
| CC-05 | At least 1 file modified (`config.py`) | `len(result.files_modified) >= 1` | `test_files_modified_count` |
| CC-06 | All generated `.py` files parse without `SyntaxError` | `ast.parse()` on every `.py` | `test_all_py_parse` |
| CC-07 | No function in `app/` exceeds 50 LOC | AST walk | `test_no_function_over_50_loc` |
| CC-08 | `K8S_REPLICAS`, `K8S_CPU_LIMIT`, `K8S_MEMORY_LIMIT`, `K8S_NAMESPACE` inside `class Settings` | 4-space indent check | `test_config_fields_patched` |
| CC-09 | `app/models/__init__.py` unchanged | `before == after` | `test_no_spurious_models_init_changes` |
| CC-10 | `app/routes/__init__.py` unchanged | `before == after` | `test_no_spurious_routes_init_changes` |
| CC-11 | `k8s/deployment.yaml` has `readinessProbe` and `livenessProbe` | Content check | `test_deployment_yaml_created` |
| CC-12 | `k8s/service.yaml` uses `ClusterIP` type | Content check | `test_service_yaml_created` |
| CC-13 | `k8s/hpa.yaml` has `HorizontalPodAutoscaler`, CPU and memory metrics | Content check | `test_hpa_yaml_created` |
| CC-14 | `k8s/pdb.yaml` has `PodDisruptionBudget` with `minAvailable` | Content check | `test_pdb_yaml_created` |
| CC-15 | `k8s/configmap.yaml` and `k8s/secret.yaml` both exist | Content check | `test_configmap_and_secret_created` |
| CC-16 | `k8s/ingress.yaml` has nginx annotations and `tls:` | Content check | `test_ingress_yaml_created` |
| CC-17 | `k8s/deployment.yaml` has CPU and memory `limits` | Content check | `test_deployment_has_resource_limits` |
| CC-18 | `execution_time_ms` is a positive integer | `result.execution_time_ms > 0` | `test_execution_time_recorded` |
| CC-19 | `next_steps` non-empty and mentions `kubectl` | `"kubectl" in combined` | `test_next_steps_present` |
| CC-20 | Project still parses after two consecutive runs | `ast.parse()` on all `.py` | `test_idempotent_project_still_parses` |
| CC-21 | `k8s/` directory contains exactly 7 YAML files | `len(yaml_files) == 7` | `test_k8s_dir_has_all_seven_files` |
| CC-22 | `secret.yaml` warns about placeholder values | `"placeholder"` or `"IMPORTANT"` or `"Replace"` in content | `test_secret_has_placeholder_warning` |
| CC-23 | `deployment.yaml` references both ConfigMap and Secret via `envFrom` | `configMapRef` and `secretRef` in content | `test_deployment_has_env_from_configmap_and_secret` |

---

## 7. Definition of Done

- [ ] All 23 tests in `test_add_kubernetes_manifests.py` pass
- [ ] `k8s/` directory contains exactly 7 YAML files
- [ ] `k8s/deployment.yaml` has `readinessProbe`, `livenessProbe`, resource `limits`, `envFrom` with `configMapRef` + `secretRef`, `runAsNonRoot: true`
- [ ] `k8s/service.yaml` type is `ClusterIP`, port 80 → 8000
- [ ] `k8s/hpa.yaml` uses `autoscaling/v2`, CPU 70%, memory 80%, min 2, max 10
- [ ] `k8s/pdb.yaml` uses `policy/v1`, `minAvailable: 1`
- [ ] `k8s/configmap.yaml` contains ENVIRONMENT, LOG_LEVEL, POSTGRES_*, REDIS_URL
- [ ] `k8s/secret.yaml` contains `<base64-encoded-…>` placeholders and IMPORTANT warning
- [ ] `k8s/ingress.yaml` has `ingressClassName: nginx`, TLS block, `ssl-redirect: "true"`
- [ ] App name derived as `project.name.lower().replace("_", "-")`
- [ ] `config.py` receives `K8S_REPLICAS`, `K8S_CPU_LIMIT`, `K8S_MEMORY_LIMIT`, `K8S_NAMESPACE` at 4-space indent
- [ ] Second invocation returns `no_op` without writing any file
- [ ] `dry_run=True` returns `success` without writing any file
- [ ] `execution_time_ms` is a positive integer on every return path
- [ ] `next_steps` mentions `kubectl apply -f k8s/`

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|---|---|---|---|
| INV-K8S-01 | Idempotency key is `HorizontalPodAutoscaler` in `k8s/hpa.yaml` | Only `_write_hpa` writes this string | `test_idempotent` |
| INV-K8S-02 | Exactly 7 YAML files are written — no more, no fewer | Seven explicit `_write_*` calls + `files_created.append(...)` | `test_k8s_dir_has_all_seven_files` |
| INV-K8S-03 | `app_name` is always Kubernetes-safe (lowercase, hyphens only) | `project.name.lower().replace("_", "-").replace(" ", "-")` | `test_deployment_yaml_created` |
| INV-K8S-04 | `_patch_config` skips any field already present in `config.py` | `line.strip().split(":")[0] not in content` guard | `test_config_fields_patched` + `test_idempotent_project_still_parses` |
| INV-K8S-05 | `ast.parse()` validation loop runs only on `.py` files; YAML files are skipped | `if p.suffix == ".py"` guard in validation loop | `test_all_py_parse` |
| INV-K8S-06 | `secret.yaml` always contains both the placeholder pattern and the operator warning | `_write_secret` hardcodes `IMPORTANT:` comment | `test_secret_has_placeholder_warning` |
| INV-K8S-07 | HPA uses `autoscaling/v2` (not v1 or v2beta) | Hardcoded in `_write_hpa` | `test_hpa_yaml_created` |
| INV-K8S-08 | `app/models/__init__.py` and `app/routes/__init__.py` are never touched | No reference to those paths in source | `test_no_spurious_models_init_changes`, `test_no_spurious_routes_init_changes` |

---

## 9. User Stories

**US-1 — Bootstrapping K8s from scratch**
> As a developer who has built a Docker image but never written K8s manifests,
> I run `fastapi_add_kubernetes_manifests` and immediately get a complete,
> production-ready manifest set I can `kubectl apply` after filling in secrets.

**US-2 — Safe re-run after branch switch**
> As a developer who already ran the tool, I can run it again — it returns
> `no_op` without corrupting any existing YAML file.

**US-3 — Preview before committing**
> As a developer in a code-review workflow, I run with `dry_run=True` to
> see the planned changes without writing any files.

**US-4 — Multi-environment deployment**
> As a DevOps engineer, I override `K8S_NAMESPACE` and `K8S_REPLICAS` at
> deploy time via environment variable substitution in the YAML files.

**US-5 — Autoscaling readiness**
> As an SRE, I verify that the HPA scales on both CPU and memory, with
> `minReplicas: 2` ensuring availability during scaling events.

---

## 10. Edge Cases

| Edge Case | Expected Behaviour |
|---|---|
| `k8s/hpa.yaml` already exists with `HorizontalPodAutoscaler` | `status="no_op"`, zero writes |
| `k8s/` directory already exists | `mkdir(parents=True, exist_ok=True)` is a no-op |
| `app/core/config.py` missing | Config patch skipped silently; 7 YAML files still created |
| Project name is `""` (empty) | `app_name` falls back to `"fastapi-app"` |
| Project name contains spaces | `replace(" ", "-")` normalises to valid K8s label |
| `K8S_REPLICAS` already in `config.py` | `_patch_config` skip-guard prevents duplicate |
| `settings = Settings()` absent from `config.py` | Fields appended to end of file |
| Partial `k8s/` directory (some manifests exist) | Only `hpa.yaml` with `HorizontalPodAutoscaler` triggers `no_op`; otherwise all 7 are written |

---

## 11. Dependencies

| Dependency | Type | Version / Notes |
|---|---|---|
| `adapt.contracts.ToolInput` | Internal | `project_dir`, `dry_run` |
| `adapt.contracts.ToolResult` | Internal | `status`, `files_created`, `files_modified`, `notes`, `next_steps`, `execution_time_ms` |
| `adapt.contracts.validate_project_dir` | Internal | Returns error string if invalid |
| `adapt.contracts.prerequisites.ensure_prerequisites` | Internal | Checks `CONFIG_SETTINGS`; auto-scaffolds |
| `adapt.contracts.prerequisites.Prereq` | Internal | Enum: `CONFIG_SETTINGS` |
| `ast` | stdlib | AST parse validation (`.py` files only) |
| `textwrap` | stdlib | `dedent` for YAML string templates |
| `time` | stdlib | `time.monotonic()` for `execution_time_ms` |
| `pathlib.Path` | stdlib | All file I/O |
| **kubectl** | Runtime (operator) | Not installed by this tool; required to apply manifests |
| **nginx Ingress Controller** | Runtime (cluster) | Required for Ingress to function; assumed pre-installed |

---

## 12. File Map

```
{project_dir}/
├── k8s/
│   ├── deployment.yaml        # CREATED — Deployment with probes, limits, envFrom
│   ├── service.yaml           # CREATED — ClusterIP Service
│   ├── hpa.yaml               # CREATED — HorizontalPodAutoscaler (autoscaling/v2)
│   ├── pdb.yaml               # CREATED — PodDisruptionBudget (minAvailable: 1)
│   ├── configmap.yaml         # CREATED — Non-secret runtime config
│   ├── secret.yaml            # CREATED — Placeholder Secret template
│   └── ingress.yaml           # CREATED — nginx Ingress with TLS
└── app/
    └── core/
        └── config.py          # MODIFIED — K8S_REPLICAS, K8S_CPU_LIMIT, K8S_MEMORY_LIMIT, K8S_NAMESPACE
```

Source module: `adapt/extend/infrastructure/add_kubernetes_manifests.py`
Test module: `adapt/extend/infrastructure/test_add_kubernetes_manifests.py`

---

## 13. Rollback

```bash
# Remove the entire k8s/ directory
rm -rf k8s/

# Undo config.py patch (remove the four K8S_* lines)
git checkout app/core/config.py
```

No database migrations or destructive filesystem operations are performed.
YAML files are not touched after creation on a second run (`no_op` path).

---

## 14. Security Considerations

| Concern | Mitigation |
|---|---|
| Secrets in version control | `secret.yaml` ships with `<base64-encoded-…>` placeholders and an IMPORTANT warning; operators replace values outside VCS |
| Container runs as root | `securityContext.runAsNonRoot: true` and `runAsUser: 1000` in Deployment |
| Plaintext HTTP | `nginx.ingress.kubernetes.io/ssl-redirect: "true"` forces HTTPS; TLS block present |
| Ingress body-size attacks | `proxy-body-size: "10m"` annotation limits request body |
| Noisy-neighbour CPU/memory | Resource `limits` and `requests` set on the container |
| Namespace isolation | All manifests specify `namespace: ${K8S_NAMESPACE:-production}` |
| HPA over-scaling | `maxReplicas: 10` caps horizontal scale-out |

---

## 15. Observability

| Signal | Where |
|---|---|
| `execution_time_ms` | `ToolResult.execution_time_ms` — wall-clock ms |
| `files_created` | Absolute paths of all 7 YAML files (plus scaffolded prerequisites) |
| `files_modified` | Absolute path of patched `config.py` |
| `notes` | Per-file summary: probes, HPA targets, PDB, secret warning |
| `next_steps` | `kubectl create namespace`, `kubectl apply -f k8s/`, `kubectl rollout status`, `kubectl get hpa` |
| Pod health | `readinessProbe` and `livenessProbe` on `/healthz` port 8000 |
| Scaling | HPA metrics visible via `kubectl get hpa -n <namespace>` |

---

## 16. Test Coverage Map

| Test function | CC | What it proves |
|---|---|---|
| `test_success_status` | CC-01 | Happy path returns `status="success"` |
| `test_idempotent` | CC-02 | Second run returns `no_op` without writing files |
| `test_dry_run` | CC-03 | `dry_run=True` writes nothing |
| `test_files_created_count` | CC-04 | At least 7 YAML files created and exist on disk |
| `test_files_modified_count` | CC-05 | `config.py` reported as modified |
| `test_all_py_parse` | CC-06 | All generated `.py` files parse cleanly |
| `test_no_function_over_50_loc` | CC-07 | 50-LOC function limit enforced |
| `test_config_fields_patched` | CC-08 | Four `K8S_*` fields inside `class Settings` at 4-space indent |
| `test_no_spurious_models_init_changes` | CC-09 | `models/__init__.py` untouched |
| `test_no_spurious_routes_init_changes` | CC-10 | `routes/__init__.py` untouched |
| `test_deployment_yaml_created` | CC-11 | `deployment.yaml` has `readinessProbe` and `livenessProbe` |
| `test_service_yaml_created` | CC-12 | `service.yaml` has `ClusterIP` type |
| `test_hpa_yaml_created` | CC-13 | `hpa.yaml` has `HorizontalPodAutoscaler`, cpu, memory metrics |
| `test_pdb_yaml_created` | CC-14 | `pdb.yaml` has `PodDisruptionBudget` with `minAvailable` |
| `test_configmap_and_secret_created` | CC-15 | Both `configmap.yaml` and `secret.yaml` exist with correct kinds |
| `test_ingress_yaml_created` | CC-16 | `ingress.yaml` has nginx annotations and TLS |
| `test_deployment_has_resource_limits` | CC-17 | `deployment.yaml` has `limits` with cpu and memory |
| `test_execution_time_recorded` | CC-18 | `execution_time_ms > 0` |
| `test_next_steps_present` | CC-19 | `next_steps` non-empty and mentions `kubectl` |
| `test_idempotent_project_still_parses` | CC-20 | Two runs leave all `.py` files parseable |
| `test_k8s_dir_has_all_seven_files` | CC-21 | `k8s/` contains exactly 7 `.yaml` files |
| `test_secret_has_placeholder_warning` | CC-22 | `secret.yaml` warns about placeholder values |
| `test_deployment_has_env_from_configmap_and_secret` | CC-23 | `deployment.yaml` references ConfigMap and Secret via `envFrom` |
