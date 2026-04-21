"""Tests for TOOL-009 add_feature_flags.

Generates a real fixture project via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/auth_access/test_add_feature_flags.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/auth_access/test_add_feature_flags.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import json

from adapt.contracts import ToolInput
from adapt.extend.auth_access.add_feature_flags import MCP_TOOL, add_feature_flags
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
# Test cases
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    """T-01: Tool returns status='success' on a fresh project."""
    project_dir = create_fixture_project(name="ff01_success")
    result = add_feature_flags(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


def test_files_created_exist() -> None:
    """T-02: Every path in files_created actually exists on disk."""
    project_dir = create_fixture_project(name="ff02_files_exist")
    result = add_feature_flags(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


def test_files_modified_exist() -> None:
    """T-03: Every path in files_modified actually exists on disk."""
    project_dir = create_fixture_project(name="ff03_modified_exist")
    result = add_feature_flags(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


def test_feature_flag_model_created() -> None:
    """CC-01: app/models/feature_flag.py exists with FeatureFlag and FeatureFlagAudit."""
    project_dir = create_fixture_project(name="ff04_model")
    add_feature_flags(ToolInput(project_dir=str(project_dir)))
    model_file = project_dir / "app" / "models" / "feature_flag.py"
    assert model_file.exists(), "feature_flag.py not created"
    content = model_file.read_text()
    assert "class FeatureFlag" in content
    assert "class FeatureFlagAudit" in content
    assert "kill_switch" in content
    assert "rollout_percentage" in content


def test_flag_model_has_check_constraints() -> None:
    """CC-11/12/13: Model has check constraints for flag_type, rollout, key format."""
    project_dir = create_fixture_project(name="ff05_constraints")
    add_feature_flags(ToolInput(project_dir=str(project_dir)))
    model_file = project_dir / "app" / "models" / "feature_flag.py"
    content = model_file.read_text()
    assert "ck_feature_flags_type" in content
    assert "ck_feature_flags_rollout_range" in content
    assert "ck_feature_flags_key_format" in content


def test_feature_flag_audit_model_has_fk() -> None:
    """CC-02: FeatureFlagAudit has FK to feature_flags.id with CASCADE."""
    project_dir = create_fixture_project(name="ff06_audit_fk")
    add_feature_flags(ToolInput(project_dir=str(project_dir)))
    model_file = project_dir / "app" / "models" / "feature_flag.py"
    content = model_file.read_text()
    assert "CASCADE" in content
    assert "feature_flags.id" in content


def test_cache_module_created() -> None:
    """CC-03: app/core/feature_flag_cache.py exists with LRU + TTL + pubsub."""
    project_dir = create_fixture_project(name="ff07_cache")
    add_feature_flags(ToolInput(project_dir=str(project_dir)))
    cache_file = project_dir / "app" / "core" / "feature_flag_cache.py"
    assert cache_file.exists(), "feature_flag_cache.py not created"
    content = cache_file.read_text()
    assert "FeatureFlagCache" in content
    assert "INVALIDATION_CHANNEL" in content
    assert "publish_invalidation" in content
    assert "OrderedDict" in content


def test_evaluator_module_created() -> None:
    """CC-04: app/core/feature_flag_evaluator.py has is_enabled and get_variant."""
    project_dir = create_fixture_project(name="ff08_evaluator")
    add_feature_flags(ToolInput(project_dir=str(project_dir)))
    eval_file = project_dir / "app" / "core" / "feature_flag_evaluator.py"
    assert eval_file.exists(), "feature_flag_evaluator.py not created"
    content = eval_file.read_text()
    assert "async def is_enabled" in content
    assert "async def get_variant" in content
    assert "FlagContext" in content


def test_evaluator_has_kill_switch() -> None:
    """INV-FF-03: Evaluator checks kill_switch first and returns False."""
    project_dir = create_fixture_project(name="ff09_kill")
    add_feature_flags(ToolInput(project_dir=str(project_dir)))
    eval_file = project_dir / "app" / "core" / "feature_flag_evaluator.py"
    content = eval_file.read_text()
    assert "kill_switch" in content
    # kill_switch must be checked before enabled
    kill_idx = content.find('flag["kill_switch"]')
    enabled_idx = content.find('flag["enabled"]')
    assert kill_idx != -1 and enabled_idx != -1
    assert kill_idx < enabled_idx, "kill_switch must be checked before enabled"


def test_evaluator_bucketing_is_sha256() -> None:
    """INV-FF-04: Bucketing uses SHA-256 (deterministic)."""
    project_dir = create_fixture_project(name="ff10_sha256")
    add_feature_flags(ToolInput(project_dir=str(project_dir)))
    eval_file = project_dir / "app" / "core" / "feature_flag_evaluator.py"
    content = eval_file.read_text()
    assert "sha256" in content
    assert "hashlib" in content


def test_evaluator_never_raises() -> None:
    """INV-FF-01: is_enabled and get_variant are wrapped in try/except."""
    project_dir = create_fixture_project(name="ff11_no_raise")
    add_feature_flags(ToolInput(project_dir=str(project_dir)))
    eval_file = project_dir / "app" / "core" / "feature_flag_evaluator.py"
    content = eval_file.read_text()
    assert "try:" in content
    assert "except" in content


def test_evaluator_has_timeout() -> None:
    """INV-FF-06 / QS-2: Evaluator uses asyncio.wait_for for hard cap."""
    project_dir = create_fixture_project(name="ff12_timeout")
    add_feature_flags(ToolInput(project_dir=str(project_dir)))
    eval_file = project_dir / "app" / "core" / "feature_flag_evaluator.py"
    content = eval_file.read_text()
    assert "wait_for" in content
    assert "EVAL_TIMEOUT_S" in content


def test_deps_module_created() -> None:
    """CC-05: app/core/feature_flag_deps.py has require_flag."""
    project_dir = create_fixture_project(name="ff13_deps")
    add_feature_flags(ToolInput(project_dir=str(project_dir)))
    deps_file = project_dir / "app" / "core" / "feature_flag_deps.py"
    assert deps_file.exists(), "feature_flag_deps.py not created"
    content = deps_file.read_text()
    assert "def require_flag" in content
    assert "HTTP_404_NOT_FOUND" in content


def test_crud_module_created() -> None:
    """CC-06: app/crud/feature_flag.py has create/update/delete/get_by_key."""
    project_dir = create_fixture_project(name="ff14_crud")
    add_feature_flags(ToolInput(project_dir=str(project_dir)))
    crud_file = project_dir / "app" / "crud" / "feature_flag.py"
    assert crud_file.exists(), "crud/feature_flag.py not created"
    content = crud_file.read_text()
    for fn in ("get_by_key", "create", "update", "delete"):
        assert f"async def {fn}" in content, f"Missing function: {fn}"


def test_crud_writes_audit_on_create() -> None:
    """INV-FF-07: create() writes an audit row."""
    project_dir = create_fixture_project(name="ff15_audit_create")
    add_feature_flags(ToolInput(project_dir=str(project_dir)))
    crud_file = project_dir / "app" / "crud" / "feature_flag.py"
    content = crud_file.read_text()
    # _write_audit must be called inside create function
    create_start = content.find("async def create")
    create_end = content.find("\nasync def update", create_start)
    create_body = content[create_start:create_end]
    assert "_write_audit" in create_body or "FeatureFlagAudit" in create_body


def test_crud_writes_audit_on_update() -> None:
    """INV-FF-07: update() writes an audit row."""
    project_dir = create_fixture_project(name="ff16_audit_update")
    add_feature_flags(ToolInput(project_dir=str(project_dir)))
    crud_file = project_dir / "app" / "crud" / "feature_flag.py"
    content = crud_file.read_text()
    update_start = content.find("async def update")
    update_end = content.find("\nasync def delete", update_start)
    update_body = content[update_start:update_end]
    assert "_write_audit" in update_body or "FeatureFlagAudit" in update_body


def test_schemas_created() -> None:
    """CC-08: app/schemas/feature_flag.py has Create/Update/Public schemas."""
    project_dir = create_fixture_project(name="ff17_schemas")
    add_feature_flags(ToolInput(project_dir=str(project_dir)))
    schema_file = project_dir / "app" / "schemas" / "feature_flag.py"
    assert schema_file.exists(), "schemas/feature_flag.py not created"
    content = schema_file.read_text()
    assert "FeatureFlagCreate" in content
    assert "FeatureFlagUpdate" in content
    assert "FeatureFlagPublic" in content


def test_routes_created() -> None:
    """CC-07: app/api/routes/feature_flags.py has POST/GET/PATCH/DELETE."""
    project_dir = create_fixture_project(name="ff18_routes")
    add_feature_flags(ToolInput(project_dir=str(project_dir)))
    routes_file = project_dir / "app" / "api" / "routes" / "feature_flags.py"
    assert routes_file.exists(), "feature_flags.py routes not created"
    content = routes_file.read_text()
    assert "async def create_flag" in content
    assert "async def get_flag" in content
    assert "async def update_flag" in content
    assert "async def delete_flag" in content


def test_routes_require_superuser() -> None:
    """QS-10: Admin routes use CurrentSuperuser dep."""
    project_dir = create_fixture_project(name="ff19_superuser")
    add_feature_flags(ToolInput(project_dir=str(project_dir)))
    routes_file = project_dir / "app" / "api" / "routes" / "feature_flags.py"
    content = routes_file.read_text()
    assert "CurrentSuperuser" in content


def test_migration_created() -> None:
    """CC-09: Alembic migration creates feature_flags and feature_flag_audit tables."""
    project_dir = create_fixture_project(name="ff20_migration")
    add_feature_flags(ToolInput(project_dir=str(project_dir)))
    versions_dir = project_dir / "alembic" / "versions"
    migration_files = list(versions_dir.glob("*feature_flags*"))
    assert len(migration_files) >= 1, "No feature-flags migration file created"
    content = migration_files[0].read_text()
    assert "feature_flags" in content
    assert "feature_flag_audit" in content
    assert "def upgrade" in content
    assert "def downgrade" in content


def test_migration_has_check_constraints() -> None:
    """CC-11/12/13: Migration includes all three check constraints."""
    project_dir = create_fixture_project(name="ff21_migration_constraints")
    add_feature_flags(ToolInput(project_dir=str(project_dir)))
    versions_dir = project_dir / "alembic" / "versions"
    migration_files = list(versions_dir.glob("*feature_flags*"))
    content = migration_files[0].read_text()
    assert "ck_feature_flags_type" in content
    assert "ck_feature_flags_rollout_range" in content
    assert "ck_feature_flags_key_format" in content


def test_all_py_files_parse() -> None:
    """CC-22: All .py files in the project parse without SyntaxError after tool runs."""
    project_dir = create_fixture_project(name="ff22_parse_all")
    add_feature_flags(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_idempotent_returns_no_op() -> None:
    """CC-29 / QS: Running the tool twice returns no_op on the second run."""
    project_dir = create_fixture_project(name="ff23_idempotent")
    r1 = add_feature_flags(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_feature_flags(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


def test_idempotent_project_still_parses() -> None:
    """After two runs the project must still be fully parseable."""
    project_dir = create_fixture_project(name="ff24_idempotent_parse")
    add_feature_flags(ToolInput(project_dir=str(project_dir)))
    add_feature_flags(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_dry_run_writes_nothing() -> None:
    """dry_run=True must return status='success' but write no files."""
    project_dir = create_fixture_project(name="ff25_dry_run")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_feature_flags(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


# ---------------------------------------------------------------------------
# CONTRACT §B1.0 + §B1.0.1 — primitive copy + thin glue
# ---------------------------------------------------------------------------

def test_primitive_copied() -> None:
    """CONTRACT §B1.0: FeatureToggle + FeatureFlagCache primitives are copied."""
    project_dir = create_fixture_project(name="ff_b10_prim")
    add_feature_flags(ToolInput(project_dir=str(project_dir)))
    ft = project_dir / "core" / "venous" / "flags" / "FeatureToggle" / "FeatureToggle.py"
    ffc = project_dir / "core" / "venous" / "auth" / "FeatureFlagCache" / "FeatureFlagCache.py"
    assert ft.exists(), f"FeatureToggle primitive not copied: {ft}"
    assert ffc.exists(), f"FeatureFlagCache primitive not copied: {ffc}"
    assert "class FeatureToggleRegistry" in ft.read_text()
    assert "class FeatureFlagCache" in ffc.read_text()


def test_manifest_records_primitives() -> None:
    """CONTRACT §B1.0: .venous_manifest.json records both primitives."""
    project_dir = create_fixture_project(name="ff_b10_manifest")
    add_feature_flags(ToolInput(project_dir=str(project_dir)))
    manifest = json.loads((project_dir / ".venous_manifest.json").read_text())
    qnames = {p["qualified_name"] for p in manifest["primitives"]}
    assert "core.venous.flags.FeatureToggle" in qnames
    assert "core.venous.auth.FeatureFlagCache" in qnames


def test_glue_imports_primitives() -> None:
    """CONTRACT §B1.0.1: glue imports FeatureToggleRegistry + FeatureFlagCache."""
    project_dir = create_fixture_project(name="ff_b10_glue_imports")
    add_feature_flags(ToolInput(project_dir=str(project_dir)))
    glue = project_dir / "app" / "feature_flags.py"
    assert glue.exists(), f"glue not written: {glue}"
    body = glue.read_text()
    assert "from core.venous.flags.FeatureToggle" in body
    assert "from core.venous.auth.FeatureFlagCache" in body
    assert "FeatureToggleRegistry" in body
    assert "FeatureFlagCache" in body


def test_glue_body_under_20_loc() -> None:
    """CONTRACT §B1.0.1: primary glue body stays below 20 executable lines."""
    project_dir = create_fixture_project(name="ff_b10_loc")
    add_feature_flags(ToolInput(project_dir=str(project_dir)))
    tree = ast.parse((project_dir / "app" / "feature_flags.py").read_text())
    body_lines = 0
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.body[0].lineno
            end = node.end_lineno or start
            body_lines += end - start + 1
    assert body_lines <= 20, body_lines


def test_mcp_tool_metadata() -> None:
    """MCP_TOOL declares imports_primitives per CONTRACT §B1.0."""
    assert MCP_TOOL["entry"] == "add_feature_flags"
    assert "core.venous.flags.FeatureToggle" in MCP_TOOL["imports_primitives"]
    assert "core.venous.auth.FeatureFlagCache" in MCP_TOOL["imports_primitives"]
    assert tuple(MCP_TOOL["imports_adapters"]) == ()


# ---------------------------------------------------------------------------
# Standalone runner (fallback when pytest is unavailable)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_success_status,
        test_files_created_exist,
        test_files_modified_exist,
        test_feature_flag_model_created,
        test_flag_model_has_check_constraints,
        test_feature_flag_audit_model_has_fk,
        test_cache_module_created,
        test_evaluator_module_created,
        test_evaluator_has_kill_switch,
        test_evaluator_bucketing_is_sha256,
        test_evaluator_never_raises,
        test_evaluator_has_timeout,
        test_deps_module_created,
        test_crud_module_created,
        test_crud_writes_audit_on_create,
        test_crud_writes_audit_on_update,
        test_schemas_created,
        test_routes_created,
        test_routes_require_superuser,
        test_migration_created,
        test_migration_has_check_constraints,
        test_all_py_files_parse,
        test_idempotent_returns_no_op,
        test_idempotent_project_still_parses,
        test_dry_run_writes_nothing,
        test_primitive_copied,
        test_manifest_records_primitives,
        test_glue_imports_primitives,
        test_glue_body_under_20_loc,
        test_mcp_tool_metadata,
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
