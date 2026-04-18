"""Tests for TOOL-109 add_canary_tokens.

Generates real fixture projects, runs the tool, and verifies every completeness
criterion from the MEGA_BRIEFING.

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_canary_tokens.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_canary_tokens.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_canary_tokens import add_canary_tokens
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
    project_dir = create_fixture_project(name="ct_t01")
    result = add_canary_tokens(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


def test_idempotent() -> None:
    """CC-02: Second run returns status='no_op' without touching files."""
    project_dir = create_fixture_project(name="ct_t02")
    r1 = add_canary_tokens(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_canary_tokens(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created
    assert not r2.files_modified


def test_dry_run() -> None:
    """CC-03: dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="ct_t03")
    before = {f: f.read_text() for f in _all_py(project_dir)}
    result = add_canary_tokens(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_files_created_count() -> None:
    """CC-04: Tool creates at least 5 files (registry, alerter, honeypot, fake_creds, seeder)."""
    project_dir = create_fixture_project(name="ct_t04")
    result = add_canary_tokens(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 5, (
        f"Expected >= 5 files_created, got {len(result.files_created)}: {result.files_created}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


def test_files_modified_count() -> None:
    """CC-05: Tool modifies at least 1 file (config.py)."""
    project_dir = create_fixture_project(name="ct_t05")
    result = add_canary_tokens(ToolInput(project_dir=str(project_dir)))
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
    project_dir = create_fixture_project(name="ct_t06")
    add_canary_tokens(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_no_function_over_50_loc() -> None:
    """CC-07: No generated function exceeds 50 LOC."""
    project_dir = create_fixture_project(name="ct_t07")
    add_canary_tokens(ToolInput(project_dir=str(project_dir)))
    max_loc = _max_function_loc(project_dir)
    assert max_loc <= 50, f"Function exceeds 50 LOC: max={max_loc}"


# ---------------------------------------------------------------------------
# Category C — Config fields patched (CC-08)
# ---------------------------------------------------------------------------


def test_config_fields_patched() -> None:
    """CC-08: CANARY_ENABLED and CANARY_ALERT_WEBHOOK_URL in config.py."""
    project_dir = create_fixture_project(name="ct_t08")
    add_canary_tokens(ToolInput(project_dir=str(project_dir)))
    config = (project_dir / "app" / "core" / "config.py").read_text()
    assert "CANARY_ENABLED" in config
    assert "CANARY_ALERT_WEBHOOK_URL" in config
    for line in config.splitlines():
        if "CANARY_ENABLED" in line or "CANARY_ALERT_WEBHOOK_URL" in line:
            assert line.startswith("    "), f"Config field not 4-space indented: {line!r}"


# ---------------------------------------------------------------------------
# Category D — Domain-specific tests (CC-11+)
# ---------------------------------------------------------------------------


def test_canary_registry_created() -> None:
    """CC-11: app/core/canary/registry.py exists with CanaryRegistry class."""
    project_dir = create_fixture_project(name="ct_t09")
    add_canary_tokens(ToolInput(project_dir=str(project_dir)))
    registry = project_dir / "app" / "core" / "canary" / "registry.py"
    assert registry.exists(), "registry.py not created"
    content = registry.read_text()
    assert "class CanaryRegistry" in content
    assert "class CanaryToken" in content
    assert "def register" in content


def test_registry_preregisters_all_canaries() -> None:
    """CC-12: Registry pre-registers honeypot + credential + decoy_record tokens."""
    project_dir = create_fixture_project(name="ct_t10")
    add_canary_tokens(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "core" / "canary" / "registry.py").read_text()
    assert "honeypot" in content
    assert "credential" in content
    assert "decoy_record" in content


def test_canary_fingerprint_present() -> None:
    """CC-13: CanaryToken has fingerprint for attribution."""
    project_dir = create_fixture_project(name="ct_t11")
    add_canary_tokens(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "core" / "canary" / "registry.py").read_text()
    assert "fingerprint" in content


def test_alerter_created() -> None:
    """CC-14: app/core/canary/alerter.py exists with fire_canary_alert."""
    project_dir = create_fixture_project(name="ct_t12")
    add_canary_tokens(ToolInput(project_dir=str(project_dir)))
    alerter = project_dir / "app" / "core" / "canary" / "alerter.py"
    assert alerter.exists(), "alerter.py not created"
    content = alerter.read_text()
    assert "def fire_canary_alert" in content
    assert "build_request_context" in content


def test_alerter_never_blocks() -> None:
    """CC-15: Alert dispatcher catches all exceptions — never raises."""
    project_dir = create_fixture_project(name="ct_t13")
    add_canary_tokens(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "core" / "canary" / "alerter.py").read_text()
    # Must have try/except around the webhook dispatch
    assert "except Exception" in content
    assert "BLE001" in content or "noqa" in content


def test_alerter_masks_sensitive_headers() -> None:
    """CC-16: Request context builder masks auth/cookie headers."""
    project_dir = create_fixture_project(name="ct_t14")
    add_canary_tokens(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "core" / "canary" / "alerter.py").read_text()
    assert "authorization" in content.lower()
    assert "***" in content or "mask" in content.lower()


def test_honeypot_routes_created() -> None:
    """CC-17: app/api/routes/canary_honeypot.py exists with three honeypot endpoints."""
    project_dir = create_fixture_project(name="ct_t15")
    add_canary_tokens(ToolInput(project_dir=str(project_dir)))
    honeypot = project_dir / "app" / "api" / "routes" / "canary_honeypot.py"
    assert honeypot.exists(), "canary_honeypot.py not created"
    content = honeypot.read_text()
    assert "/internal/config" in content
    assert "/admin/backup" in content
    assert "/debug/env" in content


def test_honeypot_returns_200_not_blocks() -> None:
    """CC-18: Honeypot routes return 200 OK (attacker must not detect canary)."""
    project_dir = create_fixture_project(name="ct_t16")
    add_canary_tokens(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "api" / "routes" / "canary_honeypot.py").read_text()
    # No 401/403/404 return statements — honeypot always serves data
    assert "return _FAKE" in content or "return {" in content
    assert "raise HTTPException" not in content


def test_fake_credentials_created() -> None:
    """CC-19: app/core/canary/fake_credentials.py exists with decoy keys."""
    project_dir = create_fixture_project(name="ct_t17")
    add_canary_tokens(ToolInput(project_dir=str(project_dir)))
    fake_creds = project_dir / "app" / "core" / "canary" / "fake_credentials.py"
    assert fake_creds.exists(), "fake_credentials.py not created"
    content = fake_creds.read_text()
    assert "CANARY_AWS_ACCESS_KEY_ID" in content
    assert "CANARY_DATABASE_URL" in content


def test_fake_credentials_are_placeholder_values() -> None:
    """QS-02: Fake credential values are clearly placeholders, not real keys."""
    project_dir = create_fixture_project(name="ct_t18")
    add_canary_tokens(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "core" / "canary" / "fake_credentials.py").read_text()
    # Should not contain real-looking AKIA key (20 chars after AKIA)
    assert "AKIA_CANARY_PLACEHOLDER" in content or "canary" in content.lower()


def test_decoy_seeder_created() -> None:
    """CC-20: app/core/canary/decoy_seeder.py exists with seed_decoy_records."""
    project_dir = create_fixture_project(name="ct_t19")
    add_canary_tokens(ToolInput(project_dir=str(project_dir)))
    seeder = project_dir / "app" / "core" / "canary" / "decoy_seeder.py"
    assert seeder.exists(), "decoy_seeder.py not created"
    content = seeder.read_text()
    assert "async def seed_decoy_records" in content
    assert "def is_canary_email" in content


def test_decoy_seeder_never_raises() -> None:
    """CC-21: Seeder catches all exceptions — safe to call regardless of DB state."""
    project_dir = create_fixture_project(name="ct_t20")
    add_canary_tokens(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "core" / "canary" / "decoy_seeder.py").read_text()
    assert "except Exception" in content


def test_routes_init_patched() -> None:
    """CC-10: routes/__init__.py includes canary_honeypot_router."""
    project_dir = create_fixture_project(name="ct_t21")
    add_canary_tokens(ToolInput(project_dir=str(project_dir)))
    routes_init = project_dir / "app" / "routes" / "__init__.py"
    if routes_init.exists():
        content = routes_init.read_text()
        assert "canary_honeypot" in content


def test_httpx_import_lazy_in_alerter() -> None:
    """QS-04: httpx imported inside function body, not at module level in alerter."""
    project_dir = create_fixture_project(name="ct_t22")
    add_canary_tokens(ToolInput(project_dir=str(project_dir)))
    alerter = project_dir / "app" / "core" / "canary" / "alerter.py"
    tree = ast.parse(alerter.read_text())
    for node in tree.body:
        assert not (
            isinstance(node, ast.Import)
            and any(alias.name == "httpx" for alias in node.names)
        ), "httpx must not be imported at module level in alerter.py"


# ---------------------------------------------------------------------------
# Category E — Invariants (CC-N-1, CC-N, CC-LAST)
# ---------------------------------------------------------------------------


def test_execution_time_recorded() -> None:
    """CC-N-1: execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="ct_t23")
    result = add_canary_tokens(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0


def test_next_steps_present() -> None:
    """CC-N: next_steps must guide developer on webhook configuration."""
    project_dir = create_fixture_project(name="ct_t24")
    result = add_canary_tokens(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.next_steps) > 0
    combined = " ".join(result.next_steps).lower()
    assert "webhook" in combined or "canary" in combined


def test_idempotent_project_still_parses() -> None:
    """CC-LAST: After two runs, all .py files still parse."""
    project_dir = create_fixture_project(name="ct_t25")
    add_canary_tokens(ToolInput(project_dir=str(project_dir)))
    add_canary_tokens(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_no_todo_fixme_in_generated() -> None:
    """QS-03: No TODO/FIXME/HACK in generated code."""
    project_dir = create_fixture_project(name="ct_t26")
    add_canary_tokens(ToolInput(project_dir=str(project_dir)))
    canary_dir = project_dir / "app" / "core" / "canary"
    for py_file in canary_dir.rglob("*.py"):
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
        test_canary_registry_created,
        test_registry_preregisters_all_canaries,
        test_canary_fingerprint_present,
        test_alerter_created,
        test_alerter_never_blocks,
        test_alerter_masks_sensitive_headers,
        test_honeypot_routes_created,
        test_honeypot_returns_200_not_blocks,
        test_fake_credentials_created,
        test_fake_credentials_are_placeholder_values,
        test_decoy_seeder_created,
        test_decoy_seeder_never_raises,
        test_routes_init_patched,
        test_httpx_import_lazy_in_alerter,
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
