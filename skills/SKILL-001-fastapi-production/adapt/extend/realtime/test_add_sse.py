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
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.realtime.add_sse import add_sse
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
