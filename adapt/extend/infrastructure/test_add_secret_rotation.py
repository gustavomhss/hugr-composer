"""Structural tests for TOOL-114 add_secret_rotation.

Generates real fixture projects, runs the tool, and verifies all
completeness criteria from the MEGA_BRIEFING.

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_secret_rotation.py -v

or standalone::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_secret_rotation.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_secret_rotation import add_secret_rotation
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
    project_dir = create_fixture_project(name="rot_t01")
    result = add_secret_rotation(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", (
        f"Expected success, got {result.status}: {result.error}"
    )


# ---------------------------------------------------------------------------
# CC-02 — idempotent
# ---------------------------------------------------------------------------

def test_idempotent() -> None:
    """Second run returns status='no_op' without touching files."""
    project_dir = create_fixture_project(name="rot_t02")
    r1 = add_secret_rotation(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_secret_rotation(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


# ---------------------------------------------------------------------------
# CC-03 — dry_run
# ---------------------------------------------------------------------------

def test_dry_run() -> None:
    """dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="rot_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_secret_rotation(ToolInput(project_dir=str(project_dir), dry_run=True))
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
    project_dir = create_fixture_project(name="rot_t04")
    result = add_secret_rotation(ToolInput(project_dir=str(project_dir)))
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
    """Tool modifies at least 2 files (config, requirements)."""
    project_dir = create_fixture_project(name="rot_t05")
    result = add_secret_rotation(ToolInput(project_dir=str(project_dir)))
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
    project_dir = create_fixture_project(name="rot_t06")
    add_secret_rotation(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# CC-07 — no function over 50 LOC
# ---------------------------------------------------------------------------

def test_no_function_over_50_loc() -> None:
    """No function in generated app/ exceeds 50 LOC."""
    project_dir = create_fixture_project(name="rot_t07")
    add_secret_rotation(ToolInput(project_dir=str(project_dir)))
    max_loc = _max_function_loc(project_dir, "app")
    assert max_loc <= 50, f"Found function with {max_loc} LOC (limit: 50)"


# ---------------------------------------------------------------------------
# CC-08 — config fields patched
# ---------------------------------------------------------------------------

def test_config_fields_patched() -> None:
    """SECRET_PROVIDER, VAULT_URL, etc. are in config.py Settings class."""
    project_dir = create_fixture_project(name="rot_t08")
    add_secret_rotation(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    for field in ["SECRET_PROVIDER", "VAULT_URL", "VAULT_TOKEN",
                  "SECRET_ROTATION_INTERVAL_H"]:
        assert field in content, f"Config field {field} missing from config.py"
    for line in content.splitlines():
        if "SECRET_PROVIDER" in line and ":" in line:
            assert line.startswith("    "), (
                f"SECRET_PROVIDER not inside class body: {line!r}"
            )
            break


# ---------------------------------------------------------------------------
# CC-11+ — domain-specific tests
# ---------------------------------------------------------------------------

def test_secret_rotation_file_exists() -> None:
    """app/core/secret_rotation.py exists with SecretProvider ABC."""
    project_dir = create_fixture_project(name="rot_t11")
    add_secret_rotation(ToolInput(project_dir=str(project_dir)))
    rotation_file = project_dir / "app" / "core" / "secret_rotation.py"
    assert rotation_file.exists(), "secret_rotation.py not created"
    content = rotation_file.read_text()
    assert "SecretProvider" in content, "SecretProvider ABC not found"
    assert "EnvSecretProvider" in content, "EnvSecretProvider not found"


def test_vault_provider_lazy_import() -> None:
    """hvac is NOT imported at top level in secret_rotation.py."""
    project_dir = create_fixture_project(name="rot_t12")
    add_secret_rotation(ToolInput(project_dir=str(project_dir)))
    rotation_file = project_dir / "app" / "core" / "secret_rotation.py"
    tree = ast.parse(rotation_file.read_text())
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "hvac", "hvac imported at top level"
        elif isinstance(node, ast.ImportFrom):
            assert node.module != "hvac", "hvac imported at top level via 'from'"


def test_boto3_lazy_import() -> None:
    """boto3 is NOT imported at top level in secret_rotation.py."""
    project_dir = create_fixture_project(name="rot_t13")
    add_secret_rotation(ToolInput(project_dir=str(project_dir)))
    rotation_file = project_dir / "app" / "core" / "secret_rotation.py"
    tree = ast.parse(rotation_file.read_text())
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "boto3", "boto3 imported at top level"
        elif isinstance(node, ast.ImportFrom):
            assert node.module != "boto3", "boto3 imported at top level via 'from'"


def test_leak_detector_created() -> None:
    """app/middleware/leak_detector.py exists with LeakDetectorMiddleware."""
    project_dir = create_fixture_project(name="rot_t14")
    add_secret_rotation(ToolInput(project_dir=str(project_dir)))
    leak_file = project_dir / "app" / "middleware" / "leak_detector.py"
    assert leak_file.exists(), "leak_detector.py not created"
    content = leak_file.read_text()
    assert "LeakDetectorMiddleware" in content, "LeakDetectorMiddleware not found"
    assert "scan_for_leaks" in content or "REDACTED" in content, (
        "leak scanning logic not found"
    )


def test_rotate_secrets_cli_created() -> None:
    """scripts/rotate_secrets.py exists with main() function."""
    project_dir = create_fixture_project(name="rot_t15")
    add_secret_rotation(ToolInput(project_dir=str(project_dir)))
    cli_file = project_dir / "scripts" / "rotate_secrets.py"
    assert cli_file.exists(), "scripts/rotate_secrets.py not created"
    content = cli_file.read_text()
    assert "def main" in content, "main() function not found in CLI"
    assert "--name" in content or "argparse" in content, "argparse CLI not found"


def test_dual_key_rotation_present() -> None:
    """rotate method implements dual-key window in secret_rotation.py."""
    project_dir = create_fixture_project(name="rot_t16")
    add_secret_rotation(ToolInput(project_dir=str(project_dir)))
    rotation_file = project_dir / "app" / "core" / "secret_rotation.py"
    content = rotation_file.read_text()
    assert "previous" in content, "dual-key 'previous' pattern not found"
    assert "rotate" in content, "rotate method not found"


def test_startup_validation_present() -> None:
    """validate_secrets_at_startup function exists and checks weak patterns."""
    project_dir = create_fixture_project(name="rot_t17")
    add_secret_rotation(ToolInput(project_dir=str(project_dir)))
    rotation_file = project_dir / "app" / "core" / "secret_rotation.py"
    content = rotation_file.read_text()
    assert "validate_secrets_at_startup" in content, (
        "validate_secrets_at_startup not found"
    )
    assert "changethis" in content or "_WEAK_PATTERNS" in content, (
        "weak pattern detection not found"
    )


def test_requirements_patched() -> None:
    """requirements.txt has hvac and boto3 entries."""
    project_dir = create_fixture_project(name="rot_t18")
    add_secret_rotation(ToolInput(project_dir=str(project_dir)))
    requirements = project_dir / "requirements.txt"
    content = requirements.read_text()
    assert "hvac" in content, "hvac not in requirements.txt"
    assert "boto3" in content, "boto3 not in requirements.txt"


def test_no_secrets_in_logs() -> None:
    """Secret values are NEVER concatenated directly into log statements."""
    project_dir = create_fixture_project(name="rot_t19")
    add_secret_rotation(ToolInput(project_dir=str(project_dir)))
    rotation_file = project_dir / "app" / "core" / "secret_rotation.py"
    content = rotation_file.read_text()
    # Ensure the secret value variable is never passed directly to logger.info/warning/error
    import re
    # Checks that f"...{value}..." or f"...{token}..." is not in log calls
    suspicious = re.findall(r'logger\.\w+\([^)]*\{(?:value|token|secret)\}', content)
    assert not suspicious, f"Potential secret leak in log calls: {suspicious}"


# ---------------------------------------------------------------------------
# CC-N-1 — execution_time_ms
# ---------------------------------------------------------------------------

def test_execution_time_recorded() -> None:
    """execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="rot_t_time")
    result = add_secret_rotation(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


# ---------------------------------------------------------------------------
# CC-N — next_steps_present
# ---------------------------------------------------------------------------

def test_next_steps_present() -> None:
    """Result includes next_steps mentioning SECRET_PROVIDER."""
    project_dir = create_fixture_project(name="rot_t_ns")
    result = add_secret_rotation(ToolInput(project_dir=str(project_dir)))
    assert len(result.next_steps) > 0, "next_steps should not be empty"
    joined = " ".join(result.next_steps)
    assert "SECRET_PROVIDER" in joined or "vault" in joined.lower(), (
        "Expected SECRET_PROVIDER mention in next_steps"
    )


# ---------------------------------------------------------------------------
# CC-LAST — idempotent project still parses
# ---------------------------------------------------------------------------

def test_idempotent_project_still_parses() -> None:
    """After two runs all .py files remain parseable."""
    project_dir = create_fixture_project(name="rot_t_last")
    add_secret_rotation(ToolInput(project_dir=str(project_dir)))
    add_secret_rotation(ToolInput(project_dir=str(project_dir)))
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
        test_secret_rotation_file_exists,
        test_vault_provider_lazy_import,
        test_boto3_lazy_import,
        test_leak_detector_created,
        test_rotate_secrets_cli_created,
        test_dual_key_rotation_present,
        test_startup_validation_present,
        test_requirements_patched,
        test_no_secrets_in_logs,
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
    print(f"TOOL-114 add_secret_rotation: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
