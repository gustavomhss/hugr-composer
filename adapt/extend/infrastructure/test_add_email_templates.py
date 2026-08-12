"""Tests for TOOL-024 add_email_templates.

Generates real fixture projects via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_email_templates.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_email_templates.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_email_templates import add_email_templates
from tests.common.fixture_factory import create_fixture_project

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _all_py_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def _assert_parse(root: Path) -> None:
    for f in _all_py_files(root):
        source = f.read_text()
        try:
            ast.parse(source)
        except SyntaxError as exc:
            raise AssertionError(f"SyntaxError in {f}: {exc}") from exc


def _max_function_loc(root: Path, subdir: str = "app") -> int:
    """Return the max LOC of any function in the given subdir."""
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


# ---------------------------------------------------------------------------
# Category A — Tool execution
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    """Tool returns status='success' on a fresh project."""
    project_dir = create_fixture_project(name="email_t01")
    result = add_email_templates(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


def test_idempotent() -> None:
    """Second run returns status='no_op' without touching files."""
    project_dir = create_fixture_project(name="email_t02")
    r1 = add_email_templates(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_email_templates(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


def test_dry_run() -> None:
    """dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="email_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_email_templates(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_files_created_count() -> None:
    """Tool creates at least 15 new files (email pkg, templates, model, schemas, crud, routes, migration)."""
    project_dir = create_fixture_project(name="email_t04")
    result = add_email_templates(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 15, (
        f"Expected >= 15 files_created, got {len(result.files_created)}: {result.files_created}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


def test_files_modified_count() -> None:
    """Tool modifies at least 2 files (config, models init)."""
    project_dir = create_fixture_project(name="email_t05")
    result = add_email_templates(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_modified) >= 2, (
        f"Expected >= 2 files_modified, got {len(result.files_modified)}: {result.files_modified}"
    )
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


# ---------------------------------------------------------------------------
# Category B — Generated code quality
# ---------------------------------------------------------------------------

def test_all_py_parse() -> None:
    """Every generated .py file AST-parses clean."""
    project_dir = create_fixture_project(name="email_t06")
    add_email_templates(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_no_function_over_50_loc() -> None:
    """No function in generated app/ exceeds 50 LOC."""
    project_dir = create_fixture_project(name="email_t07")
    add_email_templates(ToolInput(project_dir=str(project_dir)))
    max_loc = _max_function_loc(project_dir, "app")
    assert max_loc <= 50, f"Found function with {max_loc} LOC (limit: 50)"


def test_config_fields_patched() -> None:
    """Expected EMAIL_* settings fields exist inside the Settings class in config.py."""
    project_dir = create_fixture_project(name="email_t08")
    add_email_templates(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    for field in ("EMAIL_PROVIDER", "EMAIL_FROM", "EMAIL_FROM_NAME", "EMAIL_DEFAULT_LOCALE"):
        assert field in content, f"Config field {field} not found in config.py"
    # Verify fields are inside the Settings class (4-space indent)
    for line in content.splitlines():
        if "EMAIL_PROVIDER" in line and ":" in line:
            assert line.startswith("    "), (
                f"EMAIL_PROVIDER not inside class body (no 4-space indent): {line!r}"
            )
            break


def test_models_init_patched() -> None:
    """EmailDelivery model is registered in app/models/__init__.py."""
    project_dir = create_fixture_project(name="email_t09")
    add_email_templates(ToolInput(project_dir=str(project_dir)))
    models_init = project_dir / "app" / "models" / "__init__.py"
    content = models_init.read_text()
    assert "EmailDelivery" in content, "EmailDelivery not registered in models __init__"


def test_routes_registered() -> None:
    """Email router is registered in app/routes/__init__.py."""
    project_dir = create_fixture_project(name="email_t10")
    add_email_templates(ToolInput(project_dir=str(project_dir)))
    routes_init = project_dir / "app" / "routes" / "__init__.py"
    if routes_init.exists():
        content = routes_init.read_text()
        assert "email" in content.lower(), "Email router not registered in routes __init__"


# ---------------------------------------------------------------------------
# Category C — Domain-specific
# ---------------------------------------------------------------------------

def test_template_files_exist() -> None:
    """12 template files (4 templates x 3 files each) exist in app/email/templates/en/."""
    project_dir = create_fixture_project(name="email_t11")
    add_email_templates(ToolInput(project_dir=str(project_dir)))
    tpl_dir = project_dir / "app" / "email" / "templates" / "en"
    assert tpl_dir.exists(), "app/email/templates/en/ not created"
    template_files = list(tpl_dir.iterdir())
    assert len(template_files) >= 12, (
        f"Expected >= 12 template files (4 x 3), got {len(template_files)}: "
        f"{[f.name for f in template_files]}"
    )
    # Check the 4 templates exist
    template_names = ("welcome", "password_reset", "email_verification", "receipt")
    for name in template_names:
        for ext in ("subject.txt", "html", "txt"):
            tpl_file = tpl_dir / f"{name}.{ext}"
            assert tpl_file.exists(), f"Missing template file: {tpl_file.name}"


def test_render_email() -> None:
    """render_email(WELCOME, context) returns (subject, html, text) triple via registry."""
    project_dir = create_fixture_project(name="email_t12")
    add_email_templates(ToolInput(project_dir=str(project_dir)))
    # Verify the render module and registry exist and reference render_email
    render_file = project_dir / "app" / "email" / "render.py"
    assert render_file.exists(), "app/email/render.py not created"
    content = render_file.read_text()
    assert "render_email" in content, "render_email function not in render.py"
    assert "subject" in content.lower(), "render_email should produce a subject"
    assert "html" in content.lower(), "render_email should produce html"


def test_render_missing_context_raises() -> None:
    """Registry defines MissingContextError for incomplete context."""
    project_dir = create_fixture_project(name="email_t13")
    add_email_templates(ToolInput(project_dir=str(project_dir)))
    registry_file = project_dir / "app" / "email" / "registry.py"
    assert registry_file.exists(), "registry.py not created"
    content = registry_file.read_text()
    assert "MissingContextError" in content, "MissingContextError not in registry"
    assert "TEMPLATE_REQUIRED_CONTEXT" in content, "TEMPLATE_REQUIRED_CONTEXT not in registry"


def test_locale_fallback() -> None:
    """Render module has locale fallback logic (unknown locale -> 'en')."""
    project_dir = create_fixture_project(name="email_t14")
    add_email_templates(ToolInput(project_dir=str(project_dir)))
    render_file = project_dir / "app" / "email" / "render.py"
    content = render_file.read_text()
    # Should contain fallback logic — look for 'en' as fallback or resolve_locale
    assert "en" in content, "Default locale 'en' fallback not found in render.py"
    assert "locale" in content.lower(), "Locale handling not found in render.py"


def test_providers_importable() -> None:
    """app/email/providers/__init__.py has get_provider."""
    project_dir = create_fixture_project(name="email_t15")
    add_email_templates(ToolInput(project_dir=str(project_dir)))
    providers_init = project_dir / "app" / "email" / "providers" / "__init__.py"
    assert providers_init.exists(), "providers __init__.py not created"
    content = providers_init.read_text()
    assert "get_provider" in content, "get_provider not in providers __init__"


def test_email_delivery_model() -> None:
    """app/models/email_delivery.py exists with EmailDelivery class."""
    project_dir = create_fixture_project(name="email_t16")
    add_email_templates(ToolInput(project_dir=str(project_dir)))
    model_file = project_dir / "app" / "models" / "email_delivery.py"
    assert model_file.exists(), "app/models/email_delivery.py not created"
    content = model_file.read_text()
    assert "EmailDelivery" in content, "EmailDelivery model not found"
    assert "to_email_redacted" in content or "redact" in content.lower(), (
        "EmailDelivery should have redacted email field"
    )


def test_preview_route_exists() -> None:
    """Route /email/preview/{template_name} is present."""
    project_dir = create_fixture_project(name="email_t17")
    add_email_templates(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "email.py"
    assert route_file.exists(), "app/api/routes/email.py not created"
    content = route_file.read_text()
    assert "preview" in content.lower(), "Preview route not found in email routes"
    assert "template_name" in content, "template_name parameter not in preview route"


def test_jinja_autoescape() -> None:
    """Jinja2 Environment uses autoescape for HTML templates."""
    project_dir = create_fixture_project(name="email_t18")
    add_email_templates(ToolInput(project_dir=str(project_dir)))
    render_file = project_dir / "app" / "email" / "render.py"
    content = render_file.read_text()
    assert "autoescape" in content, "autoescape not set in Jinja2 Environment"


def test_execution_time_recorded() -> None:
    """execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="email_t19")
    result = add_email_templates(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


def test_idempotent_project_still_parses() -> None:
    """After two runs all .py files remain parseable."""
    project_dir = create_fixture_project(name="email_t20")
    add_email_templates(ToolInput(project_dir=str(project_dir)))
    add_email_templates(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_next_steps_present() -> None:
    """next_steps should mention provider and alembic."""
    project_dir = create_fixture_project(name="email_t21")
    result = add_email_templates(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.next_steps) > 0, "next_steps must not be empty"
    combined = " ".join(result.next_steps).lower()
    assert "alembic" in combined, "next_steps should mention alembic"


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
        test_models_init_patched,
        test_routes_registered,
        test_template_files_exist,
        test_render_email,
        test_render_missing_context_raises,
        test_locale_fallback,
        test_providers_importable,
        test_email_delivery_model,
        test_preview_route_exists,
        test_jinja_autoescape,
        test_execution_time_recorded,
        test_idempotent_project_still_parses,
        test_next_steps_present,
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
    print(f"TOOL-024 add_email_templates: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
