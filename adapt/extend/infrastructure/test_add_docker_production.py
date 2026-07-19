"""Tests for TOOL-092 add_docker_production.

Generates real fixture projects via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the MEGA_BRIEFING spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_docker_production.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_docker_production.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_docker_production import add_docker_production
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
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if hasattr(node, "end_lineno") and node.end_lineno:
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
    project_dir = _fresh("docker_t01")
    result = add_docker_production(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


# ---------------------------------------------------------------------------
# CC-02 — idempotency
# ---------------------------------------------------------------------------

def test_idempotent() -> None:
    """Second run returns status='no_op' without touching files."""
    project_dir = _fresh("docker_t02")
    r1 = add_docker_production(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_docker_production(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


# ---------------------------------------------------------------------------
# CC-03 — dry_run
# ---------------------------------------------------------------------------

def test_dry_run() -> None:
    """dry_run=True returns success but writes no files."""
    project_dir = _fresh("docker_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_docker_production(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


# ---------------------------------------------------------------------------
# CC-04 — files_created count
# ---------------------------------------------------------------------------

def test_files_created_count() -> None:
    """Tool creates at least 3 files (Dockerfile, compose, entrypoint; .dockerignore may pre-exist)."""
    project_dir = _fresh("docker_t04")
    result = add_docker_production(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 3, (
        f"Expected >= 3 files_created, got {len(result.files_created)}: {result.files_created}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-05 — files_modified count
# ---------------------------------------------------------------------------

def test_files_modified_count() -> None:
    """Tool modifies at least 1 file (config.py)."""
    project_dir = _fresh("docker_t05")
    result = add_docker_production(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_modified) >= 1, (
        f"Expected >= 1 files_modified, got {len(result.files_modified)}: {result.files_modified}"
    )
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-06 — all .py files parse
# ---------------------------------------------------------------------------

def test_all_py_parse() -> None:
    """Every generated .py file AST-parses clean."""
    project_dir = _fresh("docker_t06")
    add_docker_production(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# CC-07 — no function over 50 LOC
# ---------------------------------------------------------------------------

def test_no_function_over_50_loc() -> None:
    """No function in generated app/ exceeds 50 LOC."""
    project_dir = _fresh("docker_t07")
    add_docker_production(ToolInput(project_dir=str(project_dir)))
    max_loc = _max_function_loc(project_dir, "app")
    assert max_loc <= 50, f"Found function with {max_loc} LOC (limit: 50)"


# ---------------------------------------------------------------------------
# CC-08 — config fields patched
# ---------------------------------------------------------------------------

def test_config_fields_patched() -> None:
    """DOCKER_WORKERS, DOCKER_PORT, DOCKER_HEALTH_PATH exist inside Settings."""
    project_dir = _fresh("docker_t08")
    add_docker_production(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    for field in ("DOCKER_WORKERS", "DOCKER_PORT", "DOCKER_HEALTH_PATH"):
        assert field in content, f"Config field {field} not found in config.py"
    # Verify 4-space indent (field is inside the Settings class body)
    for line in content.splitlines():
        if "DOCKER_WORKERS" in line:
            assert line.startswith("    "), (
                f"DOCKER_WORKERS not inside class body (no 4-space indent): {line!r}"
            )
            break


# ---------------------------------------------------------------------------
# CC-09 — models __init__ (not applicable, no model created)
# ---------------------------------------------------------------------------

def test_no_spurious_models_init_changes() -> None:
    """Tool does not write spurious content to app/models/__init__.py."""
    project_dir = _fresh("docker_t09")
    models_init = project_dir / "app" / "models" / "__init__.py"
    before = models_init.read_text() if models_init.exists() else None
    add_docker_production(ToolInput(project_dir=str(project_dir)))
    after = models_init.read_text() if models_init.exists() else None
    # models/__init__.py must not gain unrelated content
    assert before == after, "Tool must not modify models/__init__.py"


# ---------------------------------------------------------------------------
# CC-10 — routes __init__ (not applicable, no routes created)
# ---------------------------------------------------------------------------

def test_no_spurious_routes_init_changes() -> None:
    """Tool does not add any router to app/routes/__init__.py."""
    project_dir = _fresh("docker_t10")
    routes_init = project_dir / "app" / "routes" / "__init__.py"
    before = routes_init.read_text() if routes_init.exists() else None
    add_docker_production(ToolInput(project_dir=str(project_dir)))
    after = routes_init.read_text() if routes_init.exists() else None
    assert before == after, "Tool must not modify routes/__init__.py"


# ---------------------------------------------------------------------------
# CC-11 — Dockerfile created with HEALTHCHECK
# ---------------------------------------------------------------------------

def test_dockerfile_created_with_healthcheck() -> None:
    """Dockerfile exists and contains HEALTHCHECK directive."""
    project_dir = _fresh("docker_t11")
    add_docker_production(ToolInput(project_dir=str(project_dir)))
    dockerfile = project_dir / "Dockerfile"
    assert dockerfile.exists(), "Dockerfile not created"
    content = dockerfile.read_text()
    assert "HEALTHCHECK" in content, "Dockerfile missing HEALTHCHECK directive"
    # Our production Dockerfile always sets HEALTHCHECK (overrides base)
    assert "gunicorn" in content, "Production Dockerfile must use gunicorn"


# ---------------------------------------------------------------------------
# CC-12 — Dockerfile multi-stage (builder + runtime)
# ---------------------------------------------------------------------------

def test_dockerfile_multistage() -> None:
    """Dockerfile contains both 'builder' and 'runtime' build stages."""
    project_dir = _fresh("docker_t12")
    add_docker_production(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "Dockerfile").read_text()
    assert "builder" in content, "Dockerfile missing 'builder' stage"
    assert "runtime" in content, "Dockerfile missing 'runtime' stage"


# ---------------------------------------------------------------------------
# CC-13 — Dockerfile non-root USER
# ---------------------------------------------------------------------------

def test_dockerfile_nonroot_user() -> None:
    """Dockerfile sets USER to non-root (1000)."""
    project_dir = _fresh("docker_t13")
    add_docker_production(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "Dockerfile").read_text()
    assert "USER 1000" in content or "USER appuser" in content, (
        "Dockerfile must run as non-root USER"
    )


# ---------------------------------------------------------------------------
# CC-14 — .dockerignore created
# ---------------------------------------------------------------------------

def test_dockerignore_created() -> None:
    """.dockerignore exists and excludes __pycache__ and .venv."""
    project_dir = _fresh("docker_t14")
    add_docker_production(ToolInput(project_dir=str(project_dir)))
    dockerignore = project_dir / ".dockerignore"
    assert dockerignore.exists(), ".dockerignore not created"
    content = dockerignore.read_text()
    assert "__pycache__" in content, ".dockerignore must exclude __pycache__"
    assert ".venv" in content or "venv" in content, ".dockerignore must exclude venv"


# ---------------------------------------------------------------------------
# CC-15 — docker-compose.prod.yml created
# ---------------------------------------------------------------------------

def test_compose_prod_created() -> None:
    """docker-compose.prod.yml exists with postgres and redis services."""
    project_dir = _fresh("docker_t15")
    add_docker_production(ToolInput(project_dir=str(project_dir)))
    compose = project_dir / "docker-compose.prod.yml"
    assert compose.exists(), "docker-compose.prod.yml not created"
    content = compose.read_text()
    assert "postgres" in content.lower(), "compose file missing postgres service"
    assert "redis" in content.lower(), "compose file missing redis service"


# ---------------------------------------------------------------------------
# CC-16 — entrypoint.sh created
# ---------------------------------------------------------------------------

def test_entrypoint_created() -> None:
    """scripts/docker-entrypoint.sh exists and references alembic upgrade."""
    project_dir = _fresh("docker_t16")
    add_docker_production(ToolInput(project_dir=str(project_dir)))
    entrypoint = project_dir / "scripts" / "docker-entrypoint.sh"
    assert entrypoint.exists(), "scripts/docker-entrypoint.sh not created"
    content = entrypoint.read_text()
    assert "alembic upgrade" in content, "entrypoint.sh must run alembic upgrade head"


# ---------------------------------------------------------------------------
# CC-17 — compose has restart policies
# ---------------------------------------------------------------------------

def test_compose_has_restart_policies() -> None:
    """docker-compose.prod.yml services have restart policies."""
    project_dir = _fresh("docker_t17")
    add_docker_production(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "docker-compose.prod.yml").read_text()
    assert "restart" in content, "docker-compose.prod.yml must define restart policies"


# ---------------------------------------------------------------------------
# CC-N-1 — execution time recorded
# ---------------------------------------------------------------------------

def test_execution_time_recorded() -> None:
    """execution_time_ms must be a positive integer."""
    project_dir = _fresh("docker_t18")
    result = add_docker_production(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


# ---------------------------------------------------------------------------
# CC-N — next_steps present
# ---------------------------------------------------------------------------

def test_next_steps_present() -> None:
    """next_steps guides developer to build and run the container."""
    project_dir = _fresh("docker_t19")
    result = add_docker_production(ToolInput(project_dir=str(project_dir)))
    assert len(result.next_steps) > 0, "next_steps must not be empty"
    combined = " ".join(result.next_steps).lower()
    assert "docker" in combined, "next_steps should mention docker"


# ---------------------------------------------------------------------------
# CC-LAST — idempotent project still parses
# ---------------------------------------------------------------------------

def test_idempotent_project_still_parses() -> None:
    """After two runs all .py files remain parseable."""
    project_dir = _fresh("docker_t20")
    add_docker_production(ToolInput(project_dir=str(project_dir)))
    add_docker_production(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# Additional domain tests
# ---------------------------------------------------------------------------

def test_pip_cache_mount_in_dockerfile() -> None:
    """Dockerfile uses RUN --mount=type=cache for pip caching."""
    project_dir = _fresh("docker_t21")
    add_docker_production(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "Dockerfile").read_text()
    assert "--mount=type=cache" in content, "Dockerfile must use pip cache mount"


def test_gunicorn_uvicorn_in_dockerfile() -> None:
    """Dockerfile CMD uses gunicorn with UvicornWorker."""
    project_dir = _fresh("docker_t22")
    add_docker_production(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "Dockerfile").read_text()
    assert "gunicorn" in content, "Dockerfile must use gunicorn"
    assert "UvicornWorker" in content or "uvicorn.workers" in content, (
        "Dockerfile must use uvicorn workers"
    )


def test_compose_has_healthchecks() -> None:
    """docker-compose.prod.yml services have healthcheck definitions."""
    project_dir = _fresh("docker_t23")
    add_docker_production(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "docker-compose.prod.yml").read_text()
    assert "healthcheck" in content, "docker-compose.prod.yml must define healthchecks"


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
        test_dockerfile_created_with_healthcheck,
        test_dockerfile_multistage,
        test_dockerfile_nonroot_user,
        test_dockerignore_created,
        test_compose_prod_created,
        test_entrypoint_created,
        test_compose_has_restart_policies,
        test_execution_time_recorded,
        test_next_steps_present,
        test_idempotent_project_still_parses,
        test_pip_cache_mount_in_dockerfile,
        test_gunicorn_uvicorn_in_dockerfile,
        test_compose_has_healthchecks,
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

    print(f"\n{'='*60}")
    print(f"TOOL-092 add_docker_production: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
