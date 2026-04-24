"""Generator for Kubernetes manifests."""

from __future__ import annotations

MCP_TOOL = {
    'name': 'fastapi_deployment_generate_k8s',
    'description': 'Generate K8s manifests: Deployment, Service, HPA, PDB, ConfigMap, Secret.',
    'tags': ['deployment', 'generator'],
    'entry': 'generate_k8s_manifests',
}

import textwrap
from pathlib import Path


def generate_k8s_manifests(
    output_dir: str,
    app_name: str = "fastapi-app",
    namespace: str = "default",
    replicas: int = 2,
    cpu_request: str = "100m",
    memory_request: str = "256Mi",
) -> dict:
    """Generate a complete set of Kubernetes manifests for production.

    Creates a ``k8s/`` subdirectory with Deployment, Service, HPA, PDB,
    ConfigMap, and Secret manifests.

    Args:
        output_dir: Root directory; manifests are written to ``<output_dir>/k8s/``.
        app_name: Application name used in metadata and labels.
        namespace: Kubernetes namespace.
        replicas: Number of initial replicas.
        cpu_request: CPU resource request (e.g. ``"100m"``).
        memory_request: Memory resource request (e.g. ``"256Mi"``).

    Returns:
        Dict with files_created and notes.
    """
    out = Path(output_dir) / "k8s"
    out.mkdir(parents=True, exist_ok=True)

    # Derive resource limits (2x requests as a sensible default)
    cpu_limit = _double_cpu(cpu_request)
    memory_limit = _double_memory(memory_request)

    files_created: list[str] = []

    # --- deployment.yaml ---
    deployment = textwrap.dedent(f"""\
        apiVersion: apps/v1
        kind: Deployment
        metadata:
          name: {app_name}
          namespace: {namespace}
          labels:
            app: {app_name}
        spec:
          replicas: {replicas}
          selector:
            matchLabels:
              app: {app_name}
          strategy:
            type: RollingUpdate
            rollingUpdate:
              maxUnavailable: 0
              maxSurge: 1
          template:
            metadata:
              labels:
                app: {app_name}
            spec:
              securityContext:
                runAsNonRoot: true
                runAsUser: 1000
                runAsGroup: 1000
                fsGroup: 1000
              containers:
                - name: {app_name}
                  image: {app_name}:latest
                  ports:
                    - containerPort: 8000
                      protocol: TCP
                  envFrom:
                    - configMapRef:
                        name: {app_name}-config
                    - secretRef:
                        name: {app_name}-secret
                  resources:
                    requests:
                      cpu: "{cpu_request}"
                      memory: "{memory_request}"
                    limits:
                      cpu: "{cpu_limit}"
                      memory: "{memory_limit}"
                  securityContext:
                    readOnlyRootFilesystem: true
                    allowPrivilegeEscalation: false
                    capabilities:
                      drop:
                        - ALL
                  livenessProbe:
                    httpGet:
                      path: /healthz
                      port: 8000
                    initialDelaySeconds: 10
                    periodSeconds: 15
                    timeoutSeconds: 5
                    failureThreshold: 3
                  readinessProbe:
                    httpGet:
                      path: /readyz
                      port: 8000
                    initialDelaySeconds: 5
                    periodSeconds: 10
                    timeoutSeconds: 5
                    failureThreshold: 3
                  startupProbe:
                    httpGet:
                      path: /startupz
                      port: 8000
                    initialDelaySeconds: 5
                    periodSeconds: 5
                    timeoutSeconds: 5
                    failureThreshold: 30
              terminationGracePeriodSeconds: 30
    """)

    p = out / "deployment.yaml"
    p.write_text(deployment)
    files_created.append(str(p))

    # --- service.yaml ---
    service = textwrap.dedent(f"""\
        apiVersion: v1
        kind: Service
        metadata:
          name: {app_name}
          namespace: {namespace}
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

    p = out / "service.yaml"
    p.write_text(service)
    files_created.append(str(p))

    # --- hpa.yaml ---
    hpa = textwrap.dedent(f"""\
        apiVersion: autoscaling/v2
        kind: HorizontalPodAutoscaler
        metadata:
          name: {app_name}
          namespace: {namespace}
          labels:
            app: {app_name}
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
          behavior:
            scaleDown:
              stabilizationWindowSeconds: 300
              policies:
                - type: Pods
                  value: 1
                  periodSeconds: 60
            scaleUp:
              stabilizationWindowSeconds: 60
              policies:
                - type: Pods
                  value: 2
                  periodSeconds: 60
    """)

    p = out / "hpa.yaml"
    p.write_text(hpa)
    files_created.append(str(p))

    # --- pdb.yaml ---
    pdb = textwrap.dedent(f"""\
        apiVersion: policy/v1
        kind: PodDisruptionBudget
        metadata:
          name: {app_name}
          namespace: {namespace}
          labels:
            app: {app_name}
        spec:
          minAvailable: 1
          selector:
            matchLabels:
              app: {app_name}
    """)

    p = out / "pdb.yaml"
    p.write_text(pdb)
    files_created.append(str(p))

    # --- configmap.yaml ---
    # Non-secret POSTGRES_* fields live in the ConfigMap; only
    # POSTGRES_PASSWORD belongs in the Secret. This matches the emitted
    # `app/core/config.py` contract — it reads POSTGRES_SERVER/PORT/
    # USER/PASSWORD/DB and builds SQLALCHEMY_DATABASE_URI from them.
    # Emitting DATABASE_URL here would be silently ignored and the
    # deployment would fall back to the `localhost` default.
    configmap = textwrap.dedent(f"""\
        apiVersion: v1
        kind: ConfigMap
        metadata:
          name: {app_name}-config
          namespace: {namespace}
          labels:
            app: {app_name}
        data:
          API_V1_STR: "/api/v1"
          PROJECT_NAME: "{app_name}"
          ENVIRONMENT: "production"
          LOG_LEVEL: "info"
          # Database wiring — password is in the Secret. The in-cluster
          # PostgreSQL Service is assumed to be reachable at `postgres`;
          # override POSTGRES_SERVER if you use an external managed DB
          # (RDS, Cloud SQL, Neon, etc.).
          POSTGRES_SERVER: "postgres"
          POSTGRES_PORT: "5432"
          POSTGRES_USER: "postgres"
          POSTGRES_DB: "{app_name}"
    """)

    p = out / "configmap.yaml"
    p.write_text(configmap)
    files_created.append(str(p))

    # --- secret.yaml ---
    secret = textwrap.dedent(f"""\
        apiVersion: v1
        kind: Secret
        metadata:
          name: {app_name}-secret
          namespace: {namespace}
          labels:
            app: {app_name}
        type: Opaque
        stringData:
          # IMPORTANT: These REPLACE_WITH_* placeholders are NOT valid
          # credentials. The application refuses to boot while any
          # setting value starts with `REPLACE_WITH_` (fail-fast check
          # in app/core/config.py — `_enforce_security_contract`).
          #
          # Fill in real values before `kubectl apply`. In production,
          # prefer sealed-secrets, external-secrets, or Vault instead of
          # committing secrets to source control.
          #
          # Generate SECRET_KEY once:
          #     openssl rand -hex 32
          #
          # POSTGRES_PASSWORD is the ONLY DB field in the Secret; the
          # non-secret POSTGRES_SERVER / PORT / USER / DB live in the
          # ConfigMap. The emitted config.py builds the DB URI from the
          # five POSTGRES_* env vars. A pre-built URI here would be
          # ignored by the pydantic-settings loader and the pod would
          # silently fall back to the localhost default.
          SECRET_KEY: "REPLACE_WITH_openssl_rand_hex_32"
          POSTGRES_PASSWORD: "REPLACE_WITH_strong_db_password"
    """)

    p = out / "secret.yaml"
    p.write_text(secret)
    files_created.append(str(p))

    return {
        "files_created": files_created,
        "notes": [
            f"Generated 6 manifests in k8s/ for '{app_name}' (namespace: {namespace}).",
            f"Deployment: {replicas} replicas, rolling update, liveness/readiness/startup probes.",
            f"Resources: {cpu_request}/{memory_request} request, {cpu_limit}/{memory_limit} limit.",
            "HPA: 2-10 replicas, 70% CPU target. PDB: minAvailable 1.",
            "Security: runAsNonRoot, readOnlyRootFilesystem, drop ALL capabilities.",
            "Secret uses stringData placeholders -- replace before applying.",
        ],
    }


def _double_cpu(cpu: str) -> str:
    """Double a Kubernetes CPU value (e.g. '100m' -> '200m', '1' -> '2')."""
    if cpu.endswith("m"):
        return f"{int(cpu[:-1]) * 2}m"
    return str(int(cpu) * 2)


def _double_memory(memory: str) -> str:
    """Double a Kubernetes memory value (e.g. '256Mi' -> '512Mi')."""
    for suffix in ("Gi", "Mi", "Ki"):
        if memory.endswith(suffix):
            return f"{int(memory[: -len(suffix)]) * 2}{suffix}"
    return str(int(memory) * 2)
