"""TOOL-093: add_kubernetes_manifests — generate production-ready K8s YAML manifests.

Generates all K8s resources needed to deploy a FastAPI application:

* ``k8s/deployment.yaml`` — Deployment with readiness/liveness probes, resource
  limits, env vars sourced from ConfigMap and Secret.
* ``k8s/service.yaml`` — ClusterIP Service exposing the app internally.
* ``k8s/hpa.yaml`` — HorizontalPodAutoscaler targeting CPU and memory metrics.
* ``k8s/pdb.yaml`` — PodDisruptionBudget ensuring minAvailable during disruptions.
* ``k8s/configmap.yaml`` — Non-secret runtime configuration.
* ``k8s/secret.yaml`` — Secret template with placeholder values (base64-encoded).
* ``k8s/ingress.yaml`` — Ingress with nginx annotations and TLS termination.

Configuration knobs injected into ``app/core/config.py``:
    ``K8S_REPLICAS``, ``K8S_CPU_LIMIT``, ``K8S_MEMORY_LIMIT``, ``K8S_NAMESPACE``

No pip dependencies — this tool generates YAML files via ``textwrap.dedent``.
All YAML is generated from Python string templates; no external YAML library needed.

The tool is idempotent: a second run detects the ``HorizontalPodAutoscaler``
fingerprint in ``k8s/hpa.yaml`` and returns ``status="no_op"``.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_kubernetes_manifests import add_kubernetes_manifests

    result = add_kubernetes_manifests(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # ["…/k8s/deployment.yaml", "…/k8s/service.yaml", …]
    print(result.next_steps)    # ["kubectl apply -f k8s/", …]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_resiliency_add_kubernetes_manifests",
    "description": (
        "Generate production-ready Kubernetes manifests: Deployment, Service, HPA, "
        "PDB, ConfigMap, Secret, and Ingress YAML files."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_kubernetes_manifests",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_kubernetes_manifests(inp: ToolInput) -> ToolResult:
    """Generate production-ready Kubernetes manifests for a FastAPI project.

    Creates k8s/deployment.yaml (readiness/liveness probes, resource limits,
    env from ConfigMap/Secret), k8s/service.yaml (ClusterIP), k8s/hpa.yaml
    (CPU/memory autoscaling), k8s/pdb.yaml (minAvailable), k8s/configmap.yaml
    (non-secret config), k8s/secret.yaml (placeholder template), and
    k8s/ingress.yaml (nginx annotations + TLS).

    Patches ``app/core/config.py`` with K8S_REPLICAS, K8S_CPU_LIMIT,
    K8S_MEMORY_LIMIT, K8S_NAMESPACE.

    Args:
        inp: ``ToolInput`` with ``project_dir`` (absolute path) and optional
            ``dry_run`` flag.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)

    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err,
                          execution_time_ms=_elapsed_ms(start))

    # --- Prerequisite check (standalone mode) --------------------------------
    from adapt.contracts.prerequisites import ensure_prerequisites, Prereq

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.CONFIG_SETTINGS,
        auto_scaffold=not inp.dry_run,
    )
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=[
                "These prerequisites cannot be auto-created.",
                "Generate a base project first:",
                "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    if scaffolded:
        files_created.extend(scaffolded)

    # --- Pre-flight: already installed? -------------------------------------
    hpa_file = project / "k8s" / "hpa.yaml"
    if hpa_file.exists() and "HorizontalPodAutoscaler" in hpa_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["HorizontalPodAutoscaler already present in k8s/hpa.yaml — K8s manifests already installed, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    # --- dry_run guard (BEFORE any writes) -----------------------------------
    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create k8s/ directory with 7 manifests:",
                "          deployment.yaml, service.yaml, hpa.yaml, pdb.yaml,",
                "          configmap.yaml, secret.yaml, ingress.yaml.",
                "[dry_run] Would patch app/core/config.py with K8S_REPLICAS, K8S_CPU_LIMIT,",
                "          K8S_MEMORY_LIMIT, K8S_NAMESPACE.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []
    k8s_dir = project / "k8s"
    k8s_dir.mkdir(parents=True, exist_ok=True)

    # Infer app name from project directory
    app_name = project.name.lower().replace("_", "-").replace(" ", "-") or "fastapi-app"

    # --- Write all 7 manifests -----------------------------------------------
    _write_deployment(k8s_dir / "deployment.yaml", app_name)
    files_created.append(str(k8s_dir / "deployment.yaml"))

    _write_service(k8s_dir / "service.yaml", app_name)
    files_created.append(str(k8s_dir / "service.yaml"))

    _write_hpa(k8s_dir / "hpa.yaml", app_name)
    files_created.append(str(k8s_dir / "hpa.yaml"))

    _write_pdb(k8s_dir / "pdb.yaml", app_name)
    files_created.append(str(k8s_dir / "pdb.yaml"))

    _write_configmap(k8s_dir / "configmap.yaml", app_name)
    files_created.append(str(k8s_dir / "configmap.yaml"))

    _write_secret(k8s_dir / "secret.yaml", app_name)
    files_created.append(str(k8s_dir / "secret.yaml"))

    _write_ingress(k8s_dir / "ingress.yaml", app_name)
    files_created.append(str(k8s_dir / "ingress.yaml"))

    # --- Patch config.py with K8s settings fields ----------------------------
    config_file = project / "app" / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # --- ast.parse validation (Python files only — YAML skipped) ------------
    for path_str in files_created:
        p = Path(path_str)
        if p.suffix == ".py" and p.is_file():
            try:
                ast.parse(p.read_text())
            except SyntaxError as exc:
                return ToolResult(
                    status="error",
                    error=f"Generated file has syntax error: {p}: {exc}",
                    execution_time_ms=_elapsed_ms(start),
                )

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            f"Kubernetes manifests generated in k8s/ for app '{app_name}':",
            "  deployment.yaml: readiness/liveness probes, resource limits, ConfigMap/Secret env.",
            "  service.yaml: ClusterIP on port 8000.",
            "  hpa.yaml: autoscales 2–10 replicas on CPU (70%) and memory (80%).",
            "  pdb.yaml: minAvailable=1 to protect rolling deployments.",
            "  configmap.yaml: non-secret runtime config (ENVIRONMENT, LOG_LEVEL).",
            "  secret.yaml: template with base64 placeholder values — fill before applying.",
            "  ingress.yaml: nginx class, TLS termination, proxy-body-size annotation.",
            "Config fields added: K8S_REPLICAS, K8S_CPU_LIMIT, K8S_MEMORY_LIMIT, K8S_NAMESPACE.",
        ],
        next_steps=[
            "Edit k8s/secret.yaml: replace all <base64-encoded-…> placeholders.",
            "Edit k8s/ingress.yaml: replace 'your-app.example.com' with your domain.",
            "kubectl create namespace ${K8S_NAMESPACE:-production}",
            "kubectl apply -f k8s/",
            "kubectl rollout status deployment/fastapi-app -n ${K8S_NAMESPACE:-production}",
            "kubectl get hpa -n ${K8S_NAMESPACE:-production}  # verify autoscaling",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# Manifest writers — each < 50 LOC
# ---------------------------------------------------------------------------

def _write_deployment(dest: Path, app_name: str) -> None:
    """Write k8s/deployment.yaml with probes, resource limits, and env vars.

    Args:
        dest: Absolute path for deployment.yaml.
        app_name: Kubernetes-safe application name (lowercase, hyphens).
    """
    content = textwrap.dedent(f"""\
        apiVersion: apps/v1
        kind: Deployment
        metadata:
          name: {app_name}
          namespace: ${{K8S_NAMESPACE:-production}}
          labels:
            app: {app_name}
        spec:
          replicas: ${{K8S_REPLICAS:-2}}
          selector:
            matchLabels:
              app: {app_name}
          template:
            metadata:
              labels:
                app: {app_name}
            spec:
              securityContext:
                runAsNonRoot: true
                runAsUser: 1000
              containers:
                - name: {app_name}
                  image: {app_name}:latest
                  imagePullPolicy: Always
                  ports:
                    - containerPort: 8000
                  envFrom:
                    - configMapRef:
                        name: {app_name}-config
                    - secretRef:
                        name: {app_name}-secret
                  resources:
                    requests:
                      cpu: "250m"
                      memory: "256Mi"
                    limits:
                      cpu: "${{K8S_CPU_LIMIT:-1000m}}"
                      memory: "${{K8S_MEMORY_LIMIT:-512Mi}}"
                  readinessProbe:
                    httpGet:
                      path: /healthz
                      port: 8000
                    initialDelaySeconds: 10
                    periodSeconds: 10
                    failureThreshold: 3
                  livenessProbe:
                    httpGet:
                      path: /healthz
                      port: 8000
                    initialDelaySeconds: 30
                    periodSeconds: 30
                    failureThreshold: 3
    """)
    dest.write_text(content)


def _write_service(dest: Path, app_name: str) -> None:
    """Write k8s/service.yaml as a ClusterIP Service.

    Args:
        dest: Absolute path for service.yaml.
        app_name: Kubernetes-safe application name.
    """
    content = textwrap.dedent(f"""\
        apiVersion: v1
        kind: Service
        metadata:
          name: {app_name}
          namespace: ${{K8S_NAMESPACE:-production}}
          labels:
            app: {app_name}
        spec:
          type: ClusterIP
          selector:
            app: {app_name}
          ports:
            - name: http
              port: 80
              targetPort: 8000
              protocol: TCP
    """)
    dest.write_text(content)


def _write_hpa(dest: Path, app_name: str) -> None:
    """Write k8s/hpa.yaml targeting CPU (70%) and memory (80%) autoscaling.

    Args:
        dest: Absolute path for hpa.yaml.
        app_name: Kubernetes-safe application name.
    """
    content = textwrap.dedent(f"""\
        apiVersion: autoscaling/v2
        kind: HorizontalPodAutoscaler
        metadata:
          name: {app_name}
          namespace: ${{K8S_NAMESPACE:-production}}
        spec:
          scaleTargetRef:
            apiVersion: apps/v1
            kind: Deployment
            name: {app_name}
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
    """)
    dest.write_text(content)


def _write_pdb(dest: Path, app_name: str) -> None:
    """Write k8s/pdb.yaml with minAvailable=1 to protect rolling updates.

    Args:
        dest: Absolute path for pdb.yaml.
        app_name: Kubernetes-safe application name.
    """
    content = textwrap.dedent(f"""\
        apiVersion: policy/v1
        kind: PodDisruptionBudget
        metadata:
          name: {app_name}
          namespace: ${{K8S_NAMESPACE:-production}}
        spec:
          minAvailable: 1
          selector:
            matchLabels:
              app: {app_name}
    """)
    dest.write_text(content)


def _write_configmap(dest: Path, app_name: str) -> None:
    """Write k8s/configmap.yaml with non-secret runtime configuration.

    Args:
        dest: Absolute path for configmap.yaml.
        app_name: Kubernetes-safe application name.
    """
    content = textwrap.dedent(f"""\
        apiVersion: v1
        kind: ConfigMap
        metadata:
          name: {app_name}-config
          namespace: ${{K8S_NAMESPACE:-production}}
        data:
          ENVIRONMENT: "production"
          LOG_LEVEL: "info"
          POSTGRES_SERVER: "postgres"
          POSTGRES_PORT: "5432"
          POSTGRES_DB: "app"
          POSTGRES_USER: "postgres"
          REDIS_URL: "redis://redis:6379/0"
    """)
    dest.write_text(content)


def _write_secret(dest: Path, app_name: str) -> None:
    """Write k8s/secret.yaml as a template with base64 placeholder values.

    All values are clearly marked as placeholders — operators MUST replace them
    before applying the manifest to a cluster.

    Args:
        dest: Absolute path for secret.yaml.
        app_name: Kubernetes-safe application name.
    """
    content = textwrap.dedent(f"""\
        apiVersion: v1
        kind: Secret
        metadata:
          name: {app_name}-secret
          namespace: ${{K8S_NAMESPACE:-production}}
        type: Opaque
        # IMPORTANT: Replace ALL placeholder values below with real base64-encoded secrets.
        # Generate: echo -n 'mysecret' | base64
        data:
          SECRET_KEY: <base64-encoded-secret-key>
          POSTGRES_PASSWORD: <base64-encoded-postgres-password>
    """)
    dest.write_text(content)


def _write_ingress(dest: Path, app_name: str) -> None:
    """Write k8s/ingress.yaml with nginx class, TLS, and proxy annotations.

    Args:
        dest: Absolute path for ingress.yaml.
        app_name: Kubernetes-safe application name.
    """
    content = textwrap.dedent(f"""\
        apiVersion: networking.k8s.io/v1
        kind: Ingress
        metadata:
          name: {app_name}
          namespace: ${{K8S_NAMESPACE:-production}}
          annotations:
            nginx.ingress.kubernetes.io/proxy-body-size: "10m"
            nginx.ingress.kubernetes.io/proxy-read-timeout: "60"
            nginx.ingress.kubernetes.io/proxy-send-timeout: "60"
            nginx.ingress.kubernetes.io/ssl-redirect: "true"
        spec:
          ingressClassName: nginx
          tls:
            - hosts:
                - your-app.example.com
              secretName: {app_name}-tls
          rules:
            - host: your-app.example.com
              http:
                paths:
                  - path: /
                    pathType: Prefix
                    backend:
                      service:
                        name: {app_name}
                        port:
                          number: 80
    """)
    dest.write_text(content)


def _patch_config(config_file: Path) -> None:
    """Inject K8s settings fields inside the ``class Settings`` body.

    Inserts K8S_REPLICAS, K8S_CPU_LIMIT, K8S_MEMORY_LIMIT, K8S_NAMESPACE
    with 4-space indent just before the ``settings = Settings()`` instantiation
    line so the fields stay inside the class body. When that line is absent,
    appends at end of file.

    Args:
        config_file: Absolute path to ``app/core/config.py``.
    """
    content = config_file.read_text()
    fields_needed = [
        "    K8S_REPLICAS: int = 2",
        '    K8S_CPU_LIMIT: str = "1000m"',
        '    K8S_MEMORY_LIMIT: str = "512Mi"',
        '    K8S_NAMESPACE: str = "production"',
    ]
    new_lines = [line for line in fields_needed if line.strip().split(":")[0] not in content]
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


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _elapsed_ms(start: float) -> int:
    """Return wall-clock milliseconds since *start*.

    Args:
        start: Value from ``time.monotonic()`` taken at function entry.

    Returns:
        Elapsed time in milliseconds as a positive integer.
    """
    return int((time.monotonic() - start) * 1000)
