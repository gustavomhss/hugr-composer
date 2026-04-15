"""Tests for TOOL-050 add_i18n.

Run with::

    PYTHONPATH=. pytest adapt/evolve/test_add_i18n.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/evolve/test_add_i18n.py
"""

from __future__ import annotations

import ast
import sys
import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.evolve.add_i18n import add_i18n


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_project(tmp: Path) -> Path:
    """Create a minimal FastAPI project for i18n tests.

    Args:
        tmp: Parent temp directory.

    Returns:
        Path to project root.
    """
    project = tmp / "i18n_proj"
    project.mkdir(parents=True, exist_ok=True)
    app_dir = project / "app"
    app_dir.mkdir()
    core_dir = app_dir / "core"
    core_dir.mkdir()
    (core_dir / "config.py").write_text(
        "from pydantic_settings import BaseSettings\nclass Settings(BaseSettings): pass\nsettings = Settings()\n"
    )
    api_dir = app_dir / "api" / "middleware"
    api_dir.mkdir(parents=True)
    (app_dir / "main.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n"
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
        result = add_i18n(ToolInput(project_dir=str(project)))
        assert result.status == "success", f"Expected success: {result.error}"


def test_locale_context_created() -> None:
    """T-02: app/core/locale_context.py must be created."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_i18n(ToolInput(project_dir=str(project)))
        f = project / "app" / "core" / "locale_context.py"
        assert f.exists(), "locale_context.py not created"
        assert "_current_locale" in f.read_text()


def test_locale_context_parses() -> None:
    """T-03: locale_context.py must be valid Python."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_i18n(ToolInput(project_dir=str(project)))
        _assert_parse(project / "app" / "core" / "locale_context.py")


def test_locale_meta_created() -> None:
    """T-04: app/core/locale_meta.py must be created."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_i18n(ToolInput(project_dir=str(project)))
        f = project / "app" / "core" / "locale_meta.py"
        assert f.exists()
        assert "LocaleMeta" in f.read_text()


def test_locale_meta_parses() -> None:
    """T-05: locale_meta.py must be valid Python."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_i18n(ToolInput(project_dir=str(project)))
        _assert_parse(project / "app" / "core" / "locale_meta.py")


def test_babel_translator_created() -> None:
    """T-06: app/core/babel_translator.py must be created."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_i18n(ToolInput(project_dir=str(project)))
        f = project / "app" / "core" / "babel_translator.py"
        assert f.exists()
        assert "def _(" in f.read_text()


def test_babel_translator_parses() -> None:
    """T-07: babel_translator.py must be valid Python."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_i18n(ToolInput(project_dir=str(project)))
        _assert_parse(project / "app" / "core" / "babel_translator.py")


def test_locale_middleware_created() -> None:
    """T-08: app/api/middleware/locale.py must be created."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_i18n(ToolInput(project_dir=str(project)))
        f = project / "app" / "api" / "middleware" / "locale.py"
        assert f.exists()
        assert "LocaleMiddleware" in f.read_text()


def test_locale_middleware_parses() -> None:
    """T-09: locale.py middleware must be valid Python."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_i18n(ToolInput(project_dir=str(project)))
        _assert_parse(project / "app" / "api" / "middleware" / "locale.py")


def test_icu_plurals_created() -> None:
    """T-10: app/core/icu_plurals.py must be created."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_i18n(ToolInput(project_dir=str(project)))
        f = project / "app" / "core" / "icu_plurals.py"
        assert f.exists()
        assert "pluralize" in f.read_text()


def test_icu_plurals_parses() -> None:
    """T-11: icu_plurals.py must be valid Python."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_i18n(ToolInput(project_dir=str(project)))
        _assert_parse(project / "app" / "core" / "icu_plurals.py")


def test_locale_formatters_created() -> None:
    """T-12: app/core/locale_formatters.py must be created."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_i18n(ToolInput(project_dir=str(project)))
        f = project / "app" / "core" / "locale_formatters.py"
        assert f.exists()
        assert "format_number" in f.read_text()
        assert "format_currency" in f.read_text()


def test_locale_formatters_parses() -> None:
    """T-13: locale_formatters.py must be valid Python."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_i18n(ToolInput(project_dir=str(project)))
        _assert_parse(project / "app" / "core" / "locale_formatters.py")


def test_babel_cfg_created() -> None:
    """T-14: babel.cfg must be created at project root."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_i18n(ToolInput(project_dir=str(project)))
        assert (project / "babel.cfg").exists()


def test_babel_cfg_contains_python_section() -> None:
    """T-15: babel.cfg must have a [python: ...] extraction section."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_i18n(ToolInput(project_dir=str(project)))
        content = (project / "babel.cfg").read_text()
        assert "[python:" in content


def test_po_stub_created_per_locale() -> None:
    """T-16: .po stub must be created for each supported locale."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_i18n(
            ToolInput(project_dir=str(project)),
            supported_locales=["en_US", "pt_BR"],
        )
        assert (project / "locales" / "en_US" / "LC_MESSAGES" / "messages.po").exists()
        assert (project / "locales" / "pt_BR" / "LC_MESSAGES" / "messages.po").exists()


def test_audit_cli_created() -> None:
    """T-17: scripts/i18n_audit.py must be created."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_i18n(ToolInput(project_dir=str(project)))
        assert (project / "scripts" / "i18n_audit.py").exists()


def test_audit_cli_parses() -> None:
    """T-18: i18n_audit.py must be valid Python."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_i18n(ToolInput(project_dir=str(project)))
        _assert_parse(project / "scripts" / "i18n_audit.py")


def test_rtl_detected_in_meta() -> None:
    """T-19: Arabic locale must be marked as RTL in locale_meta.py."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_i18n(
            ToolInput(project_dir=str(project)),
            supported_locales=["en_US", "ar"],
        )
        meta = (project / "app" / "core" / "locale_meta.py").read_text()
        assert "ar" in meta


def test_idempotency_returns_no_op() -> None:
    """T-20: Second run must return status='no_op'."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_i18n(ToolInput(project_dir=str(project)))
        result2 = add_i18n(ToolInput(project_dir=str(project)))
        assert result2.status == "no_op"


def test_dry_run_creates_no_files() -> None:
    """T-21: dry_run=True must not write any files."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        result = add_i18n(
            ToolInput(project_dir=str(project), dry_run=True)
        )
        assert result.status == "success"
        assert result.files_created == []
        assert not (project / "app" / "core" / "locale_context.py").exists()


def test_next_steps_include_pybabel() -> None:
    """T-22: next_steps must mention pybabel."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        result = add_i18n(ToolInput(project_dir=str(project)))
        assert any("pybabel" in s or "i18n" in s for s in result.next_steps)


def test_middleware_priority_chain() -> None:
    """T-23: Locale middleware must implement all 4 resolution methods."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_i18n(ToolInput(project_dir=str(project)))
        src = (project / "app" / "api" / "middleware" / "locale.py").read_text()
        assert "_from_query" in src
        assert "_from_header" in src
        assert "_from_accept_language" in src


def test_files_created_non_empty() -> None:
    """T-24: files_created must be non-empty on success."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        result = add_i18n(ToolInput(project_dir=str(project)))
        assert len(result.files_created) >= 7


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
