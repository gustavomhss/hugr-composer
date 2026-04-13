"""Tests for TOOL-049 generate_docs.

Run with::

    PYTHONPATH=. pytest adapt/evolve/test_generate_docs.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/evolve/test_generate_docs.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.evolve.generate_docs import generate_docs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_project(tmp: Path) -> Path:
    """Create a minimal FastAPI project for docs generation tests.

    Args:
        tmp: Parent temp directory.

    Returns:
        Path to project root.
    """
    project = tmp / "docs_proj"
    project.mkdir(parents=True, exist_ok=True)
    app_dir = project / "app"
    app_dir.mkdir()
    (app_dir / "main.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI(title='MyAPI', version='1.0.0')\n"
    )
    # Minimal pyproject.toml
    (project / "pyproject.toml").write_text(
        '[project]\nname = "myapi"\nversion = "1.0.0"\n'
    )
    return project


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_success_status() -> None:
    """T-01: Tool returns status='success' on fresh project."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        result = generate_docs(ToolInput(project_dir=str(project)))
        assert result.status == "success", f"Expected success: {result.error}"


def test_invalid_deploy_target_returns_error() -> None:
    """T-02: Unknown deploy_target must return status='error'."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        result = generate_docs(
            ToolInput(project_dir=str(project)), deploy_target="ftp"
        )
        assert result.status == "error"
        assert "ftp" in result.error


def test_mkdocs_yml_created() -> None:
    """T-03: mkdocs.yml must be created."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        generate_docs(ToolInput(project_dir=str(project)))
        assert (project / "mkdocs.yml").exists()


def test_mkdocs_yml_contains_material() -> None:
    """T-04: mkdocs.yml must reference the material theme."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        generate_docs(ToolInput(project_dir=str(project)))
        assert "material" in (project / "mkdocs.yml").read_text()


def test_mkdocs_yml_contains_strict() -> None:
    """T-05: mkdocs.yml must have strict: true."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        generate_docs(ToolInput(project_dir=str(project)))
        assert "strict: true" in (project / "mkdocs.yml").read_text()


def test_index_page_created() -> None:
    """T-06: docs/generated/index.md must be created."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        generate_docs(ToolInput(project_dir=str(project)))
        assert (project / "docs" / "generated" / "index.md").exists()


def test_section_pages_created() -> None:
    """T-07: All default section pages must be created."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        generate_docs(ToolInput(project_dir=str(project)))
        docs_dir = project / "docs" / "generated"
        for section in ["api", "models", "schemas", "deployment", "architecture"]:
            assert (docs_dir / f"{section}.md").exists(), f"{section}.md missing"


def test_architecture_diagram_created() -> None:
    """T-08: architecture_diagram.md must be created."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        generate_docs(ToolInput(project_dir=str(project)))
        assert (project / "docs" / "generated" / "architecture_diagram.md").exists()


def test_architecture_diagram_contains_mermaid() -> None:
    """T-09: architecture_diagram.md must contain a Mermaid code block."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        generate_docs(ToolInput(project_dir=str(project)))
        content = (project / "docs" / "generated" / "architecture_diagram.md").read_text()
        assert "mermaid" in content


def test_redoc_html_created() -> None:
    """T-10: docs/generated/api_reference.html must be created."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        generate_docs(ToolInput(project_dir=str(project)))
        assert (project / "docs" / "generated" / "api_reference.html").exists()


def test_redoc_html_contains_redoc() -> None:
    """T-11: api_reference.html must contain Redoc embed."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        generate_docs(ToolInput(project_dir=str(project)))
        content = (project / "docs" / "generated" / "api_reference.html").read_text()
        assert "redoc" in content.lower()


def test_ci_workflow_created() -> None:
    """T-12: GitHub Actions docs workflow must be created."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        generate_docs(ToolInput(project_dir=str(project)))
        workflow = project / ".github" / "workflows" / "docs.yml"
        assert workflow.exists()


def test_ci_workflow_contains_mkdocs_build() -> None:
    """T-13: CI workflow must run mkdocs build."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        generate_docs(ToolInput(project_dir=str(project)))
        content = (project / ".github" / "workflows" / "docs.yml").read_text()
        assert "mkdocs" in content


def test_publish_script_created() -> None:
    """T-14: scripts/publish_docs.sh must be created."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        generate_docs(ToolInput(project_dir=str(project)))
        assert (project / "scripts" / "publish_docs.sh").exists()


def test_subset_sections_only() -> None:
    """T-15: include_sections subset must create only those pages."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        generate_docs(
            ToolInput(project_dir=str(project)),
            include_sections=["api", "models"],
        )
        docs_dir = project / "docs" / "generated"
        assert (docs_dir / "api.md").exists()
        assert (docs_dir / "models.md").exists()
        assert not (docs_dir / "deployment.md").exists()


def test_idempotency_returns_no_op() -> None:
    """T-16: Second run must return status='no_op'."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        generate_docs(ToolInput(project_dir=str(project)))
        result2 = generate_docs(ToolInput(project_dir=str(project)))
        assert result2.status == "no_op"


def test_dry_run_creates_no_files() -> None:
    """T-17: dry_run=True must not write any files."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        result = generate_docs(
            ToolInput(project_dir=str(project), dry_run=True)
        )
        assert result.status == "success"
        assert result.files_created == []
        assert not (project / "mkdocs.yml").exists()


def test_next_steps_include_mkdocs_serve() -> None:
    """T-18: next_steps must mention mkdocs serve."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        result = generate_docs(ToolInput(project_dir=str(project)))
        assert any("mkdocs serve" in s for s in result.next_steps)


def test_custom_output_dir() -> None:
    """T-19: Custom output_dir must be respected."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        generate_docs(
            ToolInput(project_dir=str(project)), output_dir="site_docs"
        )
        assert (project / "site_docs" / "index.md").exists()


def test_files_created_non_empty() -> None:
    """T-20: files_created must be non-empty."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        result = generate_docs(ToolInput(project_dir=str(project)))
        assert len(result.files_created) >= 8


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
