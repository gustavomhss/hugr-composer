"""Tests for TOOL-010 add_api_key_auth.

Generates a real fixture project via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the spec.

Run with::

    PYTHONPATH=. python3 adapt/extend/auth_access/test_add_api_key_auth.py
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.auth_access.add_api_key_auth import add_api_key_auth
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


def _run(name: str) -> tuple[Path, object]:
    project_dir = create_fixture_project(name=name)
    result = add_api_key_auth(ToolInput(project_dir=str(project_dir)))
    return project_dir, result


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


def test_success_status() -> None:
    """T-01: Tool returns status='success' on a fresh project."""
    _, result = _run("t010_01_success")
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


def test_files_created_exist() -> None:
    """T-02: Every path in files_created actually exists on disk."""
    _, result = _run("t010_02_created")
    assert result.status == "success"
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


def test_files_modified_exist() -> None:
    """T-03: Every path in files_modified actually exists on disk."""
    _, result = _run("t010_03_modified")
    assert result.status == "success"
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


def test_model_file_created() -> None:
    """CC-01: app/models/api_key.py exists and contains APIKey."""
    project_dir, _ = _run("t010_04_model")
    model_file = project_dir / "app" / "models" / "api_key.py"
    assert model_file.exists(), "api_key.py not created"
    content = model_file.read_text()
    assert "class APIKey" in content
    assert "key_id" in content
    assert "secret_hash" in content
    assert "scopes" in content
    assert "revoked_at" in content


def test_model_status_check_constraint() -> None:
    """CC-11: Model has status CHECK active/revoked/expired."""
    project_dir, _ = _run("t010_05_status_constraint")
    content = (project_dir / "app" / "models" / "api_key.py").read_text()
    assert "active" in content and "revoked" in content and "expired" in content


def test_hasher_file_created() -> None:
    """CC-02: app/core/api_key_hasher.py exists with required functions."""
    project_dir, _ = _run("t010_06_hasher")
    hasher_file = project_dir / "app" / "core" / "api_key_hasher.py"
    assert hasher_file.exists(), "api_key_hasher.py not created"
    content = hasher_file.read_text()
    for fn in ("generate_secret", "generate_key_id", "hash_secret", "verify_secret"):
        assert f"def {fn}" in content, f"Missing function: {fn}"


def test_dummy_hash_present() -> None:
    """QS-03: DUMMY_HASH constant exists for constant-time fake verification."""
    project_dir, _ = _run("t010_07_dummy_hash")
    content = (project_dir / "app" / "core" / "api_key_hasher.py").read_text()
    assert "DUMMY_HASH" in content, "DUMMY_HASH constant missing"


def test_verify_uses_compare_digest() -> None:
    """INV-AK-05: verify_secret uses hmac.compare_digest (constant-time)."""
    project_dir, _ = _run("t010_08_compare_digest")
    content = (project_dir / "app" / "core" / "api_key_hasher.py").read_text()
    assert "compare_digest" in content, "verify_secret must use hmac.compare_digest"


def test_rate_limit_file_created() -> None:
    """CC-04: app/core/api_key_rate_limit.py exists with check_rate_limit."""
    project_dir, _ = _run("t010_09_rate_limit")
    rate_file = project_dir / "app" / "core" / "api_key_rate_limit.py"
    assert rate_file.exists(), "api_key_rate_limit.py not created"
    content = rate_file.read_text()
    assert "async def check_rate_limit" in content


def test_rate_limit_has_redis_and_fallback() -> None:
    """QS-07: Rate limit has both Redis path and in-process fallback."""
    project_dir, _ = _run("t010_10_rate_fallback")
    content = (project_dir / "app" / "core" / "api_key_rate_limit.py").read_text()
    assert "pipeline" in content or "pipe" in content, "Redis pipeline path missing"
    assert "_check_in_process" in content or "in_process" in content, "In-process fallback missing"


def test_scopes_file_created() -> None:
    """CC: app/auth/api_key_scopes.py exists with evaluate_scope."""
    project_dir, _ = _run("t010_11_scopes")
    scopes_file = project_dir / "app" / "auth" / "api_key_scopes.py"
    assert scopes_file.exists(), "api_key_scopes.py not created"
    content = scopes_file.read_text()
    assert "def evaluate_scope" in content
    assert "ScopeCheckResult" in content


def test_scope_wildcard_supported() -> None:
    """QS-06: Scope evaluator supports resource:action wildcard (*:*)."""
    project_dir, _ = _run("t010_12_wildcard")
    content = (project_dir / "app" / "auth" / "api_key_scopes.py").read_text()
    assert '"*"' in content or "'*'" in content, "Wildcard logic missing in scope evaluator"


# ---------------------------------------------------------------------------
# R7-N2 (CRITICAL): grantable-scope allow-list / privilege-escalation guard
# ---------------------------------------------------------------------------


def _load_emitted_scopes_module(project_dir: Path):
    """Import the emitted ``app/auth/api_key_scopes.py`` as a standalone module.

    Loads it under a unique name (per project) so repeated tests don't collide
    in ``sys.modules`` and so the env-driven allow-list is re-read.
    """
    import importlib.util

    scopes_file = project_dir / "app" / "auth" / "api_key_scopes.py"
    mod_name = f"_emitted_scopes_{project_dir.name}"
    spec = importlib.util.spec_from_file_location(mod_name, scopes_file)
    assert spec and spec.loader, "could not build import spec for emitted scopes module"
    mod = importlib.util.module_from_spec(spec)
    # Register before exec so the module's @dataclass can resolve its own
    # module via sys.modules (dataclasses looks the class's module up there).
    sys.modules[mod_name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.modules.pop(mod_name, None)
    return mod


def test_scope_allowlist_emitted() -> None:
    """R7-N2: emitted scopes module exposes the grantable-scope guard API."""
    project_dir, _ = _run("t010_14_allowlist_emitted")
    content = (project_dir / "app" / "auth" / "api_key_scopes.py").read_text()
    assert "def validate_grantable_scopes" in content, (
        "R7-N2: grantable-scope validator missing from emitted scopes module"
    )
    assert "ScopeNotGrantableError" in content
    assert "GRANTABLE_SCOPES" in content


def test_routes_enforce_scope_allowlist() -> None:
    """R7-N2: POST /api-keys/ wires the validator before key material is made."""
    project_dir, _ = _run("t010_15_routes_enforce")
    routes = (project_dir / "app" / "api" / "routes" / "api_keys.py").read_text()
    assert "validate_grantable_scopes(key_in.scopes)" in routes, (
        "R7-N2: create_api_key does not validate requested scopes"
    )
    # The guard must run BEFORE the secret/token is generated.
    guard_idx = routes.index("validate_grantable_scopes(key_in.scopes)")
    gen_idx = routes.index("generate_secret()")
    assert guard_idx < gen_idx, "R7-N2: scope validation must precede key-material generation"
    assert "422" in routes or "HTTP_422" in routes, "R7-N2: invalid scope must surface as 422"


def test_wildcard_scope_rejected_at_grant() -> None:
    """R7-N2: a self-service caller cannot mint a wildcard-scoped key."""
    project_dir, _ = _run("t010_16_wildcard_rejected")
    mod = _load_emitted_scopes_module(project_dir)
    for bad in ("*:*", "admin:*", "*:write"):
        try:
            mod.validate_grantable_scopes([bad])
        except mod.ScopeNotGrantableError:
            continue
        raise AssertionError(f"R7-N2: wildcard scope {bad!r} was wrongly accepted")


def test_unlisted_scope_rejected_at_grant() -> None:
    """R7-N2: a scope outside the allow-list is rejected (deny-by-default)."""
    project_dir, _ = _run("t010_17_unlisted_rejected")
    mod = _load_emitted_scopes_module(project_dir)
    try:
        mod.validate_grantable_scopes(["billing:delete"])
    except mod.ScopeNotGrantableError:
        return
    raise AssertionError("R7-N2: unlisted scope 'billing:delete' was wrongly accepted")


def test_default_scopes_grantable() -> None:
    """R7-N2: the schema-default scopes (read/write) remain grantable."""
    project_dir, _ = _run("t010_18_default_grantable")
    mod = _load_emitted_scopes_module(project_dir)
    assert mod.validate_grantable_scopes(["read"]) == ["read"]
    assert mod.validate_grantable_scopes(["read", "write", "read"]) == ["read", "write"]


# ---------------------------------------------------------------------------
# R8-J1-3 / R8-J7-2: grantable allow-list must be coherent with the
# resource:action evaluator the guards actually use.
# ---------------------------------------------------------------------------


def test_default_grant_satisfies_resource_action_guard() -> None:
    """R8-J1-3: a default-granted bare 'read' satisfies require_scope('orders:read').

    Pre-fix this FAILED: the default allow-list grants bare ``read`` but the
    evaluator only matched ``resource:action`` (splitting on ``:`` gave
    ``action=""``), so a default key authorized nothing.
    """
    project_dir, _ = _run("t010_r8_grant_eval_coherent")
    mod = _load_emitted_scopes_module(project_dir)
    granted = mod.validate_grantable_scopes(["read"])  # the default schema scope
    result = mod.evaluate_scope(granted, "orders:read")
    assert result.allowed is True, (
        "R8-J1-3: a granted bare 'read' must satisfy require_scope('orders:read')"
    )
    # bare 'read' must NOT widen to write
    assert mod.evaluate_scope(granted, "orders:write").allowed is False, (
        "bare 'read' must not satisfy a :write guard"
    )


def test_bare_write_grant_satisfies_write_guard() -> None:
    """R8-J1-3: a granted bare 'write' satisfies any resource:write guard."""
    project_dir, _ = _run("t010_r8_bare_write")
    mod = _load_emitted_scopes_module(project_dir)
    granted = mod.validate_grantable_scopes(["write"])
    assert mod.evaluate_scope(granted, "billing:write").allowed is True
    assert mod.evaluate_scope(granted, "billing:read").allowed is False


def test_resource_action_grant_still_works() -> None:
    """R8-J1-3: explicit resource:action grants (via env config) still evaluate.

    Exercises the documented finer-grained config path: an operator widens
    ``API_KEY_GRANTABLE_SCOPES`` to resource-scoped literals.
    """
    project_dir = create_fixture_project(name="t010_r8_resource_grant")
    add_api_key_auth(ToolInput(project_dir=str(project_dir)))
    prev = os.environ.get("API_KEY_GRANTABLE_SCOPES")
    os.environ["API_KEY_GRANTABLE_SCOPES"] = "orders:read,billing:write"
    try:
        mod = _load_emitted_scopes_module(project_dir)
        granted = mod.validate_grantable_scopes(["orders:read", "billing:write"])
        assert mod.evaluate_scope(granted, "orders:read").allowed is True
        assert mod.evaluate_scope(granted, "billing:write").allowed is True
        # not granted -> denied (deny-by-default)
        assert mod.evaluate_scope(granted, "billing:read").allowed is False
    finally:
        if prev is None:
            os.environ.pop("API_KEY_GRANTABLE_SCOPES", None)
        else:
            os.environ["API_KEY_GRANTABLE_SCOPES"] = prev


def test_docstring_example_matches_evaluator() -> None:
    """R8-J7-2: the in-file docstring example reflects real evaluator behaviour."""
    project_dir, _ = _run("t010_r8_docstring_example")
    mod = _load_emitted_scopes_module(project_dir)
    # Example block (resource:action with wildcard) must hold.
    result = mod.evaluate_scope(["orders:read", "billing:*"], "billing:write")
    assert result.allowed is True
    assert result.matched_scope == "billing:*"
    # Example block (bare-action grant) must hold.
    assert mod.evaluate_scope(["read"], "orders:read").allowed is True
    assert mod.evaluate_scope(["read"], "orders:write").allowed is False


def test_r7n2_protection_preserved_after_coherence_fix() -> None:
    """R7-N2 must remain intact: wildcards & unlisted scopes still rejected at grant."""
    project_dir, _ = _run("t010_r8_r7n2_preserved")
    mod = _load_emitted_scopes_module(project_dir)
    for bad in ("*:*", "admin:*", "*:write", "read:*"):
        try:
            mod.validate_grantable_scopes([bad])
        except mod.ScopeNotGrantableError:
            continue
        raise AssertionError(f"R7-N2 regressed: wildcard {bad!r} was accepted at grant")
    # An unlisted resource:action literal is still denied by default.
    try:
        mod.validate_grantable_scopes(["orders:read"])
    except mod.ScopeNotGrantableError:
        pass
    else:
        raise AssertionError(
            "R7-N2 regressed: 'orders:read' grantable without being in the allow-list"
        )


def test_deps_file_created() -> None:
    """CC-03: app/core/api_key_deps.py exists with get_current_api_key + require_scope."""
    project_dir, _ = _run("t010_13_deps")
    deps_file = project_dir / "app" / "core" / "api_key_deps.py"
    assert deps_file.exists(), "api_key_deps.py not created"
    content = deps_file.read_text()
    assert "async def get_current_api_key" in content
    assert "def require_scope" in content


def test_deps_uses_dummy_hash_for_unknown_key() -> None:
    """INV-AK-05 / QS-03: Dependency uses DUMMY_HASH for unknown key_id."""
    project_dir, _ = _run("t010_14_deps_dummy")
    content = (project_dir / "app" / "core" / "api_key_deps.py").read_text()
    assert "DUMMY_HASH" in content, "Dependency must use DUMMY_HASH for unknown key_id"


def test_crud_file_created() -> None:
    """CC-05: app/crud/api_key.py exists with create/get_by_key_id/list_for_user/revoke."""
    project_dir, _ = _run("t010_15_crud")
    crud_file = project_dir / "app" / "crud" / "api_key.py"
    assert crud_file.exists(), "crud/api_key.py not created"
    content = crud_file.read_text()
    for fn in (
        "async def create",
        "async def get_by_key_id",
        "async def list_for_user",
        "async def revoke",
    ):
        assert fn in content, f"Missing CRUD function: {fn}"


def test_crud_never_stores_plaintext() -> None:
    """INV-AK-01: CRUD create accepts secret_hash, not a raw secret parameter."""
    project_dir, _ = _run("t010_16_crud_no_plain")
    content = (project_dir / "app" / "crud" / "api_key.py").read_text()
    # The create function signature must have secret_hash but NOT a bare 'secret:' param
    assert "secret_hash" in content
    # 'secret:' as a function parameter should not appear (only secret_hash)
    assert "secret: str" not in content, "CRUD must not accept a raw 'secret: str' parameter"


def test_schema_file_created() -> None:
    """CC-07: app/schemas/api_key.py exists with all four schemas."""
    project_dir, _ = _run("t010_17_schemas")
    schema_file = project_dir / "app" / "schemas" / "api_key.py"
    assert schema_file.exists(), "schemas/api_key.py not created"
    content = schema_file.read_text()
    for cls in ("APIKeyCreate", "APIKeyUpdate", "APIKeyPublic", "APIKeyCreatedResponse"):
        assert f"class {cls}" in content, f"Missing schema class: {cls}"


def test_public_schema_excludes_secret_hash() -> None:
    """CC-15 / INV-AK-02: APIKeyPublic does NOT declare a secret_hash field."""
    project_dir, _ = _run("t010_18_public_no_hash")
    content = (project_dir / "app" / "schemas" / "api_key.py").read_text()
    pub_start = content.find("class APIKeyPublic")
    pub_end = content.find("\nclass ", pub_start + 1)
    body = content[pub_start:pub_end] if pub_end != -1 else content[pub_start:]
    # Check there is no field declaration like `secret_hash: str`
    assert "secret_hash:" not in body, "APIKeyPublic must not declare a secret_hash field"


def test_created_response_has_plaintext_and_warning() -> None:
    """CC-14: APIKeyCreatedResponse includes plaintext_token and warning."""
    project_dir, _ = _run("t010_19_created_response")
    content = (project_dir / "app" / "schemas" / "api_key.py").read_text()
    assert "plaintext_token" in content
    assert "warning" in content.lower() or "Warning" in content


def test_routes_file_created() -> None:
    """CC-06: app/api/routes/api_keys.py exists with all endpoints."""
    project_dir, _ = _run("t010_20_routes")
    routes_file = project_dir / "app" / "api" / "routes" / "api_keys.py"
    assert routes_file.exists(), "routes/api_keys.py not created"
    content = routes_file.read_text()
    assert "async def create_api_key" in content
    assert "async def list_my_api_keys" in content
    assert "async def rotate_api_key" in content
    assert "async def revoke_api_key" in content


def test_routes_owner_check() -> None:
    """INV-AK-06 / CC-27: rotate and revoke verify user_id ownership."""
    project_dir, _ = _run("t010_21_owner_check")
    content = (project_dir / "app" / "api" / "routes" / "api_keys.py").read_text()
    assert "user_id" in content and "current_user.id" in content


def test_routes_revoke_returns_409_on_repeat() -> None:
    """INV-AK-03: revoke endpoint raises 409 if already revoked."""
    project_dir, _ = _run("t010_22_revoke_409")
    content = (project_dir / "app" / "api" / "routes" / "api_keys.py").read_text()
    assert "409" in content or "HTTP_409_CONFLICT" in content


def test_migration_file_created() -> None:
    """CC-08: Alembic migration file 0010_add_api_key_auth.py exists."""
    project_dir, _ = _run("t010_23_migration")
    migration_files = list((project_dir / "alembic" / "versions").glob("*api_key*"))
    assert migration_files, "No api_key migration file created"
    content = migration_files[0].read_text()
    assert "api_keys" in content
    assert "def upgrade" in content
    assert "def downgrade" in content


def test_migration_has_check_constraints() -> None:
    """CC-09: Migration includes status and key_id check constraints."""
    project_dir, _ = _run("t010_24_migration_constraints")
    migration_files = list((project_dir / "alembic" / "versions").glob("*api_key*"))
    content = migration_files[0].read_text()
    assert "ck_api_keys_status" in content
    assert "ck_api_keys_key_id_format" in content


def test_all_py_files_parse() -> None:
    """CC-20: All .py files in the project parse without SyntaxError after tool runs."""
    project_dir, result = _run("t010_25_parse_all")
    assert result.status == "success"
    _assert_parse(project_dir)


def test_idempotent_returns_no_op() -> None:
    """CC-26: Running the tool twice returns no_op on the second run."""
    project_dir = create_fixture_project(name="t010_26_idempotent")
    r1 = add_api_key_auth(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_api_key_auth(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created
    assert not r2.files_modified


def test_idempotent_project_still_parses() -> None:
    """After two runs the project must still be fully parseable."""
    project_dir = create_fixture_project(name="t010_27_idempotent_parse")
    add_api_key_auth(ToolInput(project_dir=str(project_dir)))
    add_api_key_auth(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_dry_run_writes_nothing() -> None:
    """dry_run=True must return status='success' but write no files."""
    project_dir = create_fixture_project(name="t010_28_dry_run")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_api_key_auth(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_execution_time_recorded() -> None:
    """execution_time_ms must be a positive integer after a successful run."""
    _, result = _run("t010_29_timing")
    assert result.execution_time_ms > 0


def test_next_steps_include_alembic() -> None:
    """next_steps should mention alembic upgrade."""
    _, result = _run("t010_30_next_steps")
    assert result.status == "success"
    assert any("alembic" in s.lower() for s in result.next_steps)


def test_token_format_uses_api_prefix() -> None:
    """QS-10: Routes generate tokens with api_ prefix for grep-ability."""
    project_dir, _ = _run("t010_31_token_format")
    content = (project_dir / "app" / "api" / "routes" / "api_keys.py").read_text()
    assert "api_" in content, "Token format must use api_ prefix"


def test_rate_limit_returns_429() -> None:
    """INV-AK-07: Dependency raises 429 when rate limit exceeded."""
    project_dir, _ = _run("t010_32_429")
    content = (project_dir / "app" / "core" / "api_key_deps.py").read_text()
    assert "429" in content or "HTTP_429_TOO_MANY_REQUESTS" in content


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_success_status,
        test_files_created_exist,
        test_files_modified_exist,
        test_model_file_created,
        test_model_status_check_constraint,
        test_hasher_file_created,
        test_dummy_hash_present,
        test_verify_uses_compare_digest,
        test_rate_limit_file_created,
        test_rate_limit_has_redis_and_fallback,
        test_scopes_file_created,
        test_scope_wildcard_supported,
        test_default_grant_satisfies_resource_action_guard,
        test_bare_write_grant_satisfies_write_guard,
        test_resource_action_grant_still_works,
        test_docstring_example_matches_evaluator,
        test_r7n2_protection_preserved_after_coherence_fix,
        test_deps_file_created,
        test_deps_uses_dummy_hash_for_unknown_key,
        test_crud_file_created,
        test_crud_never_stores_plaintext,
        test_schema_file_created,
        test_public_schema_excludes_secret_hash,
        test_created_response_has_plaintext_and_warning,
        test_routes_file_created,
        test_routes_owner_check,
        test_routes_revoke_returns_409_on_repeat,
        test_migration_file_created,
        test_migration_has_check_constraints,
        test_all_py_files_parse,
        test_idempotent_returns_no_op,
        test_idempotent_project_still_parses,
        test_dry_run_writes_nothing,
        test_execution_time_recorded,
        test_next_steps_include_alembic,
        test_token_format_uses_api_prefix,
        test_rate_limit_returns_429,
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
