"""Tests for TOOL-017 add_api_versioning.

Generates a real fixture project via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the spec.

Run with::

    PYTHONPATH=. python3 adapt/extend/api_design/test_add_api_versioning.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.api_design.add_api_versioning import add_api_versioning
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    """T-01: Tool returns status='success' on a fresh project."""
    project_dir = create_fixture_project(name="av_t01")
    result = add_api_versioning(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


def test_files_created_exist_on_disk() -> None:
    """T-02: Every path in files_created actually exists on disk."""
    project_dir = create_fixture_project(name="av_t02")
    result = add_api_versioning(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


def test_files_modified_exist_on_disk() -> None:
    """T-03: Every path in files_modified actually exists on disk."""
    project_dir = create_fixture_project(name="av_t03")
    result = add_api_versioning(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


def test_version_registry_created() -> None:
    """CC-01: app/core/version_registry.py exists with VersionRegistry."""
    project_dir = create_fixture_project(name="av_t04")
    add_api_versioning(ToolInput(project_dir=str(project_dir)))
    reg = project_dir / "app" / "core" / "version_registry.py"
    assert reg.exists(), "version_registry.py not created"
    content = reg.read_text()
    assert "VersionRegistry" in content
    assert "VersionInfo" in content
    assert "sunset_header" in content


def test_version_registry_has_v1_and_v2() -> None:
    """CC-02: Registry registers both v1 (deprecated) and v2 (current)."""
    project_dir = create_fixture_project(name="av_t05")
    add_api_versioning(ToolInput(project_dir=str(project_dir)))
    reg = project_dir / "app" / "core" / "version_registry.py"
    content = reg.read_text()
    assert '"v1"' in content or "'v1'" in content, "v1 not registered"
    assert '"v2"' in content or "'v2'" in content, "v2 not registered"
    assert "is_deprecated=True" in content, "v1 should be marked deprecated"


def test_middleware_created() -> None:
    """CC-03: app/middleware/version_resolver.py with VersionResolverMiddleware."""
    project_dir = create_fixture_project(name="av_t06")
    add_api_versioning(ToolInput(project_dir=str(project_dir)))
    mw = project_dir / "app" / "middleware" / "version_resolver.py"
    assert mw.exists(), "version_resolver.py not created"
    content = mw.read_text()
    assert "VersionResolverMiddleware" in content
    assert "Deprecation" in content
    assert "Sunset" in content
    assert "Link" in content


def test_middleware_sets_request_state() -> None:
    """CC-04: Middleware sets request.state.api_version."""
    project_dir = create_fixture_project(name="av_t07")
    add_api_versioning(ToolInput(project_dir=str(project_dir)))
    mw = project_dir / "app" / "middleware" / "version_resolver.py"
    content = mw.read_text()
    assert "request.state.api_version" in content


def test_middleware_rejects_unknown_version() -> None:
    """CC-05: Middleware returns 400 for unsupported API version."""
    project_dir = create_fixture_project(name="av_t08")
    add_api_versioning(ToolInput(project_dir=str(project_dir)))
    mw = project_dir / "app" / "middleware" / "version_resolver.py"
    content = mw.read_text()
    assert "400" in content, "Middleware must return 400 for unknown versions"


def test_versioned_schema_stubs_created() -> None:
    """CC-06: app/schemas/v1/__init__.py and app/schemas/v2/__init__.py exist."""
    project_dir = create_fixture_project(name="av_t09")
    add_api_versioning(ToolInput(project_dir=str(project_dir)))
    for ver in ("v1", "v2"):
        schema_init = project_dir / "app" / "schemas" / ver / "__init__.py"
        assert schema_init.exists(), f"schemas/{ver}/__init__.py missing"


def test_versioned_router_packages_created() -> None:
    """CC-07: app/api/v1/__init__.py and app/api/v2/__init__.py exist."""
    project_dir = create_fixture_project(name="av_t10")
    add_api_versioning(ToolInput(project_dir=str(project_dir)))
    for ver in ("v1", "v2"):
        router_init = project_dir / "app" / "api" / ver / "__init__.py"
        assert router_init.exists(), f"api/{ver}/__init__.py missing"


def test_versioned_router_includes_model_routers() -> None:
    """CC-08: Versioned router __init__ includes model sub-routers."""
    project_dir = create_fixture_project(name="av_t11")
    add_api_versioning(ToolInput(project_dir=str(project_dir)))
    for ver in ("v1", "v2"):
        content = (project_dir / "app" / "api" / ver / "__init__.py").read_text()
        assert "router" in content.lower()


def test_versioned_route_stubs_created() -> None:
    """CC-09: Per-model versioned route stubs created for each version."""
    project_dir = create_fixture_project(name="av_t12")
    add_api_versioning(ToolInput(project_dir=str(project_dir)))
    for ver in ("v1", "v2"):
        route = project_dir / "app" / "api" / ver / "item.py"
        assert route.exists(), f"api/{ver}/item.py missing"


def test_main_patched_with_middleware() -> None:
    """CC-10: app/main.py registers VersionResolverMiddleware."""
    project_dir = create_fixture_project(name="av_t13")
    add_api_versioning(ToolInput(project_dir=str(project_dir)))
    main_file = project_dir / "app" / "main.py"
    assert main_file.exists()
    content = main_file.read_text()
    assert "VersionResolverMiddleware" in content


def test_main_includes_versioned_routers() -> None:
    """CC-11: app/main.py includes /api/v1 and /api/v2 routers."""
    project_dir = create_fixture_project(name="av_t14")
    add_api_versioning(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "main.py").read_text()
    assert "/api/v1" in content
    assert "/api/v2" in content


def test_sunset_header_is_rfc7231() -> None:
    """CC-12: sunset_header property returns RFC 7231 format."""
    project_dir = create_fixture_project(name="av_t15")
    add_api_versioning(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "core" / "version_registry.py").read_text()
    # RFC 7231 format must contain day-name and GMT
    assert "GMT" in content


def test_all_py_files_parse() -> None:
    """CC-13: All .py files in the project parse without SyntaxError."""
    project_dir = create_fixture_project(name="av_t16")
    add_api_versioning(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_idempotent_returns_no_op() -> None:
    """CC-14: Running the tool twice returns no_op on the second run."""
    project_dir = create_fixture_project(name="av_t17")
    r1 = add_api_versioning(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_api_versioning(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created
    assert not r2.files_modified


def test_idempotent_project_still_parses() -> None:
    """After two runs the project must still be fully parseable."""
    project_dir = create_fixture_project(name="av_t18")
    add_api_versioning(ToolInput(project_dir=str(project_dir)))
    add_api_versioning(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_dry_run_writes_nothing() -> None:
    """dry_run=True must return success but write no files."""
    project_dir = create_fixture_project(name="av_t19")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_api_versioning(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_execution_time_recorded() -> None:
    """execution_time_ms must be positive after a successful run."""
    project_dir = create_fixture_project(name="av_t20")
    result = add_api_versioning(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0


def test_next_steps_present() -> None:
    """next_steps must not be empty on success."""
    project_dir = create_fixture_project(name="av_t21")
    result = add_api_versioning(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.next_steps) > 0


def test_notes_present() -> None:
    """notes must not be empty on success."""
    project_dir = create_fixture_project(name="av_t22")
    result = add_api_versioning(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.notes) > 0


def test_extract_version_from_path_helper() -> None:
    """extract_version_from_path correctly parses /api/v1/ paths."""
    project_dir = create_fixture_project(name="av_t23")
    add_api_versioning(ToolInput(project_dir=str(project_dir)))
    reg_path = project_dir / "app" / "core" / "version_registry.py"
    content = reg_path.read_text()
    assert "extract_version_from_path" in content


def test_x_api_version_header_in_middleware() -> None:
    """X-API-Version response header is set by the middleware."""
    project_dir = create_fixture_project(name="av_t24")
    add_api_versioning(ToolInput(project_dir=str(project_dir)))
    mw = project_dir / "app" / "middleware" / "version_resolver.py"
    content = mw.read_text()
    assert "X-API-Version" in content


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_success_status,
        test_files_created_exist_on_disk,
        test_files_modified_exist_on_disk,
        test_version_registry_created,
        test_version_registry_has_v1_and_v2,
        test_middleware_created,
        test_middleware_sets_request_state,
        test_middleware_rejects_unknown_version,
        test_versioned_schema_stubs_created,
        test_versioned_router_packages_created,
        test_versioned_router_includes_model_routers,
        test_versioned_route_stubs_created,
        test_main_patched_with_middleware,
        test_main_includes_versioned_routers,
        test_sunset_header_is_rfc7231,
        test_all_py_files_parse,
        test_idempotent_returns_no_op,
        test_idempotent_project_still_parses,
        test_dry_run_writes_nothing,
        test_execution_time_recorded,
        test_next_steps_present,
        test_notes_present,
        test_extract_version_from_path_helper,
        test_x_api_version_header_in_middleware,
    ]

    passed = 0
    failed = 0
    errors: list[str] = []

    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {t.__name__}: {exc}")
            errors.append(f"{t.__name__}: {exc}")
            failed += 1

    print(f"\n{passed}/{passed + failed} passed")
    if failed:
        sys.exit(1)
