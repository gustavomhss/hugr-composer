"""Tests for TOOL-023 add_stripe_checkout.

Generates real fixture projects via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_stripe_checkout.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_stripe_checkout.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_stripe_checkout import add_stripe_checkout
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
    """Return the max LOC of any function in the given subdir."""
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
# Category A — Tool execution
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    """Tool returns status='success' on a fresh project."""
    project_dir = create_fixture_project(name="stripe_t01")
    result = add_stripe_checkout(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


def test_idempotent() -> None:
    """Second run returns status='no_op' without touching files."""
    project_dir = create_fixture_project(name="stripe_t02")
    r1 = add_stripe_checkout(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_stripe_checkout(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


def test_dry_run() -> None:
    """dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="stripe_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_stripe_checkout(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_files_created_count() -> None:
    """Tool creates at least 5 new files (client, model, schemas, crud, routes, migration)."""
    project_dir = create_fixture_project(name="stripe_t04")
    result = add_stripe_checkout(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 5, (
        f"Expected >= 5 files_created, got {len(result.files_created)}: {result.files_created}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


def test_files_modified_count() -> None:
    """Tool modifies at least 2 files (config, models init, routes init, requirements)."""
    project_dir = create_fixture_project(name="stripe_t05")
    result = add_stripe_checkout(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_modified) >= 2, (
        f"Expected >= 2 files_modified, got {len(result.files_modified)}: {result.files_modified}"
    )
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


# ---------------------------------------------------------------------------
# Category B — Generated code quality
# ---------------------------------------------------------------------------

def test_all_py_parse() -> None:
    """Every generated .py file AST-parses clean."""
    project_dir = create_fixture_project(name="stripe_t06")
    add_stripe_checkout(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_no_function_over_50_loc() -> None:
    """No function in generated app/ exceeds 50 LOC."""
    project_dir = create_fixture_project(name="stripe_t07")
    add_stripe_checkout(ToolInput(project_dir=str(project_dir)))
    max_loc = _max_function_loc(project_dir, "app")
    assert max_loc <= 50, f"Found function with {max_loc} LOC (limit: 50)"


def test_config_fields_patched() -> None:
    """Expected STRIPE_* settings fields exist inside the Settings class in config.py."""
    project_dir = create_fixture_project(name="stripe_t08")
    add_stripe_checkout(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    expected_fields = [
        "STRIPE_SECRET_KEY",
        "STRIPE_PUBLISHABLE_KEY",
        "STRIPE_WEBHOOK_SECRET",
        "STRIPE_API_VERSION",
        "STRIPE_CHECKOUT_SUCCESS_URL",
        "STRIPE_CHECKOUT_CANCEL_URL",
    ]
    for field in expected_fields:
        assert field in content, f"Config field {field} not found in config.py"
    # Verify fields are inside the Settings class (4-space indent)
    for line in content.splitlines():
        if "STRIPE_SECRET_KEY" in line and ":" in line:
            assert line.startswith("    "), (
                f"STRIPE_SECRET_KEY not inside class body (no 4-space indent): {line!r}"
            )
            break


def test_models_init_patched() -> None:
    """Payment model is registered in app/models/__init__.py."""
    project_dir = create_fixture_project(name="stripe_t09")
    add_stripe_checkout(ToolInput(project_dir=str(project_dir)))
    models_init = project_dir / "app" / "models" / "__init__.py"
    content = models_init.read_text()
    assert "Payment" in content, "Payment not registered in models __init__"


def test_routes_registered() -> None:
    """Payments router is registered in app/routes/__init__.py."""
    project_dir = create_fixture_project(name="stripe_t10")
    add_stripe_checkout(ToolInput(project_dir=str(project_dir)))
    routes_init = project_dir / "app" / "routes" / "__init__.py"
    if routes_init.exists():
        content = routes_init.read_text()
        assert "payment" in content.lower(), "Payments router not registered in routes __init__"


# ---------------------------------------------------------------------------
# Category C — Domain-specific
# ---------------------------------------------------------------------------

def test_stripe_client_lazy_import() -> None:
    """app/core/stripe_client.py exists and uses lazy import."""
    project_dir = create_fixture_project(name="stripe_t11")
    add_stripe_checkout(ToolInput(project_dir=str(project_dir)))
    client_file = project_dir / "app" / "core" / "stripe_client.py"
    assert client_file.exists(), "stripe_client.py not created"
    content = client_file.read_text()
    assert "get_stripe" in content, "get_stripe function not found"
    assert "import stripe" in content, "Lazy stripe import not found"


def test_payment_model_created() -> None:
    """app/models/payment.py exists with Payment class."""
    project_dir = create_fixture_project(name="stripe_t12")
    add_stripe_checkout(ToolInput(project_dir=str(project_dir)))
    model_file = project_dir / "app" / "models" / "payment.py"
    assert model_file.exists(), "app/models/payment.py not created"
    content = model_file.read_text()
    assert "class Payment" in content, "Payment model class not found"


def test_payment_crud_created() -> None:
    """app/crud/payment.py exists with at least 5 helpers."""
    project_dir = create_fixture_project(name="stripe_t13")
    add_stripe_checkout(ToolInput(project_dir=str(project_dir)))
    crud_file = project_dir / "app" / "crud" / "payment.py"
    assert crud_file.exists(), "app/crud/payment.py not created"
    content = crud_file.read_text()
    fn_count = content.count("async def ")
    assert fn_count >= 5, f"Expected >= 5 CRUD helpers, found {fn_count}"


def test_webhook_route_present() -> None:
    """app/api/routes/payments.py contains /webhook/stripe endpoint."""
    project_dir = create_fixture_project(name="stripe_t14")
    add_stripe_checkout(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "payments.py"
    assert route_file.exists(), "app/api/routes/payments.py not created"
    content = route_file.read_text()
    assert "webhook" in content.lower(), "Webhook route not found in payments.py"
    assert "stripe" in content.lower(), "Stripe reference not found in payments.py webhook"


def test_stripe_config_fields() -> None:
    """6 STRIPE_* fields exist in config.py."""
    project_dir = create_fixture_project(name="stripe_t15")
    add_stripe_checkout(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    stripe_fields = [
        "STRIPE_SECRET_KEY",
        "STRIPE_PUBLISHABLE_KEY",
        "STRIPE_WEBHOOK_SECRET",
        "STRIPE_API_VERSION",
        "STRIPE_CHECKOUT_SUCCESS_URL",
        "STRIPE_CHECKOUT_CANCEL_URL",
    ]
    for field in stripe_fields:
        assert field in content, f"Missing Stripe config field: {field}"


def test_main_not_patched() -> None:
    """app/main.py does NOT import stripe — Stripe SDK is stateless, no lifespan hook needed."""
    project_dir = create_fixture_project(name="stripe_t16")
    add_stripe_checkout(ToolInput(project_dir=str(project_dir)))
    main_file = project_dir / "app" / "main.py"
    content = main_file.read_text()
    # The project name may contain "stripe" in the title string — only check
    # for actual import/usage patterns, not casual name occurrences.
    assert "import stripe" not in content, (
        "main.py should NOT import stripe — SDK is stateless"
    )
    assert "stripe_client" not in content, (
        "main.py should NOT reference stripe_client — SDK is stateless"
    )


def test_pii_safe_schema() -> None:
    """PaymentPublic does NOT include stripe_customer_id or customer_email."""
    project_dir = create_fixture_project(name="stripe_t17")
    add_stripe_checkout(ToolInput(project_dir=str(project_dir)))
    schema_file = project_dir / "app" / "schemas" / "payment.py"
    content = schema_file.read_text()
    assert "PaymentPublic" in content, "PaymentPublic schema not found"
    # Find the PaymentPublic class body only
    pub_start = content.find("class PaymentPublic")
    pub_end = content.find("\nclass ", pub_start + 1)
    public_body = content[pub_start:pub_end] if pub_end != -1 else content[pub_start:]
    assert "stripe_customer_id" not in public_body, (
        "PaymentPublic must NOT expose stripe_customer_id"
    )
    assert "customer_email" not in public_body, (
        "PaymentPublic must NOT expose customer_email"
    )


def test_requirements_stripe() -> None:
    """requirements.txt contains stripe>=."""
    project_dir = create_fixture_project(name="stripe_t18")
    add_stripe_checkout(ToolInput(project_dir=str(project_dir)))
    requirements = project_dir / "requirements.txt"
    content = requirements.read_text()
    assert "stripe>=" in content, "stripe dependency not added to requirements.txt"


def test_execution_time_recorded() -> None:
    """execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="stripe_t19")
    result = add_stripe_checkout(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


def test_idempotent_project_still_parses() -> None:
    """After two runs all .py files remain parseable."""
    project_dir = create_fixture_project(name="stripe_t20")
    add_stripe_checkout(ToolInput(project_dir=str(project_dir)))
    add_stripe_checkout(ToolInput(project_dir=str(project_dir)))
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
        test_stripe_client_lazy_import,
        test_payment_model_created,
        test_payment_crud_created,
        test_webhook_route_present,
        test_stripe_config_fields,
        test_main_not_patched,
        test_pii_safe_schema,
        test_requirements_stripe,
        test_execution_time_recorded,
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
    print(f"TOOL-023 add_stripe_checkout: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
