"""TOOL-014: add_sse — add Server-Sent Events to a FastAPI/SQLAlchemy project.

Writes SSEManager (Redis fan-out), publisher, channel-access guard, SSE routes,
formatter, rate-limiter, connection registry, and settings keys.  Supports
heartbeats, per-user caps, Last-Event-ID replay, multi-line data (HTML5 spec).
Idempotent: detects SSEManager fingerprint; returns no_op if found.
Templates in ``templates/`` emit all generated source; this file orchestrates.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_realtime_add_sse",
    "description": "Add Server-Sent Events (SSE) endpoints for real-time push to browser clients.",
    "tags": ["extend", "realtime"],
    "entry": "add_sse",
}

_NOTES_SUCCESS = [
    "SSE support added: manager, publisher, access guard, routes.",
    "Subscribe: GET /api/v1/events/stream?channel=<name>.",
    "Publish: await publish_event(channel, event_name, payload).",
]
_NEXT_STEPS = [
    "Set REDIS_URL in .env (Redis required for pub/sub and replay).",
    "Restart; verify at GET /docs → /events/stream.",
]
_PREREQ_NOTES = ["Generate a base project first: fastapi_generate_project(...)"]


def add_sse(
    inp: ToolInput,
    *,
    heartbeat_seconds: int = 15,
    max_connections_per_user: int = 10,
    replay_buffer_size: int = 100,
    replay_ttl_seconds: int = 600,
) -> ToolResult:
    """Add Server-Sent Events support to a FastAPI project.

    Creates the SSE manager, publisher, channel-access guard, routes, formatter,
    rate-limiter, and connection registry.  Patches ``app/core/config.py`` and
    ``app/routes/__init__.py`` for the new settings and route registration.

    Args:
        inp: ``ToolInput`` with ``project_dir`` (absolute path) and optional
            ``dry_run`` flag.
        heartbeat_seconds: Interval between ``:keepalive`` comments (default 15).
        max_connections_per_user: Simultaneous SSE streams per user (default 10).
        replay_buffer_size: Events kept per channel for Last-Event-ID replay (default 100).
        replay_ttl_seconds: TTL of per-channel replay buffer in Redis (default 600).

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.

    Warnings:
        SSE does not back-pressure slow consumers — overflow events are dropped
        and counted.  Redis is required at runtime; set REDIS_URL in .env.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

    from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.CONFIG_SETTINGS,
        Prereq.ROUTES_INIT,
        Prereq.REQUIREMENTS_TXT,
        auto_scaffold=not inp.dry_run,
    )
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=_PREREQ_NOTES,
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = list(scaffolded or [])
    app_dir = project / "app"

    manager_file = app_dir / "core" / "sse" / "manager.py"
    if manager_file.exists() and "SSEManager" in manager_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["SSEManager already present — SSE is already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create SSE manager, publisher, access guard, routes,",
                "         formatter, rate-limiter, connection registry.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []
    subs = {
        "replay_buffer_size": str(replay_buffer_size),
        "replay_ttl_seconds": str(replay_ttl_seconds),
        "heartbeat_seconds": str(heartbeat_seconds),
        "max_connections_per_user": str(max_connections_per_user),
    }

    sse_dir = app_dir / "core" / "sse"
    sse_dir.mkdir(parents=True, exist_ok=True)

    sse_init = sse_dir / "__init__.py"
    if not sse_init.exists():
        sse_init.write_text('"""SSE sub-package."""\n')
        files_created.append(str(sse_init))

    render_to(_HERE, "formatter.py.tmpl", dest=sse_dir / "formatter.py", substitutions=subs)
    files_created.append(str(sse_dir / "formatter.py"))

    render_to(_HERE, "rate_limiter.py.tmpl", dest=sse_dir / "rate_limiter.py", substitutions={})
    files_created.append(str(sse_dir / "rate_limiter.py"))

    render_to(
        _HERE,
        "connection_registry.py.tmpl",
        dest=sse_dir / "connection_registry.py",
        substitutions={},
    )
    files_created.append(str(sse_dir / "connection_registry.py"))

    render_to(_HERE, "access.py.tmpl", dest=sse_dir / "access.py", substitutions={})
    files_created.append(str(sse_dir / "access.py"))

    render_to(_HERE, "publisher.py.tmpl", dest=sse_dir / "publisher.py", substitutions=subs)
    files_created.append(str(sse_dir / "publisher.py"))

    render_to(_HERE, "manager.py.tmpl", dest=manager_file, substitutions=subs)
    files_created.append(str(manager_file))

    events_route_file = app_dir / "api" / "routes" / "events.py"
    events_route_file.parent.mkdir(parents=True, exist_ok=True)
    render_to(_HERE, "events_route.py.tmpl", dest=events_route_file, substitutions={})
    files_created.append(str(events_route_file))

    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(
            config_file,
            heartbeat_seconds,
            max_connections_per_user,
            replay_buffer_size,
            replay_ttl_seconds,
        )
        files_modified.append(str(config_file))

    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_routes_init(
            routes_init,
            import_line="from app.api.routes.events import router as events_router",
            include_line="api_router.include_router(events_router)",
        )
        files_modified.append(str(routes_init))

    redis_module = app_dir / "core" / "redis.py"
    if not redis_module.exists():
        render_to(_HERE, "redis_module.py.tmpl", dest=redis_module, substitutions={})
        files_created.append(str(redis_module))

    requirements_file = project / "requirements.txt"
    if requirements_file.exists():
        _patch_requirements(requirements_file)
        files_modified.append(str(requirements_file))

    _emit_project_test(project, files_created)

    for path_str in files_created:
        p = Path(path_str)
        if p.suffix != ".py" or not p.is_absolute() or not p.is_file():
            continue
        try:
            ast.parse(p.read_text())
        except SyntaxError as exc:
            return ToolResult(
                status="error",
                error=f"Generated file has syntax error: {p}: {exc}",
                execution_time_ms=_elapsed_ms(start),
            )

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            *_NOTES_SUCCESS,
            f"Heartbeat: every {heartbeat_seconds}s.  "
            f"Connection cap: {max_connections_per_user}/user.",
            f"Replay buffer: {replay_buffer_size} events, TTL {replay_ttl_seconds}s.",
        ],
        next_steps=_NEXT_STEPS,
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _emit_project_test(project: Path, created: list[str]) -> None:
    tests_dir = project / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    emitted = tests_dir / "test_add_sse_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_sse_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


def _patch_config(
    config_file: Path,
    heartbeat_seconds: int,
    max_connections_per_user: int,
    replay_buffer_size: int,
    replay_ttl_seconds: int,
) -> None:
    src = config_file.read_text()
    if "SSE_HEARTBEAT_SECONDS" in src:
        return
    block = (
        "    # --- SSE (Server-Sent Events) settings — added by add_sse tool ---\n"
        f"    SSE_HEARTBEAT_SECONDS: int = {heartbeat_seconds}\n"
        f"    SSE_MAX_CONNECTIONS_PER_USER: int = {max_connections_per_user}\n"
        f"    SSE_REPLAY_BUFFER_SIZE: int = {replay_buffer_size}\n"
        f"    SSE_REPLAY_TTL_SECONDS: int = {replay_ttl_seconds}\n"
        "    SSE_MAX_PAYLOAD_BYTES: int = 65_536\n"
    )
    anchor = "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    if anchor in src:
        config_file.write_text(src.replace(anchor, anchor + "\n\n" + block))
    elif "settings = Settings()" in src:
        config_file.write_text(
            src.replace("settings = Settings()", block + "\nsettings = Settings()")
        )
    else:
        config_file.write_text(src.rstrip("\n") + "\n" + block)


def _patch_routes_init(routes_init: Path, *, import_line: str, include_line: str) -> None:
    src = routes_init.read_text()
    if import_line in src:
        return
    lines = src.splitlines()
    last_app_import_idx = -1
    for idx, line in enumerate(lines):
        if line.startswith("from app."):
            last_app_import_idx = idx
    if last_app_import_idx == -1:
        for idx, line in enumerate(lines):
            if "api_router" in line and "APIRouter()" in line:
                last_app_import_idx = idx - 1
                break
    lines.insert(last_app_import_idx + 1, import_line)
    last_include_idx = -1
    for idx, line in enumerate(lines):
        if line.startswith("api_router.include_router"):
            last_include_idx = idx
    if last_include_idx == -1:
        for idx, line in enumerate(lines):
            if "api_router" in line and "APIRouter()" in line:
                last_include_idx = idx
                break
    lines.insert(last_include_idx + 1, include_line)
    routes_init.write_text("\n".join(lines) + ("\n" if src.endswith("\n") else ""))


def _patch_requirements(requirements_file: Path) -> None:
    src = requirements_file.read_text()
    if "redis" not in src:
        requirements_file.write_text(src.rstrip("\n") + "\nredis[hiredis]>=5.0.0\n")


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
