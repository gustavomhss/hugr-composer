"""TOOL-017: add_websocket_chat — add WebSocket chat to a FastAPI project.

Writes WebSocketManager (Redis pub/sub fan-out), /ws/chat/{room_id} endpoint
with JWT auth, ChatRoom/ChatMessage models, schemas, CRUD, HTTP routes, and an
Alembic migration.  Fan-out is ALWAYS through Redis.  JWT verified before any
DB write; 1008 on auth failure; per-user connection cap via Redis counter;
per-room rate-limiting via Redis INCR/EXPIRE.  Idempotent.

Warnings:
    WebSocket fan-out is fire-and-forget; a disconnected peer silently misses
    messages.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.migration_helper import find_migration_head

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_realtime_add_websocket_chat",
    "description": (
        "Add production-grade WebSocket chat with JWT auth, Redis pub/sub, "
        "rooms, and message history."
    ),
    "tags": ["extend", "realtime"],
    "entry": "add_websocket_chat",
}


def add_websocket_chat(
    inp: ToolInput,
    *,
    max_connections_per_user: int = 5,
    message_max_length: int = 4000,
    rate_limit_per_minute: int = 30,
) -> ToolResult:
    """Add WebSocket chat support to a FastAPI project.

    Args:
        inp: ``ToolInput`` with ``project_dir`` and optional ``dry_run``.
        max_connections_per_user: Max simultaneous WS sockets per user (default 5).
        message_max_length: Hard cap on ``ChatMessageIn.content`` (default 4000).
        rate_limit_per_minute: Per-user max messages/min per room (default 30).

    Returns:
        ``ToolResult`` with status, files_created, files_modified, notes, next_steps.

    Warnings:
        WebSocket fan-out does not guarantee delivery — Redis pub/sub is
        fire-and-forget; a disconnected peer silently misses messages.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_ms(start))

    from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.BASE_MODEL,
        Prereq.MODELS_INIT,
        Prereq.CONFIG_SETTINGS,
        Prereq.ROUTES_INIT,
        Prereq.ALEMBIC_VERSIONS,
        Prereq.REQUIREMENTS_TXT,
        auto_scaffold=not inp.dry_run,
    )
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=["Generate a base project first: fastapi_generate_project(...)"],
            execution_time_ms=_ms(start),
        )

    files_created: list[str] = list(scaffolded or [])
    app_dir = project / "app"
    chat_ws_file = app_dir / "ws" / "chat.py"
    if chat_ws_file.exists() and "WebSocketManager" in chat_ws_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["WebSocketManager already present."],
            execution_time_ms=_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create WebSocketManager, endpoint, models, CRUD, migration.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_ms(start),
        )

    files_modified: list[str] = []
    subs_chat = {
        "rate_limit_per_minute": str(rate_limit_per_minute),
        "message_max_length": str(message_max_length),
    }
    subs_mgr = {"max_connections_per_user": str(max_connections_per_user)}
    subs_schema = {"message_max_length": str(message_max_length)}

    # Step 1 – models
    chat_model_file = app_dir / "models" / "chat.py"
    chat_model_file.parent.mkdir(parents=True, exist_ok=True)
    render_to(_HERE, "chat_models_no_tenant.py.tmpl", dest=chat_model_file, substitutions={})
    files_created.append(str(chat_model_file))
    models_init = app_dir / "models" / "__init__.py"
    if models_init.exists():
        _patch_models_init(models_init, [("chat", "ChatRoom"), ("chat", "ChatMessage")])
        files_modified.append(str(models_init))

    # Step 2 – schemas
    schema_file = app_dir / "schemas" / "chat.py"
    schema_file.parent.mkdir(parents=True, exist_ok=True)
    render_to(_HERE, "chat_schemas.py.tmpl", dest=schema_file, substitutions=subs_schema)
    files_created.append(str(schema_file))

    # Step 3 – CRUD
    crud_file = app_dir / "crud" / "chat.py"
    crud_file.parent.mkdir(parents=True, exist_ok=True)
    render_to(_HERE, "chat_crud.py.tmpl", dest=crud_file, substitutions={})
    files_created.append(str(crud_file))

    # Step 4 – ws package (manager + endpoint)
    ws_dir = app_dir / "ws"
    ws_dir.mkdir(parents=True, exist_ok=True)
    ws_init = ws_dir / "__init__.py"
    if not ws_init.exists():
        ws_init.write_text('"""WebSocket sub-package."""\n')
        files_created.append(str(ws_init))
    manager_file = ws_dir / "connection_manager.py"
    render_to(_HERE, "connection_manager.py.tmpl", dest=manager_file, substitutions=subs_mgr)
    files_created.append(str(manager_file))
    render_to(_HERE, "chat_endpoint.py.tmpl", dest=chat_ws_file, substitutions=subs_chat)
    files_created.append(str(chat_ws_file))

    # Step 5 – HTTP companion routes
    http_route_file = app_dir / "api" / "routes" / "chat.py"
    http_route_file.parent.mkdir(parents=True, exist_ok=True)
    render_to(_HERE, "chat_http_routes.py.tmpl", dest=http_route_file, substitutions={})
    files_created.append(str(http_route_file))

    # Step 6 – Alembic migration
    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        down_rev = find_migration_head(versions_dir) or "0001_initial"
        mig_file = versions_dir / "0017_add_websocket_chat.py"
        render_to(
            _HERE, "chat_migration.py.tmpl", dest=mig_file, substitutions={"down_rev": down_rev}
        )
        files_created.append(str(mig_file))

    # Step 7 – patch config
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(
            config_file, max_connections_per_user, message_max_length, rate_limit_per_minute
        )
        files_modified.append(str(config_file))

    # Step 8 – register HTTP chat router
    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_routes_init(
            routes_init,
            "from app.api.routes.chat import router as chat_router",
            "api_router.include_router(chat_router)",
        )
        files_modified.append(str(routes_init))

    # Step 9 – mount WS chat router in app/main.py
    main_file = app_dir / "main.py"
    if main_file.exists() and _patch_main(main_file):
        files_modified.append(str(main_file))

    # Step 10 – ensure app/core/redis.py exists
    redis_module = app_dir / "core" / "redis.py"
    if not redis_module.exists():
        render_to(_HERE, "redis_module.py.tmpl", dest=redis_module, substitutions={})
        files_created.append(str(redis_module))

    # Step 11 – add redis to requirements.txt
    req_file = project / "requirements.txt"
    if req_file.exists():
        src = req_file.read_text()
        if "redis" not in src:
            req_file.write_text(src.rstrip("\n") + "\nredis[hiredis]>=5.0.0\n")
        files_modified.append(str(req_file))

    _emit_project_test(project, files_created)
    _validate_generated(files_created, start)

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "WebSocket chat added: manager, endpoint, models, schemas, CRUD.",
            "WS /ws/chat/{room_id}?token=<JWT> — Redis fan-out, multi-worker safe.",
            f"Cap: {max_connections_per_user}.  Rate: {rate_limit_per_minute}/min.  "
            f"Max len: {message_max_length}.",
        ],
        next_steps=[
            "alembic upgrade head",
            "Set REDIS_URL in .env.",
            "Restart the app; connect: ws://<host>/ws/chat/<room_id>?token=<JWT>",
        ],
        execution_time_ms=_ms(start),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_generated(files_created: list[str], start: float) -> None:
    for path_str in files_created:
        p = Path(path_str)
        if p.suffix == ".py" and p.is_absolute() and p.is_file():
            try:
                ast.parse(p.read_text())
            except SyntaxError as exc:
                raise SyntaxError(f"Generated file {p} has syntax error: {exc}") from exc


def _emit_project_test(project: Path, created: list[str]) -> None:
    tests_dir = project / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    emitted = tests_dir / "test_add_websocket_chat_emitted.py"
    if not emitted.exists():
        render_to(_HERE, "test_add_websocket_chat_emitted.py.tmpl", dest=emitted, substitutions={})
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


def _patch_config(config_file: Path, max_conn: int, max_len: int, rate: int) -> None:
    src = config_file.read_text()
    if "WEBSOCKET_CHAT_MAX_CONNECTIONS_PER_USER" in src:
        return
    block = (
        "    # --- WebSocket chat settings ---\n"
        f"    WEBSOCKET_CHAT_MAX_CONNECTIONS_PER_USER: int = {max_conn}\n"
        f"    WEBSOCKET_CHAT_MESSAGE_MAX_LENGTH: int = {max_len}\n"
        f"    WEBSOCKET_CHAT_RATE_LIMIT_PER_MINUTE: int = {rate}\n"
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


def _patch_main(main_file: Path) -> bool:
    src = main_file.read_text()
    if "from app.ws.chat import router as ws_chat_router" in src:
        return False
    lines = src.splitlines()
    last_from_app = max((i for i, ln in enumerate(lines) if ln.startswith("from app.")), default=-1)
    if last_from_app == -1:
        return False
    lines.insert(last_from_app + 1, "from app.ws.chat import router as ws_chat_router")
    inc = max((i for i, ln in enumerate(lines) if "app.include_router(" in ln), default=-1)
    if inc == -1:
        inc = max((i for i, ln in enumerate(lines) if "= FastAPI(" in ln), default=-1)
    if inc == -1:
        return False
    lines.insert(inc + 1, "app.include_router(ws_chat_router)")
    main_file.write_text("\n".join(lines) + ("\n" if src.endswith("\n") else ""))
    return True


def _ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
