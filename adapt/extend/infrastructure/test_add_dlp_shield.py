"""Tests for TOOL-108 add_dlp_shield.

Generates real fixture projects, runs the tool, and verifies every completeness
criterion from the MEGA_BRIEFING.

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_dlp_shield.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_dlp_shield.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_dlp_shield import add_dlp_shield
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
    project_dir = create_fixture_project(name="dlp_t01")
    result = add_dlp_shield(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


def test_idempotent() -> None:
    """CC-02: Second run returns status='no_op' without touching files."""
    project_dir = create_fixture_project(name="dlp_t02")
    r1 = add_dlp_shield(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_dlp_shield(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created
    assert not r2.files_modified


def test_dry_run() -> None:
    """CC-03: dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="dlp_t03")
    before = {f: f.read_text() for f in _all_py(project_dir)}
    result = add_dlp_shield(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_files_created_count() -> None:
    """CC-04: Tool creates at least 4 files (patterns, redactor, decorator, middleware)."""
    project_dir = create_fixture_project(name="dlp_t04")
    result = add_dlp_shield(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 4, (
        f"Expected >= 4 files_created, got {len(result.files_created)}: {result.files_created}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


def test_files_modified_count() -> None:
    """CC-05: Tool modifies at least 1 file (config.py)."""
    project_dir = create_fixture_project(name="dlp_t05")
    result = add_dlp_shield(ToolInput(project_dir=str(project_dir)))
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
    project_dir = create_fixture_project(name="dlp_t06")
    add_dlp_shield(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_no_function_over_50_loc() -> None:
    """CC-07: No generated function exceeds 50 LOC."""
    project_dir = create_fixture_project(name="dlp_t07")
    add_dlp_shield(ToolInput(project_dir=str(project_dir)))
    max_loc = _max_function_loc(project_dir)
    assert max_loc <= 50, f"Function exceeds 50 LOC: max={max_loc}"


# ---------------------------------------------------------------------------
# Category C — Config fields patched (CC-08)
# ---------------------------------------------------------------------------


def test_config_fields_patched() -> None:
    """CC-08: DLP_ENABLED, DLP_REDACTION_MODE, DLP_SENSITIVE_PATTERNS in config.py."""
    project_dir = create_fixture_project(name="dlp_t08")
    add_dlp_shield(ToolInput(project_dir=str(project_dir)))
    config = (project_dir / "app" / "core" / "config.py").read_text()
    assert "DLP_ENABLED" in config
    assert "DLP_REDACTION_MODE" in config
    assert "DLP_SENSITIVE_PATTERNS" in config
    for line in config.splitlines():
        if "DLP_ENABLED" in line or "DLP_REDACTION_MODE" in line:
            assert line.startswith("    "), f"Config field not 4-space indented: {line!r}"


# ---------------------------------------------------------------------------
# Category D — Domain-specific tests (CC-11+)
# ---------------------------------------------------------------------------


def test_patterns_file_created() -> None:
    """CC-11: app/core/dlp/patterns.py exists with builtin patterns."""
    project_dir = create_fixture_project(name="dlp_t09")
    add_dlp_shield(ToolInput(project_dir=str(project_dir)))
    patterns = project_dir / "app" / "core" / "dlp" / "patterns.py"
    assert patterns.exists(), "patterns.py not created"
    content = patterns.read_text()
    assert "BUILTIN_PATTERNS" in content
    assert "SensitivePattern" in content


def test_luhn_validation_present() -> None:
    """CC-12: Luhn validation function present for credit card checking."""
    project_dir = create_fixture_project(name="dlp_t10")
    add_dlp_shield(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "core" / "dlp" / "patterns.py").read_text()
    assert "luhn" in content.lower()
    assert "def luhn_valid" in content


def test_patterns_cover_pii_pci_phi() -> None:
    """CC-13: Pattern levels cover pii, pci, phi categories."""
    project_dir = create_fixture_project(name="dlp_t11")
    add_dlp_shield(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "core" / "dlp" / "patterns.py").read_text()
    assert '"pci"' in content
    assert '"pii"' in content or "'pii'" in content
    assert '"phi"' in content or "'phi'" in content


def test_redactor_file_created() -> None:
    """CC-14: app/core/dlp/redactor.py exists with Redactor class."""
    project_dir = create_fixture_project(name="dlp_t12")
    add_dlp_shield(ToolInput(project_dir=str(project_dir)))
    redactor = project_dir / "app" / "core" / "dlp" / "redactor.py"
    assert redactor.exists(), "redactor.py not created"
    content = redactor.read_text()
    assert "class Redactor" in content
    assert "def redact_value" in content
    assert "def redact_payload" in content


def test_redaction_modes_supported() -> None:
    """CC-15: All four redaction modes present (full, partial, tokenize, remove)."""
    project_dir = create_fixture_project(name="dlp_t13")
    add_dlp_shield(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "core" / "dlp" / "redactor.py").read_text()
    assert '"full"' in content or "'full'" in content
    assert '"partial"' in content or "'partial'" in content
    assert '"tokenize"' in content or "'tokenize'" in content
    assert '"remove"' in content or "'remove'" in content


def test_sensitive_decorator_created() -> None:
    """CC-16: app/core/dlp/decorator.py exists with @sensitive decorator."""
    project_dir = create_fixture_project(name="dlp_t14")
    add_dlp_shield(ToolInput(project_dir=str(project_dir)))
    decorator = project_dir / "app" / "core" / "dlp" / "decorator.py"
    assert decorator.exists(), "decorator.py not created"
    content = decorator.read_text()
    assert "def sensitive" in content
    assert "_dlp_sensitivity_level" in content or "sensitivity_level" in content


def test_dlp_middleware_created() -> None:
    """CC-17: app/middleware/dlp_shield.py exists with DLPMiddleware."""
    project_dir = create_fixture_project(name="dlp_t15")
    add_dlp_shield(ToolInput(project_dir=str(project_dir)))
    mw = project_dir / "app" / "middleware" / "dlp_shield.py"
    assert mw.exists(), "dlp_shield middleware not created"
    content = mw.read_text()
    assert "class DLPMiddleware" in content
    assert "BaseHTTPMiddleware" in content
    assert "async def dispatch" in content


def test_middleware_skips_non_json() -> None:
    """CC-18: Middleware checks content-type before scanning."""
    project_dir = create_fixture_project(name="dlp_t16")
    add_dlp_shield(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "middleware" / "dlp_shield.py").read_text()
    assert "content-type" in content or "content_type" in content
    assert "application/json" in content


def test_httpx_import_lazy() -> None:
    """QS-04: httpx (optional SDK) imported inside function body, not at module level."""
    project_dir = create_fixture_project(name="dlp_t17")
    add_dlp_shield(ToolInput(project_dir=str(project_dir)))
    dlp_dir = project_dir / "app" / "core" / "dlp"
    for py_file in dlp_dir.rglob("*.py"):
        tree = ast.parse(py_file.read_text())
        for node in tree.body:
            assert not (
                isinstance(node, ast.Import)
                and any(alias.name == "httpx" for alias in node.names)
            ), f"Top-level httpx import in {py_file}"


# ---------------------------------------------------------------------------
# Category E — Invariants (CC-N-1, CC-N, CC-LAST)
# ---------------------------------------------------------------------------


def test_execution_time_recorded() -> None:
    """CC-N-1: execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="dlp_t18")
    result = add_dlp_shield(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0


def test_next_steps_present() -> None:
    """CC-N: next_steps must guide developer on DLP activation."""
    project_dir = create_fixture_project(name="dlp_t19")
    result = add_dlp_shield(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.next_steps) > 0
    combined = " ".join(result.next_steps).lower()
    assert "dlp" in combined or "middleware" in combined or "enabled" in combined


def test_idempotent_project_still_parses() -> None:
    """CC-LAST: After two runs, all .py files still parse."""
    project_dir = create_fixture_project(name="dlp_t20")
    add_dlp_shield(ToolInput(project_dir=str(project_dir)))
    add_dlp_shield(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_no_todo_fixme_in_generated() -> None:
    """QS-03: No TODO/FIXME/HACK in generated code."""
    project_dir = create_fixture_project(name="dlp_t21")
    add_dlp_shield(ToolInput(project_dir=str(project_dir)))
    dlp_dir = project_dir / "app" / "core" / "dlp"
    for py_file in dlp_dir.rglob("*.py"):
        content = py_file.read_text()
        assert "# TODO" not in content, f"TODO found in {py_file}"
        assert "# FIXME" not in content, f"FIXME found in {py_file}"
        assert "# HACK" not in content, f"HACK found in {py_file}"


def test_ssr_patterns_regex_count() -> None:
    """CC-extra: At least 4 compiled regex patterns in BUILTIN_PATTERNS."""
    project_dir = create_fixture_project(name="dlp_t22")
    add_dlp_shield(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "core" / "dlp" / "patterns.py").read_text()
    # Count SensitivePattern(...) instantiations
    count = content.count("SensitivePattern(")
    assert count >= 4, f"Expected >= 4 SensitivePattern instances, got {count}"


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
        test_patterns_file_created,
        test_luhn_validation_present,
        test_patterns_cover_pii_pci_phi,
        test_redactor_file_created,
        test_redaction_modes_supported,
        test_sensitive_decorator_created,
        test_dlp_middleware_created,
        test_middleware_skips_non_json,
        test_httpx_import_lazy,
        test_execution_time_recorded,
        test_next_steps_present,
        test_idempotent_project_still_parses,
        test_no_todo_fixme_in_generated,
        test_ssr_patterns_regex_count,
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
