"""Tests for TOOL-065 add_stripe_subscription.

Generates real fixture projects via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_stripe_subscription.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_stripe_subscription.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_stripe_subscription import add_stripe_subscription
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
    """CC-01: Tool returns status='success' on a fresh project."""
    project_dir = create_fixture_project(name="sub_t01")
    result = add_stripe_subscription(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


def test_idempotent() -> None:
    """CC-02: Second run returns status='no_op' without touching files."""
    project_dir = create_fixture_project(name="sub_t02")
    r1 = add_stripe_subscription(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_stripe_subscription(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


def test_dry_run() -> None:
    """CC-03: dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="sub_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_stripe_subscription(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_files_created_count() -> None:
    """CC-04: Tool creates at least 6 new files."""
    project_dir = create_fixture_project(name="sub_t04")
    result = add_stripe_subscription(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 6, (
        f"Expected >= 6 files_created, got {len(result.files_created)}: {result.files_created}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


def test_files_modified_count() -> None:
    """CC-05: Tool modifies at least 3 files (config, models init, routes init, requirements)."""
    project_dir = create_fixture_project(name="sub_t05")
    result = add_stripe_subscription(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_modified) >= 3, (
        f"Expected >= 3 files_modified, got {len(result.files_modified)}: {result.files_modified}"
    )
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


# ---------------------------------------------------------------------------
# Category B — Generated code quality
# ---------------------------------------------------------------------------

def test_all_py_parse() -> None:
    """CC-06: Every generated .py file AST-parses clean."""
    project_dir = create_fixture_project(name="sub_t06")
    add_stripe_subscription(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_no_function_over_50_loc() -> None:
    """CC-07: No function in generated app/ exceeds 50 LOC."""
    project_dir = create_fixture_project(name="sub_t07")
    add_stripe_subscription(ToolInput(project_dir=str(project_dir)))
    max_loc = _max_function_loc(project_dir, "app")
    assert max_loc <= 50, f"Found function with {max_loc} LOC (limit: 50)"


def test_config_fields_patched() -> None:
    """CC-08: STRIPE_* settings fields exist inside the Settings class body."""
    project_dir = create_fixture_project(name="sub_t08")
    add_stripe_subscription(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    expected_fields = [
        "STRIPE_SECRET_KEY",
        "STRIPE_WEBHOOK_SECRET",
        "STRIPE_BILLING_PORTAL_RETURN_URL",
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
    """CC-09: Subscription model is registered in app/models/__init__.py."""
    project_dir = create_fixture_project(name="sub_t09")
    add_stripe_subscription(ToolInput(project_dir=str(project_dir)))
    models_init = project_dir / "app" / "models" / "__init__.py"
    content = models_init.read_text()
    assert "Subscription" in content, "Subscription not registered in models __init__"


def test_routes_registered() -> None:
    """CC-10: Subscriptions router is registered in app/routes/__init__.py."""
    project_dir = create_fixture_project(name="sub_t10")
    add_stripe_subscription(ToolInput(project_dir=str(project_dir)))
    routes_init = project_dir / "app" / "routes" / "__init__.py"
    if routes_init.exists():
        content = routes_init.read_text()
        assert "subscription" in content.lower(), (
            "Subscriptions router not registered in routes __init__"
        )


# ---------------------------------------------------------------------------
# Category C — Domain-specific
# ---------------------------------------------------------------------------

def test_stripe_billing_created() -> None:
    """CC-11: app/core/stripe_billing.py exists with StripeBilling factory
    and the lazy-stripe-import is inherited from the shipped adapter.

    Post-Rails: the glue imports the framework-free ``Billing`` Protocol
    and the Stripe-specific ``StripeBillingAdapter``; the adapter module
    lives on disk AND imports ``stripe`` lazily inside ``_get_stripe``.
    """
    project_dir = create_fixture_project(name="sub_t11")
    add_stripe_subscription(ToolInput(project_dir=str(project_dir)))
    billing_file = project_dir / "app" / "core" / "stripe_billing.py"
    assert billing_file.exists(), "stripe_billing.py not created"
    content = billing_file.read_text()
    # Rails wiring: facade imports the shipped motor + adapter.
    # Direct module imports are used (robust against bare __init__.py
    # placeholders that the scaffolder may have written on older builds).
    assert "core.venous.billing.Billing" in content
    assert "core.venous._adapters.stripe" in content
    assert "StripeBillingAdapter" in content
    assert "get_stripe_billing" in content, "get_stripe_billing factory missing"

    # The adapter itself MUST have been shipped into the project's
    # core/venous tree and its ``import stripe`` is lazy (inside a
    # function body).
    adapter_file = (
        project_dir / "core" / "venous" / "_adapters" / "stripe"
        / "BillingAdapter.py"
    )
    assert adapter_file.exists(), "StripeBillingAdapter not shipped"
    adapter_content = adapter_file.read_text()
    assert "import stripe" in adapter_content, "Lazy stripe import missing"
    # Reject module-level import by checking indentation: the real lazy
    # import is inside ``_get_stripe`` and therefore indented.
    module_level_imports = [
        line for line in adapter_content.splitlines()
        if line.startswith("import stripe") or line.startswith("from stripe ")
    ]
    assert not module_level_imports, (
        "stripe must be imported lazily inside a function body, not at "
        f"module level; found: {module_level_imports!r}"
    )


def test_subscription_model_created() -> None:
    """CC-11: app/models/subscription.py exists with Subscription class."""
    project_dir = create_fixture_project(name="sub_t12")
    add_stripe_subscription(ToolInput(project_dir=str(project_dir)))
    model_file = project_dir / "app" / "models" / "subscription.py"
    assert model_file.exists(), "app/models/subscription.py not created"
    content = model_file.read_text()
    assert "class Subscription" in content, "Subscription model class not found"
    # Verify all required fields
    for field in [
        "stripe_subscription_id",
        "stripe_customer_id",
        "plan_id",
        "status",
        "current_period_start",
        "current_period_end",
        "cancel_at_period_end",
    ]:
        assert field in content, f"Subscription model missing field: {field}"


def test_subscription_crud_created() -> None:
    """CC-11: app/crud/subscription.py exists with at least 5 async helpers."""
    project_dir = create_fixture_project(name="sub_t13")
    add_stripe_subscription(ToolInput(project_dir=str(project_dir)))
    crud_file = project_dir / "app" / "crud" / "subscription.py"
    assert crud_file.exists(), "app/crud/subscription.py not created"
    content = crud_file.read_text()
    fn_count = content.count("async def ")
    assert fn_count >= 5, f"Expected >= 5 CRUD helpers, found {fn_count}"


def test_webhook_route_present() -> None:
    """CC-11: app/api/routes/subscriptions.py contains /webhook/stripe endpoint."""
    project_dir = create_fixture_project(name="sub_t14")
    add_stripe_subscription(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "subscriptions.py"
    assert route_file.exists(), "app/api/routes/subscriptions.py not created"
    content = route_file.read_text()
    assert "webhook" in content.lower(), "Webhook route not found in subscriptions.py"
    assert "stripe" in content.lower(), "Stripe reference not found in subscriptions.py"


def test_cancel_and_change_plan_routes() -> None:
    """CC-11: subscriptions.py contains cancel and change-plan endpoints."""
    project_dir = create_fixture_project(name="sub_t15")
    add_stripe_subscription(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "subscriptions.py"
    content = route_file.read_text()
    assert "cancel" in content.lower(), "Cancel endpoint not found in subscriptions.py"
    assert "change-plan" in content.lower(), "change-plan endpoint not found"


def test_pii_safe_schema() -> None:
    """CC-11: SubscriptionPublic does NOT include stripe_customer_id as a field."""
    project_dir = create_fixture_project(name="sub_t16")
    add_stripe_subscription(ToolInput(project_dir=str(project_dir)))
    schema_file = project_dir / "app" / "schemas" / "subscription.py"
    content = schema_file.read_text()
    assert "SubscriptionPublic" in content, "SubscriptionPublic schema not found"
    # Parse the AST and check that SubscriptionPublic has no stripe_customer_id attribute
    tree = ast.parse(content)
    pub_fields: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "SubscriptionPublic":
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    pub_fields.append(item.target.id)
    assert "stripe_customer_id" not in pub_fields, (
        f"SubscriptionPublic must NOT expose stripe_customer_id as a field. "
        f"Fields found: {pub_fields}"
    )


def test_requirements_stripe() -> None:
    """CC-12: requirements.txt contains stripe>=."""
    project_dir = create_fixture_project(name="sub_t17")
    add_stripe_subscription(ToolInput(project_dir=str(project_dir)))
    requirements = project_dir / "requirements.txt"
    content = requirements.read_text()
    assert "stripe>=" in content, "stripe dependency not added to requirements.txt"


def test_execution_time_recorded() -> None:
    """CC-13: execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="sub_t18")
    result = add_stripe_subscription(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


def test_next_steps_present() -> None:
    """CC-14: next_steps is non-empty and mentions 'alembic'."""
    project_dir = create_fixture_project(name="sub_t19")
    result = add_stripe_subscription(ToolInput(project_dir=str(project_dir)))
    assert result.next_steps, "next_steps must be non-empty"
    combined = " ".join(result.next_steps).lower()
    assert "alembic" in combined, "next_steps should mention alembic upgrade"


def test_idempotent_project_still_parses() -> None:
    """CC-15: After two runs all .py files remain parseable."""
    project_dir = create_fixture_project(name="sub_t20")
    add_stripe_subscription(ToolInput(project_dir=str(project_dir)))
    add_stripe_subscription(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_stripe_not_top_level_import_in_billing() -> None:
    """CC-17: stripe is NOT imported at module top level in stripe_billing.py."""
    project_dir = create_fixture_project(name="sub_t21")
    add_stripe_subscription(ToolInput(project_dir=str(project_dir)))
    billing_file = project_dir / "app" / "core" / "stripe_billing.py"
    tree = ast.parse(billing_file.read_text())
    # Check module-level imports only (not inside function bodies)
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "stripe", (
                    "stripe must NOT be imported at module top level in stripe_billing.py"
                )
        elif isinstance(node, ast.ImportFrom):
            assert node.module != "stripe", (
                "stripe must NOT be imported at module top level in stripe_billing.py"
            )


def test_webhook_signature_verified_before_db() -> None:
    """CC-11: Webhook handler calls construct_webhook_event before any DB operation."""
    project_dir = create_fixture_project(name="sub_t22")
    add_stripe_subscription(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "subscriptions.py"
    content = route_file.read_text()
    # construct_webhook_event must appear in the webhook handler
    assert "construct_webhook_event" in content, (
        "Webhook route must call construct_webhook_event for signature verification"
    )
    # Verify it appears before any session commit / crud call in the function
    webhook_start = content.find("async def stripe_webhook")
    construct_pos = content.find("construct_webhook_event", webhook_start)
    handle_pos = content.find("_handle_subscription_event", webhook_start)
    assert construct_pos < handle_pos, (
        "construct_webhook_event must be called BEFORE _handle_subscription_event"
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
        test_models_init_patched,
        test_routes_registered,
        test_stripe_billing_created,
        test_subscription_model_created,
        test_subscription_crud_created,
        test_webhook_route_present,
        test_cancel_and_change_plan_routes,
        test_pii_safe_schema,
        test_requirements_stripe,
        test_execution_time_recorded,
        test_next_steps_present,
        test_idempotent_project_still_parses,
        test_stripe_not_top_level_import_in_billing,
        test_webhook_signature_verified_before_db,
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
    print(f"TOOL-065 add_stripe_subscription: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
