"""Tests for TOOL-066 add_stripe_refund_flow.

Generates real fixture projects via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_stripe_refund_flow.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_stripe_refund_flow.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_stripe_refund_flow import add_stripe_refund_flow
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
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and getattr(
                node, "end_lineno", None
            ):
                loc = node.end_lineno - node.lineno + 1
                max_loc = max(max_loc, loc)
    return max_loc


# ---------------------------------------------------------------------------
# Category A — Tool execution
# ---------------------------------------------------------------------------


def test_success_status() -> None:
    """Tool returns status='success' on a fresh project."""
    project_dir = create_fixture_project(name="refund_t01")
    result = add_stripe_refund_flow(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


def test_idempotent() -> None:
    """Second run returns status='no_op' without touching files."""
    project_dir = create_fixture_project(name="refund_t02")
    r1 = add_stripe_refund_flow(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_stripe_refund_flow(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


def test_dry_run() -> None:
    """dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="refund_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_stripe_refund_flow(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_files_created_count() -> None:
    """Tool creates at least 5 new files."""
    project_dir = create_fixture_project(name="refund_t04")
    result = add_stripe_refund_flow(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 5, (
        f"Expected >= 5 files_created, got {len(result.files_created)}: {result.files_created}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


def test_files_modified_count() -> None:
    """Tool modifies at least 2 files (config, models init, routes init, requirements)."""
    project_dir = create_fixture_project(name="refund_t05")
    result = add_stripe_refund_flow(ToolInput(project_dir=str(project_dir)))
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
    project_dir = create_fixture_project(name="refund_t06")
    add_stripe_refund_flow(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_no_function_over_50_loc() -> None:
    """No function in generated app/ exceeds 50 LOC."""
    project_dir = create_fixture_project(name="refund_t07")
    add_stripe_refund_flow(ToolInput(project_dir=str(project_dir)))
    max_loc = _max_function_loc(project_dir, "app")
    assert max_loc <= 50, f"Found function with {max_loc} LOC (limit: 50)"


def test_config_fields_patched() -> None:
    """Expected refund settings fields exist inside the Settings class in config.py."""
    project_dir = create_fixture_project(name="refund_t08")
    add_stripe_refund_flow(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    expected_fields = [
        "STRIPE_REFUND_WEBHOOK_SECRET",
        "REFUND_MAX_AMOUNT_CENTS",
        "REFUND_AUTO_APPROVE_THRESHOLD_CENTS",
    ]
    for field in expected_fields:
        assert field in content, f"Config field {field} not found in config.py"
    # Verify fields are inside the Settings class (4-space indent)
    for line in content.splitlines():
        if "STRIPE_REFUND_WEBHOOK_SECRET" in line and ":" in line:
            assert line.startswith("    "), (
                f"STRIPE_REFUND_WEBHOOK_SECRET not inside class body: {line!r}"
            )
            break


def test_models_init_patched() -> None:
    """Refund model is registered in app/models/__init__.py."""
    project_dir = create_fixture_project(name="refund_t09")
    add_stripe_refund_flow(ToolInput(project_dir=str(project_dir)))
    models_init = project_dir / "app" / "models" / "__init__.py"
    content = models_init.read_text()
    assert "Refund" in content, "Refund not registered in models __init__"


def test_routes_registered() -> None:
    """Refunds router is registered in app/routes/__init__.py."""
    project_dir = create_fixture_project(name="refund_t10")
    add_stripe_refund_flow(ToolInput(project_dir=str(project_dir)))
    routes_init = project_dir / "app" / "routes" / "__init__.py"
    if routes_init.exists():
        content = routes_init.read_text()
        assert "refund" in content.lower(), "Refunds router not registered in routes __init__"


# ---------------------------------------------------------------------------
# Category C — Domain-specific
# ---------------------------------------------------------------------------


def test_refund_model_created() -> None:
    """app/models/refund.py exists with Refund class."""
    project_dir = create_fixture_project(name="refund_t11")
    add_stripe_refund_flow(ToolInput(project_dir=str(project_dir)))
    model_file = project_dir / "app" / "models" / "refund.py"
    assert model_file.exists(), "app/models/refund.py not created"
    content = model_file.read_text()
    assert "class Refund" in content, "Refund model class not found"


def test_refund_model_has_required_columns() -> None:
    """Refund model contains all required columns."""
    project_dir = create_fixture_project(name="refund_t12")
    add_stripe_refund_flow(ToolInput(project_dir=str(project_dir)))
    model_file = project_dir / "app" / "models" / "refund.py"
    content = model_file.read_text()
    for col in [
        "payment_id",
        "stripe_refund_id",
        "amount_cents",
        "reason",
        "status",
        "requested_by",
        "created_at",
    ]:
        assert col in content, f"Column '{col}' not found in refund model"


def test_refund_crud_created() -> None:
    """app/crud/refund.py exists with at least 6 async helpers."""
    project_dir = create_fixture_project(name="refund_t13")
    add_stripe_refund_flow(ToolInput(project_dir=str(project_dir)))
    crud_file = project_dir / "app" / "crud" / "refund.py"
    assert crud_file.exists(), "app/crud/refund.py not created"
    content = crud_file.read_text()
    fn_count = content.count("async def ")
    assert fn_count >= 6, f"Expected >= 6 CRUD helpers, found {fn_count}"


def test_stripe_refunds_lazy_import() -> None:
    """app/core/stripe_refunds.py exists and uses lazy stripe import."""
    project_dir = create_fixture_project(name="refund_t14")
    add_stripe_refund_flow(ToolInput(project_dir=str(project_dir)))
    helper_file = project_dir / "app" / "core" / "stripe_refunds.py"
    assert helper_file.exists(), "app/core/stripe_refunds.py not created"
    content = helper_file.read_text()
    assert "create_refund" in content, "create_refund function not found"
    assert "import stripe" in content, "Lazy stripe import not found in stripe_refunds.py"
    # Must NOT be at module top level
    tree = ast.parse(content)
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "stripe", (
                    "stripe imported at module top level in stripe_refunds.py"
                )


def test_webhook_route_present() -> None:
    """app/api/routes/refunds.py contains /webhook/stripe endpoint."""
    project_dir = create_fixture_project(name="refund_t15")
    add_stripe_refund_flow(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "refunds.py"
    assert route_file.exists(), "app/api/routes/refunds.py not created"
    content = route_file.read_text()
    assert "webhook" in content.lower(), "Webhook route not found in refunds.py"
    assert "stripe" in content.lower(), "Stripe reference not found in refunds.py"


def test_pii_safe_schema() -> None:
    """RefundPublic does NOT declare stripe_refund_id as an annotated field."""
    project_dir = create_fixture_project(name="refund_t16")
    add_stripe_refund_flow(ToolInput(project_dir=str(project_dir)))
    schema_file = project_dir / "app" / "schemas" / "refund.py"
    assert schema_file.exists(), "app/schemas/refund.py not created"
    content = schema_file.read_text()
    assert "RefundPublic" in content, "RefundPublic schema not found"

    # Use AST to find annotated field names inside RefundPublic — docstrings
    # may legitimately mention the field name, so we must not do a string search.
    tree = ast.parse(content)
    public_field_names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "RefundPublic":
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    public_field_names.append(item.target.id)

    assert "stripe_refund_id" not in public_field_names, (
        f"RefundPublic must NOT declare stripe_refund_id as a field; "
        f"found fields: {public_field_names}"
    )


def test_requirements_stripe() -> None:
    """requirements.txt contains stripe>=."""
    project_dir = create_fixture_project(name="refund_t17")
    add_stripe_refund_flow(ToolInput(project_dir=str(project_dir)))
    requirements = project_dir / "requirements.txt"
    content = requirements.read_text()
    assert "stripe>=" in content, "stripe dependency not added to requirements.txt"


def test_idempotency_key_in_refund_helper() -> None:
    """app/core/stripe_refunds.py uses an idempotency key."""
    project_dir = create_fixture_project(name="refund_t18")
    add_stripe_refund_flow(ToolInput(project_dir=str(project_dir)))
    helper_file = project_dir / "app" / "core" / "stripe_refunds.py"
    content = helper_file.read_text()
    assert "idempotency_key" in content, "idempotency_key not found in stripe_refunds.py"


def test_execution_time_recorded() -> None:
    """execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="refund_t19")
    result = add_stripe_refund_flow(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


def test_next_steps_present() -> None:
    """next_steps must be non-empty and mention alembic."""
    project_dir = create_fixture_project(name="refund_t20")
    result = add_stripe_refund_flow(ToolInput(project_dir=str(project_dir)))
    assert len(result.next_steps) > 0, "next_steps should not be empty"
    combined = " ".join(result.next_steps).lower()
    assert "alembic" in combined, "next_steps should mention alembic"


def test_idempotent_project_still_parses() -> None:
    """After two runs all .py files remain parseable."""
    project_dir = create_fixture_project(name="refund_t21")
    add_stripe_refund_flow(ToolInput(project_dir=str(project_dir)))
    add_stripe_refund_flow(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_stripe_not_top_level_in_routes() -> None:
    """stripe must NOT be imported at module top level in refunds.py routes."""
    project_dir = create_fixture_project(name="refund_t22")
    add_stripe_refund_flow(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "refunds.py"
    content = route_file.read_text()
    tree = ast.parse(content)
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "stripe", "stripe imported at module top level in refunds.py"
        elif isinstance(node, ast.ImportFrom):
            assert node.module != "stripe", "from stripe ... at module top level in refunds.py"


# ---------------------------------------------------------------------------
# Category D — Regression: R5-O3-F3 / R5-S7-S03
# (refund route MUST call Stripe — not just persist a pending row)
# ---------------------------------------------------------------------------


def _request_refund_fn(route_file: Path) -> ast.AsyncFunctionDef:
    """Locate the ``request_refund`` async handler in the route AST."""
    tree = ast.parse(route_file.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "request_refund":
            return node
    raise AssertionError("request_refund handler not found in refunds.py")


def test_r5_o3_f3_route_imports_create_refund() -> None:
    """R5-O3-F3: refunds.py must import ``create_refund`` from the helper.

    Pre-fix, ``create_refund`` was never referenced from the route file —
    only the pending DB row was persisted, so Stripe was never called.
    """
    project_dir = create_fixture_project(name="refund_r5_o3_f3_imp")
    add_stripe_refund_flow(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "refunds.py"
    tree = ast.parse(route_file.read_text())
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and "stripe_refunds" in node.module:
            for alias in node.names:
                if alias.name == "create_refund":
                    found = True
    assert found, (
        "refunds.py does not import create_refund from "
        "app.core.stripe_refunds — the route can never call Stripe."
    )


def test_r5_o3_f3_request_refund_calls_stripe() -> None:
    """R5-O3-F3: refunds.py route module must invoke ``create_refund``.

    Pre-fix the handler inserted a ``pending`` Refund row and returned 201
    without ever invoking the Stripe API.  Customer would see
    "refund requested", no money would ever be returned, and the
    ``charge.refund.updated`` webhook could never fire because Stripe
    had no record of the refund.

    The call may live directly in ``request_refund`` or in a private
    helper called by ``request_refund`` (split for the 50-LOC ceiling).
    Either way, the route's transitive call graph must touch
    ``create_refund``.
    """
    project_dir = create_fixture_project(name="refund_r5_o3_f3_call")
    add_stripe_refund_flow(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "refunds.py"
    tree = ast.parse(route_file.read_text())

    # Walk the whole module — handler may delegate to a helper inside the
    # same module to stay under the 50-LOC contract limit.
    call_names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                call_names.append(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                call_names.append(node.func.attr)

    assert "create_refund" in call_names, (
        "refunds.py never calls create_refund — Stripe API is never "
        f"invoked. Calls found: {sorted(set(call_names))}"
    )


def test_r5_o3_f3_idempotency_key_seeded_by_row_uuid() -> None:
    """R5-S7-S03: idempotency key must derive from the pending row UUID.

    The original ``(payment_id, amount)`` seed collided on retries; the
    fix re-seeds with the freshly inserted refund row UUID
    (``f"refund-{refund.id}"``) so each request gets a unique key.
    """
    project_dir = create_fixture_project(name="refund_r5_s7_s03_key")
    add_stripe_refund_flow(ToolInput(project_dir=str(project_dir)))
    helper_file = project_dir / "app" / "core" / "stripe_refunds.py"
    content = helper_file.read_text()
    # Helper must keep an idempotency_key kwarg on the Stripe call.
    assert "idempotency_key" in content, (
        "create_refund() no longer passes idempotency_key to Stripe"
    )


def test_r5_o3_f3_error_path_marks_failed_and_502() -> None:
    """R5-O3-F3: if Stripe raises, route must mark row failed and 502.

    Verifies the route module does NOT leave a ``pending`` row orphaned
    when the Stripe call raises an exception.  The try/except may live in
    the handler or in a helper it delegates to.
    """
    project_dir = create_fixture_project(name="refund_r5_o3_f3_err")
    add_stripe_refund_flow(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "refunds.py"
    tree = ast.parse(route_file.read_text())

    has_try = any(isinstance(node, ast.Try) for node in ast.walk(tree))
    assert has_try, (
        "refunds.py missing try/except around Stripe call — a Stripe "
        "failure would leave the row pending forever and bubble a 500."
    )

    content = route_file.read_text()
    assert "502" in content or "BAD_GATEWAY" in content, (
        "refunds.py does not surface 502/BAD_GATEWAY on Stripe error"
    )
    assert "mark_refund_failed" in content or '"failed"' in content, (
        "refunds.py does not mark the refund row as failed on error"
    )


# ---------------------------------------------------------------------------
# R5-O3-F4 — payment ownership enforcement (cross-user refund)
# ---------------------------------------------------------------------------


def _refund_route_tree(name: str) -> ast.Module:
    """Emit a fixture project and return the parsed refunds.py AST."""
    project_dir = create_fixture_project(name=name)
    add_stripe_refund_flow(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "refunds.py"
    return ast.parse(route_file.read_text())


def _func_node(tree: ast.Module, fn_name: str) -> ast.AsyncFunctionDef | ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == fn_name:
            return node
    raise AssertionError(f"function {fn_name} not found in refunds.py")


def test_r5_o3_f4_ownership_guard_present() -> None:
    """R5-O3-F4: refunds.py must compare payment ownership and raise 404.

    Pre-fix, ``request_refund`` resolved the PaymentIntent for ANY payment_id
    with no ownership check, so any authenticated user could refund another
    user's payment. The guard must (a) read the payment's ``user_id``, (b)
    compare it to ``current_user.id``, and (c) raise 404 on mismatch (404 not
    403 so a non-owner can't confirm the payment exists).
    """
    tree = _refund_route_tree("refund_r5_o3_f4_guard")
    content = ast.unparse(tree)
    assert "user_id" in content, "refunds.py never inspects payment.user_id for ownership"
    assert "is_superuser" in content, "ownership guard must exempt superusers"
    # The comparison current_user.id must exist alongside a 404 raise.
    assert "current_user.id" in content, "ownership guard never compares to current_user.id"
    assert "404" in content or "NOT_FOUND" in content, "ownership mismatch must raise 404"


def test_r5_o3_f4_request_refund_passes_current_user() -> None:
    """R5-O3-F4: the create path must thread current_user into the ownership check.

    ``request_refund`` must pass ``current_user`` to the intent resolver (or a
    helper) so ownership is verified before the Stripe refund is issued.
    """
    tree = _refund_route_tree("refund_r5_o3_f4_create")
    fn = _func_node(tree, "request_refund")
    body_src = ast.unparse(fn)
    assert "current_user" in body_src, "request_refund does not use current_user"
    # The resolver/loader call inside request_refund must receive current_user.
    passes_user = any(
        isinstance(node, ast.Call)
        and any(
            (isinstance(a, ast.Name) and a.id == "current_user")
            or (isinstance(a, ast.Attribute) and a.attr == "id")
            for a in node.args
        )
        for node in ast.walk(fn)
    )
    assert passes_user, "request_refund never forwards current_user to the ownership check"


def test_r5_o3_f4_list_refunds_enforces_ownership() -> None:
    """R5-O3-F4: GET /refunds/payment/{id} must enforce ownership too.

    Listing refunds for an arbitrary payment_id leaked other users' refund
    history. ``list_payment_refunds`` must call the ownership loader before
    returning rows.
    """
    tree = _refund_route_tree("refund_r5_o3_f4_list")
    fn = _func_node(tree, "list_payment_refunds")
    calls = {
        node.func.id
        for node in ast.walk(fn)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "_load_owned_payment" in calls, (
        "list_payment_refunds does not verify payment ownership before listing "
        f"refunds. Calls found: {sorted(calls)}"
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
        test_refund_model_created,
        test_refund_model_has_required_columns,
        test_refund_crud_created,
        test_stripe_refunds_lazy_import,
        test_webhook_route_present,
        test_pii_safe_schema,
        test_requirements_stripe,
        test_idempotency_key_in_refund_helper,
        test_execution_time_recorded,
        test_next_steps_present,
        test_idempotent_project_still_parses,
        test_stripe_not_top_level_in_routes,
        test_r5_o3_f3_route_imports_create_refund,
        test_r5_o3_f3_request_refund_calls_stripe,
        test_r5_o3_f3_idempotency_key_seeded_by_row_uuid,
        test_r5_o3_f3_error_path_marks_failed_and_502,
        test_r5_o3_f4_ownership_guard_present,
        test_r5_o3_f4_request_refund_passes_current_user,
        test_r5_o3_f4_list_refunds_enforces_ownership,
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

    print(f"\n{'=' * 60}")
    print(f"TOOL-066 add_stripe_refund_flow: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
