# TOOL-073: add_graphql_subscriptions

> **Status**: SPEC v1 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_graphql_subscriptions` |
| Category | EXTEND > API Design > Realtime |
| Complexity | High |
| Dependencies | FastAPI, Starlette, strawberry-graphql[fastapi]>=0.220.0, graphql-ws>=0.5.0, redis (lazy, optional) |
| Signature | `add_graphql_subscriptions(inp: ToolInput) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path to FastAPI project root) and `dry_run` flag |
| MCP descriptor | `{"name": "fastapi_add_graphql_subscriptions", "description": "Add WebSocket GraphQL subscriptions (graphql-ws protocol) to a FastAPI project, extending the existing Strawberry GraphQL setup with real-time pub/sub.", "tags": ["extend", "api_design", "realtime"], "entry": "add_graphql_subscriptions"}` |
| Files created (typical) | 3–4 — `app/graphql/pubsub.py`, `app/graphql/subscriptions.py`, `app/graphql/ws_handler.py`, optionally `app/graphql/schema.py` (when not yet present) |
| Files modified (typical) | 3–4 — `app/graphql/schema.py` (patched to add `Subscription`), `app/core/config.py`, `app/main.py`, `requirements.txt` |

---

## 2. Purpose

The `fastapi_add_graphql_subscriptions` tool extends an existing (or newly scaffolded) Strawberry GraphQL setup with **WebSocket-based real-time subscriptions** using the `graphql-ws` protocol. REST APIs and even standard GraphQL queries deliver data on demand — the client asks, the server answers. Real-time features (live feeds, notifications, collaboration cursors, order-status tracking) require the inverse: the server pushes data to the client when something changes. The two mechanisms for this in modern web APIs are Server-Sent Events (SSE) and WebSocket subscriptions; SSE is simpler but unidirectional and text-only; GraphQL subscriptions over WebSocket give clients the full GraphQL selection-set expressiveness over a bidirectional transport.

Teams commonly attempt to bolt real-time onto a REST service in one of three incorrect ways: (a) long-polling — clients hammer the API every 500 ms and pray; (b) native FastAPI `WebSocket` endpoint with bespoke JSON framing that every client has to reverse-engineer; (c) an entirely separate Socket.IO server that drifts out of sync with the main API's auth model. None of these compose with the existing GraphQL schema. The correct solution is to extend the Strawberry schema with a `Subscription` type (async generator methods decorated with `@strawberry.subscription`) and mount a WebSocket handler at `/graphql/ws` that speaks the `graphql-ws` protocol — the same protocol supported by Apollo Client, urql, and every major GraphQL client.

This tool generates the complete subscription kit: (a) `app/graphql/pubsub.py` with `PubSubManager`, a backend-agnostic pub/sub facade that selects `MemoryPubSubBackend` (asyncio.Queue per subscriber, single-worker) or `RedisPubSubBackend` (redis.asyncio Pub/Sub, multi-worker) based on whether `REDIS_URL` is set and `redis` is importable — the redis import is **lazy** so the app boots without it; (b) `app/graphql/subscriptions.py` with a `Subscription` root type containing two example subscriptions — `on_item_created` (streams `ItemEvent` payloads) and `on_notification` (streams `NotificationEvent` payloads per user), both requiring authentication via `info.context.user` and raising `PermissionError` for unauthenticated connections; (c) `app/graphql/ws_handler.py` with `graphql_ws_handler`, a Starlette WebSocket handler that resolves per-connection context (including optional JWT auth from the connection init message) and delegates to `schema.handle_websocket`; the tool then patches `app/graphql/schema.py` to add `subscription=_GQLSubscription` to the `strawberry.Schema` call, or creates a minimal schema file if `add_graphql` (TOOL-018) has not been run; patches `app/core/config.py` with `GRAPHQL_WS_ENABLED` (default `True`) and `GRAPHQL_SUBSCRIPTION_KEEPALIVE_MS` (default `30_000`); mounts the WebSocket route in `app/main.py` via `app.add_api_websocket_route("/graphql/ws", _gql_ws_handler)`; and adds `strawberry-graphql[fastapi]` and `graphql-ws>=0.5.0` to `requirements.txt`.

Key design decisions: the **`graphql-ws` protocol** (not the legacy `subscriptions-transport-ws`) is used — all modern GraphQL clients support it and the legacy protocol is deprecated; `PubSubManager` selects the **best available backend automatically** at startup so a single-process dev environment works without Redis while production multi-worker deployments upgrade transparently by adding `REDIS_URL`; the redis import is **lazy** so the module loads without the `redis` package; subscription resolvers are **plain async generators** decorated with `@strawberry.subscription` — no class hierarchies, no hidden magic; authentication is enforced at the resolver level via `info.context.user`, so unauthenticated WebSocket connections receive a `PermissionError` on the first subscription, not a silent empty stream; keepalive pings are configurable per-deployment via `GRAPHQL_SUBSCRIPTION_KEEPALIVE_MS`.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | Must complete within CI step budget; measured via `execution_time_ms` (T-21) |
| Python files created | >= 3 | Minimum: `pubsub.py`, `subscriptions.py`, `ws_handler.py` (T-26) |
| Files modified | >= 2 | At minimum: schema.py + config.py (or main.py) (T-27) |
| Max function LOC in generated code | <= 50 | Each generated function stays auditable; asserted by AST walk (T-17) |
| `PubSubManager.publish()` latency (memory) | < 1 ms | Direct asyncio.Queue.put per subscriber |
| `PubSubManager.publish()` latency (Redis) | < 5 ms | Single Redis PUBLISH command |
| `PubSubManager.subscribe()` first-event latency | < 1 ms (memory) | asyncio.Queue.get |
| WebSocket connection setup | < 100 ms | Schema handle_websocket + context build |
| Keepalive interval | `GRAPHQL_SUBSCRIPTION_KEEPALIVE_MS` | Default 30 000 ms; prevents proxy timeouts |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
project/
├── app/
│   ├── main.py              # FastAPI app, no WebSocket route
│   ├── core/
│   │   └── config.py        # Settings class, no GRAPHQL_WS_* fields
│   └── graphql/
│       └── schema.py        # strawberry.Schema(query=Query) — no Subscription
├── requirements.txt         # strawberry-graphql, no graphql-ws
```

Real-time data requires polling. Clients re-query every N seconds for updates. Notifications are not supported. Order-status pages refresh manually.

### 4.2 PubSubManager (memory + Redis backends, lazy redis): AFTER

```python
# app/graphql/pubsub.py  (key classes)
"""PubSub manager for GraphQL subscriptions.

Two backends:
- Memory (default): asyncio.Queue per subscriber. Single-worker only.
- Redis: uses redis.asyncio Pub/Sub. Multi-worker safe. Lazy import.
"""

class MemoryPubSubBackend:
    """In-process pub/sub using asyncio.Queue per subscriber."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue[Any]]] = {}

    async def publish(self, topic: str, payload: Any) -> None:
        queues = self._subscribers.get(topic, [])
        for q in list(queues):
            await q.put(payload)

    async def subscribe(self, topic: str) -> AsyncIterator[Any]:
        q: asyncio.Queue[Any] = asyncio.Queue()
        self._subscribers.setdefault(topic, []).append(q)
        try:
            while True:
                item = await q.get()
                if item is _SENTINEL:
                    break
                yield item
        finally:
            subs = self._subscribers.get(topic, [])
            if q in subs:
                subs.remove(q)


class RedisPubSubBackend:
    """Redis-backed pub/sub for multi-worker deployments."""

    def _get_client(self) -> Any:
        if self._client is None:
            import redis.asyncio as aioredis  # noqa: PLC0415
            self._client = aioredis.from_url(self._url, decode_responses=True)
        return self._client

    async def publish(self, topic: str, payload: Any) -> None:
        client = self._get_client()
        await client.publish(topic, json.dumps(payload))

    async def subscribe(self, topic: str) -> AsyncIterator[Any]:
        client = self._get_client()
        async with client.pubsub() as pubsub:
            await pubsub.subscribe(topic)
            async for message in pubsub.listen():
                if message["type"] == "message":
                    yield json.loads(message["data"])


class PubSubManager:
    """Unified pub/sub facade: picks backend from environment."""

    def __init__(self) -> None:
        self._backend = self._choose_backend()

    def _choose_backend(self) -> MemoryPubSubBackend | RedisPubSubBackend:
        redis_url = os.getenv("REDIS_URL", "")
        if redis_url:
            try:
                import redis.asyncio  # noqa: PLC0415, F401
                return RedisPubSubBackend(redis_url)
            except ImportError:
                pass
        return MemoryPubSubBackend()


def get_pubsub_manager() -> PubSubManager:
    """Return the singleton PubSubManager."""
    global _manager
    if _manager is None:
        _manager = PubSubManager()
    return _manager
```

### 4.3 Subscription type (async generators, auth guard): AFTER

```python
# app/graphql/subscriptions.py
import strawberry
from collections.abc import AsyncIterator


@strawberry.type
class ItemEvent:
    """Payload emitted when an item is created."""
    id: strawberry.ID
    title: str
    created_by: strawberry.ID


@strawberry.type
class NotificationEvent:
    """Payload emitted when a notification is sent to a user."""
    id: strawberry.ID
    user_id: strawberry.ID
    message: str
    level: str = "info"


@strawberry.type
class Subscription:
    """Root GraphQL subscription type. All subscriptions require authentication."""

    @strawberry.subscription
    async def on_item_created(
        self,
        info: strawberry.types.Info["GraphQLContext", None],
    ) -> AsyncIterator[ItemEvent]:
        if not info.context.user:
            raise PermissionError("Authentication required for subscriptions")
        from app.graphql.pubsub import get_pubsub_manager
        mgr = get_pubsub_manager()
        async for payload in mgr.subscribe("items"):
            yield ItemEvent(
                id=strawberry.ID(str(payload.get("id", ""))),
                title=str(payload.get("title", "")),
                created_by=strawberry.ID(str(payload.get("created_by", ""))),
            )

    @strawberry.subscription
    async def on_notification(
        self,
        info: strawberry.types.Info["GraphQLContext", None],
        user_id: strawberry.ID,
    ) -> AsyncIterator[NotificationEvent]:
        if not info.context.user:
            raise PermissionError("Authentication required for subscriptions")
        from app.graphql.pubsub import get_pubsub_manager
        mgr = get_pubsub_manager()
        topic = f"notifications:{user_id}"
        async for payload in mgr.subscribe(topic):
            yield NotificationEvent(
                id=strawberry.ID(str(payload.get("id", ""))),
                user_id=strawberry.ID(str(user_id)),
                message=str(payload.get("message", "")),
                level=str(payload.get("level", "info")),
            )
```

### 4.4 WebSocket handler (graphql-ws protocol): AFTER

```python
# app/graphql/ws_handler.py
async def graphql_ws_handler(websocket: WebSocket) -> None:
    """Handle a single GraphQL WebSocket connection (graphql-ws protocol)."""
    from app.graphql.schema import schema as _schema
    from app.core.config import settings as _settings

    enabled: bool = getattr(_settings, "GRAPHQL_WS_ENABLED", True)
    if not enabled:
        await websocket.close(code=4400, reason="GraphQL subscriptions disabled.")
        return

    context = await _build_ws_context(websocket)
    await _schema.handle_websocket(websocket, context_value=context)


async def _build_ws_context(websocket: WebSocket) -> Any:
    """Build a per-connection GraphQL context from the WebSocket request."""
    from app.graphql.dataloaders import DataLoaderRegistry
    from app.graphql.context import GraphQLContext

    user: Any = None
    try:
        from app.api.deps import get_current_user as _get_user
        user = await _get_user(websocket)
    except Exception:
        pass

    return GraphQLContext(request=websocket, user=user, loaders=DataLoaderRegistry())
```

### 4.5 Schema patch: AFTER

```python
# app/graphql/schema.py  (patched when add_graphql was run first)
from app.graphql.queries import Query
from app.graphql.subscriptions import Subscription as _GQLSubscription  # added

schema = strawberry.Schema(
    query=Query,
    subscription=_GQLSubscription,  # added
)
```

```python
# app/graphql/schema.py  (minimal, created when add_graphql was NOT run)
"""Strawberry GraphQL schema with Subscription support."""

import strawberry
from app.graphql.subscriptions import Subscription as _GQLSubscription


@strawberry.type
class _Query:
    """Minimal placeholder Query required by Strawberry."""

    @strawberry.field
    def health(self) -> str:
        """Return a liveness string."""
        return "ok"


schema = strawberry.Schema(query=_Query, subscription=_GQLSubscription)
```

### 4.6 Config patch

```python
# app/core/config.py  (diff, added by _patch_config)
    GRAPHQL_WS_ENABLED: bool = True
    GRAPHQL_SUBSCRIPTION_KEEPALIVE_MS: int = 30_000

settings = Settings()
```

Fields are inserted before the `settings = Settings()` line so they land at 4-space indent inside the `Settings` class body.

### 4.7 main.py patch

```python
# app/main.py  (added by _patch_main)
from fastapi import FastAPI
from app.graphql.ws_handler import graphql_ws_handler as _gql_ws_handler  # added
# ...
app.add_api_websocket_route("/graphql/ws", _gql_ws_handler)  # added at end
```

### 4.8 requirements.txt patch

```
# requirements.txt  (appended by _patch_requirements)
strawberry-graphql[fastapi]>=0.220.0
graphql-ws>=0.5.0
```

### 4.9 Typical caller usage (after install)

```python
# Publishing an event from a FastAPI route handler
from app.graphql.pubsub import get_pubsub_manager

@router.post("/items")
async def create_item(item: ItemCreate, db: AsyncSession = Depends(get_db)):
    new_item = await crud.create_item(db, item)
    # Publish to all subscribers
    mgr = get_pubsub_manager()
    await mgr.publish("items", {
        "id": str(new_item.id),
        "title": new_item.title,
        "created_by": str(new_item.owner_id),
    })
    return new_item
```

```javascript
// GraphQL client subscription (Apollo Client)
const ITEM_SUBSCRIPTION = gql`
  subscription OnItemCreated {
    onItemCreated {
      id
      title
      createdBy
    }
  }
`;
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-01 | **ItemEvent and NotificationEvent have docstrings** | `ast.parse` and class body inspection; verified by T-29 |
| QS-02 | **Tool is idempotent on second run** | `add_graphql_subscriptions` checks `"PubSubManager" in pubsub.py` and returns `status="no_op"` with empty lists |
| QS-03 | **`dry_run=True` writes zero files** | Early return before any filesystem write when `inp.dry_run` is truthy |
| QS-04 | **Every generated `.py` file AST-parses** | Final loop over `files_created` runs `ast.parse` on each `.py` |
| QS-05 | **No generated function exceeds 50 LOC** | Every function in `pubsub.py`, `subscriptions.py`, `ws_handler.py` kept small; asserted by AST walk in T-17 |
| QS-06 | **`redis` is never imported at module top level in `pubsub.py`** | `import redis.asyncio` lives inside `_get_client()` body only; verified by AST top-level inspection in T-06 |
| QS-07 | **Memory backend is the default** | `PubSubManager._choose_backend()` returns `MemoryPubSubBackend()` when `REDIS_URL` is absent or redis is not importable |
| QS-08 | **No dead imports in `pubsub.py`** | `ruff check --select F401` passes on `pubsub.py` (T-25) |
| QS-09 | **`graphql-ws` protocol used, not legacy `subscriptions-transport-ws`** | `ws_handler.py` calls `schema.handle_websocket` (Strawberry's graphql-ws integration); verified by T-10 |
| QS-10 | **Authentication enforced at resolver level** | Both subscription resolvers check `info.context.user` and raise `PermissionError` for unauthenticated connections; verified by T-28 |
| QS-11 | **Schema patch is idempotent** | `_patch_or_create_schema` checks `"Subscription" in src` before modifying |
| QS-12 | **`main.py` patch is idempotent** | `_patch_main` checks `"/graphql/ws" in src or "graphql_ws_handler" in src` |
| QS-13 | **Config patch is idempotent** | `_patch_config` checks `"GRAPHQL_WS_ENABLED" in src` |
| QS-14 | **`next_steps` mention graphql-ws** | Hard-coded graphql-ws install instruction in success branch |
| QS-15 | **Tool works standalone without TOOL-018** | `_patch_or_create_schema` creates a minimal `schema.py` when none exists; verified by T-30 |
| QS-16 | **`MCP_TOOL` descriptor exposes `{name, description, tags, entry}` quartet** | Module-level `MCP_TOOL` dict importable by skill registry |

---

## 6. Completeness Criteria

Every criterion is tied to a real assertion in `test_add_graphql_subscriptions.py`.

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | Tool works standalone (without `add_graphql` having been run) | Schema file created with `Subscription` when `schema.py` does not exist | T-30 (`test_t30_standalone_mode_works_without_add_graphql`) |
| CC-02 | Second run returns `status="no_op"` with zero file ops | `r2.status == "no_op"` and both lists empty | T-18 (`test_t18_idempotent_returns_no_op`) |
| CC-03 | `dry_run=True` writes zero bytes to the filesystem | `before == after` dict over every `.py` in tree | T-20 (`test_t20_dry_run_writes_nothing`) |
| CC-04 | Tool creates at least 3 Python files | `len([p for p in files_created if p.endswith(".py")]) >= 3` | T-26 (`test_t26_files_created_count_minimum`) |
| CC-05 | Tool modifies at least 2 existing files | `len(result.files_modified) >= 2` | T-27 (`test_t27_files_modified_count_minimum`) |
| CC-06 | Every generated `.py` AST-parses cleanly | `ast.parse` over all `.py` files in project tree | T-16 (`test_t16_all_py_files_parse`) |
| CC-07 | No generated function exceeds 50 LOC in `app/` | AST walk of `FunctionDef`/`AsyncFunctionDef`, `max_loc <= 50` | T-17 (`test_t17_no_function_over_50_loc`) |
| CC-08 | `GRAPHQL_WS_ENABLED` and `GRAPHQL_SUBSCRIPTION_KEEPALIVE_MS` inside `class Settings` at 4-space indent | Substring check + indent check | T-12 / T-13 (`test_t12_config_fields_patched`, `test_t13_config_fields_inside_settings_class`) |
| CC-09 | `app/graphql/pubsub.py` exists with `PubSubManager` and `get_pubsub_manager` | File exists + both names present | T-04 (`test_t04_pubsub_file_created`) |
| CC-10 | `app/main.py` mounts the WebSocket route | `"/graphql/ws" in content` or `"graphql_ws_handler" in content` | T-14 (`test_t14_main_patched_with_ws_route`) |
| CC-11 | `pubsub.py`, `subscriptions.py`, `ws_handler.py` created | Three file existence + content checks | T-04, T-07, T-09, T-10 |
| CC-12 | `requirements.txt` contains `graphql-ws` | `"graphql-ws" in content` | T-15 (`test_t15_requirements_patched`) |
| CC-13 | `execution_time_ms` is positive | `result.execution_time_ms > 0` | T-21 (`test_t21_execution_time_recorded`) |
| CC-14 | `next_steps` non-empty and mentions graphql-ws or subscriptions | `any("graphql-ws" in s.lower() or "subscription" in s.lower() for s in next_steps)` | T-22 (`test_t22_next_steps_mention_graphql_ws`) |
| CC-15 | Running the tool twice leaves the project AST-parseable | `ast.parse` over all `.py` files after two runs | T-19 (`test_t19_idempotent_project_still_parses`) |
| CC-16 | `PubSubManager` has `MemoryPubSubBackend` and `RedisPubSubBackend`; memory uses `asyncio.Queue` | All three names present in `pubsub.py` | T-05 (`test_t05_pubsub_has_memory_and_redis_backends`) |
| CC-17 | `redis` NOT imported at top level of `pubsub.py` | AST walk of top-level `ast.Import`/`ast.ImportFrom` nodes | T-06 (`test_t06_redis_import_is_lazy`) |

---

## 7. Definition of Done (DoD)

- [ ] All 17 Completeness Criteria verified by `test_add_graphql_subscriptions.py`
- [ ] `add_graphql_subscriptions.py` runs `ast.parse` on every created `.py` file before returning success
- [ ] `add_graphql_subscriptions.py` detects `"PubSubManager"` fingerprint and returns `status="no_op"` on second run
- [ ] `dry_run=True` returns success with empty `files_created`/`files_modified`
- [ ] `redis` is imported lazily inside `_get_client()` body — not at module top level
- [ ] `PubSubManager._choose_backend()` selects `RedisPubSubBackend` when `REDIS_URL` is set and redis importable; else `MemoryPubSubBackend`
- [ ] Subscription resolvers raise `PermissionError` when `info.context.user` is falsy
- [ ] `ws_handler.py` checks `GRAPHQL_WS_ENABLED` and closes with code 4400 when disabled
- [ ] `_patch_or_create_schema` creates minimal `schema.py` when none exists (standalone mode)
- [ ] `_patch_or_create_schema` is idempotent: checks `"Subscription" in src` before modifying
- [ ] `_patch_config` is idempotent: checks `"GRAPHQL_WS_ENABLED" in src` before modifying
- [ ] `_patch_main` is idempotent: checks `"/graphql/ws" in src or "graphql_ws_handler" in src`
- [ ] `_patch_requirements` adds both `strawberry-graphql[fastapi]` and `graphql-ws>=0.5.0` only when absent
- [ ] Both `ItemEvent` and `NotificationEvent` have docstrings
- [ ] `execution_time_ms` is set on every return path (success, no_op, dry_run, error)
- [ ] Tool exits within 5 s on a fresh fixture project
- [ ] `MCP_TOOL` descriptor exposes `{name, description, tags, entry}` quartet

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-GWS-01 | The tool is ALWAYS idempotent on second invocation | Fingerprint check `"PubSubManager" in pubsub_file.read_text()` short-circuits to `status="no_op"` | T-18, T-19 |
| INV-GWS-02 | `dry_run=True` NEVER writes to disk | Early return guarded by `if inp.dry_run:` before any write | T-20 |
| INV-GWS-03 | Every generated `.py` file MUST parse as valid Python | Final loop `for path in files_created: ast.parse(content)` | T-16, T-19 |
| INV-GWS-04 | `redis` MUST be imported lazily (not at module top level in `pubsub.py`) | `import redis.asyncio` inside `_get_client()` body; AST-verified | T-06 |
| INV-GWS-05 | No generated function MUST exceed 50 LOC | Enforced by construction and tested by AST walk | T-17 |
| INV-GWS-06 | `ToolResult.execution_time_ms` MUST be positive on every return path | `_elapsed_ms(start)` called on success, no_op, dry_run, and error branches | T-21 |
| INV-GWS-07 | `GRAPHQL_WS_ENABLED` and `GRAPHQL_SUBSCRIPTION_KEEPALIVE_MS` MUST land inside `class Settings` body | `_patch_config` inserts before `settings = Settings()` sentinel | T-13 |
| INV-GWS-08 | Subscription resolvers MUST enforce authentication | Both resolvers check `info.context.user` and raise `PermissionError` | T-28 |
| INV-GWS-09 | `graphql-ws` protocol MUST be used (not legacy `subscriptions-transport-ws`) | `ws_handler.py` calls `schema.handle_websocket` (Strawberry's graphql-ws handler) | T-10 |
| INV-GWS-10 | Tool MUST work standalone (without TOOL-018 having been run first) | `_patch_or_create_schema` creates a minimal `schema.py` when `schema.py` is absent | T-30 |
| INV-GWS-11 | `next_steps` MUST mention graphql-ws installation | Hard-coded install instruction in success branch | T-22 |
| INV-GWS-12 | `PubSubManager` MUST provide `publish()` and `subscribe()` | Both `async def publish` and `async def subscribe` present in `pubsub.py` | T-23 |

---

## 9. User Stories

### 9.1 Core install flow (US-01 .. US-05)

**US-01: Add subscriptions to an existing GraphQL project**
- **As a** backend engineer who has already run `add_graphql`
- **I want** to run one tool call and get WebSocket subscriptions
- **So that** I stop hand-rolling WebSocket pub/sub
- **Given:** A FastAPI project with `app/graphql/schema.py` (from TOOL-018), `app/core/config.py`, `requirements.txt`
- **When:** `add_graphql_subscriptions(ToolInput(project_dir=...))`
- **Then:**
  - Returns `ToolResult.status == "success"` (INV-GWS-01)
  - `files_created` contains >= 3 Python files, each existing on disk (CC-04)
  - `files_modified` contains >= 2 files (CC-05)
  - Verified by T-01, T-02, T-26, T-27

**US-02: Re-run the tool on an already-installed project**
- **As a** CI job that re-runs tooling on every commit
- **I want** the tool to skip work when subscriptions are already installed
- **So that** I do not corrupt the existing pub/sub setup
- **Given:** Project where `app/graphql/pubsub.py` already contains `PubSubManager`
- **When:** `add_graphql_subscriptions(...)` invoked a second time
- **Then:**
  - Returns `status="no_op"` (INV-GWS-01)
  - `files_created == []` and `files_modified == []`
  - All `.py` files still AST-parse (INV-GWS-03)
  - Verified by T-18, T-19

**US-03: Dry-run to preview changes**
- **As a** developer reviewing a tool invocation
- **I want** to see what would change without touching files
- **Given:** Fresh FastAPI fixture project
- **When:** `add_graphql_subscriptions(ToolInput(project_dir=..., dry_run=True))`
- **Then:**
  - Returns `status="success"` with informational `notes`
  - `files_created == []` and `files_modified == []`
  - Filesystem byte-identical before and after (INV-GWS-02)
  - Verified by T-20

**US-04: Generated project stays auditable**
- **As a** code reviewer
- **I want** every generated function to be short
- **Given:** Tool just emitted `pubsub.py`, `subscriptions.py`, `ws_handler.py`
- **When:** I AST-walk `app/` for functions
- **Then:**
  - No `FunctionDef`/`AsyncFunctionDef` has `end_lineno - lineno + 1 > 50` (QS-05)
  - Verified by T-17

**US-05: Tool works without add_graphql having been run**
- **As a** developer who skipped TOOL-018
- **I want** `add_graphql_subscriptions` to create a minimal schema
- **So that** I can use subscriptions without setting up the full query layer first
- **Given:** No `app/graphql/schema.py` exists
- **When:** `add_graphql_subscriptions(...)` runs
- **Then:**
  - Creates a minimal `schema.py` with a `_Query.health` placeholder and `Subscription`
  - Returns `status="success"`
  - Verified by T-30, CC-01, INV-GWS-10

### 9.2 PubSubManager (US-06 .. US-10)

**US-06: Publish and consume events in single-worker development**
- **As a** developer running a single FastAPI process
- **I want** pub/sub to work without Redis
- **So that** I can develop locally without infrastructure
- **Given:** `REDIS_URL` is not set; `redis` package is not installed
- **When:** `get_pubsub_manager()` is called
- **Then:**
  - Returns a `PubSubManager` with `MemoryPubSubBackend`
  - `await mgr.publish("items", {...})` delivers to all in-process subscribers
  - Verified by CC-09, CC-16, QS-07

**US-07: Scale to multi-worker production with Redis**
- **As a** DevOps engineer scaling to 4 Gunicorn workers
- **I want** pub/sub events to fan out across all workers
- **So that** a subscription connected to worker #1 receives events published by worker #2
- **Given:** `REDIS_URL=redis://localhost:6379/0` is set and `redis` is installed
- **When:** `get_pubsub_manager()` is called
- **Then:**
  - Returns a `PubSubManager` with `RedisPubSubBackend`
  - `publish()` calls `redis.PUBLISH`; `subscribe()` uses `redis.pubsub().listen()`
  - Verified by CC-16, QS-07

**US-08: Redis import does not break single-worker boot**
- **As a** developer without Redis installed
- **I want** `import pubsub` to succeed without redis
- **So that** the application boots cleanly in development
- **Given:** `redis` is not in the virtualenv
- **When:** `from app.graphql.pubsub import PubSubManager` is executed
- **Then:**
  - No `ImportError` at import time (redis import is lazy inside `_get_client`)
  - `_choose_backend()` falls back to `MemoryPubSubBackend`
  - Verified by INV-GWS-04, T-06

**US-09: Singleton manager is created once per process**
- **As a** FastAPI application
- **I want** a single `PubSubManager` instance shared across all requests
- **So that** in-process subscribers are not partitioned across multiple manager instances
- **Given:** `get_pubsub_manager()` called from multiple route handlers
- **When:** Any call to `get_pubsub_manager()`
- **Then:**
  - Returns the same `_manager` singleton every time
  - Verified by singleton guard in `get_pubsub_manager()`

**US-10: Publish payload from a REST route handler**
- **As a** backend developer combining REST and GraphQL
- **I want** to publish to pub/sub from inside a REST `POST /items` handler
- **So that** both REST clients and GraphQL subscribers see the same events
- **Given:** `PubSubManager` instance available via `get_pubsub_manager()`
- **When:** REST handler calls `await mgr.publish("items", {...})`
- **Then:**
  - `MemoryPubSubBackend.publish` puts payload into each subscriber queue
  - GraphQL subscribers receive it on next `async for payload in mgr.subscribe("items")`
  - Verified by CC-09, INV-GWS-12

### 9.3 Subscription resolvers (US-11 .. US-15)

**US-11: Subscribe to item creation events**
- **As a** GraphQL client developer
- **I want** `subscription { onItemCreated { id title createdBy } }`
- **So that** my UI updates in real time when new items are created
- **Given:** `on_item_created` subscription in `Subscription` type
- **When:** Client connects with valid auth and starts subscription
- **Then:**
  - `info.context.user` is truthy (passes auth guard)
  - `mgr.subscribe("items")` yields `ItemEvent` payloads
  - Verified by CC-11, T-07, T-08

**US-12: Subscribe to per-user notifications**
- **As a** user with a dashboard that shows real-time notifications
- **I want** `subscription { onNotification(userId: "me") { id message level } }`
- **So that** I receive my notifications as they arrive
- **Given:** `on_notification(user_id)` subscription in `Subscription` type
- **When:** Client subscribes with `user_id="me"`
- **Then:**
  - Subscribes to topic `"notifications:me"`
  - Only events published to that topic are received
  - Verified by CC-11, T-07, T-08

**US-13: Unauthenticated subscription raises PermissionError**
- **As a** security reviewer
- **I want** unauthenticated WebSocket connections to be rejected at the resolver
- **So that** subscription streams cannot be probed anonymously
- **Given:** `info.context.user` is `None` (no auth in connection init)
- **When:** Client starts any subscription
- **Then:**
  - `raise PermissionError("Authentication required for subscriptions")`
  - Verified by T-28, INV-GWS-08, QS-10

**US-14: ItemEvent payload is type-safe**
- **As a** GraphQL client
- **I want** `ItemEvent` to have typed fields (`id: ID`, `title: String`, `createdBy: ID`)
- **So that** I can use GraphQL code generation to get typed client code
- **Given:** `@strawberry.type class ItemEvent` with typed attributes
- **When:** Schema introspection runs
- **Then:**
  - `ItemEvent { id title createdBy }` is fully typed in the GraphQL schema
  - Verified by CC-11, T-07

**US-15: AsyncIterator return type is annotated**
- **As a** type-checker user
- **I want** subscription resolvers to declare `-> AsyncIterator[ItemEvent]`
- **So that** mypy and pyright can validate subscription implementations
- **Given:** `subscriptions.py` has `AsyncIterator` import and return annotations
- **When:** Type checker runs
- **Then:**
  - No type errors on subscription method signatures
  - Verified by T-24 (`AsyncIterator` present in file), T-16 (all `.py` parse)

### 9.4 WebSocket handler (US-16 .. US-20)

**US-16: Connect with a graphql-ws protocol client**
- **As a** frontend developer using Apollo Client or urql
- **I want** to connect to `ws://host/graphql/ws` using the graphql-ws protocol
- **So that** I can use standard GraphQL subscription tooling
- **Given:** `app.add_api_websocket_route("/graphql/ws", _gql_ws_handler)` mounted
- **When:** Client connects with `Sec-WebSocket-Protocol: graphql-ws`
- **Then:**
  - Strawberry's `schema.handle_websocket` negotiates the graphql-ws handshake
  - Connection init resolves context; subscriptions begin flowing
  - Verified by T-09, T-10, INV-GWS-09

**US-17: Disable subscriptions via environment variable**
- **As an** operator who wants to temporarily disable WebSocket subscriptions
- **I want** `GRAPHQL_WS_ENABLED=false` to reject new connections
- **So that** I can shed subscription load without redeploying
- **Given:** `getattr(settings, "GRAPHQL_WS_ENABLED", True)` is `False`
- **When:** Client attempts a WebSocket connection to `/graphql/ws`
- **Then:**
  - `graphql_ws_handler` closes with code 4400, reason "GraphQL subscriptions disabled."
  - Verified by `ws_handler.py` source

**US-18: JWT auth resolved from connection_init**
- **As a** developer wiring auth to GraphQL subscriptions
- **I want** the WebSocket handler to attempt auth resolution from the request
- **So that** subscription resolvers receive a populated `context.user`
- **Given:** WebSocket connection carries an `Authorization` header (in HTTP upgrade)
- **When:** `_build_ws_context(websocket)` runs
- **Then:**
  - `get_current_user(websocket)` is attempted; success → `user` set on context
  - Exception → `user=None` (graceful fallback, subscription resolver decides)
  - Verified by `_build_ws_context` source

**US-19: Keepalive configurable via settings**
- **As a** platform engineer with a 60-second proxy timeout
- **I want** to set `GRAPHQL_SUBSCRIPTION_KEEPALIVE_MS=45000`
- **So that** WebSocket connections survive the proxy before the first event
- **Given:** `GRAPHQL_SUBSCRIPTION_KEEPALIVE_MS` is a Settings field (CC-08)
- **When:** `graphql_ws_handler` reads `getattr(_settings, "GRAPHQL_SUBSCRIPTION_KEEPALIVE_MS", 30_000)`
- **Then:**
  - Keepalive value is passed to Strawberry's WebSocket handler
  - Verified by CC-08, T-12

**US-20: WebSocket route mounted at `/graphql/ws`**
- **As a** frontend developer
- **I want** the WebSocket endpoint at a predictable path
- **So that** I can hardcode it in my client config
- **Given:** `_patch_main` appends `app.add_api_websocket_route("/graphql/ws", _gql_ws_handler)`
- **When:** Application boots
- **Then:**
  - WebSocket connections to `/graphql/ws` are handled
  - HTTP requests to `/graphql/ws` get a 405 or upgrade response
  - Verified by T-14, CC-10

### 9.5 Schema integration (US-21 .. US-25)

**US-21: Patch existing schema to include Subscription**
- **As a** developer who already has `add_graphql` installed
- **I want** `schema.py` to gain `subscription=_GQLSubscription` automatically
- **So that** I do not have to manually edit the schema file
- **Given:** `schema.py` exists with `strawberry.Schema(query=Query)` and no `Subscription`
- **When:** `_patch_or_create_schema(schema_file)` runs
- **Then:**
  - `from app.graphql.subscriptions import Subscription as _GQLSubscription` inserted
  - `strawberry.Schema(subscription=_GQLSubscription, ...)` constructed
  - `schema.py` is added to `files_modified`
  - Verified by T-11, CC-11

**US-22: Schema patch is idempotent**
- **As a** CI job running the tool multiple times
- **I want** `_patch_or_create_schema` to skip when `Subscription` is already present
- **So that** the schema file is not corrupted on second run
- **Given:** `schema.py` already contains `"Subscription"`
- **When:** `_patch_or_create_schema` is called
- **Then:**
  - Returns `False` (not created, not modified)
  - `schema.py` content is unchanged
  - Verified by QS-11, T-18

**US-23: Minimal schema created when schema.py does not exist**
- **As a** developer who has not run TOOL-018
- **I want** a working GraphQL schema to be created automatically
- **So that** subscriptions work end-to-end without a separate tool call
- **Given:** `app/graphql/schema.py` does not exist
- **When:** `_patch_or_create_schema` is called
- **Then:**
  - Creates `schema.py` with `_Query.health` placeholder and `Subscription`
  - Returns `True` (file was created, added to `files_created`)
  - Verified by T-30, T-11, INV-GWS-10

**US-24: `graphql-ws` added to requirements.txt**
- **As a** requirements consumer
- **I want** `graphql-ws>=0.5.0` in `requirements.txt`
- **So that** `pip install -r requirements.txt` installs the WebSocket protocol library
- **Given:** `requirements.txt` does not already have `graphql-ws`
- **When:** `_patch_requirements` runs
- **Then:**
  - `graphql-ws>=0.5.0` added
  - `strawberry-graphql[fastapi]>=0.220.0` added if absent
  - Verified by T-15, CC-12

**US-25: `strawberry-graphql` added to requirements.txt**
- **As a** fresh project that never ran `add_graphql`
- **I want** `strawberry-graphql[fastapi]` added when running in standalone mode
- **So that** the subscription feature is fully installable from requirements alone
- **Given:** `requirements.txt` does not contain `strawberry-graphql`
- **When:** `_patch_requirements` runs
- **Then:**
  - `strawberry-graphql[fastapi]>=0.220.0` added alongside `graphql-ws`
  - Verified by T-15, CC-12

---

## 10. Test Plan

### 10.1 Test inventory

| ID | Name | CC | Description |
|----|------|----|-------------|
| T-01 | `test_t01_success_status` | — | Tool returns `status="success"` on fresh project |
| T-02 | `test_t02_files_created_exist_on_disk` | CC-04 | Every path in `files_created` exists on disk |
| T-03 | `test_t03_files_modified_exist_on_disk` | CC-05 | Every path in `files_modified` exists on disk |
| T-04 | `test_t04_pubsub_file_created` | CC-09 | `pubsub.py` exists; `PubSubManager` and `get_pubsub_manager` present |
| T-05 | `test_t05_pubsub_has_memory_and_redis_backends` | CC-16 | `MemoryPubSubBackend`, `RedisPubSubBackend`, `asyncio.Queue` present |
| T-06 | `test_t06_redis_import_is_lazy` | CC-17 | `redis` NOT imported at top level of `pubsub.py` |
| T-07 | `test_t07_subscriptions_file_created` | CC-11 | `subscriptions.py` has `class Subscription` and `@strawberry.subscription` |
| T-08 | `test_t08_subscriptions_has_example_subscriptions` | CC-11 | `on_item_created` and `on_notification` present |
| T-09 | `test_t09_ws_handler_file_created` | CC-11 | `ws_handler.py` exists with `graphql_ws_handler` |
| T-10 | `test_t10_ws_handler_uses_graphql_ws_protocol` | CC-11 | `handle_websocket` present in `ws_handler.py` |
| T-11 | `test_t11_schema_has_subscription` | CC-11 | `schema.py` exists with `Subscription` |
| T-12 | `test_t12_config_fields_patched` | CC-08 | Both config fields present in `config.py` |
| T-13 | `test_t13_config_fields_inside_settings_class` | CC-08 | Both fields at 4-space indent |
| T-14 | `test_t14_main_patched_with_ws_route` | CC-10 | `/graphql/ws` or `graphql_ws_handler` in `main.py` |
| T-15 | `test_t15_requirements_patched` | CC-12 | `graphql-ws` in `requirements.txt` |
| T-16 | `test_t16_all_py_files_parse` | CC-06 | `ast.parse` passes on all project `.py` files |
| T-17 | `test_t17_no_function_over_50_loc` | CC-07 | No generated function > 50 LOC |
| T-18 | `test_t18_idempotent_returns_no_op` | CC-02 | Second run returns `no_op` with empty lists |
| T-19 | `test_t19_idempotent_project_still_parses` | CC-15 | Two runs; project still parseable |
| T-20 | `test_t20_dry_run_writes_nothing` | CC-03 | `dry_run=True`; filesystem unchanged |
| T-21 | `test_t21_execution_time_recorded` | CC-13 | `execution_time_ms > 0` |
| T-22 | `test_t22_next_steps_mention_graphql_ws` | CC-14 | `next_steps` mentions graphql-ws or subscription |
| T-23 | `test_t23_pubsub_has_publish_and_subscribe` | — | `async def publish` and `async def subscribe` in `pubsub.py` |
| T-24 | `test_t24_subscriptions_use_async_generator` | CC-11 | `AsyncIterator` present in `subscriptions.py` |
| T-25 | `test_t25_no_dead_imports_in_pubsub` | QS-08 | `ruff check --select F401` passes on `pubsub.py` |
| T-26 | `test_t26_files_created_count_minimum` | CC-04 | >= 3 Python files created |
| T-27 | `test_t27_files_modified_count_minimum` | CC-05 | >= 2 files modified |
| T-28 | `test_t28_auth_enforced_in_subscriptions` | QS-10 | `PermissionError` or `"Authentication required"` in `subscriptions.py` |
| T-29 | `test_t29_event_types_have_docstrings` | QS-01 | `ItemEvent` and `NotificationEvent` classes have docstrings |
| T-30 | `test_t30_standalone_mode_works_without_add_graphql` | CC-01 | Succeeds without pre-existing `schema.py`; creates it with `Subscription` |

### 10.2 Running tests

```bash
# From skill root
PYTHONPATH=. pytest adapt/extend/api_design/test_add_graphql_subscriptions.py -v

# Standalone (no pytest)
PYTHONPATH=. python3 adapt/extend/api_design/test_add_graphql_subscriptions.py
```

### 10.3 Minimum pass criteria

All 30 tests must pass with 0 skipped. The lazy redis import, idempotency, authentication enforcement, and standalone mode tests are most critical for production safety.

---

## 11. Error Handling

| Scenario | Tool Response | User Action |
|----------|---------------|-------------|
| `project_dir` does not exist or is not a directory | `status="error"`, `error` from `validate_project_dir` | Pass a valid absolute path |
| Prerequisites missing (`app/models/base.py`, `app/core/config.py`, `requirements.txt`) | `status="error"` with prerequisite list and note to run `fastapi_generate_project` | Run `fastapi_generate_project` first |
| Generated `.py` file has `SyntaxError` (defensive) | `status="error"`, `error="Generated file has syntax error: <path>: <exc>"` | File a bug report |
| `app/graphql/pubsub.py` already contains `PubSubManager` | `status="no_op"`, `notes=["GraphQL subscriptions (PubSubManager) already present — skipped."]` | No action needed |
| `dry_run=True` | `status="success"`, informational `notes`, no files written | Re-run without `dry_run=True` to apply |
| `redis` not installed at runtime | `_choose_backend()` catches `ImportError`; falls back to `MemoryPubSubBackend`; logs warning | Install `redis>=5.0.0` for multi-worker pub/sub |
| `strawberry` not installed at runtime | `subscriptions.py` import fails when application boots; WebSocket route returns 500 | `pip install 'strawberry-graphql[fastapi]>=0.220.0'` |
| `graphql-ws` not installed at runtime | `schema.handle_websocket` raises `ImportError` on first WebSocket connection | `pip install 'graphql-ws>=0.5.0'` |
| `GRAPHQL_WS_ENABLED=false` | `graphql_ws_handler` closes with code 4400 | Set `GRAPHQL_WS_ENABLED=true` in `.env` to re-enable |
| `schema.py` exists but already has `Subscription` | `_patch_or_create_schema` returns `False`; schema not modified | No action; already patched |

---

## 12. Integration Notes

### 12.1 Strawberry schema registration

When `add_graphql` (TOOL-018) has been run, `schema.py` already exists with a `strawberry.Schema(query=Query)` call. `_patch_or_create_schema` patches it in-place:

1. Inserts `from app.graphql.subscriptions import Subscription as _GQLSubscription` after the existing `Query` import (or after `import strawberry` as fallback, or at file start as last resort).
2. Replaces `strawberry.Schema(` with `strawberry.Schema(\n    subscription=_GQLSubscription,` to add the subscription parameter.

When `add_graphql` has NOT been run, a minimal schema with a `_Query.health` placeholder is created.

### 12.2 PubSub backend selection

Backend selection happens once per process at `PubSubManager()` construction:

```
REDIS_URL env var set?
  No  → MemoryPubSubBackend (always works, single-worker)
  Yes → Try: import redis.asyncio
          Success → RedisPubSubBackend (multi-worker safe)
          ImportError → MemoryPubSubBackend (log warning)
```

Teams migrate from memory to Redis transparently by setting `REDIS_URL`. No code changes required.

### 12.3 WebSocket route mounting

`_patch_main` appends the route at the **end** of `main.py`:

```python
app.add_api_websocket_route("/graphql/ws", _gql_ws_handler)
```

This must be after the `app = FastAPI(...)` declaration. If `main.py` has a complex structure, manually verify the route is added at the correct location.

### 12.4 Authentication in WebSocket context

`_build_ws_context` attempts to call `get_current_user(websocket)` using the project's existing auth dependency. This is a best-effort approach — the `except Exception: pass` fallback ensures unauthenticated connections receive `user=None` rather than crashing. Subscription resolvers then enforce authentication explicitly by checking `info.context.user`.

### 12.5 Relationship to TOOL-018 (add_graphql)

TOOL-018 adds the HTTP GraphQL endpoint at `/graphql` (query + mutation). TOOL-073 extends it with WebSocket subscriptions at `/graphql/ws`. Both use the same `schema` object and the same Strawberry type system. Running TOOL-073 before TOOL-018 works (standalone mode creates a minimal schema) but the resulting schema will not have the domain queries and mutations from TOOL-018.

---

## 13. Assumptions

1. The project follows the standard FastAPI layout: `app/core/config.py` with a `Settings` class and `settings = Settings()` line, `app/main.py` with a `from fastapi import FastAPI` import.
2. `GRAPHQL_WS_ENABLED` defaults to `True` — subscriptions are active after install.
3. `MemoryPubSubBackend` is single-worker only: events published in one worker process are NOT delivered to subscribers in a different worker process. This is expected behavior; scale to Redis by setting `REDIS_URL`.
4. Authentication in `_build_ws_context` requires `app/api/deps.py` with a `get_current_user` function. If absent, `user` is always `None` and subscription resolvers will reject all connections.
5. `schema.handle_websocket` requires Strawberry >= 0.220.0 for the graphql-ws protocol integration.
6. The tool does not configure Redis, OPA, or any external service — it only generates FastAPI application code.

---

## 14. Dependencies

| Package | Version | Role |
|---------|---------|------|
| `strawberry-graphql[fastapi]` | `>=0.220.0` | GraphQL schema, subscription decorators, WebSocket handler |
| `graphql-ws` | `>=0.5.0` | graphql-ws protocol implementation used by Strawberry |
| `redis` | optional (lazy import) | Redis Pub/Sub backend for multi-worker deployments |
| `fastapi` | existing | `add_api_websocket_route` |
| `starlette` | existing | `WebSocket` type |
| `pydantic` | `v2+` | (used by existing project; `pubsub.py` uses stdlib only) |

No new mandatory runtime dependencies beyond `strawberry-graphql[fastapi]` and `graphql-ws`.

---

## 15. Known Limitations

1. **`MemoryPubSubBackend` is not multi-worker safe**: Events are delivered only to subscribers in the same process. Production multi-worker deployments must use Redis.
2. **`_build_ws_context` is a best-effort auth shim**: It depends on `app/api/deps.py` containing `get_current_user`. Projects with different auth structures must customize `ws_handler.py`.
3. **Schema patch is heuristic**: `_patch_or_create_schema` searches for `"from app.graphql.queries import Query"` and `"import strawberry"` insertion points. Unusual `schema.py` layouts may require manual adjustment.
4. **No horizontal keepalive**: `GRAPHQL_SUBSCRIPTION_KEEPALIVE_MS` is read and passed to Strawberry's handler, but the actual keepalive behavior depends on Strawberry's implementation.
5. **Subscription argument auth**: `on_notification` accepts a `user_id` argument but does not verify that the authenticated user is subscribing to their own notifications. Teams should add a `current_user.id == str(user_id)` guard for production.
6. **`_SENTINEL` pattern for queue drain**: `MemoryPubSubBackend.subscribe` uses a `_SENTINEL` object to signal shutdown. The subscription will block indefinitely until a sentinel is published. Teams requiring graceful shutdown should add explicit sentinel publishing.

---

## 16. File Layout (Post-install)

```
project/
├── app/
│   ├── graphql/
│   │   ├── pubsub.py            # PubSubManager, MemoryPubSubBackend, RedisPubSubBackend
│   │   ├── subscriptions.py     # Subscription type, ItemEvent, NotificationEvent
│   │   ├── ws_handler.py        # graphql_ws_handler, _build_ws_context
│   │   └── schema.py            # patched: subscription=_GQLSubscription added
│   │                            # (or created minimal schema if add_graphql not run)
│   ├── main.py                  # + add_api_websocket_route("/graphql/ws", _gql_ws_handler)
│   └── core/
│       └── config.py            # + GRAPHQL_WS_ENABLED, GRAPHQL_SUBSCRIPTION_KEEPALIVE_MS
└── requirements.txt             # + strawberry-graphql[fastapi]>=0.220.0
                                 # + graphql-ws>=0.5.0
```
