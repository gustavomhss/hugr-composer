"""Tests for TOOL-073 add_graphql_subscriptions.

Generates a real fixture project, runs the tool, and verifies all
completeness criteria: PubSubManager generated, subscriptions wired,
WebSocket handler present, schema patched, config patched,
main.py patched, idempotency, dry_run.

Run with::

    PYTHONPATH=. python3 adapt/extend/api_design/test_add_graphql_subscriptions.py
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.api_design.add_graphql_subscriptions import add_graphql_subscriptions
from tests.common.fixture_factory import create_fixture_project


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _all_py_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def _assert_parse(root: Path) -> None:
    for f in _all_py_files(root):
        src = f.read_text()
        try:
            ast.parse(src)
        except SyntaxError as exc:
            raise AssertionError(f"SyntaxError in {f}: {exc}") from exc


def _max_function_loc(root: Path) -> int:
    """Return the maximum function LOC across all .py files under root."""
    max_loc = 0
    for py in root.rglob("*.py"):
        try:
            tree = ast.parse(py.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.end_lineno:
                    loc = node.end_lineno - node.lineno + 1
                    if loc > max_loc:
                        max_loc = loc
    return max_loc


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_t01_success_status() -> None:
    """T-01: Tool returns status='success' on a fresh project."""
    project_dir = create_fixture_project(name="gws_t01")
    result = add_graphql_subscriptions(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", (
        f"Expected success, got {result.status}: {result.error}"
    )


def test_t02_files_created_exist_on_disk() -> None:
    """T-02: Every path in files_created exists on disk."""
    project_dir = create_fixture_project(name="gws_t02")
    result = add_graphql_subscriptions(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


def test_t03_files_modified_exist_on_disk() -> None:
    """T-03: Every path in files_modified exists on disk."""
    project_dir = create_fixture_project(name="gws_t03")
    result = add_graphql_subscriptions(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


def test_t04_pubsub_file_created() -> None:
    """CC-04: app/graphql/pubsub.py exists with ``get_pubsub`` factory
    (post-Rails: the facade is thin glue over the shipped PubSub motor)."""
    project_dir = create_fixture_project(name="gws_t04")
    add_graphql_subscriptions(ToolInput(project_dir=str(project_dir)))
    pubsub_file = project_dir / "app" / "graphql" / "pubsub.py"
    assert pubsub_file.exists(), "pubsub.py not created"
    content = pubsub_file.read_text()
    assert "def get_pubsub" in content
    # Must import the HuGR-shipped motor (Rails wiring)
    assert "from core.venous.events.PubSub import" in content


def test_t05_pubsub_has_memory_and_redis_backends() -> None:
    """CC-05: PubSub has memory backend (default) and Redis backend (lazy).

    Post-Rails: the memory backend is the shipped ``InMemoryPubSub`` motor
    and the Redis backend is the shipped ``RedisPubSubBackend`` adapter.
    """
    project_dir = create_fixture_project(name="gws_t05")
    add_graphql_subscriptions(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "graphql" / "pubsub.py").read_text()
    # In-memory motor reference.
    assert "InMemoryPubSub" in content
    # Redis adapter reference (lazy — inside _build()).
    assert "RedisPubSubBackend" in content
    # The motor module must actually be on disk (ensure_primitives ran).
    motor_file = (
        project_dir / "core" / "venous" / "events" / "PubSub" / "PubSub.py"
    )
    assert motor_file.exists(), "PubSub motor not shipped into project"
    adapter_file = (
        project_dir / "core" / "venous" / "_adapters" / "redis"
        / "PubSubAdapter.py"
    )
    assert adapter_file.exists(), "Redis PubSub adapter not shipped into project"


def test_t06_redis_import_is_lazy() -> None:
    """CC-17: redis must NOT be imported at module top level in pubsub.py."""
    project_dir = create_fixture_project(name="gws_t06")
    add_graphql_subscriptions(ToolInput(project_dir=str(project_dir)))
    pubsub_file = project_dir / "app" / "graphql" / "pubsub.py"
    tree = ast.parse(pubsub_file.read_text())
    for node in tree.body:  # ONLY top-level
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "redis" not in alias.name, (
                    f"redis imported at top level of pubsub.py: {alias.name}"
                )
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert "redis" not in node.module, (
                f"redis imported at top level of pubsub.py: {node.module}"
            )


def test_t07_subscriptions_file_created() -> None:
    """CC-11: app/graphql/subscriptions.py exists with Subscription type."""
    project_dir = create_fixture_project(name="gws_t07")
    add_graphql_subscriptions(ToolInput(project_dir=str(project_dir)))
    subs_file = project_dir / "app" / "graphql" / "subscriptions.py"
    assert subs_file.exists(), "subscriptions.py not created"
    content = subs_file.read_text()
    assert "class Subscription" in content
    assert "@strawberry.subscription" in content


def test_t08_subscriptions_has_example_subscriptions() -> None:
    """CC-08: Subscription type has on_item_created and on_notification."""
    project_dir = create_fixture_project(name="gws_t08")
    add_graphql_subscriptions(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "graphql" / "subscriptions.py").read_text()
    assert "on_item_created" in content
    assert "on_notification" in content


def test_t09_ws_handler_file_created() -> None:
    """CC-11: app/graphql/ws_handler.py exists with graphql_ws_handler."""
    project_dir = create_fixture_project(name="gws_t09")
    add_graphql_subscriptions(ToolInput(project_dir=str(project_dir)))
    ws_file = project_dir / "app" / "graphql" / "ws_handler.py"
    assert ws_file.exists(), "ws_handler.py not created"
    content = ws_file.read_text()
    assert "graphql_ws_handler" in content


def test_t10_ws_handler_uses_graphql_ws_protocol() -> None:
    """CC-11: ws_handler uses graphql-ws protocol (handle_websocket)."""
    project_dir = create_fixture_project(name="gws_t10")
    add_graphql_subscriptions(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "graphql" / "ws_handler.py").read_text()
    assert "handle_websocket" in content


def test_t11_schema_has_subscription() -> None:
    """CC-11: app/graphql/schema.py contains Subscription type."""
    project_dir = create_fixture_project(name="gws_t11")
    add_graphql_subscriptions(ToolInput(project_dir=str(project_dir)))
    schema_file = project_dir / "app" / "graphql" / "schema.py"
    assert schema_file.exists(), "schema.py not found"
    content = schema_file.read_text()
    assert "Subscription" in content


def test_t12_config_fields_patched() -> None:
    """CC-08: config.py contains GRAPHQL_WS_ENABLED and GRAPHQL_SUBSCRIPTION_KEEPALIVE_MS."""
    project_dir = create_fixture_project(name="gws_t12")
    add_graphql_subscriptions(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    assert "GRAPHQL_WS_ENABLED" in content
    assert "GRAPHQL_SUBSCRIPTION_KEEPALIVE_MS" in content


def test_t13_config_fields_inside_settings_class() -> None:
    """CC-08: Config fields are inside the Settings class body (4-space indent)."""
    project_dir = create_fixture_project(name="gws_t13")
    add_graphql_subscriptions(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    for field in ("GRAPHQL_WS_ENABLED", "GRAPHQL_SUBSCRIPTION_KEEPALIVE_MS"):
        for line in content.splitlines():
            if field in line and ":" in line:
                assert line.startswith("    "), (
                    f"Field {field!r} not inside Settings class body (missing 4-space indent): {line!r}"
                )
                break


def test_t14_main_patched_with_ws_route() -> None:
    """CC-10: app/main.py mounts the WebSocket route for GraphQL subscriptions."""
    project_dir = create_fixture_project(name="gws_t14")
    add_graphql_subscriptions(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "main.py").read_text()
    assert "/graphql/ws" in content or "graphql_ws_handler" in content


def test_t15_requirements_patched() -> None:
    """CC-12: requirements.txt contains graphql-ws."""
    project_dir = create_fixture_project(name="gws_t15")
    add_graphql_subscriptions(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "requirements.txt").read_text()
    assert "graphql-ws" in content


def test_t16_all_py_files_parse() -> None:
    """CC-06: All generated .py files parse without SyntaxError."""
    project_dir = create_fixture_project(name="gws_t16")
    add_graphql_subscriptions(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_t17_no_function_over_50_loc() -> None:
    """CC-07: No generated function exceeds 50 LOC."""
    project_dir = create_fixture_project(name="gws_t17")
    add_graphql_subscriptions(ToolInput(project_dir=str(project_dir)))
    app_dir = project_dir / "app"
    for py in app_dir.rglob("*.py"):
        try:
            tree = ast.parse(py.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.end_lineno:
                    loc = node.end_lineno - node.lineno + 1
                    assert loc <= 50, (
                        f"Function {node.name!r} in {py} is {loc} LOC (max 50)"
                    )


def test_t18_idempotent_returns_no_op() -> None:
    """CC-02: Running the tool twice returns no_op on the second run."""
    project_dir = create_fixture_project(name="gws_t18")
    r1 = add_graphql_subscriptions(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_graphql_subscriptions(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created
    assert not r2.files_modified


def test_t19_idempotent_project_still_parses() -> None:
    """CC-15: After two runs the project must still be fully parseable."""
    project_dir = create_fixture_project(name="gws_t19")
    add_graphql_subscriptions(ToolInput(project_dir=str(project_dir)))
    add_graphql_subscriptions(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_t20_dry_run_writes_nothing() -> None:
    """CC-03: dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="gws_t20")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_graphql_subscriptions(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_t21_execution_time_recorded() -> None:
    """CC-13: execution_time_ms must be positive after a successful run."""
    project_dir = create_fixture_project(name="gws_t21")
    result = add_graphql_subscriptions(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0


def test_t22_next_steps_mention_graphql_ws() -> None:
    """CC-14: next_steps should mention graphql-ws installation."""
    project_dir = create_fixture_project(name="gws_t22")
    result = add_graphql_subscriptions(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.next_steps) > 0
    assert any("graphql-ws" in s.lower() or "subscription" in s.lower() for s in result.next_steps)


def test_t23_pubsub_has_publish_and_subscribe() -> None:
    """CC-11: The generated pubsub.py exposes ``publish()`` and — via the
    returned motor — ``subscribe()``.

    Post-Rails the facade is thin: it re-exports ``publish`` and defers
    ``subscribe`` to the motor returned by ``get_pubsub()``. Witnessing
    both the facade shortcut AND the motor API is enough.
    """
    project_dir = create_fixture_project(name="gws_t23")
    add_graphql_subscriptions(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "graphql" / "pubsub.py").read_text()
    # Facade shortcut.
    assert "async def publish" in content
    # Motor must expose subscribe — check it on disk.
    motor = (
        project_dir / "core" / "venous" / "events" / "PubSub" / "PubSub.py"
    ).read_text()
    assert "async def subscribe" in motor
    assert "async def publish" in motor


def test_t24_subscriptions_use_async_generator() -> None:
    """CC-11: Subscription resolvers are async generators (AsyncIterator)."""
    project_dir = create_fixture_project(name="gws_t24")
    add_graphql_subscriptions(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "graphql" / "subscriptions.py").read_text()
    assert "AsyncIterator" in content


def test_t25_no_dead_imports_in_pubsub() -> None:
    """QS-08: No dead imports in pubsub.py (every import is used)."""
    project_dir = create_fixture_project(name="gws_t25")
    add_graphql_subscriptions(ToolInput(project_dir=str(project_dir)))
    pubsub_file = project_dir / "app" / "graphql" / "pubsub.py"
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--select", "F401", str(pubsub_file)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0 or "F401" not in result.stdout, (
        f"Dead imports found in pubsub.py:\n{result.stdout}"
    )


def test_t26_files_created_count_minimum() -> None:
    """CC-04: At least 3 files created (subscriptions.py, pubsub.py, ws_handler.py)."""
    project_dir = create_fixture_project(name="gws_t26")
    result = add_graphql_subscriptions(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    py_created = [p for p in result.files_created if p.endswith(".py")]
    assert len(py_created) >= 3, (
        f"Expected at least 3 Python files created, got {len(py_created)}: {py_created}"
    )


def test_t27_files_modified_count_minimum() -> None:
    """CC-05: At least 2 files modified (schema.py + config.py or main.py)."""
    project_dir = create_fixture_project(name="gws_t27")
    result = add_graphql_subscriptions(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_modified) >= 2, (
        f"Expected at least 2 modified files, got {len(result.files_modified)}: {result.files_modified}"
    )


def test_t28_auth_enforced_in_subscriptions() -> None:
    """QS: Subscriptions check authentication (PermissionError on no user)."""
    project_dir = create_fixture_project(name="gws_t28")
    add_graphql_subscriptions(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "graphql" / "subscriptions.py").read_text()
    assert "PermissionError" in content or "Authentication required" in content


def test_t29_event_types_have_docstrings() -> None:
    """QS-01: ItemEvent and NotificationEvent types have docstrings."""
    project_dir = create_fixture_project(name="gws_t29")
    add_graphql_subscriptions(ToolInput(project_dir=str(project_dir)))
    subs_file = project_dir / "app" / "graphql" / "subscriptions.py"
    tree = ast.parse(subs_file.read_text())
    classes_with_docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            if (
                node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            ):
                classes_with_docstrings.add(node.name)
    assert "ItemEvent" in classes_with_docstrings, "ItemEvent missing docstring"
    assert "NotificationEvent" in classes_with_docstrings, "NotificationEvent missing docstring"


def test_t30_standalone_mode_works_without_add_graphql() -> None:
    """CC-01: Tool works standalone (without add_graphql having been run first)."""
    project_dir = create_fixture_project(name="gws_t30")
    # Remove schema.py if it exists (as if add_graphql was never run)
    schema_file = project_dir / "app" / "graphql" / "schema.py"
    if schema_file.exists():
        schema_file.unlink()
    result = add_graphql_subscriptions(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", (
        f"Expected success in standalone mode, got {result.status}: {result.error}"
    )
    assert schema_file.exists(), "schema.py should be created in standalone mode"
    content = schema_file.read_text()
    assert "Subscription" in content


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_t01_success_status,
        test_t02_files_created_exist_on_disk,
        test_t03_files_modified_exist_on_disk,
        test_t04_pubsub_file_created,
        test_t05_pubsub_has_memory_and_redis_backends,
        test_t06_redis_import_is_lazy,
        test_t07_subscriptions_file_created,
        test_t08_subscriptions_has_example_subscriptions,
        test_t09_ws_handler_file_created,
        test_t10_ws_handler_uses_graphql_ws_protocol,
        test_t11_schema_has_subscription,
        test_t12_config_fields_patched,
        test_t13_config_fields_inside_settings_class,
        test_t14_main_patched_with_ws_route,
        test_t15_requirements_patched,
        test_t16_all_py_files_parse,
        test_t17_no_function_over_50_loc,
        test_t18_idempotent_returns_no_op,
        test_t19_idempotent_project_still_parses,
        test_t20_dry_run_writes_nothing,
        test_t21_execution_time_recorded,
        test_t22_next_steps_mention_graphql_ws,
        test_t23_pubsub_has_publish_and_subscribe,
        test_t24_subscriptions_use_async_generator,
        test_t25_no_dead_imports_in_pubsub,
        test_t26_files_created_count_minimum,
        test_t27_files_modified_count_minimum,
        test_t28_auth_enforced_in_subscriptions,
        test_t29_event_types_have_docstrings,
        test_t30_standalone_mode_works_without_add_graphql,
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
