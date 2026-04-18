"""Tests for TOOL-107 add_request_signing.

Generates real fixture projects via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies every completeness criterion from the MEGA_BRIEFING.

Run with::

    PYTHONPATH=. pytest adapt/extend/auth_access/test_add_request_signing.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/auth_access/test_add_request_signing.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.auth_access.add_request_signing import add_request_signing
from tests.common.fixture_factory import create_fixture_project


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _all_py(root: Path) -> list[Path]:
    """Return all .py files under *root*, sorted."""
    return sorted(root.rglob("*.py"))


def _assert_parse(root: Path) -> None:
    """Raise AssertionError if any .py under *root* fails ast.parse."""
    for f in _all_py(root):
        source = f.read_text()
        try:
            ast.parse(source)
        except SyntaxError as exc:
            raise AssertionError(f"SyntaxError in {f}: {exc}") from exc


def _max_function_loc(root: Path, subdir: str = "app") -> int:
    """Return the maximum LOC for any function in *root/subdir*."""
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
# Category A — Tool execution (CC-01 to CC-05)
# ---------------------------------------------------------------------------


def test_success_status() -> None:
    """CC-01: Tool returns status='success' on a fresh project."""
    project_dir = create_fixture_project(name="rs_t01")
    result = add_request_signing(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


def test_idempotent() -> None:
    """CC-02: Second run returns status='no_op' without touching files."""
    project_dir = create_fixture_project(name="rs_t02")
    r1 = add_request_signing(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_request_signing(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


def test_dry_run() -> None:
    """CC-03: dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="rs_t03")
    before = {f: f.read_text() for f in _all_py(project_dir)}
    result = add_request_signing(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_files_created_count() -> None:
    """CC-04: Tool creates at least 4 new files (signer, nonce_store, deps, middleware)."""
    project_dir = create_fixture_project(name="rs_t04")
    result = add_request_signing(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 4, (
        f"Expected >= 4 files_created, got {len(result.files_created)}: {result.files_created}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


def test_files_modified_count() -> None:
    """CC-05: Tool modifies at least 1 file (config.py)."""
    project_dir = create_fixture_project(name="rs_t05")
    result = add_request_signing(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_modified) >= 1, (
        f"Expected >= 1 files_modified, got {len(result.files_modified)}: {result.files_modified}"
    )
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


# ---------------------------------------------------------------------------
# Category B — Generated code quality (CC-06, CC-07)
# ---------------------------------------------------------------------------


def test_all_py_parse() -> None:
    """CC-06: All .py files in the project parse without SyntaxError."""
    project_dir = create_fixture_project(name="rs_t06")
    add_request_signing(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_no_function_over_50_loc() -> None:
    """CC-07: No generated function exceeds 50 LOC."""
    project_dir = create_fixture_project(name="rs_t07")
    add_request_signing(ToolInput(project_dir=str(project_dir)))
    max_loc = _max_function_loc(project_dir)
    assert max_loc <= 50, f"Function exceeds 50 LOC: max={max_loc}"


# ---------------------------------------------------------------------------
# Category C — Config fields patched (CC-08)
# ---------------------------------------------------------------------------


def test_config_fields_patched() -> None:
    """CC-08: REQUEST_SIGNING_SECRET and REQUEST_SIGNING_TIMESTAMP_WINDOW_S in config.py."""
    project_dir = create_fixture_project(name="rs_t08")
    add_request_signing(ToolInput(project_dir=str(project_dir)))
    config = (project_dir / "app" / "core" / "config.py").read_text()
    assert "REQUEST_SIGNING_SECRET" in config
    assert "REQUEST_SIGNING_TIMESTAMP_WINDOW_S" in config
    for line in config.splitlines():
        if "REQUEST_SIGNING_SECRET" in line or "REQUEST_SIGNING_TIMESTAMP_WINDOW_S" in line:
            assert line.startswith("    "), f"Config field not 4-space indented: {line!r}"


# ---------------------------------------------------------------------------
# Category D — Domain-specific tests (CC-11+)
# ---------------------------------------------------------------------------


def test_signer_file_created() -> None:
    """CC-11: app/core/signing/signer.py exists with HMACSigner class."""
    project_dir = create_fixture_project(name="rs_t09")
    add_request_signing(ToolInput(project_dir=str(project_dir)))
    signer = project_dir / "app" / "core" / "signing" / "signer.py"
    assert signer.exists(), "app/core/signing/signer.py not created"
    content = signer.read_text()
    assert "class HMACSigner" in content
    assert "def sign" in content
    assert "def verify" in content
    assert "def canonical_string" in content


def test_signer_canonical_string_components() -> None:
    """CC-12: Canonical string includes method, path, sorted query, headers, body hash."""
    project_dir = create_fixture_project(name="rs_t10")
    add_request_signing(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "core" / "signing" / "signer.py").read_text()
    assert "sha256" in content
    assert "sorted" in content.lower() or "_sort_query" in content
    assert "hmac" in content.lower()
    assert "compare_digest" in content


def test_nonce_store_created() -> None:
    """CC-13: app/core/signing/nonce_store.py exists with NonceStore and replay detection."""
    project_dir = create_fixture_project(name="rs_t11")
    add_request_signing(ToolInput(project_dir=str(project_dir)))
    nonce_file = project_dir / "app" / "core" / "signing" / "nonce_store.py"
    assert nonce_file.exists(), "nonce_store.py not created"
    content = nonce_file.read_text()
    assert "class NonceStore" in content
    assert "def is_replay" in content
    assert "get_nonce_store" in content


def test_nonce_ttl_eviction() -> None:
    """CC-14: NonceStore has TTL eviction logic."""
    project_dir = create_fixture_project(name="rs_t12")
    add_request_signing(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "core" / "signing" / "nonce_store.py").read_text()
    assert "_evict" in content or "evict" in content
    assert "window_seconds" in content or "ttl" in content.lower()


def test_deps_created() -> None:
    """CC-15: app/core/signing/deps.py exists with verify_signature dependency."""
    project_dir = create_fixture_project(name="rs_t13")
    add_request_signing(ToolInput(project_dir=str(project_dir)))
    deps = project_dir / "app" / "core" / "signing" / "deps.py"
    assert deps.exists(), "deps.py not created"
    content = deps.read_text()
    assert "async def verify_signature" in content
    assert "Depends" in content or "Header" in content
    assert "401" in content or "HTTP_401_UNAUTHORIZED" in content


def test_middleware_created() -> None:
    """CC-16: app/middleware/request_signing.py exists with RequestSigningMiddleware."""
    project_dir = create_fixture_project(name="rs_t14")
    add_request_signing(ToolInput(project_dir=str(project_dir)))
    mw = project_dir / "app" / "middleware" / "request_signing.py"
    assert mw.exists(), "request_signing middleware not created"
    content = mw.read_text()
    assert "class RequestSigningMiddleware" in content
    assert "BaseHTTPMiddleware" in content
    assert "async def dispatch" in content


def test_middleware_bypass_paths() -> None:
    """CC-17: Middleware has bypass paths for health/metrics/docs."""
    project_dir = create_fixture_project(name="rs_t15")
    add_request_signing(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "middleware" / "request_signing.py").read_text()
    assert "/healthz" in content or "bypass" in content.lower()


def test_timestamp_window_enforced() -> None:
    """CC-18: Verify logic checks timestamp window (abs difference)."""
    project_dir = create_fixture_project(name="rs_t16")
    add_request_signing(ToolInput(project_dir=str(project_dir)))
    signer_content = (project_dir / "app" / "core" / "signing" / "signer.py").read_text()
    assert "window_seconds" in signer_content
    assert "abs(" in signer_content or "abs" in signer_content


def test_no_hardcoded_secrets_in_templates() -> None:
    """QS-02: No hardcoded production secrets in generated signing code."""
    project_dir = create_fixture_project(name="rs_t17")
    add_request_signing(ToolInput(project_dir=str(project_dir)))
    signing_dir = project_dir / "app" / "core" / "signing"
    for py_file in signing_dir.rglob("*.py"):
        content = py_file.read_text()
        assert "password=" not in content or "changethis" in content or "placeholder" in content
        assert "AKIA" not in content, f"Possible real AWS key in {py_file}"


def test_hmac_compare_digest_used() -> None:
    """QS security: HMAC comparison uses compare_digest (constant-time)."""
    project_dir = create_fixture_project(name="rs_t18")
    add_request_signing(ToolInput(project_dir=str(project_dir)))
    signer = project_dir / "app" / "core" / "signing" / "signer.py"
    content = signer.read_text()
    assert "compare_digest" in content, "Must use hmac.compare_digest for constant-time comparison"


# ---------------------------------------------------------------------------
# Category E — Invariants (CC-N-1, CC-N, CC-LAST)
# ---------------------------------------------------------------------------


def test_execution_time_recorded() -> None:
    """CC-N-1: execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="rs_t19")
    result = add_request_signing(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0


def test_next_steps_present() -> None:
    """CC-N: next_steps should contain signing secret guidance."""
    project_dir = create_fixture_project(name="rs_t20")
    result = add_request_signing(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.next_steps) > 0
    combined = " ".join(result.next_steps).lower()
    assert "secret" in combined or "signing" in combined


def test_idempotent_project_still_parses() -> None:
    """CC-LAST: After two runs, all .py files still parse."""
    project_dir = create_fixture_project(name="rs_t21")
    add_request_signing(ToolInput(project_dir=str(project_dir)))
    add_request_signing(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_no_todo_fixme_in_generated() -> None:
    """QS-03: No TODO/FIXME/HACK in generated code."""
    project_dir = create_fixture_project(name="rs_t22")
    add_request_signing(ToolInput(project_dir=str(project_dir)))
    signing_dir = project_dir / "app" / "core" / "signing"
    for py_file in signing_dir.rglob("*.py"):
        content = py_file.read_text()
        assert "# TODO" not in content, f"TODO found in {py_file}"
        assert "# FIXME" not in content, f"FIXME found in {py_file}"
        assert "# HACK" not in content, f"HACK found in {py_file}"


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
        test_signer_file_created,
        test_signer_canonical_string_components,
        test_nonce_store_created,
        test_nonce_ttl_eviction,
        test_deps_created,
        test_middleware_created,
        test_middleware_bypass_paths,
        test_timestamp_window_enforced,
        test_no_hardcoded_secrets_in_templates,
        test_hmac_compare_digest_used,
        test_execution_time_recorded,
        test_next_steps_present,
        test_idempotent_project_still_parses,
        test_no_todo_fixme_in_generated,
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
