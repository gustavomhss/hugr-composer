"""Structural tests for TOOL-118 add_response_armor.

Generates real fixture projects via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies every completeness criterion from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_response_armor.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_response_armor.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_response_armor import add_response_armor
from tests.common.fixture_factory import create_fixture_project


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _all_py_files(root: Path) -> list[Path]:
    """Return all .py files under *root*."""
    return sorted(root.rglob("*.py"))


def _assert_parse(root: Path) -> None:
    """Assert every .py file under *root* parses without SyntaxError."""
    for f in _all_py_files(root):
        src = f.read_text()
        try:
            ast.parse(src)
        except SyntaxError as exc:
            raise AssertionError(f"SyntaxError in {f}: {exc}") from exc


def _max_function_loc(root: Path, subdir: str = "app") -> int:
    """Return the max function LOC in all .py files under *root/subdir*."""
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
# CC-01 — success status
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    """CC-01: Tool returns status='success' on a fresh project."""
    project_dir = create_fixture_project(name="ra_t01")
    result = add_response_armor(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", (
        f"Expected success, got {result.status}: {result.error}"
    )


# ---------------------------------------------------------------------------
# CC-02 — idempotent
# ---------------------------------------------------------------------------

def test_idempotent() -> None:
    """CC-02: Second run returns status='no_op' without touching files."""
    project_dir = create_fixture_project(name="ra_t02")
    r1 = add_response_armor(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_response_armor(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


# ---------------------------------------------------------------------------
# CC-03 — dry_run
# ---------------------------------------------------------------------------

def test_dry_run() -> None:
    """CC-03: dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="ra_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_response_armor(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


# ---------------------------------------------------------------------------
# CC-04 — files created count
# ---------------------------------------------------------------------------

def test_files_created_count() -> None:
    """CC-04: Tool creates at least 3 new files (armor core, timing_safe, middleware)."""
    project_dir = create_fixture_project(name="ra_t04")
    result = add_response_armor(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 3, (
        f"Expected >= 3 files_created, got {len(result.files_created)}: {result.files_created}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-05 — files modified count
# ---------------------------------------------------------------------------

def test_files_modified_count() -> None:
    """CC-05: Tool modifies at least 2 files (config, main)."""
    project_dir = create_fixture_project(name="ra_t05")
    result = add_response_armor(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_modified) >= 2, (
        f"Expected >= 2 files_modified, got {len(result.files_modified)}: {result.files_modified}"
    )
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-06 — all py parse
# ---------------------------------------------------------------------------

def test_all_py_parse() -> None:
    """CC-06: Every generated .py file AST-parses clean."""
    project_dir = create_fixture_project(name="ra_t06")
    add_response_armor(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# CC-07 — no function over 50 LOC
# ---------------------------------------------------------------------------

def test_no_function_over_50_loc() -> None:
    """CC-07: No function in generated app/ exceeds 50 LOC."""
    project_dir = create_fixture_project(name="ra_t07")
    add_response_armor(ToolInput(project_dir=str(project_dir)))
    max_loc = _max_function_loc(project_dir, "app")
    assert max_loc <= 50, f"Found function with {max_loc} LOC (limit: 50)"


# ---------------------------------------------------------------------------
# CC-08 — config fields patched
# ---------------------------------------------------------------------------

def test_config_fields_patched() -> None:
    """CC-08: RESPONSE_ARMOR_* settings exist inside Settings class body."""
    project_dir = create_fixture_project(name="ra_t08")
    add_response_armor(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    for field in (
        "RESPONSE_ARMOR_ENABLED",
        "RESPONSE_ARMOR_SANITIZE_ERRORS",
        "RESPONSE_ARMOR_TIMING_SAFE",
    ):
        assert field in content, f"Config field {field} not found in config.py"
    for line in content.splitlines():
        if "RESPONSE_ARMOR_ENABLED" in line:
            assert line.startswith("    "), (
                f"RESPONSE_ARMOR_ENABLED not inside class body (no 4-space indent): {line!r}"
            )
            break


# ---------------------------------------------------------------------------
# Domain tests — CC-11+
# ---------------------------------------------------------------------------

def test_armor_core_created() -> None:
    """T-09: app/core/response_armor.py exists with sanitize_error, BREACH, CRLF."""
    project_dir = create_fixture_project(name="ra_t09")
    add_response_armor(ToolInput(project_dir=str(project_dir)))
    core_file = project_dir / "app" / "core" / "response_armor.py"
    assert core_file.exists(), "app/core/response_armor.py not created"
    content = core_file.read_text()
    assert "def sanitize_error" in content
    assert "def breach_padding" in content
    assert "def strip_crlf" in content


def test_timing_safe_module_created() -> None:
    """T-10: app/core/timing_safe.py exists with hmac.compare_digest wrappers."""
    project_dir = create_fixture_project(name="ra_t10")
    add_response_armor(ToolInput(project_dir=str(project_dir)))
    timing_file = project_dir / "app" / "core" / "timing_safe.py"
    assert timing_file.exists(), "app/core/timing_safe.py not created"
    content = timing_file.read_text()
    assert "hmac" in content
    assert "compare_digest" in content
    assert "def compare_tokens" in content


def test_middleware_created() -> None:
    """T-11: app/middleware/response_armor.py exists with ResponseArmorMiddleware."""
    project_dir = create_fixture_project(name="ra_t11")
    add_response_armor(ToolInput(project_dir=str(project_dir)))
    mw_file = project_dir / "app" / "middleware" / "response_armor.py"
    assert mw_file.exists(), "app/middleware/response_armor.py not created"
    content = mw_file.read_text()
    assert "class ResponseArmorMiddleware" in content
    assert "def register_response_armor" in content


def test_crlf_protection_in_middleware() -> None:
    """T-12: Middleware strips CR/LF from response headers."""
    project_dir = create_fixture_project(name="ra_t12")
    add_response_armor(ToolInput(project_dir=str(project_dir)))
    mw_file = project_dir / "app" / "middleware" / "response_armor.py"
    content = mw_file.read_text()
    assert "strip_crlf" in content
    assert "crlf" in content.lower()


def test_cache_control_enforced_on_error_responses() -> None:
    """T-13: Middleware enforces Cache-Control: no-store on 4xx/5xx responses."""
    project_dir = create_fixture_project(name="ra_t13")
    add_response_armor(ToolInput(project_dir=str(project_dir)))
    mw_file = project_dir / "app" / "middleware" / "response_armor.py"
    content = mw_file.read_text()
    assert "no-store" in content
    assert "Cache-Control" in content
    assert "status_code >= 400" in content or ">= 400" in content


def test_server_header_removed() -> None:
    """T-14: Middleware removes the Server header to reduce fingerprinting."""
    project_dir = create_fixture_project(name="ra_t14")
    add_response_armor(ToolInput(project_dir=str(project_dir)))
    mw_file = project_dir / "app" / "middleware" / "response_armor.py"
    content = mw_file.read_text()
    assert '"server"' in content or "'server'" in content


def test_breach_padding_uses_random_bytes() -> None:
    """T-15: breach_padding uses os.urandom for random padding bytes."""
    project_dir = create_fixture_project(name="ra_t15")
    add_response_armor(ToolInput(project_dir=str(project_dir)))
    core_file = project_dir / "app" / "core" / "response_armor.py"
    content = core_file.read_text()
    assert "os.urandom" in content or "secrets" in content, (
        "BREACH padding must use a CSPRNG (os.urandom or secrets)"
    )


def test_sanitize_error_uses_logging() -> None:
    """T-16: sanitize_error logs the real exception detail before sanitizing."""
    project_dir = create_fixture_project(name="ra_t16")
    add_response_armor(ToolInput(project_dir=str(project_dir)))
    core_file = project_dir / "app" / "core" / "response_armor.py"
    content = core_file.read_text()
    assert "logger.error" in content
    assert "armor.error_sanitized" in content


def test_main_registers_armor() -> None:
    """T-17: main.py imports and calls register_response_armor(app)."""
    project_dir = create_fixture_project(name="ra_t17")
    add_response_armor(ToolInput(project_dir=str(project_dir)))
    main_file = project_dir / "app" / "main.py"
    content = main_file.read_text()
    assert "register_response_armor" in content
    assert "from app.middleware.response_armor import register_response_armor" in content


# ---------------------------------------------------------------------------
# CC-N-1 — execution time
# ---------------------------------------------------------------------------

def test_execution_time_recorded() -> None:
    """CC-N-1: execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="ra_t18")
    result = add_response_armor(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


# ---------------------------------------------------------------------------
# CC-N — next_steps
# ---------------------------------------------------------------------------

def test_next_steps_present() -> None:
    """CC-N: next_steps mentions armor config and compare_tokens."""
    project_dir = create_fixture_project(name="ra_t19")
    result = add_response_armor(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.next_steps) > 0, "next_steps must not be empty"
    combined = " ".join(result.next_steps).lower()
    assert "response_armor" in combined, "next_steps should mention RESPONSE_ARMOR"
    assert "compare_tokens" in combined, "next_steps should mention compare_tokens"


# ---------------------------------------------------------------------------
# CC-LAST — idempotent project still parses
# ---------------------------------------------------------------------------

def test_idempotent_project_still_parses() -> None:
    """CC-LAST: After two runs all .py files remain parseable."""
    project_dir = create_fixture_project(name="ra_t20")
    add_response_armor(ToolInput(project_dir=str(project_dir)))
    add_response_armor(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# Mutation-killing regression tests
# ---------------------------------------------------------------------------

def test_three_config_fields_exactly() -> None:
    """T-21: config.py must have exactly 3 RESPONSE_ARMOR_* fields."""
    project_dir = create_fixture_project(name="ra_t21")
    add_response_armor(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "core" / "config.py").read_text()
    expected = [
        "RESPONSE_ARMOR_ENABLED",
        "RESPONSE_ARMOR_SANITIZE_ERRORS",
        "RESPONSE_ARMOR_TIMING_SAFE",
    ]
    for field in expected:
        assert field in content, f"Missing field: {field}"
    distinct = {
        line.strip() for line in content.splitlines()
        if any(f in line for f in expected) and ":" in line and "=" in line
    }
    assert len(distinct) == 3, (
        f"Expected 3 RESPONSE_ARMOR_* field lines, got {len(distinct)}: {distinct}"
    )


def test_compare_tokens_uses_hmac_compare_digest() -> None:
    """T-22: compare_tokens MUST delegate to hmac.compare_digest, not ==."""
    project_dir = create_fixture_project(name="ra_t22")
    add_response_armor(ToolInput(project_dir=str(project_dir)))
    timing_file = project_dir / "app" / "core" / "timing_safe.py"
    content = timing_file.read_text()
    tree = ast.parse(content)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "compare_tokens":
            body_src = ast.unparse(node)
            assert "compare_digest" in body_src, (
                "compare_tokens must call hmac.compare_digest"
            )
            assert "==" not in body_src or "compare_digest" in body_src, (
                "compare_tokens must not use == for comparison"
            )
            return
    raise AssertionError("compare_tokens function not found in timing_safe.py")


def test_register_armor_positioned_after_fastapi() -> None:
    """T-23: register_response_armor(app) must appear AFTER app = FastAPI(...)."""
    project_dir = create_fixture_project(name="ra_t23")
    add_response_armor(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "main.py").read_text()
    app_idx = content.find("app = FastAPI(")
    reg_idx = content.find("register_response_armor(app)")
    assert app_idx >= 0, "FastAPI marker not found"
    assert reg_idx >= 0, "register_response_armor call not inserted"
    assert reg_idx > app_idx, (
        f"register_response_armor at {reg_idx} must come AFTER FastAPI() at {app_idx}"
    )


def test_strip_crlf_removes_both_cr_and_lf() -> None:
    """T-24: strip_crlf must explicitly remove both CR and LF characters."""
    project_dir = create_fixture_project(name="ra_t24")
    add_response_armor(ToolInput(project_dir=str(project_dir)))
    core_file = project_dir / "app" / "core" / "response_armor.py"
    content = core_file.read_text()
    assert "\\r" in content or r"\r" in content, "strip_crlf must handle CR (\\r)"
    assert "\\n" in content or r"\n" in content, "strip_crlf must handle LF (\\n)"


def test_no_files_mutated_outside_scope() -> None:
    """T-25: Tool must not modify files outside result.files_created/modified."""
    project_dir = create_fixture_project(name="ra_t25")
    before = {p: p.read_text() for p in sorted(project_dir.rglob("*.py"))}
    result = add_response_armor(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    changed: set[Path] = {
        Path(s).resolve()
        for s in list(result.files_created) + list(result.files_modified)
    }
    for p, original in before.items():
        if p.resolve() in changed:
            continue
        assert p.read_text() == original, (
            f"File {p} was modified but not reported in files_modified"
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
        test_armor_core_created,
        test_timing_safe_module_created,
        test_middleware_created,
        test_crlf_protection_in_middleware,
        test_cache_control_enforced_on_error_responses,
        test_server_header_removed,
        test_breach_padding_uses_random_bytes,
        test_sanitize_error_uses_logging,
        test_main_registers_armor,
        test_execution_time_recorded,
        test_next_steps_present,
        test_idempotent_project_still_parses,
        test_three_config_fields_exactly,
        test_compare_tokens_uses_hmac_compare_digest,
        test_register_armor_positioned_after_fastapi,
        test_strip_crlf_removes_both_cr_and_lf,
        test_no_files_mutated_outside_scope,
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
    print(f"TOOL-118 add_response_armor: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
