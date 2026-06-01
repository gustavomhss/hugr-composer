"""Tests for TOOL-093 add_kubernetes_manifests.

Generates real fixture projects via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the MEGA_BRIEFING spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_kubernetes_manifests.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_kubernetes_manifests.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_kubernetes_manifests import add_kubernetes_manifests
from tests.common.fixture_factory import create_fixture_project

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _all_py_files(root: Path) -> list[Path]:
    """Return all .py files under *root* sorted alphabetically.

    Args:
        root: Directory to search recursively.

    Returns:
        Sorted list of .py file paths.
    """
    return sorted(root.rglob("*.py"))


def _assert_parse(root: Path) -> None:
    """Assert every .py file under *root* has valid AST syntax.

    Args:
        root: Directory to walk recursively.

    Raises:
        AssertionError: On syntax error in any generated file.
    """
    for f in _all_py_files(root):
        source = f.read_text()
        try:
            ast.parse(source)
        except SyntaxError as exc:
            raise AssertionError(f"SyntaxError in {f}: {exc}") from exc


def _max_function_loc(root: Path, subdir: str = "app") -> int:
    """Return the maximum LOC of any function in the given subdir.

    Args:
        root: Project root directory.
        subdir: Subdirectory to scan (default ``"app"``).

    Returns:
        Maximum function LOC found, or 0 if none found.
    """
    target = root / subdir
    if not target.exists():
        return 0
    max_loc = 0
    for f in sorted(target.rglob("*.py")):
        try:
            tree = ast.parse(f.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and getattr(
                node, "end_lineno", None
            ):
                loc = node.end_lineno - node.lineno + 1
                max_loc = max(max_loc, loc)
    return max_loc


def _fresh(name: str) -> Path:
    """Return a freshly generated fixture project.

    Args:
        name: Unique project name to avoid cross-test collisions.

    Returns:
        Path to the generated project root.
    """
    return create_fixture_project(name=name)


# ---------------------------------------------------------------------------
# CC-01 — success status
# ---------------------------------------------------------------------------


def test_success_status() -> None:
    """Tool returns status='success' on a fresh project."""
    project_dir = _fresh("k8s_t01")
    result = add_kubernetes_manifests(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


# ---------------------------------------------------------------------------
# CC-02 — idempotency
# ---------------------------------------------------------------------------


def test_idempotent() -> None:
    """Second run returns status='no_op' without touching files."""
    project_dir = _fresh("k8s_t02")
    r1 = add_kubernetes_manifests(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_kubernetes_manifests(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


# ---------------------------------------------------------------------------
# CC-03 — dry_run
# ---------------------------------------------------------------------------


def test_dry_run() -> None:
    """dry_run=True returns success but writes no files."""
    project_dir = _fresh("k8s_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_kubernetes_manifests(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


# ---------------------------------------------------------------------------
# CC-04 — files_created count
# ---------------------------------------------------------------------------


def test_files_created_count() -> None:
    """Tool creates exactly 7 k8s YAML manifests."""
    project_dir = _fresh("k8s_t04")
    result = add_kubernetes_manifests(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    yaml_files = [p for p in result.files_created if p.endswith(".yaml")]
    assert len(yaml_files) >= 7, (
        f"Expected >= 7 YAML files_created, got {len(yaml_files)}: {yaml_files}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-05 — files_modified count
# ---------------------------------------------------------------------------


def test_files_modified_count() -> None:
    """Tool modifies at least 1 file (config.py)."""
    project_dir = _fresh("k8s_t05")
    result = add_kubernetes_manifests(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_modified) >= 1, (
        f"Expected >= 1 files_modified, got {len(result.files_modified)}"
    )
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-06 — all .py files parse
# ---------------------------------------------------------------------------


def test_all_py_parse() -> None:
    """Every generated .py file AST-parses clean."""
    project_dir = _fresh("k8s_t06")
    add_kubernetes_manifests(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# CC-07 — no function over 50 LOC
# ---------------------------------------------------------------------------


def test_no_function_over_50_loc() -> None:
    """No function in generated app/ exceeds 50 LOC."""
    project_dir = _fresh("k8s_t07")
    add_kubernetes_manifests(ToolInput(project_dir=str(project_dir)))
    max_loc = _max_function_loc(project_dir, "app")
    assert max_loc <= 50, f"Found function with {max_loc} LOC (limit: 50)"


# ---------------------------------------------------------------------------
# CC-08 — config fields patched
# ---------------------------------------------------------------------------


def test_config_fields_patched() -> None:
    """K8S_* settings fields exist inside Settings in config.py."""
    project_dir = _fresh("k8s_t08")
    add_kubernetes_manifests(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    for field in ("K8S_REPLICAS", "K8S_CPU_LIMIT", "K8S_MEMORY_LIMIT", "K8S_NAMESPACE"):
        assert field in content, f"Config field {field} not found in config.py"
    # Verify 4-space indent (field is inside the Settings class body)
    for line in content.splitlines():
        if "K8S_REPLICAS" in line:
            assert line.startswith("    "), (
                f"K8S_REPLICAS not inside class body (no 4-space indent): {line!r}"
            )
            break


# ---------------------------------------------------------------------------
# CC-09 — models __init__ not touched
# ---------------------------------------------------------------------------


def test_no_spurious_models_init_changes() -> None:
    """Tool does not modify app/models/__init__.py."""
    project_dir = _fresh("k8s_t09")
    models_init = project_dir / "app" / "models" / "__init__.py"
    before = models_init.read_text() if models_init.exists() else None
    add_kubernetes_manifests(ToolInput(project_dir=str(project_dir)))
    after = models_init.read_text() if models_init.exists() else None
    assert before == after, "Tool must not modify models/__init__.py"


# ---------------------------------------------------------------------------
# CC-10 — routes __init__ not touched
# ---------------------------------------------------------------------------


def test_no_spurious_routes_init_changes() -> None:
    """Tool does not modify app/routes/__init__.py."""
    project_dir = _fresh("k8s_t10")
    routes_init = project_dir / "app" / "routes" / "__init__.py"
    before = routes_init.read_text() if routes_init.exists() else None
    add_kubernetes_manifests(ToolInput(project_dir=str(project_dir)))
    after = routes_init.read_text() if routes_init.exists() else None
    assert before == after, "Tool must not modify routes/__init__.py"


# ---------------------------------------------------------------------------
# CC-11 — deployment.yaml created
# ---------------------------------------------------------------------------


def test_deployment_yaml_created() -> None:
    """k8s/deployment.yaml exists with readiness and liveness probes."""
    project_dir = _fresh("k8s_t11")
    add_kubernetes_manifests(ToolInput(project_dir=str(project_dir)))
    deployment = project_dir / "k8s" / "deployment.yaml"
    assert deployment.exists(), "k8s/deployment.yaml not created"
    content = deployment.read_text()
    assert "readinessProbe" in content, "deployment.yaml missing readinessProbe"
    assert "livenessProbe" in content, "deployment.yaml missing livenessProbe"


def test_liveness_and_readiness_use_distinct_probes() -> None:
    """R6-S11-F1: liveness and readiness must hit DIFFERENT endpoints.

    Pre-fix both probes pointed at /healthz, so a DB outage failed the liveness
    probe and Kubernetes RESTARTED the pod (restart loop) instead of merely
    removing it from the Service via a failed readiness probe. Readiness must use
    the deep /readyz check (503 until DB reachable); liveness the shallow
    /healthz (process-alive, no deps); plus a startupProbe so a slow boot does
    not trip liveness.
    """
    import yaml

    project_dir = _fresh("k8s_probes")
    add_kubernetes_manifests(ToolInput(project_dir=str(project_dir)))
    doc = yaml.safe_load((project_dir / "k8s" / "deployment.yaml").read_text())
    container = doc["spec"]["template"]["spec"]["containers"][0]
    readiness = container["readinessProbe"]["httpGet"]["path"]
    liveness = container["livenessProbe"]["httpGet"]["path"]
    assert readiness == "/readyz", f"readinessProbe must hit the deep /readyz, got {readiness!r}"
    assert liveness == "/healthz", f"livenessProbe must hit the shallow /healthz, got {liveness!r}"
    assert readiness != liveness, (
        "liveness and readiness must NOT share one endpoint — a dep outage would "
        "restart the pod instead of draining it (R6-S11-F1)"
    )
    assert "startupProbe" in container, "deployment must define a startupProbe for slow boots"
    assert container["startupProbe"]["httpGet"]["path"] == "/startupz"


# ---------------------------------------------------------------------------
# CC-12 — service.yaml created
# ---------------------------------------------------------------------------


def test_service_yaml_created() -> None:
    """k8s/service.yaml exists as ClusterIP service."""
    project_dir = _fresh("k8s_t12")
    add_kubernetes_manifests(ToolInput(project_dir=str(project_dir)))
    service = project_dir / "k8s" / "service.yaml"
    assert service.exists(), "k8s/service.yaml not created"
    content = service.read_text()
    assert "ClusterIP" in content, "service.yaml must use ClusterIP type"


# ---------------------------------------------------------------------------
# CC-13 — hpa.yaml created
# ---------------------------------------------------------------------------


def test_hpa_yaml_created() -> None:
    """k8s/hpa.yaml exists with HorizontalPodAutoscaler and CPU/memory metrics."""
    project_dir = _fresh("k8s_t13")
    add_kubernetes_manifests(ToolInput(project_dir=str(project_dir)))
    hpa = project_dir / "k8s" / "hpa.yaml"
    assert hpa.exists(), "k8s/hpa.yaml not created"
    content = hpa.read_text()
    assert "HorizontalPodAutoscaler" in content, "hpa.yaml missing HPA kind"
    assert "cpu" in content.lower(), "hpa.yaml missing CPU metric"
    assert "memory" in content.lower(), "hpa.yaml missing memory metric"


# ---------------------------------------------------------------------------
# CC-14 — pdb.yaml created
# ---------------------------------------------------------------------------


def test_pdb_yaml_created() -> None:
    """k8s/pdb.yaml exists with PodDisruptionBudget and minAvailable."""
    project_dir = _fresh("k8s_t14")
    add_kubernetes_manifests(ToolInput(project_dir=str(project_dir)))
    pdb = project_dir / "k8s" / "pdb.yaml"
    assert pdb.exists(), "k8s/pdb.yaml not created"
    content = pdb.read_text()
    assert "PodDisruptionBudget" in content, "pdb.yaml missing PDB kind"
    assert "minAvailable" in content, "pdb.yaml missing minAvailable"


# ---------------------------------------------------------------------------
# CC-15 — configmap.yaml and secret.yaml created
# ---------------------------------------------------------------------------


def test_configmap_and_secret_created() -> None:
    """k8s/configmap.yaml and k8s/secret.yaml both exist."""
    project_dir = _fresh("k8s_t15")
    add_kubernetes_manifests(ToolInput(project_dir=str(project_dir)))
    configmap = project_dir / "k8s" / "configmap.yaml"
    secret = project_dir / "k8s" / "secret.yaml"
    assert configmap.exists(), "k8s/configmap.yaml not created"
    assert secret.exists(), "k8s/secret.yaml not created"
    assert "ConfigMap" in configmap.read_text(), "configmap.yaml missing ConfigMap kind"
    assert "Secret" in secret.read_text(), "secret.yaml missing Secret kind"


# ---------------------------------------------------------------------------
# CC-16 — ingress.yaml created
# ---------------------------------------------------------------------------


def test_ingress_yaml_created() -> None:
    """k8s/ingress.yaml exists with nginx annotations and TLS."""
    project_dir = _fresh("k8s_t16")
    add_kubernetes_manifests(ToolInput(project_dir=str(project_dir)))
    ingress = project_dir / "k8s" / "ingress.yaml"
    assert ingress.exists(), "k8s/ingress.yaml not created"
    content = ingress.read_text()
    assert "nginx" in content, "ingress.yaml missing nginx annotations"
    assert "tls" in content.lower(), "ingress.yaml missing TLS configuration"


# ---------------------------------------------------------------------------
# CC-17 — resource limits in deployment
# ---------------------------------------------------------------------------


def test_deployment_has_resource_limits() -> None:
    """k8s/deployment.yaml defines CPU and memory resource limits."""
    project_dir = _fresh("k8s_t17")
    add_kubernetes_manifests(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "k8s" / "deployment.yaml").read_text()
    assert "limits" in content, "deployment.yaml missing resource limits"
    assert "cpu" in content, "deployment.yaml missing CPU limit"
    assert "memory" in content, "deployment.yaml missing memory limit"


# ---------------------------------------------------------------------------
# CC-N-1 — execution time recorded
# ---------------------------------------------------------------------------


def test_execution_time_recorded() -> None:
    """execution_time_ms must be a positive integer."""
    project_dir = _fresh("k8s_t18")
    result = add_kubernetes_manifests(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


# ---------------------------------------------------------------------------
# CC-N — next_steps present
# ---------------------------------------------------------------------------


def test_next_steps_present() -> None:
    """next_steps guides developer to apply manifests with kubectl."""
    project_dir = _fresh("k8s_t19")
    result = add_kubernetes_manifests(ToolInput(project_dir=str(project_dir)))
    assert len(result.next_steps) > 0, "next_steps must not be empty"
    combined = " ".join(result.next_steps).lower()
    assert "kubectl" in combined, "next_steps should mention kubectl"


# ---------------------------------------------------------------------------
# CC-LAST — idempotent project still parses
# ---------------------------------------------------------------------------


def test_idempotent_project_still_parses() -> None:
    """After two runs all .py files remain parseable."""
    project_dir = _fresh("k8s_t20")
    add_kubernetes_manifests(ToolInput(project_dir=str(project_dir)))
    add_kubernetes_manifests(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# Additional domain tests
# ---------------------------------------------------------------------------


def test_k8s_dir_has_all_seven_files() -> None:
    """The k8s/ directory contains exactly 7 manifest files."""
    project_dir = _fresh("k8s_t21")
    add_kubernetes_manifests(ToolInput(project_dir=str(project_dir)))
    k8s_dir = project_dir / "k8s"
    yaml_files = list(k8s_dir.glob("*.yaml"))
    assert len(yaml_files) == 7, (
        f"Expected 7 YAML files in k8s/, found {len(yaml_files)}: {[f.name for f in yaml_files]}"
    )


def test_secret_has_placeholder_warning() -> None:
    """k8s/secret.yaml contains a comment warning about placeholder values."""
    project_dir = _fresh("k8s_t22")
    add_kubernetes_manifests(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "k8s" / "secret.yaml").read_text()
    assert "placeholder" in content.lower() or "IMPORTANT" in content or "Replace" in content, (
        "secret.yaml must warn operators to replace placeholder values"
    )


def test_deployment_has_env_from_configmap_and_secret() -> None:
    """k8s/deployment.yaml references both ConfigMap and Secret via envFrom."""
    project_dir = _fresh("k8s_t23")
    add_kubernetes_manifests(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "k8s" / "deployment.yaml").read_text()
    assert "configMapRef" in content, "deployment.yaml must reference ConfigMap"
    assert "secretRef" in content, "deployment.yaml must reference Secret"


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_success_status,
        test_idempotent,
        test_dry_run,
        test_files_created_count,
        test_files_modified_count,
        test_all_py_parse,
        test_no_function_over_50_loc,
        test_config_fields_patched,
        test_no_spurious_models_init_changes,
        test_no_spurious_routes_init_changes,
        test_deployment_yaml_created,
        test_liveness_and_readiness_use_distinct_probes,
        test_service_yaml_created,
        test_hpa_yaml_created,
        test_pdb_yaml_created,
        test_configmap_and_secret_created,
        test_ingress_yaml_created,
        test_deployment_has_resource_limits,
        test_execution_time_recorded,
        test_next_steps_present,
        test_idempotent_project_still_parses,
        test_k8s_dir_has_all_seven_files,
        test_secret_has_placeholder_warning,
        test_deployment_has_env_from_configmap_and_secret,
    ]

    passed = failed = 0
    for test_fn in tests:
        try:
            test_fn()
            print(f"  PASS  {test_fn.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {test_fn.__name__}: {exc}")
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"TOOL-093 add_kubernetes_manifests: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
