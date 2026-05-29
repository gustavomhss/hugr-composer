"""Tests for TOOL-062 add_websocket_presence.

Generates real fixture projects via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/realtime/test_add_websocket_presence.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/realtime/test_add_websocket_presence.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.realtime.add_websocket_presence import add_websocket_presence
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
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and hasattr(node, "end_lineno")
                and node.end_lineno
            ):
                loc = node.end_lineno - node.lineno + 1
                max_loc = max(max_loc, loc)
    return max_loc


# ---------------------------------------------------------------------------
# Category A — Tool execution
# ---------------------------------------------------------------------------


def test_success_status() -> None:
    """Tool returns status='success' on a fresh project."""
    project_dir = create_fixture_project(name="wsp_t01")
    result = add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


def test_idempotent() -> None:
    """Second run returns status='no_op' without touching files."""
    project_dir = create_fixture_project(name="wsp_t02")
    r1 = add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


def test_dry_run() -> None:
    """dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="wsp_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_websocket_presence(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_files_created_count() -> None:
    """Tool creates at least 5 new files (model, schemas, manager, endpoint, routes)."""
    project_dir = create_fixture_project(name="wsp_t04")
    result = add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 5, (
        f"Expected >= 5 files_created, got {len(result.files_created)}: {result.files_created}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


def test_files_modified_count() -> None:
    """Tool modifies at least 2 files (config, models init)."""
    project_dir = create_fixture_project(name="wsp_t05")
    result = add_websocket_presence(ToolInput(project_dir=str(project_dir)))
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
    project_dir = create_fixture_project(name="wsp_t06")
    add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_no_function_over_50_loc() -> None:
    """No function in generated app/ exceeds 50 LOC."""
    project_dir = create_fixture_project(name="wsp_t07")
    add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    max_loc = _max_function_loc(project_dir, "app")
    assert max_loc <= 50, f"Found function with {max_loc} LOC (limit: 50)"


def test_config_fields_patched() -> None:
    """Expected PRESENCE_* settings fields exist inside the Settings class in config.py."""
    project_dir = create_fixture_project(name="wsp_t08")
    add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    for field in (
        "PRESENCE_HEARTBEAT_SECONDS",
        "PRESENCE_TTL_SECONDS",
        "PRESENCE_MAX_DEVICES",
    ):
        assert field in content, f"Config field {field} not found in config.py"
    # Verify fields are inside the Settings class (4-space indent)
    for line in content.splitlines():
        if "PRESENCE_HEARTBEAT_SECONDS" in line:
            assert line.startswith("    "), (
                f"PRESENCE_HEARTBEAT_SECONDS not inside class body (no 4-space indent): {line!r}"
            )
            break


def test_models_init_patched() -> None:
    """UserPresence is registered in app/models/__init__.py."""
    project_dir = create_fixture_project(name="wsp_t09")
    add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    models_init = project_dir / "app" / "models" / "__init__.py"
    content = models_init.read_text()
    assert "UserPresence" in content, "UserPresence not registered in models __init__"


def test_routes_registered() -> None:
    """Presence HTTP routes are registered in app/routes/__init__.py."""
    project_dir = create_fixture_project(name="wsp_t10")
    add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    routes_init = project_dir / "app" / "routes" / "__init__.py"
    if routes_init.exists():
        content = routes_init.read_text()
        assert "presence" in content.lower(), "Presence router not registered in routes __init__"


# ---------------------------------------------------------------------------
# Category C — Domain-specific
# ---------------------------------------------------------------------------


def test_presence_manager_file_created() -> None:
    """app/ws/presence.py exists with PresenceManager."""
    project_dir = create_fixture_project(name="wsp_t11")
    add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    ws_file = project_dir / "app" / "ws" / "presence.py"
    assert ws_file.exists(), "app/ws/presence.py not created"
    content = ws_file.read_text()
    assert "PresenceManager" in content


def test_presence_endpoint_file_created() -> None:
    """app/ws/presence_endpoint.py exists with websocket route."""
    project_dir = create_fixture_project(name="wsp_t12")
    add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    endpoint_file = project_dir / "app" / "ws" / "presence_endpoint.py"
    assert endpoint_file.exists(), "app/ws/presence_endpoint.py not created"
    content = endpoint_file.read_text()
    assert "websocket" in content.lower() or "WebSocket" in content


def test_presence_model_created() -> None:
    """app/models/presence.py exists with UserPresence class."""
    project_dir = create_fixture_project(name="wsp_t13")
    add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    model_file = project_dir / "app" / "models" / "presence.py"
    assert model_file.exists(), "app/models/presence.py not created"
    content = model_file.read_text()
    assert "UserPresence" in content, "UserPresence model not found"


def test_presence_schemas_created() -> None:
    """app/schemas/presence.py exists with PresenceUpdate and PresenceList."""
    project_dir = create_fixture_project(name="wsp_t14")
    add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    schema_file = project_dir / "app" / "schemas" / "presence.py"
    assert schema_file.exists(), "app/schemas/presence.py not created"
    content = schema_file.read_text()
    assert "PresenceUpdate" in content, "PresenceUpdate schema not found"
    assert "PresenceList" in content, "PresenceList schema not found"


def test_presence_http_routes_created() -> None:
    """app/api/routes/presence.py exists with REST routes."""
    project_dir = create_fixture_project(name="wsp_t15")
    add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "presence.py"
    assert route_file.exists(), "app/api/routes/presence.py not created"
    content = route_file.read_text()
    assert "online" in content.lower(), "Presence routes must have /online endpoint"


def test_presence_manager_has_redis_pub_sub() -> None:
    """PresenceManager uses Redis pub/sub for broadcasting events."""
    project_dir = create_fixture_project(name="wsp_t16")
    add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    ws_file = project_dir / "app" / "ws" / "presence.py"
    content = ws_file.read_text()
    assert "publish" in content, "PresenceManager must use Redis publish for events"


def test_presence_manager_has_ttl() -> None:
    """PresenceManager sets TTL = heartbeat × 3 in Redis."""
    project_dir = create_fixture_project(name="wsp_t17")
    add_websocket_presence(ToolInput(project_dir=str(project_dir), dry_run=False))
    ws_file = project_dir / "app" / "ws" / "presence.py"
    content = ws_file.read_text()
    # Default heartbeat=30, TTL=90
    assert "90" in content, "Default TTL (30s × 3 = 90s) not found in presence manager"


def test_heartbeat_ping_pong() -> None:
    """Presence endpoint handles ping/pong heartbeat messages."""
    project_dir = create_fixture_project(name="wsp_t18")
    add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    endpoint_file = project_dir / "app" / "ws" / "presence_endpoint.py"
    content = endpoint_file.read_text()
    assert "ping" in content, "Endpoint must handle ping heartbeat"
    assert "pong" in content, "Endpoint must respond with pong"


def test_multi_device_support() -> None:
    """PresenceManager tracks multiple devices per user."""
    project_dir = create_fixture_project(name="wsp_t19")
    add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    ws_file = project_dir / "app" / "ws" / "presence.py"
    content = ws_file.read_text()
    assert "device" in content.lower(), "PresenceManager must track devices"


def test_execution_time_recorded() -> None:
    """execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="wsp_t20")
    result = add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


def test_next_steps_present() -> None:
    """next_steps should mention Redis and heartbeat."""
    project_dir = create_fixture_project(name="wsp_t21")
    result = add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.next_steps) > 0, "next_steps must not be empty"
    combined = " ".join(result.next_steps).lower()
    assert "redis" in combined, "next_steps should mention Redis"


def test_idempotent_project_still_parses() -> None:
    """After two runs all .py files remain parseable."""
    project_dir = create_fixture_project(name="wsp_t22")
    add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_redis_module_created_if_absent() -> None:
    """app/core/redis.py is created when it doesn't exist."""
    project_dir = create_fixture_project(name="wsp_t23")
    # Ensure redis.py doesn't exist before the tool runs
    redis_module = project_dir / "app" / "core" / "redis.py"
    if redis_module.exists():
        redis_module.unlink()
    result = add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert redis_module.exists(), "app/core/redis.py should be created"


def test_requirements_patched() -> None:
    """requirements.txt contains redis after tool runs."""
    project_dir = create_fixture_project(name="wsp_t24")
    requirements_file = project_dir / "requirements.txt"
    # Remove redis if present to force a patch
    if requirements_file.exists():
        src = requirements_file.read_text()
        requirements_file.write_text(
            "\n".join(line for line in src.splitlines() if "redis" not in line.lower()) + "\n"
        )
    add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    content = requirements_file.read_text()
    assert "redis" in content.lower(), "redis not added to requirements.txt"


def test_custom_heartbeat_seconds() -> None:
    """Custom heartbeat_seconds=15 results in TTL=45 in the manager."""
    project_dir = create_fixture_project(name="wsp_t25")
    result = add_websocket_presence(
        ToolInput(project_dir=str(project_dir)),
        heartbeat_seconds=15,
    )
    assert result.status == "success"
    ws_file = project_dir / "app" / "ws" / "presence.py"
    content = ws_file.read_text()
    assert "45" in content, "TTL (15s × 3 = 45s) not found with custom heartbeat_seconds=15"


def test_dry_run_mentions_heartbeat_ttl() -> None:
    """dry_run notes contain heartbeat and TTL values."""
    project_dir = create_fixture_project(name="wsp_t26")
    result = add_websocket_presence(
        ToolInput(project_dir=str(project_dir), dry_run=True),
        heartbeat_seconds=20,
    )
    assert result.status == "success"
    combined = " ".join(result.notes)
    assert "20" in combined, "dry_run notes should mention heartbeat_seconds=20"
    assert "60" in combined, "dry_run notes should mention TTL (20 × 3 = 60)"


# ---------------------------------------------------------------------------
# F-006: requirements parse must be line-by-line (no raw substring)
# ---------------------------------------------------------------------------


def test_requirements_aioredis_does_not_suppress_redis_add() -> None:
    """F-006: a pre-existing ``aioredis`` line must NOT prevent the tool from
    declaring ``redis``.

    Pre-fix the patcher used ``"redis" not in src`` which falsely treated
    ``aioredis>=2.0.0`` (a different package) as proof that ``redis`` was
    declared and skipped the add. Post-fix the line-by-line parser sees
    ``aioredis`` as a distinct package and still appends ``redis[hiredis]``.
    """
    project_dir = create_fixture_project(name="wsp_f006_aioredis")
    requirements_file = project_dir / "requirements.txt"
    # Strip every redis-like line, then add aioredis only.
    src = requirements_file.read_text()
    cleaned = "\n".join(line for line in src.splitlines() if "redis" not in line.lower())
    requirements_file.write_text(cleaned + "\naioredis>=2.0.0\n")

    add_websocket_presence(ToolInput(project_dir=str(project_dir)))

    final = requirements_file.read_text()
    declared = set()
    for raw_line in final.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        # Strip extras BEFORE version specifier so ``redis[hiredis]>=5.0.0``
        # normalises to ``redis`` (the extras list contains ``[`` which is
        # an earlier separator than ``>=``).
        if "[" in line:
            line = line.split("[", 1)[0].strip()
        for sep in ("===", "==", ">=", "<=", "!=", "~=", ">", "<"):
            if sep in line:
                line = line.split(sep, 1)[0].strip()
                break
        declared.add(line.lower())
    assert "redis" in declared, (
        f"redis package not added when aioredis was already declared "
        f"(F-006 regression). Final declared: {declared}\n--- file ---\n{final}"
    )
    assert "aioredis" in declared, "aioredis must be preserved"


def test_requirements_redis_comment_does_not_suppress_add() -> None:
    """F-006: a ``# redis comment`` line must NOT suppress the redis add."""
    project_dir = create_fixture_project(name="wsp_f006_comment")
    requirements_file = project_dir / "requirements.txt"
    src = requirements_file.read_text()
    cleaned = "\n".join(line for line in src.splitlines() if "redis" not in line.lower())
    requirements_file.write_text(cleaned + "\n# redis: TODO add when caching lands\n")

    add_websocket_presence(ToolInput(project_dir=str(project_dir)))

    final = requirements_file.read_text()
    # The exact package name redis must appear as a distinct requirement.
    declared = set()
    for raw_line in final.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        # Strip extras BEFORE version specifier so ``redis[hiredis]>=5.0.0``
        # normalises to ``redis`` (the extras list contains ``[`` which is
        # an earlier separator than ``>=``).
        if "[" in line:
            line = line.split("[", 1)[0].strip()
        for sep in ("===", "==", ">=", "<=", "!=", "~=", ">", "<"):
            if sep in line:
                line = line.split(sep, 1)[0].strip()
                break
        declared.add(line.lower())
    assert "redis" in declared, (
        f"redis not added when only a comment mentioned 'redis' (F-006 regression). "
        f"declared: {declared}; file:\n{final}"
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
        test_presence_manager_file_created,
        test_presence_endpoint_file_created,
        test_presence_model_created,
        test_presence_schemas_created,
        test_presence_http_routes_created,
        test_presence_manager_has_redis_pub_sub,
        test_presence_manager_has_ttl,
        test_heartbeat_ping_pong,
        test_multi_device_support,
        test_execution_time_recorded,
        test_next_steps_present,
        test_idempotent_project_still_parses,
        test_redis_module_created_if_absent,
        test_requirements_patched,
        test_custom_heartbeat_seconds,
        test_dry_run_mentions_heartbeat_ttl,
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
    print(f"TOOL-062 add_websocket_presence: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
