"""TOOL-062: add_websocket_presence — WebSocket presence tracking for FastAPI.

Writes a Redis-backed PresenceManager, the /ws/presence WebSocket endpoint
with JWT auth + heartbeat ping/pong, UserPresence SQLAlchemy model, Pydantic
schemas, and REST companion routes.

Security: JWT verified before any Redis write; failed auth closes socket
with 1008 Policy Violation; multi-device cap enforced via Redis SCARD;
Redis TTL = heartbeat_seconds x 3 (three missed heartbeats = offline).

Idempotent: detects PresenceManager fingerprint; returns no_op if found.
Templates in ``templates/`` emit all generated source; this file orchestrates.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.tool_result import _elapsed_ms

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_realtime_add_websocket_presence",
    "description": (
        "Add production-grade WebSocket presence tracking with JWT auth, "
        "Redis pub/sub, heartbeat TTL, multi-device support, and REST companion routes."
    ),
    "tags": ["extend", "realtime"],
    "entry": "add_websocket_presence",
    "imports_primitives": [],
    "imports_adapters": [],

}


def add_websocket_presence(
    inp: ToolInput,
    *,
    heartbeat_seconds: int = 30,
    max_devices_per_user: int = 5,
) -> ToolResult:
    """Add WebSocket presence tracking to a FastAPI project.

    Args:
        inp: ``ToolInput`` with ``project_dir`` and optional ``dry_run``.
        heartbeat_seconds: Ping interval; Redis TTL = heartbeat_seconds x 3 (default 30).
        max_devices_per_user: Max simultaneous device connections per user (default 5).

    Returns:
        ``ToolResult`` with status, files_created, files_modified, notes, next_steps.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

    from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.BASE_MODEL,
        Prereq.MODELS_INIT,
        Prereq.CONFIG_SETTINGS,
        Prereq.ROUTES_INIT,
        Prereq.REQUIREMENTS_TXT,
        auto_scaffold=not inp.dry_run,
    )
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=["Generate a base project first: fastapi_generate_project(...)"],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = list(scaffolded or [])
    app_dir = project / "app"
    presence_ws_file = app_dir / "ws" / "presence.py"
    if presence_ws_file.exists() and "PresenceManager" in presence_ws_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["PresenceManager already present — skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        ttl = heartbeat_seconds * 3
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create PresenceManager, /ws/presence endpoint,",
                f"         UserPresence model, schemas, REST routes. heartbeat={heartbeat_seconds}s TTL={ttl}s.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []
    heartbeat_ttl = heartbeat_seconds * 3
    subs_mgr = {
        "heartbeat_ttl": str(heartbeat_ttl),
        "max_devices_per_user": str(max_devices_per_user),
    }
    subs_ep = {"heartbeat_seconds": str(heartbeat_seconds), "timeout": str(heartbeat_ttl)}

    # Step 1 – model
    model_file = app_dir / "models" / "presence.py"
    model_file.parent.mkdir(parents=True, exist_ok=True)
    render_to(_HERE, "presence_model.py.tmpl", dest=model_file, substitutions={})
    files_created.append(str(model_file))
    models_init = app_dir / "models" / "__init__.py"
    if models_init.exists():
        _patch_models_init(models_init, [("presence", "UserPresence")])
        files_modified.append(str(models_init))

    # Step 2 – schemas
    schema_file = app_dir / "schemas" / "presence.py"
    schema_file.parent.mkdir(parents=True, exist_ok=True)
    render_to(_HERE, "presence_schemas.py.tmpl", dest=schema_file, substitutions={})
    files_created.append(str(schema_file))

    # Step 3 – ws package (manager + endpoint)
    ws_dir = app_dir / "ws"
    ws_dir.mkdir(parents=True, exist_ok=True)
    ws_init = ws_dir / "__init__.py"
    if not ws_init.exists():
        ws_init.write_text('"""WebSocket sub-package."""\n')
        files_created.append(str(ws_init))
    render_to(_HERE, "presence_manager.py.tmpl", dest=presence_ws_file, substitutions=subs_mgr)
    files_created.append(str(presence_ws_file))
    endpoint_file = ws_dir / "presence_endpoint.py"
    render_to(_HERE, "presence_endpoint.py.tmpl", dest=endpoint_file, substitutions=subs_ep)
    files_created.append(str(endpoint_file))

    # Step 4 – REST companion routes
    http_route_file = app_dir / "api" / "routes" / "presence.py"
    http_route_file.parent.mkdir(parents=True, exist_ok=True)
    render_to(_HERE, "presence_http_routes.py.tmpl", dest=http_route_file, substitutions={})
    files_created.append(str(http_route_file))

    # Step 5 – patch config
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file, heartbeat_seconds, max_devices_per_user)
        files_modified.append(str(config_file))

    # Step 6 – register presence router
    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_routes_init(
            routes_init,
            "from app.api.routes.presence import router as presence_router",
            "api_router.include_router(presence_router)",
        )
        files_modified.append(str(routes_init))

    # Step 7 – ensure app/core/redis.py exists
    redis_module = app_dir / "core" / "redis.py"
    if not redis_module.exists():
        render_to(_HERE, "redis_module.py.tmpl", dest=redis_module, substitutions={})
        files_created.append(str(redis_module))

    # Step 8 – add redis to requirements.txt
    req_file = project / "requirements.txt"
    if req_file.exists():
        src = req_file.read_text()
        if _requirements_need_redis(src):
            req_file.write_text(src.rstrip("\n") + "\nredis[hiredis]>=5.0.0\n")
        files_modified.append(str(req_file))

    _emit_project_test(project, files_created)

    for path_str in files_created:
        p = Path(path_str)
        if p.suffix == ".py" and p.is_absolute() and p.is_file():
            try:
                ast.parse(p.read_text())
            except SyntaxError as exc:
                return ToolResult(
                    status="error",
                    error=f"Syntax error in {p}: {exc}",
                    execution_time_ms=_elapsed_ms(start),
                )

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "WebSocket presence added: manager, endpoint, model, schemas, REST routes.",
            "Endpoint: WS /ws/presence?token=<JWT>",
            f"Heartbeat: every {heartbeat_seconds}s.  TTL: {heartbeat_ttl}s.  "
            f"Max devices/user: {max_devices_per_user}.",
            "Fan-out via Redis pub/sub — multi-worker safe.",
            "REST: GET /presence/online, GET /presence/{user_id}.",
        ],
        next_steps=[
            "Set REDIS_URL in .env — presence TTL and pub/sub require Redis.",
            "Restart the app so the new presence router and WS endpoint are active.",
            "Connect: ws://<host>/ws/presence?token=<access_token>",
            f'Client must send {{"type": "ping"}} every {heartbeat_seconds}s to stay online.',
            "Poll online users at GET /presence/online.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _emit_project_test(project: Path, created: list[str]) -> None:
    tests_dir = project / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    emitted = tests_dir / "test_add_websocket_presence_emitted.py"
    if not emitted.exists():
        render_to(
            _HERE, "test_add_websocket_presence_emitted.py.tmpl", dest=emitted, substitutions={}
        )
        created.append(str(emitted))


def _patch_models_init(models_init: Path, class_imports: list[tuple[str, str]]) -> None:
    if not models_init.exists():
        return
    content = models_init.read_text()
    new_lines = [
        f"from app.models.{m} import {c}  # noqa: F401"
        for m, c in class_imports
        if f"from app.models.{m} import {c}" not in content
    ]
    if new_lines:
        models_init.write_text(content.rstrip("\n") + "\n" + "\n".join(new_lines) + "\n")


def _patch_config(config_file: Path, heartbeat_seconds: int, max_devices: int) -> None:
    src = config_file.read_text()
    if "PRESENCE_HEARTBEAT_SECONDS" in src:
        return
    ttl = heartbeat_seconds * 3
    block = (
        "    # --- Presence settings ---\n"
        f"    PRESENCE_HEARTBEAT_SECONDS: int = {heartbeat_seconds}\n"
        f"    PRESENCE_TTL_SECONDS: int = {ttl}\n"
        f"    PRESENCE_MAX_DEVICES: int = {max_devices}\n"
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


def _patch_routes_init(routes_init: Path, import_line: str, include_line: str) -> None:
    src = routes_init.read_text()
    if import_line in src:
        return
    lines = src.splitlines()
    last_app = max((i for i, ln in enumerate(lines) if ln.startswith("from app.")), default=-1)
    if last_app == -1:
        last_app = max((i for i, ln in enumerate(lines) if "APIRouter()" in ln), default=0)
    lines.insert(last_app + 1, import_line)
    last_inc = max(
        (i for i, ln in enumerate(lines) if ln.startswith("api_router.include_router")), default=-1
    )
    if last_inc == -1:
        last_inc = max((i for i, ln in enumerate(lines) if "APIRouter()" in ln), default=0)
    lines.insert(last_inc + 1, include_line)
    routes_init.write_text("\n".join(lines) + ("\n" if src.endswith("\n") else ""))


def _requirements_need_redis(src: str) -> bool:
    for line in src.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        name = line.split(";")[0].split("[")[0].split("==")[0].split(">=")[0].strip().lower()
        if name == "redis":
            return False
    return True


