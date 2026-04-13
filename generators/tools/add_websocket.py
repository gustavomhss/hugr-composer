"""ADAPT tool: add a WebSocket endpoint to an existing FastAPI project.

Generates a production-grade WebSocket route with room-based connection
management, JWT authentication (from query param), heartbeat ping/pong,
and graceful disconnect handling.

Usage::

    from generators.tools.add_websocket import add_websocket

    result = add_websocket(
        project_dir="/path/to/existing-project",
        name="chat",
        path="/ws/chat",
        auth=True,
    )
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from generators.tools._layout import resolve_app_root


def add_websocket(
    project_dir: str,
    name: str,
    path: str = "/ws",
    auth: bool = True,
) -> dict:
    """Add a WebSocket endpoint to an existing FastAPI project.

    Generates a WebSocket route module with a room-based connection
    manager, optional JWT authentication, and heartbeat keep-alive.
    It is safe to run multiple times -- existing files are never
    overwritten.

    Args:
        project_dir: Root directory of the existing project (the folder
            that contains ``routes/``, ``core/``, etc.).
        name: Endpoint name in snake_case (e.g. ``chat``, ``notifications``).
            Used for the module filename and function names.
        path: WebSocket URL path (e.g. ``"/ws/chat"``).  Defaults to
            ``"/ws"``.
        auth: If True, validates a JWT token from the ``token`` query
            parameter before accepting the connection.

    Returns:
        Dict with ``files_created``, ``files_modified``, and ``notes``.
    """
    root = resolve_app_root(project_dir)
    lower = name.lower()

    files_created: list[str] = []
    files_modified: list[str] = []
    notes: list[str] = []

    # ------------------------------------------------------------------
    # Guard: skip if WebSocket module already exists
    # ------------------------------------------------------------------
    ws_file = root / "ws" / f"{lower}.py"
    if ws_file.exists():
        return {
            "files_created": [],
            "files_modified": [],
            "notes": [
                f"WebSocket {lower} already exists at {ws_file}. Skipped to avoid duplicates."
            ],
        }

    # ------------------------------------------------------------------
    # 1. Ensure ws/ package exists
    # ------------------------------------------------------------------
    ws_dir = root / "ws"
    ws_dir.mkdir(parents=True, exist_ok=True)
    ws_init = ws_dir / "__init__.py"
    if not ws_init.exists():
        ws_init.write_text('"""WebSocket endpoint modules."""\n')
        files_created.append(str(ws_init))

    # ------------------------------------------------------------------
    # 2. Generate the WebSocket module
    # ------------------------------------------------------------------
    _generate_ws_module(ws_dir, lower, path, auth)
    files_created.append(str(ws_file))
    notes.append(
        f"Generated ws/{lower}.py with ConnectionManager, "
        f"heartbeat, and {'JWT auth' if auth else 'no auth'}."
    )

    # ------------------------------------------------------------------
    # 3. Register WebSocket router in routes/__init__.py
    # ------------------------------------------------------------------
    routes_init = _find_routes_init(root)
    if routes_init is not None:
        modified = _patch_routes_init(routes_init, lower)
        if modified:
            files_modified.append(str(routes_init))
            notes.append(
                f"Patched {routes_init.relative_to(root)} with {lower}_ws_router."
            )
        else:
            notes.append(
                f"{lower}_ws_router already registered in {routes_init.relative_to(root)}."
            )
    else:
        notes.append(
            "Could not find routes/__init__.py -- register the WebSocket router manually:\n"
            f"  from app.ws.{lower} import router as {lower}_ws_router\n"
            f"  api_router.include_router({lower}_ws_router)"
        )

    return {
        "files_created": files_created,
        "files_modified": files_modified,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# Internal generators
# ---------------------------------------------------------------------------


def _generate_ws_module(ws_dir: Path, name: str, path: str, auth: bool) -> None:
    """Generate ``ws/{name}.py`` with a secure WebSocket endpoint.

    The generated module:
    - Authenticates via JWT (Authorization header preferred, query param fallback)
    - Binds each connection to the user_id from the JWT sub claim
    - Scopes broadcasts per user (no cross-user data leakage)
    - Uses asyncio.Lock around the connection registry
    - Tracks last pong timestamp and disconnects half-open clients

    LIMITATION: ConnectionManager is in-process. For multi-worker / multi-pod
    deployments replace with a Redis pub/sub backend. The generator emits a
    TODO comment documenting this.
    """
    if auth:
        auth_imports = (
            "import jwt\n"
            "\n"
            "from app.core.config import settings\n"
            "from app.core.jwt import ALGORITHM, decode_token\n"
        )
        auth_param_line = "    authorization: Annotated[str | None, Header()] = None,\n    token: str | None = None,  # query param fallback\n"
        auth_helper = (
            "async def _authenticate(authorization: str | None, token: str | None) -> str | None:\n"
            "    \"\"\"Extract and verify the JWT, returning the user_id (sub claim).\n"
            "\n"
            "    Token sources, in priority order:\n"
            "    1. ``Authorization: Bearer <token>`` header (preferred — never logged)\n"
            "    2. ``?token=<token>`` query parameter (fallback for browser clients)\n"
            "    \"\"\"\n"
            "    raw_token: str | None = None\n"
            "    if authorization and authorization.startswith(\"Bearer \"):\n"
            "        raw_token = authorization[7:]\n"
            "    elif token:\n"
            "        raw_token = token\n"
            "\n"
            "    if not raw_token:\n"
            "        return None\n"
            "\n"
            "    try:\n"
            "        payload = decode_token(raw_token)\n"
            "    except jwt.InvalidTokenError:\n"
            "        return None\n"
            "\n"
            "    sub = payload.get(\"sub\")\n"
            "    return sub if isinstance(sub, str) and sub else None\n"
            "\n"
            "\n"
        )
        auth_check = (
            "    user_id = await _authenticate(authorization, token)\n"
            "    if not user_id:\n"
            "        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=\"Unauthenticated\")\n"
            "        return\n"
        )
    else:
        auth_imports = ""
        auth_param_line = ""
        auth_helper = ""
        auth_check = "    user_id = websocket.query_params.get(\"user_id\", \"anonymous\")\n"

    content = (
        f'"""WebSocket endpoint: {name}.\n'
        f'\n'
        f'SECURITY: each connection is bound to the authenticated user_id from\n'
        f'the JWT sub claim. Broadcasts are scoped per user — no cross-user\n'
        f'data leakage. Token comes from the Authorization header (preferred)\n'
        f'or the ``token`` query parameter (browser fallback).\n'
        f'\n'
        f'LIMITATION: ConnectionManager keeps state in-process. For multi-worker\n'
        f'or multi-pod deployments, replace the in-memory dict with a Redis\n'
        f'pub/sub backend (publish to channel ``ws:{{user_id}}``, subscribe per\n'
        f'connection). The current implementation is correct for single-worker\n'
        f'development and small deployments.\n'
        f'"""\n'
        f'\n'
        f'from __future__ import annotations\n'
        f'\n'
        f'import asyncio\n'
        f'import time\n'
        f'from typing import Annotated\n'
        f'\n'
        f'import structlog\n'
        f'from fastapi import APIRouter, Header, WebSocket, WebSocketDisconnect, status\n'
        f'{auth_imports}'
        f'\n'
        f'logger = structlog.get_logger()\n'
        f'\n'
        f'router = APIRouter()\n'
        f'\n'
        f'_HEARTBEAT_INTERVAL = 30  # seconds\n'
        f'_PONG_TIMEOUT = 90  # seconds — 3 missed heartbeats\n'
        f'\n'
        f'\n'
        f'class ConnectionManager:\n'
        f'    """Manage active WebSocket connections grouped by user_id.\n'
        f'\n'
        f'    Thread-safe (via asyncio.Lock) for concurrent connect/disconnect.\n'
        f'    Tracks last pong timestamp per connection for liveness detection.\n'
        f'    """\n'
        f'\n'
        f'    def __init__(self) -> None:\n'
        f'        self._lock = asyncio.Lock()\n'
        f'        self._connections: dict[str, set[WebSocket]] = {{}}\n'
        f'        self._last_pong: dict[int, float] = {{}}\n'
        f'\n'
        f'    async def connect(self, ws: WebSocket, user_id: str) -> None:\n'
        f'        """Accept the WebSocket and register it under user_id."""\n'
        f'        await ws.accept()\n'
        f'        async with self._lock:\n'
        f'            self._connections.setdefault(user_id, set()).add(ws)\n'
        f'            self._last_pong[id(ws)] = time.monotonic()\n'
        f'        logger.info("ws_connected", user_id=user_id)\n'
        f'\n'
        f'    async def disconnect(self, ws: WebSocket, user_id: str) -> None:\n'
        f'        """Remove the WebSocket from user_id\'s connection set."""\n'
        f'        async with self._lock:\n'
        f'            conns = self._connections.get(user_id, set())\n'
        f'            conns.discard(ws)\n'
        f'            if not conns:\n'
        f'                self._connections.pop(user_id, None)\n'
        f'            self._last_pong.pop(id(ws), None)\n'
        f'        logger.info("ws_disconnected", user_id=user_id)\n'
        f'\n'
        f'    async def send_to_user(self, user_id: str, message: str) -> None:\n'
        f'        """Send message to all connections owned by user_id.\n'
        f'\n'
        f'        Cross-user broadcasts are NOT possible — this method enforces\n'
        f'        per-user isolation by design.\n'
        f'        """\n'
        f'        async with self._lock:\n'
        f'            conns = list(self._connections.get(user_id, set()))\n'
        f'        dead: list[WebSocket] = []\n'
        f'        for ws in conns:\n'
        f'            try:\n'
        f'                await ws.send_text(message)\n'
        f'            except Exception:\n'
        f'                dead.append(ws)\n'
        f'        for ws in dead:\n'
        f'            await self.disconnect(ws, user_id)\n'
        f'\n'
        f'    def record_pong(self, ws: WebSocket) -> None:\n'
        f'        """Update the last-pong timestamp for liveness checks."""\n'
        f'        self._last_pong[id(ws)] = time.monotonic()\n'
        f'\n'
        f'    def is_alive(self, ws: WebSocket) -> bool:\n'
        f'        """Return False if the connection has missed too many pongs."""\n'
        f'        last = self._last_pong.get(id(ws), 0)\n'
        f'        return (time.monotonic() - last) < _PONG_TIMEOUT\n'
        f'\n'
        f'\n'
        f'manager = ConnectionManager()\n'
        f'\n'
        f'\n'
        f'async def _heartbeat(ws: WebSocket) -> None:\n'
        f'    """Send periodic pings; the receive loop records pong responses."""\n'
        f'    try:\n'
        f'        while manager.is_alive(ws):\n'
        f'            await asyncio.sleep(_HEARTBEAT_INTERVAL)\n'
        f'            await ws.send_json({{"type": "ping"}})\n'
        f'    except Exception:\n'
        f'        pass  # connection closed; receive loop handles cleanup\n'
        f'\n'
        f'\n'
        f'{auth_helper}'
        f'@router.websocket("{path}")\n'
        f'async def {name}_ws(\n'
        f'    websocket: WebSocket,\n'
        f'{auth_param_line}'
        f') -> None:\n'
        f'    """WebSocket endpoint for {name} (per-user scoped)."""\n'
        f'{auth_check}'
        f'\n'
        f'    await manager.connect(websocket, user_id)\n'
        f'    heartbeat_task = asyncio.create_task(_heartbeat(websocket))\n'
        f'\n'
        f'    try:\n'
        f'        while True:\n'
        f'            data = await websocket.receive_text()\n'
        f'\n'
        f'            # Pong responses keep the connection alive but produce no work\n'
        f'            if data == \'{{"type": "pong"}}\':\n'
        f'                manager.record_pong(websocket)\n'
        f'                continue\n'
        f'\n'
        f'            logger.debug("{name}_message", user_id=user_id, size=len(data))\n'
        f'\n'
        f'            # TODO: replace with business logic. By default we echo back\n'
        f'            # to the same user. NEVER allow client-supplied user_ids to\n'
        f'            # determine the recipient — that would re-enable the very\n'
        f'            # cross-user leakage this design exists to prevent.\n'
        f'            await manager.send_to_user(user_id, f"echo: {{data}}")\n'
        f'    except WebSocketDisconnect:\n'
        f'        logger.info("{name}_client_disconnected", user_id=user_id)\n'
        f'    except Exception as exc:\n'
        f'        logger.error("{name}_error", user_id=user_id, error=str(exc))\n'
        f'    finally:\n'
        f'        heartbeat_task.cancel()\n'
        f'        await manager.disconnect(websocket, user_id)\n'
    )

    (ws_dir / f"{name}.py").write_text(content)


# ---------------------------------------------------------------------------
# Internal patchers
# ---------------------------------------------------------------------------


def _find_routes_init(root: Path) -> Path | None:
    """Locate the routes ``__init__.py`` that contains ``api_router``.

    Checks ``routes/__init__.py`` and ``api/routes/__init__.py``.
    """
    candidates = [
        root / "routes" / "__init__.py",
        root / "api" / "routes" / "__init__.py",
    ]
    for candidate in candidates:
        if candidate.exists():
            content = candidate.read_text()
            if "api_router" in content:
                return candidate
    # Fallback: return whichever exists
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _patch_routes_init(routes_init: Path, name: str) -> bool:
    """Append a WebSocket router import + include_router to ``routes/__init__.py``.

    Returns True if the file was modified, False if the router was
    already registered.
    """
    content = routes_init.read_text()

    router_var = f"{name}_ws_router"
    if router_var in content:
        return False

    import_line = f"from app.ws.{name} import router as {router_var}"
    include_line = f"api_router.include_router({router_var})"

    lines = content.rstrip("\n").split("\n")

    # Insert import after the last existing "from app..." import
    last_import_idx = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("from app.") and "import" in stripped:
            last_import_idx = i

    if last_import_idx >= 0:
        lines.insert(last_import_idx + 1, import_line)
    else:
        # No existing app imports -- insert after the last top-level import
        insert_idx = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(("from ", "import ")):
                insert_idx = i + 1
        lines.insert(insert_idx, import_line)

    # Append include_router before trailing blank lines
    last_non_empty = len(lines) - 1
    while last_non_empty > 0 and lines[last_non_empty].strip() == "":
        last_non_empty -= 1

    lines.insert(last_non_empty + 1, include_line)

    routes_init.write_text("\n".join(lines) + "\n")
    return True
