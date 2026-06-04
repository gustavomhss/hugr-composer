"""Tests for TOOL-014 add_sse.

Generates a real fixture project via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the spec.

Run with::

    PYTHONPATH=. python3 adapt/extend/realtime/test_add_sse.py

or::

    PYTHONPATH=. pytest adapt/extend/realtime/test_add_sse.py -v
"""

from __future__ import annotations

import ast
import sys
import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.realtime.add_sse import add_sse
from tests.common.fixture_factory import create_fixture_project

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _all_py_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def _bare_project() -> Path:
    """A valid (existing) dir MISSING the config/requirements/routes prereqs.

    Forces the auto-scaffold and prerequisite-error code paths to run.
    """
    d = Path(tempfile.mkdtemp()) / "bare"
    d.mkdir()
    return d


def _assert_parse(root: Path) -> None:
    for f in _all_py_files(root):
        source = f.read_text()
        try:
            ast.parse(source)
        except SyntaxError as exc:
            raise AssertionError(f"SyntaxError in {f}: {exc}") from exc


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


def test_success_status() -> None:
    """T-01: Tool returns status='success' on a fresh project."""
    project_dir = create_fixture_project(name="sse_t01")
    result = add_sse(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


def test_files_created_exist() -> None:
    """T-02: Every path in files_created actually exists on disk."""
    project_dir = create_fixture_project(name="sse_t02")
    result = add_sse(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


def test_files_modified_exist() -> None:
    """T-03: Every path in files_modified actually exists on disk."""
    project_dir = create_fixture_project(name="sse_t03")
    result = add_sse(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


def test_manager_file_created() -> None:
    """CC-01: app/core/sse/manager.py exists with SSEManager."""
    project_dir = create_fixture_project(name="sse_t04")
    add_sse(ToolInput(project_dir=str(project_dir)))
    manager_file = project_dir / "app" / "core" / "sse" / "manager.py"
    assert manager_file.exists(), "manager.py not created"
    content = manager_file.read_text()
    assert "SSEManager" in content
    assert "get_sse_manager" in content


def test_publisher_file_created() -> None:
    """CC-02: app/core/sse/publisher.py exists with publish_event."""
    project_dir = create_fixture_project(name="sse_t05")
    add_sse(ToolInput(project_dir=str(project_dir)))
    publisher_file = project_dir / "app" / "core" / "sse" / "publisher.py"
    assert publisher_file.exists(), "publisher.py not created"
    content = publisher_file.read_text()
    assert "async def publish_event" in content
    assert "PUBSUB_CHANNEL" in content
    assert "REPLAY_KEY" in content


def test_access_file_created() -> None:
    """CC-03: app/core/sse/access.py exists with authorize_channel."""
    project_dir = create_fixture_project(name="sse_t06")
    add_sse(ToolInput(project_dir=str(project_dir)))
    access_file = project_dir / "app" / "core" / "sse" / "access.py"
    assert access_file.exists(), "access.py not created"
    content = access_file.read_text()
    assert "authorize_channel" in content
    assert "user:" in content
    assert "tenant:" in content
    assert "public:" in content


def test_events_route_file_created() -> None:
    """CC-04: app/api/routes/events.py exists with /events/stream."""
    project_dir = create_fixture_project(name="sse_t07")
    add_sse(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "events.py"
    assert route_file.exists(), "events.py not created"
    content = route_file.read_text()
    assert "/events" in content or "prefix" in content
    assert "stream" in content


def test_streaming_response_uses_event_stream() -> None:
    """CC-11: Route uses text/event-stream media type."""
    project_dir = create_fixture_project(name="sse_t08")
    add_sse(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "events.py"
    content = route_file.read_text()
    assert "text/event-stream" in content, "Route must use text/event-stream"


def test_response_headers_cache_control() -> None:
    """CC-12: Response headers include Cache-Control: no-cache, no-transform."""
    project_dir = create_fixture_project(name="sse_t09")
    add_sse(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "events.py"
    content = route_file.read_text()
    assert "no-cache" in content, "Cache-Control: no-cache must be set"


def test_response_headers_accel_buffering() -> None:
    """CC-13: Response headers include X-Accel-Buffering: no."""
    project_dir = create_fixture_project(name="sse_t10")
    add_sse(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "events.py"
    content = route_file.read_text()
    assert "X-Accel-Buffering" in content, "X-Accel-Buffering must be set"


def test_manager_has_heartbeat() -> None:
    """CC-14: Manager emits keepalive frames on heartbeat interval."""
    project_dir = create_fixture_project(name="sse_t11")
    add_sse(ToolInput(project_dir=str(project_dir)))
    manager_file = project_dir / "app" / "core" / "sse" / "manager.py"
    content = manager_file.read_text()
    assert "keepalive" in content, "Manager must emit keepalive frames"
    assert "_HEARTBEAT_SECONDS" in content or "heartbeat" in content.lower()


def test_manager_enforces_connection_cap() -> None:
    """CC-15: Manager uses a Redis counter to cap connections per user."""
    project_dir = create_fixture_project(name="sse_t12")
    add_sse(ToolInput(project_dir=str(project_dir)))
    manager_file = project_dir / "app" / "core" / "sse" / "manager.py"
    content = manager_file.read_text()
    assert "connection_limit_exceeded" in content
    assert "_MAX_CONNECTIONS_PER_USER" in content or "MAX_CONNECTIONS" in content


def test_publisher_uses_redis_pubsub() -> None:
    """CC-16: Publisher fans out via Redis pubsub publish call."""
    project_dir = create_fixture_project(name="sse_t13")
    add_sse(ToolInput(project_dir=str(project_dir)))
    publisher_file = project_dir / "app" / "core" / "sse" / "publisher.py"
    content = publisher_file.read_text()
    assert "publish" in content, "Publisher must call Redis publish"
    assert "pipe" in content or "pipeline" in content


def test_publisher_writes_replay_buffer() -> None:
    """CC-17: Publisher writes event to sorted-set replay buffer."""
    project_dir = create_fixture_project(name="sse_t14")
    add_sse(ToolInput(project_dir=str(project_dir)))
    publisher_file = project_dir / "app" / "core" / "sse" / "publisher.py"
    content = publisher_file.read_text()
    assert "zadd" in content, "Publisher must write to sorted set for replay"
    assert "zremrangebyrank" in content, "Publisher must bound replay buffer size"


def test_publisher_enforces_payload_size() -> None:
    """CC-18: publish_event raises on payload exceeding size limit."""
    project_dir = create_fixture_project(name="sse_t15")
    add_sse(ToolInput(project_dir=str(project_dir)))
    publisher_file = project_dir / "app" / "core" / "sse" / "publisher.py"
    content = publisher_file.read_text()
    assert "MAX_PAYLOAD_BYTES" in content
    assert "raise ValueError" in content or "ValueError" in content


def test_manager_replays_last_event_id() -> None:
    """CC-19: Manager calls _replay when last_event_id is provided."""
    project_dir = create_fixture_project(name="sse_t16")
    add_sse(ToolInput(project_dir=str(project_dir)))
    manager_file = project_dir / "app" / "core" / "sse" / "manager.py"
    content = manager_file.read_text()
    assert "last_event_id" in content
    assert "_replay" in content or "replay" in content.lower()


def test_channel_auth_rejects_cross_user() -> None:
    """CC-20: authorize_channel raises 403 for user channel cross-subscription."""
    project_dir = create_fixture_project(name="sse_t17")
    add_sse(ToolInput(project_dir=str(project_dir)))
    access_file = project_dir / "app" / "core" / "sse" / "access.py"
    content = access_file.read_text()
    assert "403" in content or "HTTP_403_FORBIDDEN" in content
    assert "user:" in content


def test_channel_auth_rejects_cross_tenant() -> None:
    """CC-21: authorize_channel raises 403 for tenant channel cross-subscription."""
    project_dir = create_fixture_project(name="sse_t18")
    add_sse(ToolInput(project_dir=str(project_dir)))
    access_file = project_dir / "app" / "core" / "sse" / "access.py"
    content = access_file.read_text()
    assert "tenant:" in content
    assert "403" in content or "HTTP_403_FORBIDDEN" in content


def test_disconnect_decrements_counter() -> None:
    """CC-22: Manager decrements connection counter on disconnect via try/finally."""
    project_dir = create_fixture_project(name="sse_t19")
    add_sse(ToolInput(project_dir=str(project_dir)))
    manager_file = project_dir / "app" / "core" / "sse" / "manager.py"
    content = manager_file.read_text()
    assert "finally" in content, "Manager must use try/finally for cleanup"
    assert "decr" in content, "Manager must decrement connection counter on disconnect"


def test_formatter_file_created() -> None:
    """CC-25: app/core/sse/formatter.py exists with format_event and format_keepalive."""
    project_dir = create_fixture_project(name="sse_t20")
    add_sse(ToolInput(project_dir=str(project_dir)))
    formatter_file = project_dir / "app" / "core" / "sse" / "formatter.py"
    assert formatter_file.exists(), "formatter.py not created"
    content = formatter_file.read_text()
    assert "format_event" in content
    assert "format_keepalive" in content
    assert "SSEEvent" in content


def test_rate_limiter_file_created() -> None:
    """Rate limiter file exists with TokenBucket and ConnectionRateLimiter."""
    project_dir = create_fixture_project(name="sse_t21")
    add_sse(ToolInput(project_dir=str(project_dir)))
    rate_file = project_dir / "app" / "core" / "sse" / "rate_limiter.py"
    assert rate_file.exists(), "rate_limiter.py not created"
    content = rate_file.read_text()
    assert "TokenBucket" in content
    assert "ConnectionRateLimiter" in content
    assert "try_acquire" in content


def test_connection_registry_file_created() -> None:
    """Connection registry file exists with ConnectionSlot and try_register."""
    project_dir = create_fixture_project(name="sse_t22")
    add_sse(ToolInput(project_dir=str(project_dir)))
    reg_file = project_dir / "app" / "core" / "sse" / "connection_registry.py"
    assert reg_file.exists(), "connection_registry.py not created"
    content = reg_file.read_text()
    assert "ConnectionSlot" in content
    assert "try_register" in content
    assert "release" in content


def test_multiline_data_split_in_formatter() -> None:
    """CC-30: format_event splits multi-line data into multiple data: lines."""
    project_dir = create_fixture_project(name="sse_t23")
    add_sse(ToolInput(project_dir=str(project_dir)))
    formatter_file = project_dir / "app" / "core" / "sse" / "formatter.py"
    content = formatter_file.read_text()
    assert "splitlines" in content or "split" in content, "Formatter must split multi-line data"


def test_all_py_files_parse() -> None:
    """CC-25: All .py files in the project parse without SyntaxError after tool runs."""
    project_dir = create_fixture_project(name="sse_t24")
    add_sse(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_idempotent_returns_no_op() -> None:
    """CC-29: Running the tool twice returns no_op on the second run."""
    project_dir = create_fixture_project(name="sse_t25")
    r1 = add_sse(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_sse(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


def test_idempotent_project_still_parses() -> None:
    """After two runs the project must still be fully parseable."""
    project_dir = create_fixture_project(name="sse_t26")
    add_sse(ToolInput(project_dir=str(project_dir)))
    add_sse(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_dry_run_writes_nothing() -> None:
    """dry_run=True must return status='success' but write no files."""
    project_dir = create_fixture_project(name="sse_t27")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_sse(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_execution_time_recorded() -> None:
    """execution_time_ms must be a positive integer after a successful run."""
    project_dir = create_fixture_project(name="sse_t28")
    result = add_sse(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


def test_next_steps_present() -> None:
    """next_steps should guide the developer after a successful run."""
    project_dir = create_fixture_project(name="sse_t29")
    result = add_sse(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.next_steps) > 0, "next_steps must not be empty on success"
    assert any("Redis" in s or "redis" in s for s in result.next_steps), (
        "Should mention Redis requirement"
    )


def test_custom_heartbeat_seconds() -> None:
    """Custom heartbeat_seconds is reflected in the manager file."""
    project_dir = create_fixture_project(name="sse_t30")
    add_sse(ToolInput(project_dir=str(project_dir)), heartbeat_seconds=30)
    manager_file = project_dir / "app" / "core" / "sse" / "manager.py"
    content = manager_file.read_text()
    assert "30" in content, "Custom heartbeat_seconds (30) should appear in manager"


# ---------------------------------------------------------------------------
# Mutation-hardening tests
# ---------------------------------------------------------------------------


def test_execution_time_within_sane_bound() -> None:
    """L298 ``_elapsed_ms`` BinOp ``-`` -> ``+``: a sum of two monotonic clocks
    yields a multi-billion-ms value while still being > 0. Bound it."""
    project_dir = create_fixture_project(name="sse_m01")
    ms = add_sse(ToolInput(project_dir=str(project_dir))).execution_time_ms
    assert 0 < ms < 60_000, f"implausible execution_time_ms={ms}"


def test_auto_scaffolds_missing_prereqs_on_real_run() -> None:
    """L83 ``auto_scaffold=not inp.dry_run`` UnaryNot: dropping ``not`` means a
    real run no longer scaffolds the missing prereqs -> error instead of
    success. A bare project (no config/requirements/routes) must still succeed.
    """
    p = _bare_project()
    r = add_sse(ToolInput(project_dir=str(p)))
    assert r.status == "success", r.error
    assert (p / "app" / "core" / "config.py").exists()
    assert (p / "requirements.txt").exists()


def test_scaffolded_files_reported_in_files_created() -> None:
    """L93 ``list(scaffolded or [])`` BoolOp ``or`` -> ``and``: ``scaffolded and
    []`` evaluates to ``[]``, silently dropping every auto-scaffolded file from
    files_created. On a bare project, config.py must be reported."""
    p = _bare_project()
    r = add_sse(ToolInput(project_dir=str(p)))
    assert r.status == "success", r.error
    assert any(c.endswith("config.py") for c in r.files_created), r.files_created


def test_missing_prereqs_dry_run_reports_error() -> None:
    """L83 (UnaryNot, dry-run side) + L88 error ``+`` concat path: with
    dry_run=True auto_scaffold is OFF, so prereqs are missing and the tool must
    return an error whose message starts with 'Prerequisites not met'."""
    p = _bare_project()
    r = add_sse(ToolInput(project_dir=str(p), dry_run=True))
    assert r.status == "error"
    assert "Prerequisites not met" in (r.error or "")


def test_sse_dir_mkdir_exist_ok() -> None:
    """L125 ``sse_dir.mkdir(..., exist_ok=True)`` BoolLiteral ``True`` ->
    ``False``: when app/core/sse already exists the tool must not crash."""
    project_dir = create_fixture_project(name="sse_m05")
    (project_dir / "app" / "core" / "sse").mkdir(parents=True, exist_ok=True)
    r = add_sse(ToolInput(project_dir=str(project_dir)))
    assert r.status == "success", r.error


def test_events_route_parent_mkdir_exist_ok() -> None:
    """L156 ``events_route_file.parent.mkdir(..., exist_ok=True)`` BoolLiteral
    ``True`` -> ``False``: app/api/routes already exists in the fixture, so a
    flip to exist_ok=False would raise FileExistsError and break the run."""
    project_dir = create_fixture_project(name="sse_m06")
    assert (project_dir / "app" / "api" / "routes").exists()
    r = add_sse(ToolInput(project_dir=str(project_dir)))
    assert r.status == "success", r.error
    assert (project_dir / "app" / "api" / "routes" / "events.py").exists()


def test_sse_init_created_when_absent() -> None:
    """L128 ``if not sse_init.exists():`` UnaryNot: dropping ``not`` skips
    writing the sub-package __init__.py on a fresh project, so it would be
    absent and missing from files_created."""
    project_dir = create_fixture_project(name="sse_m07")
    r = add_sse(ToolInput(project_dir=str(project_dir)))
    init_file = project_dir / "app" / "core" / "sse" / "__init__.py"
    assert init_file.exists(), "sse/__init__.py must be created"
    assert str(init_file) in r.files_created


def test_redis_module_created_when_absent() -> None:
    """L181 ``if not redis_module.exists():`` UnaryNot: dropping ``not`` skips
    writing app/core/redis.py on a project that lacks it."""
    project_dir = create_fixture_project(name="sse_m08")
    redis_module = project_dir / "app" / "core" / "redis.py"
    assert not redis_module.exists(), "fixture must not ship app/core/redis.py"
    r = add_sse(ToolInput(project_dir=str(project_dir)))
    assert redis_module.exists(), "redis.py must be created when absent"
    assert str(redis_module) in r.files_created


def test_redis_module_not_clobbered_when_present() -> None:
    """L181 (other direction): when app/core/redis.py already exists the tool
    must NOT overwrite it. Guards the ``not redis_module.exists()`` guard."""
    project_dir = create_fixture_project(name="sse_m09")
    redis_module = project_dir / "app" / "core" / "redis.py"
    sentinel = "# SENTINEL existing redis module\n"
    redis_module.write_text(sentinel)
    r = add_sse(ToolInput(project_dir=str(project_dir)))
    assert r.status == "success", r.error
    assert redis_module.read_text() == sentinel, "existing redis.py was clobbered"


def test_config_block_placed_after_anchor() -> None:
    """L243/L254 Compare ``in`` -> ``not in`` in _patch_config: the SSE settings
    block is appended right after the ACCESS_TOKEN_EXPIRE_MINUTES anchor. A
    flip would either skip placement or place it elsewhere."""
    project_dir = create_fixture_project(name="sse_m10")
    add_sse(ToolInput(project_dir=str(project_dir)))
    cfg = (project_dir / "app" / "core" / "config.py").read_text()
    assert "SSE_HEARTBEAT_SECONDS" in cfg, "SSE settings block missing"
    anchor = "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    assert anchor in cfg
    assert cfg.index(anchor) < cfg.index("SSE_HEARTBEAT_SECONDS"), (
        "SSE block must be placed AFTER the anchor"
    )


def test_config_patch_idempotent_no_duplicate() -> None:
    """L243 ``if 'SSE_HEARTBEAT_SECONDS' in src: return`` Compare ``in`` ->
    ``not in``: the early-return guard prevents a second patch from appending a
    duplicate block. Patch config twice and assert exactly one occurrence."""
    project_dir = create_fixture_project(name="sse_m11")
    cfg_file = project_dir / "app" / "core" / "config.py"
    from adapt.extend.realtime.add_sse import _patch_config

    _patch_config(cfg_file, 15, 10, 100, 600)
    _patch_config(cfg_file, 15, 10, 100, 600)
    cfg = cfg_file.read_text()
    assert cfg.count("SSE_HEARTBEAT_SECONDS") == 1, "duplicate SSE block emitted"


def test_config_fallback_settings_anchor() -> None:
    """L256 ``elif 'settings = Settings()' in src`` Compare ``in`` -> ``not
    in``: when the primary anchor is absent the block is placed before the
    ``settings = Settings()`` line."""
    project_dir = create_fixture_project(name="sse_m12")
    from adapt.extend.realtime.add_sse import _patch_config

    cfg_file = project_dir / "app" / "core" / "config.py"
    cfg_file.write_text("class Settings:\n    DEBUG: bool = False\n\n\nsettings = Settings()\n")
    _patch_config(cfg_file, 15, 10, 100, 600)
    cfg = cfg_file.read_text()
    assert "SSE_HEARTBEAT_SECONDS" in cfg
    assert cfg.index("SSE_HEARTBEAT_SECONDS") < cfg.index("settings = Settings()"), (
        "block must precede the settings = Settings() line"
    )


def test_routes_init_patched_with_events_router() -> None:
    """L266/L273/L283 Compare flips + L278/L288 BinOp ``+1`` in
    _patch_routes_init: the events import + include lines are inserted at the
    correct positions in app/routes/__init__.py."""
    project_dir = create_fixture_project(name="sse_m13")
    add_sse(ToolInput(project_dir=str(project_dir)))
    routes_init = project_dir / "app" / "routes" / "__init__.py"
    src = routes_init.read_text()
    assert "from app.api.routes.events import router as events_router" in src
    assert "api_router.include_router(events_router)" in src


def test_routes_init_import_after_last_app_import() -> None:
    """L273 ``if last_app_import_idx == -1`` Eq -> NotEq + L278 ``insert(idx +
    1, ...)`` Add -> Sub: the events import must come AFTER the last existing
    ``from app.`` import, not before / replacing it."""
    project_dir = create_fixture_project(name="sse_m14")
    from adapt.extend.realtime.add_sse import _patch_routes_init

    routes_init = project_dir / "app" / "routes" / "__init__.py"
    routes_init.write_text(
        "from fastapi import APIRouter\n"
        "from app.api.routes.users import router as users_router\n"
        "\n"
        "api_router = APIRouter()\n"
        "api_router.include_router(users_router)\n"
    )
    _patch_routes_init(
        routes_init,
        import_line="from app.api.routes.events import router as events_router",
        include_line="api_router.include_router(events_router)",
    )
    lines = routes_init.read_text().splitlines()
    users_imp = lines.index("from app.api.routes.users import router as users_router")
    events_imp = lines.index("from app.api.routes.events import router as events_router")
    assert events_imp == users_imp + 1, (
        "events import must be inserted right after the last app import"
    )
    # The original users import must still be intact (Add->Sub would overwrite).
    assert "from app.api.routes.users import router as users_router" in lines


def test_routes_init_include_after_last_include() -> None:
    """L283 ``if last_include_idx == -1`` Eq -> NotEq + L288 ``insert(idx + 1,
    ...)`` Add -> Sub: the include line is appended after the last existing
    ``api_router.include_router`` line, not before / replacing it."""
    project_dir = create_fixture_project(name="sse_m15")
    from adapt.extend.realtime.add_sse import _patch_routes_init

    routes_init = project_dir / "app" / "routes" / "__init__.py"
    routes_init.write_text(
        "from fastapi import APIRouter\n"
        "from app.api.routes.users import router as users_router\n"
        "\n"
        "api_router = APIRouter()\n"
        "api_router.include_router(users_router)\n"
    )
    _patch_routes_init(
        routes_init,
        import_line="from app.api.routes.events import router as events_router",
        include_line="api_router.include_router(events_router)",
    )
    lines = routes_init.read_text().splitlines()
    users_inc = lines.index("api_router.include_router(users_router)")
    events_inc = lines.index("api_router.include_router(events_router)")
    assert events_inc == users_inc + 1, (
        "events include must be inserted right after the last include"
    )
    assert "api_router.include_router(users_router)" in lines


def test_routes_init_idempotent_no_duplicate() -> None:
    """L266 ``if import_line in src: return`` Compare ``in`` -> ``not in``: the
    early-return guard prevents duplicate import/include lines on re-patch."""
    project_dir = create_fixture_project(name="sse_m16")
    from adapt.extend.realtime.add_sse import _patch_routes_init

    routes_init = project_dir / "app" / "routes" / "__init__.py"
    import_line = "from app.api.routes.events import router as events_router"
    include_line = "api_router.include_router(events_router)"
    _patch_routes_init(routes_init, import_line=import_line, include_line=include_line)
    _patch_routes_init(routes_init, import_line=import_line, include_line=include_line)
    src = routes_init.read_text()
    assert src.count(import_line) == 1, "duplicate events import emitted"
    assert src.count(include_line) == 1, "duplicate events include emitted"


def test_requirements_gets_redis_once() -> None:
    """L294 ``if 'redis' not in src`` Compare ``not in`` -> ``in``: redis is
    appended only when absent. Flip would append it when already present (or
    never when absent). Assert the requirement is present after a run on a
    fixture that lacks redis, and idempotent on re-patch."""
    project_dir = create_fixture_project(name="sse_m17")
    from adapt.extend.realtime.add_sse import _patch_requirements

    req_file = project_dir / "requirements.txt"
    req_file.write_text("fastapi>=0.110.0\nuvicorn>=0.29.0\n")
    _patch_requirements(req_file)
    src1 = req_file.read_text()
    assert "redis[hiredis]>=5.0.0" in src1, "redis must be appended when absent"
    _patch_requirements(req_file)
    src2 = req_file.read_text()
    assert src2.count("redis[hiredis]>=5.0.0") == 1, "redis appended twice"


def test_emitted_project_test_created() -> None:
    """L229 ``if emitted.exists(): return`` guard in _emit_project_test: the
    emitted test file is written once on a fresh project and tracked."""
    project_dir = create_fixture_project(name="sse_m18")
    r = add_sse(ToolInput(project_dir=str(project_dir)))
    emitted = project_dir / "tests" / "test_add_sse_emitted.py"
    assert emitted.exists(), "emitted project test must be created"
    assert str(emitted) in r.files_created


def test_config_fallback_appends_block_when_no_anchor() -> None:
    """L261 ``src.rstrip('\\n') + '\\n' + block`` BinOp ``+`` -> ``-`` (else
    branch of _patch_config): when the config has NEITHER the
    ACCESS_TOKEN_EXPIRE_MINUTES anchor NOR ``settings = Settings()``, the block
    is appended to the end via string concat. A ``+`` -> ``-`` flip makes
    ``str - str`` raise TypeError; this test would then error instead of pass."""
    from adapt.extend.realtime.add_sse import _patch_config

    d = Path(tempfile.mkdtemp())
    cfg = d / "config.py"
    cfg.write_text("class Settings:\n    DEBUG: bool = False\n")
    _patch_config(cfg, 15, 10, 100, 600)
    out = cfg.read_text()
    assert "SSE_HEARTBEAT_SECONDS: int = 15" in out, "block not appended in fallback branch"
    # Original content must be preserved at the front, block strictly after it.
    assert out.index("DEBUG: bool = False") < out.index("SSE_HEARTBEAT_SECONDS")


def test_routes_init_import_fallback_before_apirouter() -> None:
    """L275 ``if 'api_router' in line and 'APIRouter()' in line`` (import
    fallback loop, taken when there is no ``from app.`` import) and L276
    ``last_app_import_idx = idx - 1``: the events import is inserted immediately
    before the ``api_router = APIRouter()`` line.

    Fixture has NO ``from app.`` import (forces the fallback) and a trailing
    comment mentioning ``api_router`` AFTER the real line:
      * In -> NotIn: the guard never matches -> idx stays -1 -> import at top.
      * And -> Or: the trailing comment also matches -> wrong (later) insert.
      * Sub -> Add: ``idx + 1`` -> import lands AFTER the APIRouter line.
    Asserting the import sits exactly between ``from fastapi`` and the APIRouter
    line kills all three."""
    from adapt.extend.realtime.add_sse import _patch_routes_init

    d = Path(tempfile.mkdtemp())
    ri = d / "init.py"
    ri.write_text(
        "from fastapi import APIRouter\n\napi_router = APIRouter()\n\n# trailing api_router note\n"
    )
    _patch_routes_init(
        ri,
        import_line="from app.api.routes.events import router as events_router",
        include_line="api_router.include_router(events_router)",
    )
    lines = ri.read_text().splitlines()
    imp = lines.index("from app.api.routes.events import router as events_router")
    apirouter = lines.index("api_router = APIRouter()")
    fastapi_imp = lines.index("from fastapi import APIRouter")
    assert fastapi_imp < imp < apirouter, (
        f"events import must sit between fastapi import and APIRouter line: {lines}"
    )


def test_routes_init_include_fallback_after_apirouter() -> None:
    """L285 ``if 'api_router' in line and 'APIRouter()' in line`` (include
    fallback loop, taken when there is no existing ``include_router`` line): the
    include line is inserted immediately after the ``api_router = APIRouter()``
    line.

    Same fixture (no existing include; trailing ``api_router`` comment after the
    real line):
      * In -> NotIn: guard never matches -> idx -1 -> include at top.
      * And -> Or: trailing comment also matches -> include lands much later.
    Asserting the include is the very next line after APIRouter kills both."""
    from adapt.extend.realtime.add_sse import _patch_routes_init

    d = Path(tempfile.mkdtemp())
    ri = d / "init.py"
    ri.write_text(
        "from fastapi import APIRouter\n\napi_router = APIRouter()\n\n# trailing api_router note\n"
    )
    _patch_routes_init(
        ri,
        import_line="from app.api.routes.events import router as events_router",
        include_line="api_router.include_router(events_router)",
    )
    lines = ri.read_text().splitlines()
    apirouter = lines.index("api_router = APIRouter()")
    inc = lines.index("api_router.include_router(events_router)")
    assert inc == apirouter + 1, f"include must be the line immediately after APIRouter: {lines}"


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_success_status,
        test_files_created_exist,
        test_files_modified_exist,
        test_manager_file_created,
        test_publisher_file_created,
        test_access_file_created,
        test_events_route_file_created,
        test_streaming_response_uses_event_stream,
        test_response_headers_cache_control,
        test_response_headers_accel_buffering,
        test_manager_has_heartbeat,
        test_manager_enforces_connection_cap,
        test_publisher_uses_redis_pubsub,
        test_publisher_writes_replay_buffer,
        test_publisher_enforces_payload_size,
        test_manager_replays_last_event_id,
        test_channel_auth_rejects_cross_user,
        test_channel_auth_rejects_cross_tenant,
        test_disconnect_decrements_counter,
        test_formatter_file_created,
        test_rate_limiter_file_created,
        test_connection_registry_file_created,
        test_multiline_data_split_in_formatter,
        test_all_py_files_parse,
        test_idempotent_returns_no_op,
        test_idempotent_project_still_parses,
        test_dry_run_writes_nothing,
        test_execution_time_recorded,
        test_next_steps_present,
        test_custom_heartbeat_seconds,
        test_execution_time_within_sane_bound,
        test_auto_scaffolds_missing_prereqs_on_real_run,
        test_scaffolded_files_reported_in_files_created,
        test_missing_prereqs_dry_run_reports_error,
        test_sse_dir_mkdir_exist_ok,
        test_events_route_parent_mkdir_exist_ok,
        test_sse_init_created_when_absent,
        test_redis_module_created_when_absent,
        test_redis_module_not_clobbered_when_present,
        test_config_block_placed_after_anchor,
        test_config_patch_idempotent_no_duplicate,
        test_config_fallback_settings_anchor,
        test_routes_init_patched_with_events_router,
        test_routes_init_import_after_last_app_import,
        test_routes_init_include_after_last_include,
        test_routes_init_idempotent_no_duplicate,
        test_requirements_gets_redis_once,
        test_emitted_project_test_created,
        test_config_fallback_appends_block_when_no_anchor,
        test_routes_init_import_fallback_before_apirouter,
        test_routes_init_include_fallback_after_apirouter,
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
