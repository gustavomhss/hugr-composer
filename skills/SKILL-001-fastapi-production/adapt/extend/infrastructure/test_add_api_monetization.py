"""Structural tests for TOOL-119 add_api_monetization.

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_api_monetization.py -v

or standalone::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_api_monetization.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_api_monetization import add_api_monetization
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
# CC-01: success status
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    """CC-01: Tool returns status='success' on a fresh project."""
    project_dir = create_fixture_project(name="mon_t01")
    result = add_api_monetization(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


# ---------------------------------------------------------------------------
# CC-02: idempotency
# ---------------------------------------------------------------------------

def test_idempotent() -> None:
    """CC-02: Second run returns status='no_op' without touching files."""
    project_dir = create_fixture_project(name="mon_t02")
    r1 = add_api_monetization(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_api_monetization(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


# ---------------------------------------------------------------------------
# CC-03: dry_run
# ---------------------------------------------------------------------------

def test_dry_run() -> None:
    """CC-03: dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="mon_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_api_monetization(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


# ---------------------------------------------------------------------------
# CC-04: files_created count
# ---------------------------------------------------------------------------

def test_files_created_count() -> None:
    """CC-04: Tool creates at least 6 new files."""
    project_dir = create_fixture_project(name="mon_t04")
    result = add_api_monetization(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 6, (
        f"Expected >= 6 files_created, got {len(result.files_created)}: {result.files_created}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-05: files_modified count
# ---------------------------------------------------------------------------

def test_files_modified_count() -> None:
    """CC-05: Tool modifies at least 2 files (config, routes init)."""
    project_dir = create_fixture_project(name="mon_t05")
    result = add_api_monetization(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_modified) >= 2, (
        f"Expected >= 2 files_modified, got {len(result.files_modified)}: {result.files_modified}"
    )
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-06: all .py parse
# ---------------------------------------------------------------------------

def test_all_py_parse() -> None:
    """CC-06: Every generated .py file AST-parses clean."""
    project_dir = create_fixture_project(name="mon_t06")
    add_api_monetization(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# CC-07: no function over 50 LOC
# ---------------------------------------------------------------------------

def test_no_function_over_50_loc() -> None:
    """CC-07: No function in generated app/ exceeds 50 LOC."""
    project_dir = create_fixture_project(name="mon_t07")
    add_api_monetization(ToolInput(project_dir=str(project_dir)))
    max_loc = _max_function_loc(project_dir, "app")
    assert max_loc <= 50, f"Found function with {max_loc} LOC (limit: 50)"


# ---------------------------------------------------------------------------
# CC-08: config fields patched
# ---------------------------------------------------------------------------

def test_config_fields_patched() -> None:
    """CC-08: METERING_* config fields exist inside the Settings class body."""
    project_dir = create_fixture_project(name="mon_t08")
    add_api_monetization(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    for field in ["METERING_ENABLED", "STRIPE_METER_API_KEY", "METERING_BATCH_SIZE"]:
        assert field in content, f"Config field {field} not found in config.py"
    for line in content.splitlines():
        if "METERING_ENABLED" in line and ":" in line:
            assert line.startswith("    "), (
                f"METERING_ENABLED not inside class body (no 4-space indent): {line!r}"
            )
            break


# ---------------------------------------------------------------------------
# CC-09: models init patched
# ---------------------------------------------------------------------------

def test_models_init_patched() -> None:
    """CC-09: UsageRecord is registered in app/models/__init__.py."""
    project_dir = create_fixture_project(name="mon_t09")
    add_api_monetization(ToolInput(project_dir=str(project_dir)))
    models_init = project_dir / "app" / "models" / "__init__.py"
    content = models_init.read_text()
    assert "UsageRecord" in content, "UsageRecord not registered in models __init__"


# ---------------------------------------------------------------------------
# CC-10: routes registered
# ---------------------------------------------------------------------------

def test_routes_registered() -> None:
    """CC-10: Billing router is registered in app/routes/__init__.py."""
    project_dir = create_fixture_project(name="mon_t10")
    add_api_monetization(ToolInput(project_dir=str(project_dir)))
    routes_init = project_dir / "app" / "routes" / "__init__.py"
    if routes_init.exists():
        content = routes_init.read_text()
        assert "billing_router" in content or "billing" in content.lower(), (
            "Billing router not registered in routes __init__"
        )


# ---------------------------------------------------------------------------
# CC-11+: domain-specific tests
# ---------------------------------------------------------------------------

def test_metering_middleware_created() -> None:
    """CC-11: app/billing/metering.py exists with MeteringMiddleware."""
    project_dir = create_fixture_project(name="mon_t11")
    add_api_monetization(ToolInput(project_dir=str(project_dir)))
    metering_file = project_dir / "app" / "billing" / "metering.py"
    assert metering_file.exists(), "app/billing/metering.py not created"
    content = metering_file.read_text()
    assert "MeteringMiddleware" in content, "MeteringMiddleware class not found"
    assert "MeterEventBuffer" in content, "MeterEventBuffer class not found"
    assert "TenantQuota" in content, "TenantQuota class not found"


def test_metering_rules_dsl_created() -> None:
    """CC-11: app/billing/rules.py contains meter() DSL function."""
    project_dir = create_fixture_project(name="mon_t12")
    add_api_monetization(ToolInput(project_dir=str(project_dir)))
    rules_file = project_dir / "app" / "billing" / "rules.py"
    assert rules_file.exists(), "app/billing/rules.py not created"
    content = rules_file.read_text()
    assert "def meter(" in content, "meter() DSL function not found in rules.py"
    assert "MeteringRule" in content, "MeteringRule class not found in rules.py"
    assert "get_rules" in content, "get_rules() function not found in rules.py"


def test_stripe_meter_sync_created() -> None:
    """CC-11: app/billing/stripe_meter_sync.py exists with batching and retry."""
    project_dir = create_fixture_project(name="mon_t13")
    add_api_monetization(ToolInput(project_dir=str(project_dir)))
    sync_file = project_dir / "app" / "billing" / "stripe_meter_sync.py"
    assert sync_file.exists(), "app/billing/stripe_meter_sync.py not created"
    content = sync_file.read_text()
    assert "flush_meter_events" in content, "flush_meter_events function not found"
    assert "_submit_with_retry" in content, "_submit_with_retry function not found"
    assert "_DEAD_LETTER" in content, "_DEAD_LETTER dead-letter queue not found"


def test_usage_record_model_created() -> None:
    """CC-11: app/models/usage_record.py exists with UsageRecord model."""
    project_dir = create_fixture_project(name="mon_t14")
    add_api_monetization(ToolInput(project_dir=str(project_dir)))
    model_file = project_dir / "app" / "models" / "usage_record.py"
    assert model_file.exists(), "app/models/usage_record.py not created"
    content = model_file.read_text()
    assert "class UsageRecord" in content, "UsageRecord class not found"
    for field in ["tenant_id", "endpoint", "method", "status_code"]:
        assert field in content, f"UsageRecord model missing field: {field}"


def test_billing_routes_endpoints() -> None:
    """CC-11: app/api/routes/billing.py contains all required endpoints."""
    project_dir = create_fixture_project(name="mon_t15")
    add_api_monetization(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "billing.py"
    assert route_file.exists(), "app/api/routes/billing.py not created"
    content = route_file.read_text()
    for endpoint in ["/usage", "/history", "/limits", "/upgrade", "/plans"]:
        assert endpoint in content, f"Billing endpoint {endpoint} not found in billing.py"


def test_stripe_lazy_import_in_sync() -> None:
    """CC-11: stripe is NOT imported at module top level in stripe_meter_sync.py."""
    project_dir = create_fixture_project(name="mon_t16")
    add_api_monetization(ToolInput(project_dir=str(project_dir)))
    sync_file = project_dir / "app" / "billing" / "stripe_meter_sync.py"
    tree = ast.parse(sync_file.read_text())
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "stripe", (
                    "stripe must NOT be imported at module top level in stripe_meter_sync.py"
                )
        elif isinstance(node, ast.ImportFrom):
            assert node.module != "stripe", (
                "stripe must NOT be imported at module top level in stripe_meter_sync.py"
            )


def test_usage_alerts_in_middleware() -> None:
    """CC-11: MeteringMiddleware calls _check_usage_alerts for quota threshold alerts."""
    project_dir = create_fixture_project(name="mon_t17")
    add_api_monetization(ToolInput(project_dir=str(project_dir)))
    metering_file = project_dir / "app" / "billing" / "metering.py"
    content = metering_file.read_text()
    assert "_check_usage_alerts" in content, "_check_usage_alerts not found in metering.py"
    assert "80" in content, "80% threshold not referenced in metering.py"
    assert "90" in content, "90% threshold not referenced in metering.py"
    assert "100" in content, "100% threshold not referenced in metering.py"


def test_tier_enforcement_429() -> None:
    """CC-11: MeteringMiddleware returns 429 when quota is exhausted."""
    project_dir = create_fixture_project(name="mon_t18")
    add_api_monetization(ToolInput(project_dir=str(project_dir)))
    metering_file = project_dir / "app" / "billing" / "metering.py"
    content = metering_file.read_text()
    assert "429" in content, "429 status code not found in MeteringMiddleware"
    assert "quota" in content.lower(), "quota exhaustion handling not found"


# ---------------------------------------------------------------------------
# CC-N-1 & CC-N: execution_time and next_steps
# ---------------------------------------------------------------------------

def test_execution_time_recorded() -> None:
    """CC-N-1: execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="mon_t19")
    result = add_api_monetization(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


def test_next_steps_present() -> None:
    """CC-N: next_steps is non-empty and mentions 'alembic'."""
    project_dir = create_fixture_project(name="mon_t20")
    result = add_api_monetization(ToolInput(project_dir=str(project_dir)))
    assert result.next_steps, "next_steps must be non-empty"
    combined = " ".join(result.next_steps).lower()
    assert "alembic" in combined, "next_steps should mention alembic upgrade"


# ---------------------------------------------------------------------------
# CC-LAST: idempotent + project still parses
# ---------------------------------------------------------------------------

def test_idempotent_project_still_parses() -> None:
    """CC-LAST: After two runs all .py files remain parseable."""
    project_dir = create_fixture_project(name="mon_t21")
    add_api_monetization(ToolInput(project_dir=str(project_dir)))
    add_api_monetization(ToolInput(project_dir=str(project_dir)))
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
        test_models_init_patched,
        test_routes_registered,
        test_metering_middleware_created,
        test_metering_rules_dsl_created,
        test_stripe_meter_sync_created,
        test_usage_record_model_created,
        test_billing_routes_endpoints,
        test_stripe_lazy_import_in_sync,
        test_usage_alerts_in_middleware,
        test_tier_enforcement_429,
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
    print(f"TOOL-119 add_api_monetization: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
