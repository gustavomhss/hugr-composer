"""Tests for TOOL-078 add_data_versioning.

Generates a real fixture project via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the MEGA_BRIEFING spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/crud_data/test_add_data_versioning.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/crud_data/test_add_data_versioning.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.crud_data.add_data_versioning import add_data_versioning
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
# CC-01: success status
# ---------------------------------------------------------------------------


def test_success_status() -> None:
    """CC-01: Tool returns status='success' on a fresh project."""
    project_dir = create_fixture_project(name="ver_t01_success")
    result = add_data_versioning(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


# ---------------------------------------------------------------------------
# CC-02: idempotency
# ---------------------------------------------------------------------------


def test_idempotent() -> None:
    """CC-02: Second run returns status='no_op' with no files created or modified."""
    project_dir = create_fixture_project(name="ver_t02_idempotent")
    r1 = add_data_versioning(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_data_versioning(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


# ---------------------------------------------------------------------------
# CC-03: dry_run
# ---------------------------------------------------------------------------


def test_dry_run() -> None:
    """CC-03: dry_run=True returns success but writes nothing to disk."""
    project_dir = create_fixture_project(name="ver_t03_dry_run")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_data_versioning(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


# ---------------------------------------------------------------------------
# CC-04: files_created
# ---------------------------------------------------------------------------


def test_files_created_count() -> None:
    """CC-04: At least 7 files created and all exist on disk."""
    project_dir = create_fixture_project(name="ver_t04_created_count")
    result = add_data_versioning(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 7, f"Expected >=7 files, got {len(result.files_created)}"
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-05: files_modified
# ---------------------------------------------------------------------------


def test_files_modified_count() -> None:
    """CC-05: At least 1 file modified and all exist on disk."""
    project_dir = create_fixture_project(name="ver_t05_modified_count")
    result = add_data_versioning(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_modified) >= 1, "Expected at least 1 modified file"
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-06: all .py files parse
# ---------------------------------------------------------------------------


def test_all_py_parse() -> None:
    """CC-06: All .py files in the project parse without SyntaxError after tool runs."""
    project_dir = create_fixture_project(name="ver_t06_parse_all")
    add_data_versioning(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# CC-07: no function over 50 LOC
# ---------------------------------------------------------------------------


def test_no_function_over_50_loc() -> None:
    """CC-07: No generated function exceeds 50 lines of code."""
    project_dir = create_fixture_project(name="ver_t07_func_loc")
    add_data_versioning(ToolInput(project_dir=str(project_dir)))
    violations: list[str] = []
    for py_file in _all_py_files(project_dir):
        tree = ast.parse(py_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                loc = (node.end_lineno or node.lineno) - node.lineno + 1
                if loc > 50:
                    violations.append(f"{py_file}:{node.name} ({loc} LOC)")
    assert not violations, "Functions exceeding 50 LOC:\n" + "\n".join(violations)


# ---------------------------------------------------------------------------
# CC-08: config fields patched
# ---------------------------------------------------------------------------


def test_config_fields_patched() -> None:
    """CC-08: VERSIONING_MAX_DRAFTS appears in config.py with 4-space indent."""
    project_dir = create_fixture_project(name="ver_t08_config")
    add_data_versioning(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    assert "VERSIONING_MAX_DRAFTS" in content, "VERSIONING_MAX_DRAFTS not in config"
    for line in content.splitlines():
        if "VERSIONING_MAX_DRAFTS" in line:
            assert line.startswith("    "), f"Config field not 4-space indented: {line!r}"


# ---------------------------------------------------------------------------
# CC-09: ContentVersion in models/__init__.py
# ---------------------------------------------------------------------------


def test_models_init_patched() -> None:
    """CC-09: ContentVersion is imported in app/models/__init__.py."""
    project_dir = create_fixture_project(name="ver_t09_models_init")
    add_data_versioning(ToolInput(project_dir=str(project_dir)))
    models_init = project_dir / "app" / "models" / "__init__.py"
    assert "ContentVersion" in models_init.read_text(), (
        "ContentVersion not registered in models/__init__.py"
    )


# ---------------------------------------------------------------------------
# CC-10: routes registered
# ---------------------------------------------------------------------------


def test_routes_registered() -> None:
    """CC-10: versions_router is registered in app/routes/__init__.py."""
    project_dir = create_fixture_project(name="ver_t10_routes_init")
    add_data_versioning(ToolInput(project_dir=str(project_dir)))
    routes_init = project_dir / "app" / "routes" / "__init__.py"
    if routes_init.exists():
        content = routes_init.read_text()
        assert "versions_router" in content or "versions" in content, (
            "versions router not registered in routes/__init__.py"
        )


# ---------------------------------------------------------------------------
# CC-11+: domain-specific tests
# ---------------------------------------------------------------------------


def test_content_version_model_created() -> None:
    """Domain: app/models/content_version.py exists with ContentVersion class."""
    project_dir = create_fixture_project(name="ver_t11_model")
    add_data_versioning(ToolInput(project_dir=str(project_dir)))
    model_file = project_dir / "app" / "models" / "content_version.py"
    assert model_file.exists(), "content_version.py not created"
    content = model_file.read_text()
    assert "class ContentVersion" in content, "ContentVersion class missing"
    assert "content_id" in content, "content_id field missing"
    assert "version_number" in content, "version_number field missing"
    assert "status" in content, "status field missing"
    assert "data_json" in content, "data_json field missing"
    assert "published_at" in content, "published_at field missing"
    assert "author_id" in content, "author_id field missing"


def test_versioning_service_created() -> None:
    """Domain: app/versioning/service.py exists with VersioningService class."""
    project_dir = create_fixture_project(name="ver_t12_service")
    add_data_versioning(ToolInput(project_dir=str(project_dir)))
    svc_file = project_dir / "app" / "versioning" / "service.py"
    assert svc_file.exists(), "versioning/service.py not created"
    content = svc_file.read_text()
    assert "class VersioningService" in content, "VersioningService class missing"
    assert "async def create_draft" in content, "create_draft method missing"
    assert "async def publish" in content, "publish method missing"
    assert "async def archive" in content, "archive method missing"
    assert "async def get_history" in content, "get_history method missing"
    assert "async def diff" in content, "diff method missing"


def test_draft_route_exists() -> None:
    """Domain: POST /versions/{content_type}/{id}/draft endpoint exists."""
    project_dir = create_fixture_project(name="ver_t13_draft_route")
    add_data_versioning(ToolInput(project_dir=str(project_dir)))
    routes_file = project_dir / "app" / "api" / "routes" / "versions.py"
    assert routes_file.exists(), "versions.py routes file not created"
    content = routes_file.read_text()
    assert "draft" in content, "draft endpoint missing"
    assert "content_id" in content, "content_id path param missing"


def test_publish_route_exists() -> None:
    """Domain: POST /versions/.../publish/... endpoint exists."""
    project_dir = create_fixture_project(name="ver_t14_publish_route")
    add_data_versioning(ToolInput(project_dir=str(project_dir)))
    routes_file = project_dir / "app" / "api" / "routes" / "versions.py"
    content = routes_file.read_text()
    assert "publish" in content, "publish endpoint missing"


def test_history_route_exists() -> None:
    """Domain: GET .../history endpoint exists."""
    project_dir = create_fixture_project(name="ver_t15_history_route")
    add_data_versioning(ToolInput(project_dir=str(project_dir)))
    routes_file = project_dir / "app" / "api" / "routes" / "versions.py"
    content = routes_file.read_text()
    assert "history" in content, "history endpoint missing"


def test_diff_route_exists() -> None:
    """Domain: GET .../diff/{v1}/{v2} endpoint exists."""
    project_dir = create_fixture_project(name="ver_t16_diff_route")
    add_data_versioning(ToolInput(project_dir=str(project_dir)))
    routes_file = project_dir / "app" / "api" / "routes" / "versions.py"
    content = routes_file.read_text()
    assert "diff" in content, "diff endpoint missing"
    assert "v1" in content and "v2" in content, "diff route missing v1/v2 params"


def test_schema_version_read_has_config_dict() -> None:
    """Domain: VersionRead schema uses ConfigDict(from_attributes=True)."""
    project_dir = create_fixture_project(name="ver_t17_schema_config")
    add_data_versioning(ToolInput(project_dir=str(project_dir)))
    schema_file = project_dir / "app" / "schemas" / "version.py"
    assert schema_file.exists(), "schemas/version.py not created"
    content = schema_file.read_text()
    assert "VersionRead" in content, "VersionRead schema missing"
    assert "from_attributes=True" in content, "ConfigDict(from_attributes=True) missing"


def test_migration_created() -> None:
    """Domain: Alembic migration for content_versions table is created."""
    project_dir = create_fixture_project(name="ver_t18_migration")
    add_data_versioning(ToolInput(project_dir=str(project_dir)))
    versions_dir = project_dir / "alembic" / "versions"
    migration_files = list(versions_dir.glob("*content_versions*"))
    assert len(migration_files) >= 1, "No content_versions migration created"


def test_migration_has_unique_index() -> None:
    """Domain: Migration creates unique (content_id, version_number) index."""
    project_dir = create_fixture_project(name="ver_t19_mig_unique")
    add_data_versioning(ToolInput(project_dir=str(project_dir)))
    versions_dir = project_dir / "alembic" / "versions"
    migration_files = list(versions_dir.glob("*content_versions*"))
    assert migration_files
    content = migration_files[0].read_text()
    assert "unique=True" in content, "Migration missing unique index"
    assert "version_number" in content, "version_number not in unique index"


def test_diff_function_computes_added_removed_changed() -> None:
    """Domain: _compute_diff returns added/removed/changed keys."""
    project_dir = create_fixture_project(name="ver_t20_diff_fn")
    add_data_versioning(ToolInput(project_dir=str(project_dir)))
    svc_file = project_dir / "app" / "versioning" / "service.py"
    content = svc_file.read_text()
    assert '"added"' in content or "'added'" in content, "diff missing 'added' key"
    assert '"removed"' in content or "'removed'" in content, "diff missing 'removed' key"
    assert '"changed"' in content or "'changed'" in content, "diff missing 'changed' key"


def test_versioning_package_init_exports() -> None:
    """Domain: app/versioning/__init__.py exports VersioningService."""
    project_dir = create_fixture_project(name="ver_t21_pkg_init")
    add_data_versioning(ToolInput(project_dir=str(project_dir)))
    init_file = project_dir / "app" / "versioning" / "__init__.py"
    assert init_file.exists(), "app/versioning/__init__.py not created"
    content = init_file.read_text()
    assert "VersioningService" in content, "VersioningService not exported from package"


# ---------------------------------------------------------------------------
# CC-N-1: execution time
# ---------------------------------------------------------------------------


def test_execution_time_recorded() -> None:
    """CC-N-1: execution_time_ms is a positive integer after a successful run."""
    project_dir = create_fixture_project(name="ver_t22_timing")
    result = add_data_versioning(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


# ---------------------------------------------------------------------------
# CC-N: next_steps
# ---------------------------------------------------------------------------


def test_next_steps_present() -> None:
    """CC-N: next_steps must not be empty on success and mention alembic."""
    project_dir = create_fixture_project(name="ver_t23_next_steps")
    result = add_data_versioning(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.next_steps) > 0, "next_steps must not be empty on success"
    assert any("alembic" in s for s in result.next_steps), "Should mention alembic upgrade"


# ---------------------------------------------------------------------------
# CC-LAST: idempotent project still parses
# ---------------------------------------------------------------------------


def test_idempotent_project_still_parses() -> None:
    """CC-LAST: After two runs the project must still be fully parseable."""
    project_dir = create_fixture_project(name="ver_t24_idem_parse")
    add_data_versioning(ToolInput(project_dir=str(project_dir)))
    add_data_versioning(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# Additional structural tests
# ---------------------------------------------------------------------------


def test_error_return_on_invalid_dir() -> None:
    """Tool returns error status when project_dir does not exist."""
    result = add_data_versioning(ToolInput(project_dir="/nonexistent/path/xyz"))
    assert result.status == "error"
    assert result.error is not None
    assert result.execution_time_ms > 0


def test_dry_run_execution_time_recorded() -> None:
    """execution_time_ms is positive even on dry_run returns."""
    project_dir = create_fixture_project(name="ver_t26_dry_timing")
    result = add_data_versioning(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.execution_time_ms > 0, "execution_time_ms must be positive on dry_run"


def test_content_version_model_has_unique_table_args() -> None:
    """Domain: ContentVersion.__table_args__ includes unique index on content_id+version."""
    project_dir = create_fixture_project(name="ver_t27_table_args")
    add_data_versioning(ToolInput(project_dir=str(project_dir)))
    model_file = project_dir / "app" / "models" / "content_version.py"
    content = model_file.read_text()
    assert "__table_args__" in content, "__table_args__ not in ContentVersion model"
    assert "unique=True" in content, "unique constraint not found in ContentVersion model"


def test_crud_version_file_created() -> None:
    """Domain: app/crud/version.py exists with list_versions_for_content."""
    project_dir = create_fixture_project(name="ver_t28_crud")
    add_data_versioning(ToolInput(project_dir=str(project_dir)))
    crud_file = project_dir / "app" / "crud" / "version.py"
    assert crud_file.exists(), "crud/version.py not created"
    content = crud_file.read_text()
    assert "async def list_versions_for_content" in content, "list_versions_for_content missing"
    assert "async def get_version_by_id" in content, "get_version_by_id missing"


def test_max_drafts_enforced_in_service() -> None:
    """Domain: VersioningService enforces max_drafts and raises ValueError."""
    project_dir = create_fixture_project(name="ver_t29_max_drafts")
    add_data_versioning(ToolInput(project_dir=str(project_dir)))
    svc_file = project_dir / "app" / "versioning" / "service.py"
    content = svc_file.read_text()
    assert "max_drafts" in content, "max_drafts not enforced in VersioningService"
    assert "ValueError" in content, "ValueError not raised when max_drafts exceeded"


def test_mcp_tool_entry_matches_function() -> None:
    """INV-10: MCP_TOOL['entry'] must match the actual function name."""
    from adapt.extend.crud_data.add_data_versioning import MCP_TOOL
    from adapt.extend.crud_data.add_data_versioning import add_data_versioning as fn

    assert MCP_TOOL["entry"] == fn.__name__, (
        f"MCP_TOOL entry={MCP_TOOL['entry']!r} != function name={fn.__name__!r}"
    )


def test_version_lookups_scoped_by_content_type() -> None:
    """R5-O2-D3: every version query must filter by content_type, not content_id alone.

    content_id is an opaque per-type identifier and the route key is
    /{content_type}/{content_id}/...; pre-fix the service + CRUD filtered by
    content_id only, so two types sharing a content_id (article 5 / product 5)
    saw each other's versions, draft counts, version numbers, and published
    state. Every lifecycle method and the CRUD list helper must now thread
    content_type and constrain ContentVersion.content_type in the query.
    """
    import ast

    project_dir = create_fixture_project(name="ver_content_type_scope")
    add_data_versioning(ToolInput(project_dir=str(project_dir)))
    svc_src = (project_dir / "app" / "versioning" / "service.py").read_text()
    crud_src = (project_dir / "app" / "crud" / "version.py").read_text()

    # Every public + private method that runs a per-content query must take a
    # content_type parameter and constrain it.
    svc_tree = ast.parse(svc_src)
    queried = (
        "publish",
        "archive",
        "get_history",
        "diff",
        "_count_drafts",
        "_next_version_number",
        "_get_version",
        "_archive_current_published",
    )
    for node in ast.walk(svc_tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name in queried:
            params = {a.arg for a in node.args.args}
            assert "content_type" in params, (
                f"VersioningService.{node.name} ignores content_type (cross-type collision)"
            )
    # The scoping predicate must appear for both the service and the CRUD lookup.
    assert "ContentVersion.content_type == content_type" in svc_src, (
        "service queries do not constrain content_type"
    )
    assert "ContentVersion.content_type == content_type" in crud_src, (
        "list_versions_for_content does not constrain content_type"
    )
    # The old content_id-only history query must be gone.
    assert ".where(ContentVersion.content_id == content_id)\n    )" not in svc_src, (
        "a content_id-only query still remains in the service"
    )


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
        test_content_version_model_created,
        test_versioning_service_created,
        test_draft_route_exists,
        test_publish_route_exists,
        test_history_route_exists,
        test_diff_route_exists,
        test_schema_version_read_has_config_dict,
        test_migration_created,
        test_migration_has_unique_index,
        test_diff_function_computes_added_removed_changed,
        test_versioning_package_init_exports,
        test_execution_time_recorded,
        test_next_steps_present,
        test_idempotent_project_still_parses,
        test_error_return_on_invalid_dir,
        test_dry_run_execution_time_recorded,
        test_content_version_model_has_unique_table_args,
        test_crud_version_file_created,
        test_max_drafts_enforced_in_service,
        test_mcp_tool_entry_matches_function,
        test_version_lookups_scoped_by_content_type,
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
