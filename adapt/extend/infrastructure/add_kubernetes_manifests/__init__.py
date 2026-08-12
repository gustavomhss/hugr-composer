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

The tool is idempotent: a second run detects the ``HorizontalPodAutoscaler``
fingerprint in ``k8s/hpa.yaml`` and returns ``status="no_op"``.

Warnings:
    - The deployment probes target /healthz (liveness), /readyz (readiness) and
      /startupz (startup). This tool does NOT generate those endpoints; create
      them with fastapi_api_generate_health first, or repoint the probes at the
      endpoint your app actually serves — otherwise the pod never becomes Ready.
    - Generated k8s/secret.yaml contains placeholder base64 values; replace ALL
      placeholders before applying to a production cluster.
    - Generated manifests do not include resource limits at the namespace level
      (LimitRange/ResourceQuota); add those separately for production clusters.
    - The k8s/secret.yaml file should NOT be committed to version control;
      use a secrets manager (e.g. Vault, AWS Secrets Manager) instead.
"""

from __future__ import annotations

import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.tool_result import _elapsed_ms

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_resiliency_add_kubernetes_manifests",
    "description": (
        "Generate production-ready Kubernetes manifests: Deployment, Service, HPA, "
        "PDB, ConfigMap, Secret, and Ingress YAML files."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_kubernetes_manifests",
    "imports_primitives": [],
    "imports_adapters": [],

}

# Template file names for the 7 manifests
_MANIFESTS = [
    ("deployment.yaml.tmpl", "deployment.yaml"),
    ("service.yaml.tmpl", "service.yaml"),
    ("hpa.yaml.tmpl", "hpa.yaml"),
    ("pdb.yaml.tmpl", "pdb.yaml"),
    ("configmap.yaml.tmpl", "configmap.yaml"),
    ("secret.yaml.tmpl", "secret.yaml"),
    ("ingress.yaml.tmpl", "ingress.yaml"),
]


def add_kubernetes_manifests(inp: ToolInput) -> ToolResult:
    """Generate production-ready Kubernetes manifests for a FastAPI project.

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
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

    from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

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

    hpa_file = project / "k8s" / "hpa.yaml"
    if hpa_file.exists() and "HorizontalPodAutoscaler" in hpa_file.read_text():
        return ToolResult(
            status="no_op",
            notes=[
                "HorizontalPodAutoscaler already present in k8s/hpa.yaml — K8s manifests already installed, skipped."
            ],
            execution_time_ms=_elapsed_ms(start),
        )

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

    app_name = project.name.lower().replace("_", "-").replace(" ", "-") or "fastapi-app"

    for tmpl_name, out_name in _MANIFESTS:
        dest = k8s_dir / out_name
        _write_yaml_from_tmpl(tmpl_name, dest, app_name)
        files_created.append(str(dest))

    config_file = project / "app" / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    _emit_project_test(project, files_created)

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            f"Kubernetes manifests generated in k8s/ for app '{app_name}':",
            "  deployment.yaml: readiness/liveness/startup probes, resource limits, ConfigMap/Secret env.",
            "  REQUIRED ENDPOINTS: the probes assume the app exposes /healthz (liveness),",
            "    /readyz (readiness) and /startupz (startup). This tool does NOT create them —",
            "    generate them with fastapi_api_generate_health first, or the pod will never",
            "    become Ready / will CrashLoop. /healthz-only apps must repoint readiness +",
            "    startup probes at /healthz in k8s/deployment.yaml before applying.",
            "  service.yaml: ClusterIP on port 8000.",
            "  hpa.yaml: autoscales 2-10 replicas on CPU (70%) and memory (80%).",
            "  pdb.yaml: minAvailable=1 to protect rolling deployments.",
            "  configmap.yaml: non-secret runtime config (ENVIRONMENT, LOG_LEVEL).",
            "  secret.yaml: template with base64 placeholder values — fill before applying.",
            "  ingress.yaml: nginx class, TLS termination, proxy-body-size annotation.",
            "Config fields added: K8S_REPLICAS, K8S_CPU_LIMIT, K8S_MEMORY_LIMIT, K8S_NAMESPACE.",
        ],
        next_steps=[
            "Ensure the app exposes /healthz, /readyz and /startupz (run "
            "fastapi_api_generate_health) — the probes depend on all three, or repoint "
            "readiness + startup probes at /healthz in k8s/deployment.yaml.",
            "Edit k8s/secret.yaml: replace all <base64-encoded-...> placeholders.",
            "Edit k8s/ingress.yaml: replace 'your-app.example.com' with your domain.",
            "kubectl create namespace ${K8S_NAMESPACE:-production}",
            "kubectl apply -f k8s/",
            "kubectl rollout status deployment/fastapi-app -n ${K8S_NAMESPACE:-production}",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _write_yaml_from_tmpl(tmpl_name: str, dest: Path, app_name: str) -> None:
    """Read a YAML template verbatim and substitute APP_NAME placeholder."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = (_HERE / "templates" / tmpl_name).read_text()
    content = content.replace("APP_NAME", app_name)
    dest.write_text(content)


def _emit_project_test(project: Path, created: list[str]) -> None:
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_kubernetes_manifests_emitted.py"
    if emitted.exists():
        return
    render_to(
        _HERE, "test_add_kubernetes_manifests_emitted.py.tmpl", dest=emitted, substitutions={}
    )
    created.append(str(emitted))


def _patch_config(config_file: Path) -> None:
    """Inject K8s settings fields inside the ``class Settings`` body."""
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


