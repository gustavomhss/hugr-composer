"""Structural tests for TOOL-115 add_dpop_tokens.

Generates real fixture projects, runs the tool, and verifies all
completeness criteria from the MEGA_BRIEFING.

Run with::

    PYTHONPATH=. pytest adapt/extend/auth_access/test_add_dpop_tokens.py -v

or standalone::

    PYTHONPATH=. python3 adapt/extend/auth_access/test_add_dpop_tokens.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.auth_access.add_dpop_tokens import add_dpop_tokens
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
# CC-01 — status='success'
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    """Tool returns status='success' on a fresh project."""
    project_dir = create_fixture_project(name="dpop_t01")
    result = add_dpop_tokens(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", (
        f"Expected success, got {result.status}: {result.error}"
    )


# ---------------------------------------------------------------------------
# CC-02 — idempotent
# ---------------------------------------------------------------------------

def test_idempotent() -> None:
    """Second run returns status='no_op' without touching files."""
    project_dir = create_fixture_project(name="dpop_t02")
    r1 = add_dpop_tokens(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_dpop_tokens(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


# ---------------------------------------------------------------------------
# CC-03 — dry_run
# ---------------------------------------------------------------------------

def test_dry_run() -> None:
    """dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="dpop_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_dpop_tokens(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


# ---------------------------------------------------------------------------
# CC-04 — files_created_count
# ---------------------------------------------------------------------------

def test_files_created_count() -> None:
    """Tool creates at least 3 files."""
    project_dir = create_fixture_project(name="dpop_t04")
    result = add_dpop_tokens(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 3, (
        f"Expected >= 3 files_created, got {len(result.files_created)}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-05 — files_modified_count
# ---------------------------------------------------------------------------

def test_files_modified_count() -> None:
    """Tool modifies at least 2 files (config, routes init, requirements)."""
    project_dir = create_fixture_project(name="dpop_t05")
    result = add_dpop_tokens(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_modified) >= 2, (
        f"Expected >= 2 files_modified, got {len(result.files_modified)}"
    )
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-06 — all .py parse
# ---------------------------------------------------------------------------

def test_all_py_parse() -> None:
    """Every generated .py file AST-parses clean."""
    project_dir = create_fixture_project(name="dpop_t06")
    add_dpop_tokens(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# CC-07 — no function over 50 LOC
# ---------------------------------------------------------------------------

def test_no_function_over_50_loc() -> None:
    """No function in generated app/ exceeds 50 LOC."""
    project_dir = create_fixture_project(name="dpop_t07")
    add_dpop_tokens(ToolInput(project_dir=str(project_dir)))
    max_loc = _max_function_loc(project_dir, "app")
    assert max_loc <= 50, f"Found function with {max_loc} LOC (limit: 50)"


# ---------------------------------------------------------------------------
# CC-08 — config fields patched
# ---------------------------------------------------------------------------

def test_config_fields_patched() -> None:
    """DPOP_ENABLED, DPOP_NONCE_TTL_S, DPOP_CLOCK_SKEW_S are in config.py."""
    project_dir = create_fixture_project(name="dpop_t08")
    add_dpop_tokens(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    for field in ["DPOP_ENABLED", "DPOP_NONCE_TTL_S", "DPOP_CLOCK_SKEW_S"]:
        assert field in content, f"Config field {field} missing"
    for line in content.splitlines():
        if "DPOP_ENABLED" in line and ":" in line:
            assert line.startswith("    "), (
                f"DPOP_ENABLED not inside class body: {line!r}"
            )
            break


# ---------------------------------------------------------------------------
# CC-10 — routes registered
# ---------------------------------------------------------------------------

def test_routes_registered() -> None:
    """DPoP nonce router is registered in app/routes/__init__.py."""
    project_dir = create_fixture_project(name="dpop_t10")
    add_dpop_tokens(ToolInput(project_dir=str(project_dir)))
    routes_init = project_dir / "app" / "routes" / "__init__.py"
    if routes_init.exists():
        content = routes_init.read_text()
        assert "dpop" in content.lower(), (
            "DPoP router not registered in routes/__init__.py"
        )


# ---------------------------------------------------------------------------
# CC-11+ — domain-specific tests
# ---------------------------------------------------------------------------

def test_dpop_core_file_exists() -> None:
    """app/core/dpop.py exists with DPoPVerifier class."""
    project_dir = create_fixture_project(name="dpop_t11")
    add_dpop_tokens(ToolInput(project_dir=str(project_dir)))
    dpop_core = project_dir / "app" / "core" / "dpop.py"
    assert dpop_core.exists(), "app/core/dpop.py not created"
    content = dpop_core.read_text()
    assert "DPoPVerifier" in content, "DPoPVerifier not found"
    assert "DPoPNonceStore" in content, "DPoPNonceStore not found"


def test_pyjwt_lazy_import() -> None:
    """PyJWT (jwt) is NOT imported at module top level in dpop.py."""
    project_dir = create_fixture_project(name="dpop_t12")
    add_dpop_tokens(ToolInput(project_dir=str(project_dir)))
    dpop_core = project_dir / "app" / "core" / "dpop.py"
    tree = ast.parse(dpop_core.read_text())
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "jwt", "jwt imported at top level in dpop.py"
        elif isinstance(node, ast.ImportFrom):
            assert node.module != "jwt", "jwt imported at top level via 'from'"


def test_require_dpop_dependency_exists() -> None:
    """app/core/dpop_deps.py exists with require_dpop and require_dpop_async."""
    project_dir = create_fixture_project(name="dpop_t13")
    add_dpop_tokens(ToolInput(project_dir=str(project_dir)))
    deps_file = project_dir / "app" / "core" / "dpop_deps.py"
    assert deps_file.exists(), "app/core/dpop_deps.py not created"
    content = deps_file.read_text()
    assert "require_dpop" in content, "require_dpop not found in deps"
    assert "require_dpop_async" in content, "require_dpop_async not found in deps"


def test_nonce_route_exists() -> None:
    """app/api/routes/dpop_nonce.py exists with /auth/dpop/nonce endpoint."""
    project_dir = create_fixture_project(name="dpop_t14")
    add_dpop_tokens(ToolInput(project_dir=str(project_dir)))
    nonce_route = project_dir / "app" / "api" / "routes" / "dpop_nonce.py"
    assert nonce_route.exists(), "dpop_nonce.py not created"
    content = nonce_route.read_text()
    assert "/auth/dpop" in content or "dpop/nonce" in content, (
        "DPoP nonce endpoint prefix not found"
    )
    assert "DPoP-Nonce" in content, "DPoP-Nonce response header not set"


def test_htm_htu_validation_present() -> None:
    """dpop.py validates htm (HTTP method) and htu (URI) claims."""
    project_dir = create_fixture_project(name="dpop_t15")
    add_dpop_tokens(ToolInput(project_dir=str(project_dir)))
    dpop_core = project_dir / "app" / "core" / "dpop.py"
    content = dpop_core.read_text()
    assert "htm" in content, "htm claim validation not found"
    assert "htu" in content, "htu claim validation not found"


def test_nonce_store_replay_protection() -> None:
    """DPoPNonceStore tracks jti claims to prevent replay attacks."""
    project_dir = create_fixture_project(name="dpop_t16")
    add_dpop_tokens(ToolInput(project_dir=str(project_dir)))
    dpop_core = project_dir / "app" / "core" / "dpop.py"
    content = dpop_core.read_text()
    assert "mark_jti" in content, "JTI replay protection method not found"
    assert "jti" in content, "jti claim not referenced"


def test_allowed_algorithms_present() -> None:
    """dpop.py defines a set of allowed signing algorithms (ES256 etc.)."""
    project_dir = create_fixture_project(name="dpop_t17")
    add_dpop_tokens(ToolInput(project_dir=str(project_dir)))
    dpop_core = project_dir / "app" / "core" / "dpop.py"
    content = dpop_core.read_text()
    assert "ES256" in content, "ES256 algorithm not in allowed set"
    assert "RS256" in content, "RS256 algorithm not in allowed set"


def test_keygen_helpers_present() -> None:
    """dpop.py provides generate_dpop_key_pair and jwk_from_public_key."""
    project_dir = create_fixture_project(name="dpop_t18")
    add_dpop_tokens(ToolInput(project_dir=str(project_dir)))
    dpop_core = project_dir / "app" / "core" / "dpop.py"
    content = dpop_core.read_text()
    assert "generate_dpop_key_pair" in content, "generate_dpop_key_pair not found"
    assert "jwk_from_public_key" in content, "jwk_from_public_key not found"


def test_requirements_pyjwt() -> None:
    """requirements.txt contains PyJWT."""
    project_dir = create_fixture_project(name="dpop_t19")
    add_dpop_tokens(ToolInput(project_dir=str(project_dir)))
    requirements = project_dir / "requirements.txt"
    content = requirements.read_text()
    assert "PyJWT" in content or "pyjwt" in content.lower(), (
        "PyJWT not in requirements.txt"
    )


# ---------------------------------------------------------------------------
# CC-N-1 — execution_time_ms
# ---------------------------------------------------------------------------

def test_execution_time_recorded() -> None:
    """execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="dpop_t_time")
    result = add_dpop_tokens(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


# ---------------------------------------------------------------------------
# CC-N — next_steps_present
# ---------------------------------------------------------------------------

def test_next_steps_present() -> None:
    """Result includes next_steps mentioning DPoP or DPOP_ENABLED."""
    project_dir = create_fixture_project(name="dpop_t_ns")
    result = add_dpop_tokens(ToolInput(project_dir=str(project_dir)))
    assert len(result.next_steps) > 0, "next_steps should not be empty"
    joined = " ".join(result.next_steps)
    assert "DPOP_ENABLED" in joined or "DPoP" in joined, (
        "Expected DPoP mention in next_steps"
    )


# ---------------------------------------------------------------------------
# CC-LAST — idempotent project still parses
# ---------------------------------------------------------------------------

def test_idempotent_project_still_parses() -> None:
    """After two runs all .py files remain parseable."""
    project_dir = create_fixture_project(name="dpop_t_last")
    add_dpop_tokens(ToolInput(project_dir=str(project_dir)))
    add_dpop_tokens(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


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
        test_routes_registered,
        test_dpop_core_file_exists,
        test_pyjwt_lazy_import,
        test_require_dpop_dependency_exists,
        test_nonce_route_exists,
        test_htm_htu_validation_present,
        test_nonce_store_replay_protection,
        test_allowed_algorithms_present,
        test_keygen_helpers_present,
        test_requirements_pyjwt,
        test_execution_time_recorded,
        test_next_steps_present,
        test_idempotent_project_still_parses,
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
    print(f"TOOL-115 add_dpop_tokens: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
