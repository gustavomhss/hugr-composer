"""Structural tests for TOOL-075 add_passkey_auth.

Generates a real fixture project via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the MEGA_BRIEFING spec.

Run with::

    PYTHONPATH=. python3 adapt/extend/auth_access/test_add_passkey_auth.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.auth_access.add_passkey_auth import add_passkey_auth
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
    result = add_passkey_auth(ToolInput(project_dir=str(project_dir)))
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
    _, result = _run("t075_01_success")
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


# ---------------------------------------------------------------------------
# CC-02: idempotency
# ---------------------------------------------------------------------------

def test_idempotent_returns_no_op() -> None:
    """CC-02: Running the tool twice returns no_op on the second run."""
    project_dir = create_fixture_project(name="t075_02_idempotent")
    r1 = add_passkey_auth(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_passkey_auth(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created
    assert not r2.files_modified


# ---------------------------------------------------------------------------
# CC-03: dry_run
# ---------------------------------------------------------------------------

def test_dry_run_writes_nothing() -> None:
    """CC-03: dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="t075_03_dry_run")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_passkey_auth(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


# ---------------------------------------------------------------------------
# CC-04: files_created count and existence
# ---------------------------------------------------------------------------

def test_files_created_count() -> None:
    """CC-04: files_created has at least 5 entries and all exist."""
    project_dir, result = _run("t075_04_created_count")
    assert result.status == "success"
    assert len(result.files_created) >= 5, (
        f"Expected >= 5 files created, got {len(result.files_created)}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-05: files_modified count and existence
# ---------------------------------------------------------------------------

def test_files_modified_count() -> None:
    """CC-05: files_modified has at least 2 entries and all exist."""
    project_dir, result = _run("t075_05_modified_count")
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
    project_dir, result = _run("t075_06_parse_all")
    assert result.status == "success"
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# CC-07: no function over 50 LOC
# ---------------------------------------------------------------------------

def test_no_function_over_50_loc() -> None:
    """CC-07: No generated function exceeds 50 LOC."""
    project_dir, result = _run("t075_07_loc")
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
    """CC-08: Config fields WEBAUTHN_RP_ID etc. patched with 4-space indent."""
    project_dir, _ = _run("t075_08_config")
    config_file = project_dir / "app" / "core" / "config.py"
    assert config_file.exists()
    content = config_file.read_text()
    for field in ("WEBAUTHN_RP_ID", "WEBAUTHN_RP_NAME", "WEBAUTHN_ORIGIN"):
        assert field in content, f"Config field {field!r} not patched"
        for line in content.splitlines():
            if field in line:
                assert line.startswith("    "), (
                    f"Field {field!r} missing 4-space indent: {line!r}"
                )


# ---------------------------------------------------------------------------
# CC-09: models/__init__.py patched
# ---------------------------------------------------------------------------

def test_models_init_patched() -> None:
    """CC-09: Passkey imported in app/models/__init__.py."""
    project_dir, _ = _run("t075_09_models_init")
    models_init = project_dir / "app" / "models" / "__init__.py"
    assert models_init.exists()
    content = models_init.read_text()
    assert "Passkey" in content, "Passkey not registered in models/__init__.py"


# ---------------------------------------------------------------------------
# CC-10: routes/__init__.py patched
# ---------------------------------------------------------------------------

def test_routes_registered() -> None:
    """CC-10: passkeys router registered in app/routes/__init__.py."""
    project_dir, _ = _run("t075_10_routes_registered")
    routes_init = project_dir / "app" / "routes" / "__init__.py"
    assert routes_init.exists()
    content = routes_init.read_text()
    assert "passkeys_router" in content, "passkeys router not registered"
    assert "passkeys" in content


# ---------------------------------------------------------------------------
# CC-11+: domain-specific tests
# ---------------------------------------------------------------------------

def test_passkey_model_created() -> None:
    """CC-11: app/models/passkey.py exists with Passkey class."""
    project_dir, _ = _run("t075_11_model")
    model_file = project_dir / "app" / "models" / "passkey.py"
    assert model_file.exists(), "passkey.py not created"
    content = model_file.read_text()
    assert "class Passkey" in content
    assert "credential_id" in content
    assert "public_key" in content
    assert "user_id" in content


def test_passkey_uses_largebinary() -> None:
    """CC-12: Passkey credential_id and public_key use LargeBinary."""
    project_dir, _ = _run("t075_12_largebinary")
    content = (project_dir / "app" / "models" / "passkey.py").read_text()
    assert "LargeBinary" in content, "credential_id/public_key must use LargeBinary"


def test_passkey_has_sign_count() -> None:
    """CC-13: Passkey model includes sign_count for cloned-credential detection."""
    project_dir, _ = _run("t075_13_sign_count")
    content = (project_dir / "app" / "models" / "passkey.py").read_text()
    assert "sign_count" in content


def test_webauthn_manager_created() -> None:
    """CC-14: app/auth/webauthn.py created with WebAuthnManager."""
    project_dir, _ = _run("t075_14_webauthn")
    webauthn_file = project_dir / "app" / "auth" / "webauthn.py"
    assert webauthn_file.exists(), "webauthn.py not created"
    content = webauthn_file.read_text()
    assert "class WebAuthnManager" in content
    assert "generate_registration_options" in content
    assert "verify_registration_response" in content
    assert "generate_authentication_options" in content
    assert "verify_authentication_response" in content


def test_py_webauthn_is_lazy_import() -> None:
    """CC-15: py_webauthn is imported lazily (inside function body) in webauthn.py."""
    project_dir, _ = _run("t075_15_lazy_pywebauthn")
    webauthn_file = project_dir / "app" / "auth" / "webauthn.py"
    tree = ast.parse(webauthn_file.read_text())
    # Top-level imports should NOT include py_webauthn
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in getattr(node, "names", [])]
            module = getattr(node, "module", "") or ""
            assert "py_webauthn" not in names and "py_webauthn" not in module, (
                "py_webauthn must not be a top-level import in webauthn.py"
            )


def test_schemas_file_created() -> None:
    """CC-16: app/schemas/passkey.py created with auth schemas."""
    project_dir, _ = _run("t075_16_schemas")
    schema_file = project_dir / "app" / "schemas" / "passkey.py"
    assert schema_file.exists(), "schemas/passkey.py not created"
    content = schema_file.read_text()
    assert "RegistrationBeginRequest" in content
    assert "RegistrationCompleteRequest" in content
    assert "AuthenticationBeginResponse" in content
    assert "AuthenticationCompleteResponse" in content


def test_routes_file_created() -> None:
    """CC-17: app/api/routes/passkeys.py has all four endpoints."""
    project_dir, _ = _run("t075_17_routes")
    routes_file = project_dir / "app" / "api" / "routes" / "passkeys.py"
    assert routes_file.exists(), "passkeys.py not created"
    content = routes_file.read_text()
    assert "register/begin" in content or "register_begin" in content
    assert "register/complete" in content or "register_complete" in content
    assert "login/begin" in content or "login_begin" in content
    assert "login/complete" in content or "login_complete" in content


def test_migration_file_created() -> None:
    """CC-18: Alembic migration file 0075_add_passkey_auth.py exists."""
    project_dir, _ = _run("t075_18_migration")
    migration_file = project_dir / "alembic" / "versions" / "0075_add_passkey_auth.py"
    assert migration_file.exists(), "Migration file not created"
    content = migration_file.read_text()
    assert "passkeys" in content
    assert "def upgrade" in content
    assert "def downgrade" in content


# ---------------------------------------------------------------------------
# CC-N-1: execution_time_ms
# ---------------------------------------------------------------------------

def test_execution_time_recorded() -> None:
    """CC-N-1: execution_time_ms is a positive integer after a successful run."""
    _, result = _run("t075_19_timing")
    assert result.execution_time_ms > 0


# ---------------------------------------------------------------------------
# CC-N: next_steps present
# ---------------------------------------------------------------------------

def test_next_steps_present() -> None:
    """CC-N: next_steps include 'alembic' and 'py_webauthn'."""
    _, result = _run("t075_20_next_steps")
    assert result.status == "success"
    assert len(result.next_steps) > 0
    combined = " ".join(result.next_steps).lower()
    assert "alembic" in combined
    assert "py_webauthn" in combined or "webauthn" in combined


# ---------------------------------------------------------------------------
# CC-LAST: idempotent project still parses
# ---------------------------------------------------------------------------

def test_idempotent_project_still_parses() -> None:
    """CC-LAST: After two runs the project must still be fully parseable."""
    project_dir = create_fixture_project(name="t075_21_idempotent_parse")
    add_passkey_auth(ToolInput(project_dir=str(project_dir)))
    add_passkey_auth(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# Extra domain test: unique constraint on credential_id
# ---------------------------------------------------------------------------

def test_passkey_unique_constraint_on_credential_id() -> None:
    """CC-22: Passkey has UniqueConstraint on credential_id."""
    project_dir, _ = _run("t075_22_unique_credential")
    content = (project_dir / "app" / "models" / "passkey.py").read_text()
    assert "UniqueConstraint" in content or "uq_passkey_credential_id" in content


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
        test_passkey_model_created,
        test_passkey_uses_largebinary,
        test_passkey_has_sign_count,
        test_webauthn_manager_created,
        test_py_webauthn_is_lazy_import,
        test_schemas_file_created,
        test_routes_file_created,
        test_migration_file_created,
        test_execution_time_recorded,
        test_next_steps_present,
        test_idempotent_project_still_parses,
        test_passkey_unique_constraint_on_credential_id,
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
