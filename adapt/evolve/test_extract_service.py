"""Tests for TOOL-045 extract_service.

Run with::

    PYTHONPATH=. pytest adapt/evolve/test_extract_service.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/evolve/test_extract_service.py
"""

from __future__ import annotations

import ast
import json
import sys
import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.evolve.extract_service import extract_service


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_project(tmp: Path) -> Path:
    """Create a minimal FastAPI monolith project for testing.

    Args:
        tmp: Parent temp directory.

    Returns:
        Path to project root.
    """
    project = tmp / "monolith"
    project.mkdir(parents=True, exist_ok=True)
    app_dir = project / "app"
    app_dir.mkdir()
    # Minimal main.py
    (app_dir / "main.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n"
    )
    # Prereq files
    (app_dir / "models").mkdir(parents=True, exist_ok=True)
    (app_dir / "models" / "base.py").write_text(
        "from sqlalchemy.orm import DeclarativeBase\nclass Base(DeclarativeBase): pass\n"
    )
    (app_dir / "core").mkdir(parents=True, exist_ok=True)
    (app_dir / "core" / "config.py").write_text(
        "from pydantic_settings import BaseSettings\nclass Settings(BaseSettings): pass\nsettings = Settings()\n"
    )
    # Sample route
    routes_dir = app_dir / "routes"
    routes_dir.mkdir()
    (routes_dir / "billing.py").write_text(
        "from fastapi import APIRouter\nrouter = APIRouter()\n"
    )
    return project


def _assert_parse(path: Path) -> None:
    src = path.read_text()
    try:
        ast.parse(src)
    except SyntaxError as exc:
        raise AssertionError(f"SyntaxError in {path}: {exc}") from exc


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_success_status() -> None:
    """T-01: Tool returns status='success' on fresh monolith."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        result = extract_service(
            ToolInput(project_dir=str(project)),
            module_paths=["app/routes/billing.py"],
            new_service_name="billing_service",
        )
        assert result.status == "success", f"Expected success: {result.error}"


def test_invalid_protocol_returns_error() -> None:
    """T-02: Invalid communication protocol must return status='error'."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        result = extract_service(
            ToolInput(project_dir=str(project)),
            new_service_name="billing_service",
            communication="telepathy",
        )
        assert result.status == "error"
        assert "telepathy" in result.error


def test_service_directory_created() -> None:
    """T-03: New service directory must exist after tool run."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        extract_service(
            ToolInput(project_dir=str(project)),
            new_service_name="billing_service",
        )
        service_dir = project.parent / "billing_service"
        assert service_dir.exists(), "Service directory not created"


def test_service_main_py_created() -> None:
    """T-04: New service must have main.py."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        extract_service(
            ToolInput(project_dir=str(project)),
            new_service_name="billing_service",
        )
        main_py = project.parent / "billing_service" / "main.py"
        assert main_py.exists(), "main.py not created in new service"


def test_service_main_parses() -> None:
    """T-05: New service main.py must be valid Python."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        extract_service(
            ToolInput(project_dir=str(project)),
            new_service_name="billing_service",
        )
        _assert_parse(project.parent / "billing_service" / "main.py")


def test_service_dockerfile_created() -> None:
    """T-06: New service must have a Dockerfile."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        extract_service(
            ToolInput(project_dir=str(project)),
            new_service_name="billing_service",
            new_service_port=8001,
        )
        dockerfile = project.parent / "billing_service" / "Dockerfile"
        assert dockerfile.exists(), "Dockerfile not created"
        assert "8001" in dockerfile.read_text()


def test_service_requirements_created() -> None:
    """T-07: New service must have requirements.txt."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        extract_service(
            ToolInput(project_dir=str(project)),
            new_service_name="billing_service",
        )
        req = project.parent / "billing_service" / "requirements.txt"
        assert req.exists(), "requirements.txt not created"
        assert "fastapi" in req.read_text().lower()


def test_contract_test_created() -> None:
    """T-08: New service must have a contract test stub."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        extract_service(
            ToolInput(project_dir=str(project)),
            new_service_name="billing_service",
        )
        test_file = project.parent / "billing_service" / "tests" / "test_contract_health.py"
        assert test_file.exists(), "Contract test not created"


def test_contract_test_parses() -> None:
    """T-09: Contract test must be valid Python."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        extract_service(
            ToolInput(project_dir=str(project)),
            new_service_name="billing_service",
        )
        test_file = project.parent / "billing_service" / "tests" / "test_contract_health.py"
        _assert_parse(test_file)


def test_http_client_created_when_generate_client_true() -> None:
    """T-10: Typed httpx client must be created in monolith when generate_client=True."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        extract_service(
            ToolInput(project_dir=str(project)),
            new_service_name="billing_service",
            generate_client=True,
            communication="http",
        )
        client_file = project / "app" / "clients" / "billing_service_client.py"
        assert client_file.exists(), "httpx client not created in monolith"


def test_http_client_parses() -> None:
    """T-11: Generated httpx client must be valid Python."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        extract_service(
            ToolInput(project_dir=str(project)),
            new_service_name="billing_service",
            generate_client=True,
            communication="http",
        )
        client_file = project / "app" / "clients" / "billing_service_client.py"
        if client_file.exists():
            _assert_parse(client_file)


def test_extraction_manifest_created() -> None:
    """T-12: EXTRACTION_MANIFEST.json must be created in monolith."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        extract_service(
            ToolInput(project_dir=str(project)),
            new_service_name="billing_service",
        )
        manifest = project / "EXTRACTION_MANIFEST.json"
        assert manifest.exists(), "EXTRACTION_MANIFEST.json not created"


def test_extraction_manifest_valid_json() -> None:
    """T-13: EXTRACTION_MANIFEST.json must be valid JSON."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        extract_service(
            ToolInput(project_dir=str(project)),
            new_service_name="billing_service",
            module_paths=["app/routes/billing.py"],
        )
        manifest = json.loads((project / "EXTRACTION_MANIFEST.json").read_text())
        assert manifest["new_service"] == "billing_service"
        assert "files_created" in manifest


def test_idempotency_returns_no_op() -> None:
    """T-14: Second run returns no_op."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        extract_service(
            ToolInput(project_dir=str(project)),
            new_service_name="billing_service",
        )
        result2 = extract_service(
            ToolInput(project_dir=str(project)),
            new_service_name="billing_service",
        )
        assert result2.status == "no_op"


def test_dry_run_creates_no_files() -> None:
    """T-15: dry_run=True must not create any files."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        result = extract_service(
            ToolInput(project_dir=str(project), dry_run=True),
            new_service_name="billing_service",
        )
        assert result.status == "success"
        assert result.files_created == []
        assert not (project.parent / "billing_service").exists()


def test_ci_workflow_created() -> None:
    """T-16: New service must have a GitHub Actions CI workflow."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        extract_service(
            ToolInput(project_dir=str(project)),
            new_service_name="billing_service",
        )
        ci = project.parent / "billing_service" / ".github" / "workflows" / "ci.yml"
        assert ci.exists(), "CI workflow not created"


def test_port_in_main_py() -> None:
    """T-17: Service port must be referenced in Dockerfile."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        extract_service(
            ToolInput(project_dir=str(project)),
            new_service_name="payment_service",
            new_service_port=9000,
        )
        dockerfile = project.parent / "payment_service" / "Dockerfile"
        assert "9000" in dockerfile.read_text()


def test_next_steps_non_empty() -> None:
    """T-18: next_steps must be non-empty."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        result = extract_service(
            ToolInput(project_dir=str(project)),
            new_service_name="billing_service",
        )
        assert len(result.next_steps) >= 1


def test_events_protocol_accepted() -> None:
    """T-19: events communication protocol must be accepted."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        result = extract_service(
            ToolInput(project_dir=str(project)),
            new_service_name="billing_service2",
            communication="events",
        )
        assert result.status == "success"


def test_grpc_protocol_accepted() -> None:
    """T-20: grpc communication protocol must be accepted."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        result = extract_service(
            ToolInput(project_dir=str(project)),
            new_service_name="billing_service3",
            communication="grpc",
        )
        assert result.status == "success"


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    test_functions = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for fn in test_functions:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {fn.__name__}: {exc}")
            failed += 1
    total = passed + failed
    print(f"\n{passed}/{total} passed", "OK" if failed == 0 else f"({failed} FAILED)")
    sys.exit(0 if failed == 0 else 1)
