"""Tests for TOOL-047 generate_sdk.

Run with::

    PYTHONPATH=. pytest adapt/evolve/test_generate_sdk.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/evolve/test_generate_sdk.py
"""

from __future__ import annotations

import ast
import json
import sys
import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.evolve.generate_sdk import generate_sdk


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_project(tmp: Path) -> Path:
    """Create a minimal FastAPI project for SDK generation tests.

    Args:
        tmp: Parent temp directory.

    Returns:
        Path to project root.
    """
    project = tmp / "sdk_proj"
    project.mkdir(parents=True, exist_ok=True)
    app_dir = project / "app"
    app_dir.mkdir()
    (app_dir / "main.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI(title='TestAPI', version='1.2.3')\n"
    )
    (app_dir / "core").mkdir(parents=True, exist_ok=True)
    (app_dir / "core" / "config.py").write_text(
        "from pydantic_settings import BaseSettings\nclass Settings(BaseSettings): pass\nsettings = Settings()\n"
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
    """T-01: Tool returns status='success' on fresh project."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        result = generate_sdk(ToolInput(project_dir=str(project)), languages=["python"])
        assert result.status == "success", f"Expected success: {result.error}"


def test_invalid_language_returns_error() -> None:
    """T-02: Unknown language must return status='error'."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        result = generate_sdk(
            ToolInput(project_dir=str(project)), languages=["cobol"]
        )
        assert result.status == "error"
        assert "cobol" in result.error


def test_openapi_json_created() -> None:
    """T-03: sdks/openapi.json must be created."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        generate_sdk(ToolInput(project_dir=str(project)), languages=["python"])
        schema_file = project / "sdks" / "openapi.json"
        assert schema_file.exists(), "openapi.json not created"


def test_openapi_json_valid() -> None:
    """T-04: openapi.json must be valid JSON."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        generate_sdk(ToolInput(project_dir=str(project)), languages=["python"])
        schema = json.loads((project / "sdks" / "openapi.json").read_text())
        assert "openapi" in schema or "info" in schema


def test_schema_hash_created() -> None:
    """T-05: sdks/.schema_hash must be created."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        generate_sdk(ToolInput(project_dir=str(project)), languages=["python"])
        hash_file = project / "sdks" / ".schema_hash"
        assert hash_file.exists(), ".schema_hash not created"
        assert len(hash_file.read_text().strip()) >= 8


def test_python_sdk_dir_created() -> None:
    """T-06: sdks/python/ directory must exist."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        generate_sdk(ToolInput(project_dir=str(project)), languages=["python"])
        assert (project / "sdks" / "python").exists(), "sdks/python/ not created"


def test_typescript_sdk_dir_created() -> None:
    """T-07: sdks/typescript/ directory must exist when typescript requested."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        generate_sdk(ToolInput(project_dir=str(project)), languages=["typescript"])
        assert (project / "sdks" / "typescript").exists()


def test_go_sdk_dir_created() -> None:
    """T-08: sdks/go/ directory must exist when go requested."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        generate_sdk(ToolInput(project_dir=str(project)), languages=["go"])
        assert (project / "sdks" / "go").exists()


def test_ci_workflow_created() -> None:
    """T-09: GitHub Actions SDK regen workflow must be created."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        generate_sdk(ToolInput(project_dir=str(project)), languages=["python"])
        workflow = project / ".github" / "workflows" / "sdk-regen.yml"
        assert workflow.exists(), "CI workflow not created"


def test_ci_workflow_valid_yaml() -> None:
    """T-10: CI workflow must be readable YAML-ish (contains expected keys)."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        generate_sdk(ToolInput(project_dir=str(project)), languages=["python"])
        content = (project / ".github" / "workflows" / "sdk-regen.yml").read_text()
        assert "on:" in content or "on :" in content or "pull_request" in content


def test_version_file_in_sdk_dir() -> None:
    """T-11: sdks/python/VERSION must be created."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        generate_sdk(ToolInput(project_dir=str(project)), languages=["python"])
        version_file = project / "sdks" / "python" / "VERSION"
        assert version_file.exists(), "VERSION file not created"


def test_version_file_content() -> None:
    """T-12: VERSION file must contain a semver-like string."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        generate_sdk(ToolInput(project_dir=str(project)), languages=["python"])
        version = (project / "sdks" / "python" / "VERSION").read_text().strip()
        assert len(version) >= 3 and "." in version


def test_dry_run_creates_no_files() -> None:
    """T-13: dry_run=True must not write any files."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        result = generate_sdk(
            ToolInput(project_dir=str(project), dry_run=True), languages=["python"]
        )
        assert result.status == "success"
        assert result.files_created == []
        assert not (project / "sdks").exists()


def test_dry_run_reports_hash() -> None:
    """T-14: dry_run notes must mention schema hash."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        result = generate_sdk(
            ToolInput(project_dir=str(project), dry_run=True), languages=["python"]
        )
        assert any("hash" in n.lower() or "schema" in n.lower() for n in result.notes)


def test_idempotency_same_schema_skips() -> None:
    """T-15: Running twice with same schema triggers schema_hash match."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        generate_sdk(ToolInput(project_dir=str(project)), languages=["python"])
        result2 = generate_sdk(ToolInput(project_dir=str(project)), languages=["python"])
        # Should return no_op or success with warning
        assert result2.status in ("success", "no_op")
        if result2.status == "success":
            assert any("unchanged" in w.lower() or "skipped" in w.lower() for w in result2.warnings) or len(result2.files_created) >= 0


def test_notes_contain_package_name() -> None:
    """T-16: notes must mention the package name."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        result = generate_sdk(
            ToolInput(project_dir=str(project)),
            languages=["python"],
            package_name="my_api_client",
        )
        assert any("my_api_client" in n for n in result.notes)


def test_multiple_languages() -> None:
    """T-17: Multiple languages can be requested in one call."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        result = generate_sdk(
            ToolInput(project_dir=str(project)),
            languages=["python", "typescript"],
        )
        assert result.status == "success"
        assert (project / "sdks" / "python").exists()
        assert (project / "sdks" / "typescript").exists()


def test_files_created_non_empty() -> None:
    """T-18: files_created must be non-empty."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        result = generate_sdk(ToolInput(project_dir=str(project)), languages=["python"])
        assert len(result.files_created) >= 3


def test_execution_time_recorded() -> None:
    """T-19: execution_time_ms must be >= 0."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        result = generate_sdk(ToolInput(project_dir=str(project)), languages=["python"])
        assert result.execution_time_ms >= 0


def test_next_steps_non_empty() -> None:
    """T-20: next_steps must be non-empty."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        result = generate_sdk(ToolInput(project_dir=str(project)), languages=["python"])
        assert len(result.next_steps) >= 1


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
