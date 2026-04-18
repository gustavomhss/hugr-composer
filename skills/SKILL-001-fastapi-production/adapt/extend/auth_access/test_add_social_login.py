"""Structural tests for TOOL-074 add_social_login.

Generates a real fixture project via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the MEGA_BRIEFING spec.

Run with::

    PYTHONPATH=. python3 adapt/extend/auth_access/test_add_social_login.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.auth_access.add_social_login import add_social_login
from tests.common.fixture_factory import create_fixture_project


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _all_py_files(root: Path) -> list[Path]:
    """Return all .py files under root, sorted."""
    return sorted(root.rglob("*.py"))


def _assert_parse(root: Path) -> None:
    """Raise AssertionError if any .py file under root fails ast.parse."""
    for f in _all_py_files(root):
        source = f.read_text()
        try:
            ast.parse(source)
        except SyntaxError as exc:
            raise AssertionError(f"SyntaxError in {f}: {exc}") from exc


def _run(name: str) -> tuple[Path, object]:
    """Create fixture project and apply the tool."""
    project_dir = create_fixture_project(name=name)
    result = add_social_login(ToolInput(project_dir=str(project_dir)))
    return project_dir, result


def _max_func_loc(path: Path) -> tuple[int, str]:
    """Return (max_loc, func_name) for all functions in a Python file."""
    tree = ast.parse(path.read_text())
    max_loc = 0
    max_name = ""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if hasattr(node, "end_lineno"):
                loc = node.end_lineno - node.lineno + 1
                if loc > max_loc:
                    max_loc = loc
                    max_name = node.name
    return max_loc, max_name


# ---------------------------------------------------------------------------
# CC-01: success status
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    """CC-01: Tool returns status='success' on a fresh project."""
    _, result = _run("t074_01_success")
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


# ---------------------------------------------------------------------------
# CC-02: idempotency
# ---------------------------------------------------------------------------

def test_idempotent_returns_no_op() -> None:
    """CC-02: Running the tool twice returns no_op on the second run."""
    project_dir = create_fixture_project(name="t074_02_idempotent")
    r1 = add_social_login(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_social_login(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created
    assert not r2.files_modified


# ---------------------------------------------------------------------------
# CC-03: dry_run
# ---------------------------------------------------------------------------

def test_dry_run_writes_nothing() -> None:
    """CC-03: dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="t074_03_dry_run")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_social_login(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


# ---------------------------------------------------------------------------
# CC-04: files_created count and existence
# ---------------------------------------------------------------------------

def test_files_created_count() -> None:
    """CC-04: files_created has at least 6 entries and all exist."""
    project_dir, result = _run("t074_04_created_count")
    assert result.status == "success"
    assert len(result.files_created) >= 6, (
        f"Expected >= 6 files created, got {len(result.files_created)}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-05: files_modified count and existence
# ---------------------------------------------------------------------------

def test_files_modified_count() -> None:
    """CC-05: files_modified has at least 2 entries and all exist."""
    project_dir, result = _run("t074_05_modified_count")
    assert result.status == "success"
    assert len(result.files_modified) >= 2, (
        f"Expected >= 2 files modified, got {len(result.files_modified)}"
    )
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-06: all .py files parse
# ---------------------------------------------------------------------------

def test_all_py_parse() -> None:
    """CC-06: All .py files in the project parse without SyntaxError."""
    project_dir, result = _run("t074_06_parse_all")
    assert result.status == "success"
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# CC-07: no function over 50 LOC
# ---------------------------------------------------------------------------

def test_no_function_over_50_loc() -> None:
    """CC-07: No generated function exceeds 50 LOC."""
    project_dir, result = _run("t074_07_loc")
    assert result.status == "success"
    for path_str in result.files_created:
        p = Path(path_str)
        if p.suffix == ".py":
            loc, name = _max_func_loc(p)
            assert loc <= 50, (
                f"Function {name!r} in {p.name} has {loc} LOC (max 50)"
            )


# ---------------------------------------------------------------------------
# CC-08: config fields patched with 4-space indent
# ---------------------------------------------------------------------------

def test_config_fields_patched() -> None:
    """CC-08: Config fields GOOGLE_CLIENT_ID etc. patched with 4-space indent."""
    project_dir, _ = _run("t074_08_config")
    config_file = project_dir / "app" / "core" / "config.py"
    assert config_file.exists()
    content = config_file.read_text()
    for field in ("GOOGLE_CLIENT_ID", "GITHUB_CLIENT_ID", "APPLE_CLIENT_ID"):
        assert field in content, f"Config field {field!r} not patched"
        # Verify 4-space indent
        for line in content.splitlines():
            if field in line:
                assert line.startswith("    "), (
                    f"Field {field!r} missing 4-space indent: {line!r}"
                )


# ---------------------------------------------------------------------------
# CC-09: models/__init__.py patched
# ---------------------------------------------------------------------------

def test_models_init_patched() -> None:
    """CC-09: SocialAccount imported in app/models/__init__.py."""
    project_dir, _ = _run("t074_09_models_init")
    models_init = project_dir / "app" / "models" / "__init__.py"
    assert models_init.exists()
    content = models_init.read_text()
    assert "SocialAccount" in content, "SocialAccount not registered in models/__init__.py"


# ---------------------------------------------------------------------------
# CC-10: routes/__init__.py patched
# ---------------------------------------------------------------------------

def test_routes_registered() -> None:
    """CC-10: social_auth router registered in app/routes/__init__.py."""
    project_dir, _ = _run("t074_10_routes_registered")
    routes_init = project_dir / "app" / "routes" / "__init__.py"
    assert routes_init.exists()
    content = routes_init.read_text()
    assert "social_auth_router" in content, "social_auth router not registered"
    assert "social_auth" in content


# ---------------------------------------------------------------------------
# CC-11+: domain-specific tests
# ---------------------------------------------------------------------------

def test_social_account_model_created() -> None:
    """CC-11: app/models/social_account.py exists with SocialAccount class."""
    project_dir, _ = _run("t074_11_model")
    model_file = project_dir / "app" / "models" / "social_account.py"
    assert model_file.exists(), "social_account.py not created"
    content = model_file.read_text()
    assert "class SocialAccount" in content
    assert "provider" in content
    assert "provider_user_id" in content
    assert "user_id" in content


def test_social_account_unique_constraint() -> None:
    """CC-12: SocialAccount has unique constraint (provider, provider_user_id)."""
    project_dir, _ = _run("t074_12_unique_constraint")
    content = (project_dir / "app" / "models" / "social_account.py").read_text()
    assert "uq_social_provider_user" in content or "UniqueConstraint" in content


def test_social_account_check_constraint() -> None:
    """CC-13: SocialAccount has CHECK constraint for known providers."""
    project_dir, _ = _run("t074_13_check_constraint")
    content = (project_dir / "app" / "models" / "social_account.py").read_text()
    assert "google" in content and "github" in content and "apple" in content


def test_social_config_file_created() -> None:
    """CC-14: app/auth/social_config.py created with PROVIDER_CONFIGS."""
    project_dir, _ = _run("t074_14_social_config")
    config_file = project_dir / "app" / "auth" / "social_config.py"
    assert config_file.exists(), "social_config.py not created"
    content = config_file.read_text()
    assert "PROVIDER_CONFIGS" in content
    assert "get_provider_config" in content


def test_social_auth_file_created() -> None:
    """CC-15: app/auth/social.py created with SocialAuthProvider."""
    project_dir, _ = _run("t074_15_social_auth")
    social_file = project_dir / "app" / "auth" / "social.py"
    assert social_file.exists(), "social.py not created"
    content = social_file.read_text()
    assert "class SocialAuthProvider" in content
    assert "build_authorization_url" in content
    assert "exchange_code" in content


def test_httpx_is_lazy_import() -> None:
    """CC-16: httpx is imported lazily (inside function body) in social.py."""
    project_dir, _ = _run("t074_16_lazy_httpx")
    social_file = project_dir / "app" / "auth" / "social.py"
    tree = ast.parse(social_file.read_text())
    # Top-level imports should NOT include httpx
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in getattr(node, "names", [])]
            module = getattr(node, "module", "") or ""
            assert "httpx" not in names and "httpx" not in module, (
                "httpx must not be a top-level import in social.py"
            )


def test_schemas_file_created() -> None:
    """CC-17: app/schemas/social.py created with SocialLoginCallbackResponse."""
    project_dir, _ = _run("t074_17_schemas")
    schema_file = project_dir / "app" / "schemas" / "social.py"
    assert schema_file.exists(), "schemas/social.py not created"
    content = schema_file.read_text()
    assert "SocialLoginCallbackResponse" in content
    assert "SocialAccountRead" in content


def test_routes_file_created() -> None:
    """CC-18: app/api/routes/social_auth.py created with login and callback."""
    project_dir, _ = _run("t074_18_routes")
    routes_file = project_dir / "app" / "api" / "routes" / "social_auth.py"
    assert routes_file.exists(), "social_auth.py not created"
    content = routes_file.read_text()
    assert "social_login" in content or "/{provider}/login" in content
    assert "social_callback" in content or "/{provider}/callback" in content


def test_callback_validates_email_verified() -> None:
    """CC-19: Callback rejects unverified emails."""
    project_dir, _ = _run("t074_19_email_verified")
    content = (project_dir / "app" / "api" / "routes" / "social_auth.py").read_text()
    assert "email_verified" in content


def test_callback_prevents_open_redirect() -> None:
    """CC-20: return_to validated to start with '/'."""
    project_dir, _ = _run("t074_20_open_redirect")
    content = (project_dir / "app" / "api" / "routes" / "social_auth.py").read_text()
    assert 'startswith("/")' in content


def test_migration_file_created() -> None:
    """CC-21: Alembic migration file 0074_add_social_login.py exists."""
    project_dir, _ = _run("t074_21_migration")
    migration_file = project_dir / "alembic" / "versions" / "0074_add_social_login.py"
    assert migration_file.exists(), "Migration file not created"
    content = migration_file.read_text()
    assert "social_accounts" in content
    assert "def upgrade" in content
    assert "def downgrade" in content


# ---------------------------------------------------------------------------
# CC-N-1: execution_time_ms
# ---------------------------------------------------------------------------

def test_execution_time_recorded() -> None:
    """CC-N-1: execution_time_ms is a positive integer after a successful run."""
    _, result = _run("t074_22_timing")
    assert result.execution_time_ms > 0


# ---------------------------------------------------------------------------
# CC-N: next_steps present
# ---------------------------------------------------------------------------

def test_next_steps_present() -> None:
    """CC-N: next_steps includes 'alembic' keyword."""
    _, result = _run("t074_23_next_steps")
    assert result.status == "success"
    assert len(result.next_steps) > 0
    assert any("alembic" in s.lower() for s in result.next_steps)


# ---------------------------------------------------------------------------
# CC-LAST: idempotent project still parses
# ---------------------------------------------------------------------------

def test_idempotent_project_still_parses() -> None:
    """CC-LAST: After two runs the project must still be fully parseable."""
    project_dir = create_fixture_project(name="t074_24_idempotent_parse")
    add_social_login(ToolInput(project_dir=str(project_dir)))
    add_social_login(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_success_status,
        test_idempotent_returns_no_op,
        test_dry_run_writes_nothing,
        test_files_created_count,
        test_files_modified_count,
        test_all_py_parse,
        test_no_function_over_50_loc,
        test_config_fields_patched,
        test_models_init_patched,
        test_routes_registered,
        test_social_account_model_created,
        test_social_account_unique_constraint,
        test_social_account_check_constraint,
        test_social_config_file_created,
        test_social_auth_file_created,
        test_httpx_is_lazy_import,
        test_schemas_file_created,
        test_routes_file_created,
        test_callback_validates_email_verified,
        test_callback_prevents_open_redirect,
        test_migration_file_created,
        test_execution_time_recorded,
        test_next_steps_present,
        test_idempotent_project_still_parses,
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
