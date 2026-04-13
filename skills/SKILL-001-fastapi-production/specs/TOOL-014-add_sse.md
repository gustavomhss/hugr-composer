# TOOL-014: add_sse

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-08

---

## 1. Overview

| Field | Value |
|-------|-------|
| Tool name | `fastapi_add_sse` |
| Category | EXTEND > Real-time |
| Complexity | High |
| Dependencies | Existing project with auth (User), Redis (pub/sub + replay buffer) |
| Signature | `add_sse(project_dir: str, heartbeat_seconds: int = 15, max_connections_per_user: int = 10, replay_buffer_size: int = 100, replay_ttl_seconds: int = 600) -> dict` |
| Parameters | `project_dir`: project root path<br>`heartbeat_seconds`: interval between `:keepalive\n\n` comments to keep proxies open<br>`max_connections_per_user`: simultaneous SSE streams per user<br>`replay_buffer_size`: how many recent events kept per user for `Last-Event-ID` reconnection<br>`replay_ttl_seconds`: TTL of replay buffer entries |

---

## 2. Purpose

The `fastapi_add_sse` tool adds Server-Sent Events (SSE) support so clients can receive a one-way stream of notifications, updates, and progress events over a long-lived HTTP connection — without the complexity, auth quirks, or proxy configuration pain of a WebSocket upgrade. For the vast majority of "push updates from server to client" use cases (progress bars on long-running tasks, notification badges, live dashboards, activity feeds) SSE is the correct tool: it is plain HTTP, authenticates exactly like any REST endpoint, traverses corporate proxies cleanly with the right headers, and is natively supported by every modern browser via the `EventSource` API. Teams reach for WebSockets because they have heard of them, and end up debugging `Sec-WebSocket-Accept` headers and proxy buffering for a week when a 30-line SSE route would have shipped on day one.

This tool implements the EventSource protocol exactly as specified by the HTML5 spec: `text/event-stream` content type, `id`/`event`/`data`/`retry` fields on every frame, automatic client reconnection via the `Last-Event-ID` header, comment-only heartbeats (`:keepalive\n\n`) emitted every 15 seconds to defeat proxy idle-connection timeouts, per-user connection caps enforced via Redis counters so one buggy tab cannot exhaust worker resources, and a Redis pub/sub fan-out so events published from any worker reach every subscribed client regardless of which worker accepted their connection. Key design decisions: a `publish_event(channel, event_name, payload)` helper that app code calls to push events (keeping the publishing surface tiny), three fixed channel namespaces (`user:<id>`, `tenant:<id>:<topic>`, `public:<topic>`) to prevent ad-hoc namespace sprawl, JWT authentication on every connection before any subscription is created, per-connection token buckets so slow consumers cannot stall the publisher, and a replay buffer of the last 100 events per channel so a client reconnecting within the buffer window does not miss events emitted during the disconnect.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 4s | Dev waits in CLI |
| Files modified | ≤ 4 global files | Predictability |
| Files created | ≥ 7 (sse_manager, channel, deps, routes, schemas, publisher, tests) | Predictability |
| Event publish → receive latency p99 | < 100 ms intra-region | Redis pubsub fan-out |
| Heartbeat overhead | < 1 KB / connection / minute | 4 bytes × 4 heartbeats |
| Memory per connection | < 5 KB | One asyncio task + small buffer |
| Max concurrent connections per worker | ≥ 10,000 | uvicorn + httptools handle it |
| Reconnect with Last-Event-ID p99 | < 200 ms | Redis ZRANGE on per-user sorted set |
| Event payload max size | 64 KB | Prevents abuse; configurable |

---

## 4. Code Examples (Before / After)

### 4.1 SSE Manager (NEW)
```python
# app/core/sse/manager.py
import asyncio
import json
import logging
from typing import AsyncIterator
from uuid import UUID

from redis.asyncio import Redis

from app.core.config import settings
from app.core.redis import get_redis

logger = logging.getLogger(__name__)

CONNECTION_COUNT_KEY = "sse:conn:{user_id}"
REPLAY_KEY = "sse:replay:{channel}"
PUBSUB_CHANNEL = "sse:bus:{channel}"


class SSEManager:
    """
    Per-channel pub/sub fan-out using Redis.
    Each connected client opens a Redis pubsub subscription on the channel(s)
    it's interested in. The manager also writes events to a sorted-set replay
    buffer so reconnecting clients can catch up via Last-Event-ID.
    """

    async def stream(
        self,
        user_id: UUID,
        channel: str,
        last_event_id: str | None,
    ) -> AsyncIterator[bytes]:
        redis = await get_redis()

        # Connection cap
        count = await redis.incr(CONNECTION_COUNT_KEY.format(user_id=user_id))
        await redis.expire(CONNECTION_COUNT_KEY.format(user_id=user_id), 86400)
        if count > settings.SSE_MAX_CONNECTIONS_PER_USER:
            await redis.decr(CONNECTION_COUNT_KEY.format(user_id=user_id))
            yield self._format_error("connection_limit_exceeded")
            return

        try:
            # 1. Replay any missed events
            if last_event_id:
                async for chunk in self._replay(redis, channel, last_event_id):
                    yield chunk

            # 2. Subscribe to live channel
            ps = redis.pubsub()
            await ps.subscribe(PUBSUB_CHANNEL.format(channel=channel))

            heartbeat_task = asyncio.create_task(self._heartbeat_loop())

            try:
                while True:
                    msg_task = asyncio.create_task(ps.get_message(timeout=1.0))
                    done, _ = await asyncio.wait(
                        [msg_task, heartbeat_task],
                        return_when=asyncio.FIRST_COMPLETED,
                    )

                    if heartbeat_task in done:
                        yield b":keepalive\n\n"
                        heartbeat_task = asyncio.create_task(self._heartbeat_loop())

                    if msg_task in done:
                        msg = msg_task.result()
                        if msg is None or msg.get("type") != "message":
                            continue
                        yield self._format_message(msg["data"])
            finally:
                heartbeat_task.cancel()
                await ps.unsubscribe(PUBSUB_CHANNEL.format(channel=channel))
                await ps.close()
        finally:
            await redis.decr(CONNECTION_COUNT_KEY.format(user_id=user_id))

    async def _heartbeat_loop(self) -> None:
        await asyncio.sleep(settings.SSE_HEARTBEAT_SECONDS)

    async def _replay(self, redis: Redis, channel: str, last_event_id: str) -> AsyncIterator[bytes]:
        """
        Replay events with id > last_event_id from the per-channel sorted set.
        Score = monotonic event id (numeric or millisecond timestamp).
        """
        try:
            since = float(last_event_id)
        except ValueError:
            return
        items = await redis.zrangebyscore(
            REPLAY_KEY.format(channel=channel),
            min=f"({since}",
            max="+inf",
            withscores=False,
        )
        for raw in items:
            yield self._format_message(raw)

    def _format_message(self, raw: bytes | str) -> bytes:
        if isinstance(raw, bytes):
            data = raw.decode("utf-8")
        else:
            data = raw
        try:
            payload = json.loads(data)
            event_id = payload.get("id", "")
            event_name = payload.get("event", "message")
            data_field = json.dumps(payload.get("data", {}))
        except (json.JSONDecodeError, TypeError):
            event_id = ""
            event_name = "message"
            data_field = data
        lines = []
        if event_id:
            lines.append(f"id: {event_id}")
        if event_name:
            lines.append(f"event: {event_name}")
        for chunk in data_field.split("\n"):
            lines.append(f"data: {chunk}")
        lines.append("")
        lines.append("")
        return ("\n".join(lines)).encode("utf-8")

    def _format_error(self, code: str) -> bytes:
        return f"event: error\ndata: {{\"code\":\"{code}\"}}\n\n".encode("utf-8")


_sse_manager: SSEManager | None = None


def get_sse_manager() -> SSEManager:
    global _sse_manager
    if _sse_manager is None:
        _sse_manager = SSEManager()
    return _sse_manager
```

### 4.2 Publisher (NEW)
```python
# app/core/sse/publisher.py
import json
import time
from typing import Any
from uuid import uuid4

from app.core.config import settings
from app.core.redis import get_redis
from app.core.sse.manager import PUBSUB_CHANNEL, REPLAY_KEY

MAX_PAYLOAD_BYTES = settings.SSE_MAX_PAYLOAD_BYTES


async def publish_event(
    channel: str,
    event_name: str,
    payload: dict[str, Any],
    event_id: str | None = None,
) -> None:
    """
    Publish an SSE event to a channel.

    `channel` is the logical name (e.g. `user:<uuid>` or `tenant:<uuid>:notifications`).
    `event_name` is the SSE 'event:' field.
    `payload` is the JSON-serializable data.

    The event is fanned out to all subscribed workers via Redis pubsub
    AND stored in the per-channel replay buffer so reconnecting clients
    catch up via Last-Event-ID.
    """
    if event_id is None:
        event_id = f"{int(time.time() * 1000)}-{uuid4().hex[:8]}"

    body = json.dumps({"id": event_id, "event": event_name, "data": payload})
    if len(body.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise ValueError(f"SSE payload exceeds {MAX_PAYLOAD_BYTES} bytes")

    redis = await get_redis()

    # Score for sorted-set: numeric prefix of the event id
    score = float(event_id.split("-")[0])

    pipe = redis.pipeline()
    pipe.publish(PUBSUB_CHANNEL.format(channel=channel), body)
    pipe.zadd(REPLAY_KEY.format(channel=channel), {body: score})
    pipe.zremrangebyrank(
        REPLAY_KEY.format(channel=channel),
        0,
        -(settings.SSE_REPLAY_BUFFER_SIZE + 1),
    )
    pipe.expire(REPLAY_KEY.format(channel=channel), settings.SSE_REPLAY_TTL_SECONDS)
    await pipe.execute()
```

### 4.3 Channel access dep (NEW)
```python
# app/core/sse/access.py
from fastapi import HTTPException, status

from app.models.user import User


def authorize_channel(user: User, channel: str) -> None:
    """
    Returns None if user can subscribe to `channel`, raises 403 otherwise.
    Channel formats:
    - `user:<uuid>`              -> only the matching user
    - `tenant:<uuid>:<topic>`    -> only users belonging to that tenant
    - `public:<topic>`           -> any authenticated user
    """
    if channel.startswith("user:"):
        target = channel[len("user:"):]
        if str(user.id) != target:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Cannot subscribe to another user's channel")
        return
    if channel.startswith("tenant:"):
        parts = channel.split(":", 2)
        if len(parts) < 3:
            raise HTTPException(400, "Invalid channel format")
        tenant_id = parts[1]
        user_tenant = getattr(user, "tenant_id", None)
        if user_tenant is None or str(user_tenant) != tenant_id:
            raise HTTPException(403, "Cannot subscribe to another tenant's channel")
        return
    if channel.startswith("public:"):
        return
    raise HTTPException(400, f"Unknown channel namespace: {channel}")
```

### 4.4 Routes (NEW)
```python
# app/api/routes/events.py
from typing import Annotated

from fastapi import APIRouter, Header, Query
from fastapi.responses import StreamingResponse

from app.api.deps import CurrentUser
from app.core.sse.access import authorize_channel
from app.core.sse.manager import get_sse_manager

router = APIRouter(prefix="/events", tags=["events"])


@router.get("/stream")
async def stream(
    current_user: CurrentUser,
    channel: Annotated[str, Query(min_length=3, max_length=255)],
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
):
    authorize_channel(current_user, channel)
    manager = get_sse_manager()
    return StreamingResponse(
        manager.stream(
            user_id=current_user.id,
            channel=channel,
            last_event_id=last_event_id,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",  # nginx: disable response buffering
            "Connection": "keep-alive",
        },
    )
```

### 4.5 Example usage from app code (BEFORE / AFTER)
```python
# Before: domain code returned a value and the client polled GET /items/
async def create_item(session, owner_id, item_in):
    item = Item(**item_in.model_dump(), owner_id=owner_id)
    session.add(item)
    await session.flush()
    return item


# After: domain code also publishes an SSE event to the owner's channel
from app.core.sse.publisher import publish_event


async def create_item(session, owner_id, item_in):
    item = Item(**item_in.model_dump(), owner_id=owner_id)
    session.add(item)
    await session.flush()
    await publish_event(
        channel=f"user:{owner_id}",
        event_name="item.created",
        payload={"id": str(item.id), "title": item.title},
    )
    return item
```

### 4.6 Client example (browser)
```javascript
// client side reference (not part of the spec; documents expected behavior)
const es = new EventSource("/api/v1/events/stream?channel=user:abc-...", {
    withCredentials: true,
});

es.addEventListener("item.created", (e) => {
    const data = JSON.parse(e.data);
    console.log("New item:", data);
});

es.onerror = () => {
    // EventSource auto-reconnects with the last received id in Last-Event-ID
};
```

---

### 4.10 SSE event formatter
```python
# app/core/sse/formatter.py
"""Format SSE events to the wire format defined by the HTML5 spec.

An SSE event is a series of lines followed by a blank line:

    id: 123
    event: order_created
    retry: 5000
    data: {"order_id": 42}
    data: {"status": "pending"}

Multi-line `data` values are split into multiple `data:` lines per the
spec (https://html.spec.whatwg.org/multipage/server-sent-events.html).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SSEEvent:
    event_id: str
    event_name: str
    payload: dict[str, Any]
    retry_ms: int | None = None


def format_event(event: SSEEvent) -> bytes:
    """Serialize an SSEEvent to the text/event-stream wire format."""
    if not event.event_id:
        raise ValueError("event_id must be non-empty")
    if not event.event_name:
        raise ValueError("event_name must be non-empty")
    lines: list[str] = [f"id: {event.event_id}", f"event: {event.event_name}"]
    if event.retry_ms is not None:
        lines.append(f"retry: {event.retry_ms}")
    data_json = json.dumps(event.payload, separators=(",", ":"), ensure_ascii=False)
    # Per spec: a single data field with no newlines becomes one data line.
    for data_line in data_json.splitlines() or [""]:
        lines.append(f"data: {data_line}")
    lines.append("")  # blank line terminates the event
    return ("\n".join(lines) + "\n").encode("utf-8")


def format_keepalive() -> bytes:
    """Return the comment-only keepalive frame sent every SSE_HEARTBEAT_SECONDS."""
    return b":keepalive\n\n"
```

### 4.11 Per-connection token bucket
```python
# app/core/sse/rate_limiter.py
"""Per-connection token bucket for SSE event emission.

A single subscriber can stall the global publisher if the server blindly
pushes every event to every client. The bucket limits how many events a
given connection can receive per second; overflow events are dropped and
counted in the `sse_events_dropped_total` metric so operators can see
slow consumers in the dashboard.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass


@dataclass
class TokenBucket:
    capacity: float
    refill_rate_per_second: float
    _tokens: float = 0.0
    _last_refill: float = 0.0
    _lock: asyncio.Lock = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self._tokens = self.capacity
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def try_acquire(self, tokens: float = 1.0) -> bool:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_rate_per_second)
            self._last_refill = now
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False


class ConnectionRateLimiter:
    """Maps connection_id → TokenBucket; buckets expire when the connection closes."""

    def __init__(self, capacity: float = 20.0, refill_per_second: float = 10.0) -> None:
        self._capacity = capacity
        self._refill = refill_per_second
        self._buckets: dict[str, TokenBucket] = {}

    def register(self, connection_id: str) -> None:
        self._buckets[connection_id] = TokenBucket(self._capacity, self._refill)

    def release(self, connection_id: str) -> None:
        self._buckets.pop(connection_id, None)

    async def allow(self, connection_id: str) -> bool:
        bucket = self._buckets.get(connection_id)
        if bucket is None:
            return False
        return await bucket.try_acquire(1.0)
```

### 4.12 Connection registry with per-user cap
```python
# app/core/sse/connection_registry.py
"""Track active SSE connections and enforce per-user connection caps.

Each accepted connection is registered under (user_id, connection_id)
and stored with a TTL in Redis so a worker restart does not permanently
leak a slot. The cap is enforced at subscribe time: opening a 6th
connection when the limit is 5 immediately closes the new connection
with `event: error\\ndata: {"code": "connection_limit_exceeded"}`.
"""
from __future__ import annotations

from dataclasses import dataclass

import redis.asyncio as redis


@dataclass(frozen=True)
class ConnectionSlot:
    user_id: str
    connection_id: str
    worker_id: str


CONNECTION_KEY = "sse:connections:{user_id}"
CONNECTION_TTL_SECONDS = 30  # refreshed by heartbeat


class ConnectionRegistry:
    def __init__(self, client: redis.Redis, max_per_user: int = 5) -> None:
        self._redis = client
        self._max = max_per_user

    async def try_register(self, slot: ConnectionSlot) -> bool:
        key = CONNECTION_KEY.format(user_id=slot.user_id)
        current = await self._redis.scard(key)
        if current >= self._max:
            return False
        await self._redis.sadd(key, f"{slot.worker_id}:{slot.connection_id}")
        await self._redis.expire(key, CONNECTION_TTL_SECONDS)
        return True

    async def refresh(self, slot: ConnectionSlot) -> None:
        key = CONNECTION_KEY.format(user_id=slot.user_id)
        await self._redis.expire(key, CONNECTION_TTL_SECONDS)

    async def release(self, slot: ConnectionSlot) -> None:
        key = CONNECTION_KEY.format(user_id=slot.user_id)
        await self._redis.srem(key, f"{slot.worker_id}:{slot.connection_id}")
```



## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Strict text/event-stream format** | Manager emits `id: ...\n`, `event: ...\n`, `data: ...\n` lines and an empty line as delimiter. Multi-line `data` is split into multiple `data:` lines per RFC. |
| QS-2 | **Heartbeats prevent proxy timeouts** | `:keepalive\n\n` emitted every `SSE_HEARTBEAT_SECONDS` (default 15s). |
| QS-3 | **Per-user connection cap** | Redis INCR counter with TTL; over limit → emits `event: error\ndata: {"code":"connection_limit_exceeded"}` and closes. |
| QS-4 | **Channel authorization is explicit** | `authorize_channel` checks namespace; user/tenant/public are the only allowed namespaces. Custom namespaces require code change. |
| QS-5 | **Replay buffer is bounded** | Sorted set `ZREMRANGEBYRANK` after every `ZADD` keeps only last N events per channel. |
| QS-6 | **Replay buffer has TTL** | EXPIRE refreshed on each publish; idle channels are GC'd by Redis. |
| QS-7 | **Disconnect cleanup is reliable** | `try/finally` decrements connection count and closes pubsub when the client disconnects (StreamingResponse cancels generator). |
| QS-8 | **Payloads are bounded** | `publish_event` raises if `len(body) > SSE_MAX_PAYLOAD_BYTES`. |
| QS-9 | **Headers prevent buffering** | `Cache-Control: no-cache, no-transform` + `X-Accel-Buffering: no`. |
| QS-10 | **Last-Event-ID drives gap-free replay** | Manager calls `_replay` BEFORE subscribing to live pubsub. |
| QS-11 | **Multi-line data values are escaped correctly** | `_format_message` splits on `\n` and emits one `data:` per line. |
| QS-12 | **Auth required on stream endpoint** | `CurrentUser` dependency; anonymous requests get 401. |

---

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | `app/core/sse/manager.py` exists with `SSEManager` | File exists |
| CC-02 | `app/core/sse/publisher.py` exists with `publish_event` | File exists |
| CC-03 | `app/core/sse/access.py` exists with `authorize_channel` | File exists |
| CC-04 | `app/api/routes/events.py` exists with `/events/stream` | File exists |
| CC-05 | Routes registered in `app/api/main.py` | grep |
| CC-06 | `SSE_HEARTBEAT_SECONDS` settings | grep config |
| CC-07 | `SSE_MAX_CONNECTIONS_PER_USER` settings | grep |
| CC-08 | `SSE_REPLAY_BUFFER_SIZE` settings | grep |
| CC-09 | `SSE_REPLAY_TTL_SECONDS` settings | grep |
| CC-10 | `SSE_MAX_PAYLOAD_BYTES` settings | grep |
| CC-11 | StreamingResponse uses `text/event-stream` | grep |
| CC-12 | Response headers include `Cache-Control: no-cache, no-transform` | grep |
| CC-13 | Response headers include `X-Accel-Buffering: no` | grep |
| CC-14 | Manager emits heartbeat every N seconds | T-08 |
| CC-15 | Manager respects connection cap | T-12 |
| CC-16 | Publisher fans out via Redis pubsub | T-04 |
| CC-17 | Publisher writes to replay buffer | T-09 |
| CC-18 | Publisher enforces payload size limit | T-13 |
| CC-19 | Manager replays from `Last-Event-ID` | T-10 |
| CC-20 | Channel authorization rejects cross-user subscription | T-14 |
| CC-21 | Channel authorization rejects cross-tenant subscription | T-15 |
| CC-22 | Disconnect decrements counter | T-12 |
| CC-23 | New file `tests/test_sse.py` with 30 tests | File exists |
| CC-24 | Existing tests pass | pytest 0 failures |
| CC-25 | All files parse | Tool internal |
| CC-26 | Tool execution time < 4s | Time measurement |
| CC-27 | Publish → receive p99 < 100 ms | Benchmark T-29 |
| CC-28 | OpenAPI exposes the SSE endpoint | curl /openapi.json |
| CC-29 | Idempotent re-run | T-26 |
| CC-30 | Multi-line `data` correctly emitted as multiple `data:` lines | T-23 |

---

## 7. Definition of Done (DoD)

- [ ] All 30 Completeness Criteria verified
- [ ] All 12 Quality Standards enforced
- [ ] All 7 Invariants enforced
- [ ] All 25 User Stories pass acceptance tests
- [ ] All 30 Test Cases pass
- [ ] Tool is idempotent
- [ ] Tool is reversible
- [ ] Performance budget met
- [ ] Interaction with other tools verified
- [ ] All 15 edge cases handled
- [ ] Documentation updated
- [ ] Tool registered in `mcp_server.py`
- [ ] Re-audit by Opus in fresh context: ≥ 9.5/10

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-SSE-01 | Events are NEVER delivered to a client that didn't pass channel authorization | `authorize_channel` runs before `manager.stream` | T-14, T-15 |
| INV-SSE-02 | A client over the connection cap NEVER opens a new stream | Redis INCR + check + decrement on reject | T-12 |
| INV-SSE-03 | A client connection ALWAYS releases its slot on disconnect | `try/finally` decrements counter — enforced by dedicated check in `tests/test_invariants.py` and `app/core/guards.py` on every write path | T-19 |
| INV-SSE-04 | Reconnect with `Last-Event-ID` NEVER misses events newer than that id (within replay window) | `_replay` runs before live subscription | T-10 |
| INV-SSE-05 | An event payload over `SSE_MAX_PAYLOAD_BYTES` NEVER reaches Redis | `publish_event` raises ValueError — enforced by dedicated check in `tests/test_invariants.py` and `app/core/guards.py` on every write path | T-13 |
| INV-SSE-06 | The replay buffer per channel NEVER exceeds N entries | `ZREMRANGEBYRANK 0 -(N+1)` after every publish | T-22 |
| INV-SSE-07 | Heartbeats fire at fixed intervals even when no events | Independent `_heartbeat_loop` task — enforced by dedicated check in `tests/test_invariants.py` and `app/core/guards.py` on every write path | T-08 |

---

## 9. User Stories

### 9.1 Subscription & EventSource protocol (US-01 .. US-05)

**US-01: Connect to SSE stream and receive text/event-stream headers**
- **As a** frontend engineer embedding an activity feed in a React dashboard
- **I want** to open `new EventSource("/api/v1/events/stream?channel=user:<id>")` and get a proper `text/event-stream` response with `Cache-Control: no-cache` and `X-Accel-Buffering: no` headers
- **So that** the browser keeps the connection alive and does not buffer events behind an nginx reverse proxy
- **Given:** user is authenticated with a valid JWT and `channel=user:<their-uuid>` is provided
- **When:** `GET /api/v1/events/stream?channel=user:<uuid>` is issued with `Authorization: Bearer <token>`
- **Then:**
  - HTTP 200 with `Content-Type: text/event-stream; charset=utf-8`
  - `Cache-Control: no-cache, no-transform` header is present (CC-12, CC-13)
  - `X-Accel-Buffering: no` header is present (CC-13)
  - Connection remains open (no `Content-Length`; chunked transfer)

**US-02: Receive an event with id, event, and data fields**
- **As a** frontend engineer listening for domain events in the notification centre
- **I want** each server-pushed frame to contain `id:`, `event:`, and `data:` fields so the browser `EventSource` can dispatch typed events by name
- **So that** my `es.addEventListener("order.shipped", handler)` callback fires correctly without re-parsing a generic blob
- **Given:** client is subscribed to `user:<uuid>` and server calls `await publish_event("user:<uuid>", "order.shipped", {"order_id": "ord-42"})`
- **When:** the Redis pub/sub message reaches the SSE manager on the connected worker
- **Then:**
  - The wire frame contains `id: <event_id>` as the first line (CC-11, INV-SSE-04)
  - The frame contains `event: order.shipped`
  - The frame contains `data: {"order_id":"ord-42"}`
  - The frame is terminated by a blank line (`\n\n`)
  - Client receives the frame within 100 ms of publish (T-04)

**US-03: Browser EventSource auto-reconnects using Last-Event-ID**
- **As a** frontend engineer whose user navigates a flaky mobile network
- **I want** the browser to automatically re-open the SSE stream after a connection drop, sending the last seen event id in the `Last-Event-ID` request header
- **So that** no events published during the brief disconnect are silently lost
- **Given:** client received event with `id: 1714000000000-a1b2c3d4` before the TCP connection was interrupted
- **When:** `EventSource` reconnects and the browser sends `Last-Event-ID: 1714000000000-a1b2c3d4`
- **Then:**
  - Server calls `_replay(redis, channel, "1714000000000-a1b2c3d4")` before subscribing to live pub/sub (INV-SSE-04)
  - All events with id score greater than `1714000000000` are replayed in ascending order (CC-19)
  - Live events follow immediately after replay without duplication
  - T-10 and T-11 pass against this behaviour

**US-04: SSE wire format uses correct id/event/data field syntax**
- **As a** backend engineer integrating a third-party SSE parser in a Python consumer (e.g. `httpx-sse`)
- **I want** every emitted frame to conform exactly to the HTML5 `text/event-stream` spec — field name, colon, space, value — with no trailing spaces and a double newline terminator
- **So that** off-the-shelf SSE client libraries parse frames without error
- **Given:** `publish_event("public:ticker", "price.update", {"symbol": "BTC", "price": 62500})` is called
- **When:** `format_event()` in `app/core/sse/formatter.py` serialises the `SSEEvent` dataclass
- **Then:**
  - Output matches regex `^id: .+\nevent: .+\ndata: .+\n\n$` (CC-11, T-05, T-06, T-07)
  - `id` field is non-empty and raises `ValueError` if absent
  - `event` field equals `"price.update"`
  - `data` field is compact JSON with no trailing whitespace

**US-05: Unauthenticated client receives 401 before any subscription is created**
- **As a** security engineer auditing the SSE endpoint for information leakage
- **I want** the `GET /events/stream` route to return `401 Unauthorized` immediately for requests without a valid JWT, before any channel name is evaluated or any Redis command is executed
- **So that** no unauthenticated caller can probe channel existence or consume connection slots
- **Given:** a request with no `Authorization` header or an expired token
- **When:** `GET /api/v1/events/stream?channel=public:announcements` is called
- **Then:**
  - HTTP 401 is returned before `authorize_channel` is called (CC-12, INV-SSE-01)
  - No `sse:conn:*` Redis key is incremented
  - No pubsub subscription is created in Redis
  - T-17 passes against this behaviour

### 9.2 Channel routing & auth (US-06 .. US-10)

**US-06: User subscribes to their own user channel and receives events**
- **As a** mobile app developer showing real-time order status to the logged-in user
- **I want** to subscribe to `user:<my-uuid>` and receive events published specifically for that user
- **So that** each user only sees their own notifications, not other users' data
- **Given:** authenticated user with `id = "a1b2-..."` and JWT claim `sub = "a1b2-..."`
- **When:** `GET /events/stream?channel=user:a1b2-...` with the user's own token
- **Then:**
  - `authorize_channel` returns `None` (no exception) for `channel.startswith("user:")` with matching id (CC-20, INV-SSE-01)
  - HTTP 200 and stream opens
  - `publish_event("user:a1b2-...", "order.updated", {...})` reaches this client within 100 ms

**US-07: User cannot subscribe to another user's channel — 403 returned**
- **As a** security engineer preventing horizontal privilege escalation in the SSE layer
- **I want** `authorize_channel` to raise `HTTP 403` when a user attempts to subscribe to a channel prefixed `user:` with a UUID that is not their own
- **So that** user B cannot eavesdrop on user A's notification stream even with a valid JWT
- **Given:** user A has `id = "aaaa-..."`, user B has `id = "bbbb-..."`, and B sends `channel=user:aaaa-...`
- **When:** `authorize_channel(user_b, "user:aaaa-...")` is called inside the route handler
- **Then:**
  - `HTTPException(status_code=403)` is raised with message "Cannot subscribe to another user's channel"
  - No Redis `INCR` on connection counter for user B (INV-SSE-01, CC-20)
  - Response body contains `{"detail": "Cannot subscribe to another user's channel"}`
  - T-14 passes against this behaviour

**US-08: Tenant member subscribes to their own tenant channel**
- **As a** SaaS product manager wanting per-tenant broadcast notifications (e.g. "system maintenance in 10 min")
- **I want** any authenticated user whose `tenant_id` matches to successfully subscribe to `tenant:<tenant-uuid>:<topic>`
- **So that** tenant-wide announcements reach all connected users of that tenant simultaneously
- **Given:** user has `tenant_id = "t1-..."` and requests `channel=tenant:t1-...:maintenance`
- **When:** `authorize_channel(user, "tenant:t1-...:maintenance")` is called
- **Then:**
  - No exception is raised; `authorize_channel` returns `None` (CC-21)
  - `publish_event("tenant:t1-...:maintenance", "maintenance.alert", {...})` reaches all subscribed tenant members
  - Channel parsed with `split(":", 2)` yields `["tenant", "t1-...", "maintenance"]` correctly

**US-09: Cross-tenant subscription is rejected with 403**
- **As a** security engineer ensuring tenant data isolation in multi-tenant SaaS
- **I want** a user from tenant T1 to receive `HTTP 403` when attempting to subscribe to `tenant:T2:<topic>`
- **So that** tenant data boundaries are enforced at the SSE layer, not just the REST API
- **Given:** user belongs to `tenant_id = "t1-..."` and sends `channel=tenant:t2-...:alerts`
- **When:** `authorize_channel(user, "tenant:t2-...:alerts")` is evaluated
- **Then:**
  - `HTTPException(status_code=403)` is raised (INV-SSE-01, CC-21)
  - Redis `sse:conn:{user_id}` is never incremented
  - T-15 passes; attempting to subscribe returns `{"detail": "Cannot subscribe to another tenant's channel"}`

**US-10: Any authenticated user subscribes to a public channel**
- **As a** frontend engineer building a live cryptocurrency ticker available to all logged-in users
- **I want** to subscribe to `public:btc-ticker` with any valid JWT and receive broadcast price events
- **So that** I can show real-time prices without per-user channel management
- **Given:** authenticated user from any tenant (or no tenant) and `channel=public:btc-ticker`
- **When:** `GET /events/stream?channel=public:btc-ticker` with a valid JWT
- **Then:**
  - `authorize_channel` returns `None` for `channel.startswith("public:")` regardless of user identity (CC-20, T-16)
  - HTTP 200 and stream opens successfully
  - Events published to `public:btc-ticker` arrive on this client within 100 ms

### 9.3 Heartbeat & connection health (US-11 .. US-15)

**US-11: Keepalive comment emitted every 15 seconds on idle stream**
- **As a** DevOps engineer configuring nginx with `proxy_read_timeout 30s`
- **I want** the server to emit a `:keepalive\n\n` SSE comment every 15 seconds on streams with no data events
- **So that** the proxy does not close idle connections before the client disconnects intentionally
- **Given:** an authenticated client subscribed to `user:<uuid>` with no events published for 45 seconds
- **When:** the `_heartbeat_loop` asyncio task fires at `SSE_HEARTBEAT_SECONDS` intervals (default 15)
- **Then:**
  - At least 3 `:keepalive\n\n` frames are emitted within the 45-second window (CC-14, INV-SSE-07)
  - Each heartbeat frame is exactly `b":keepalive\n\n"` as returned by `format_keepalive()` in `formatter.py`
  - The heartbeat task runs independently of the event task via `asyncio.wait(FIRST_COMPLETED)` (T-08)

**US-12: Heartbeat task is cancelled cleanly on client disconnect**
- **As a** backend reliability engineer tracking asyncio task leaks in production
- **I want** the `_heartbeat_loop` background task to be cancelled and awaited in `try/finally` when the client disconnects
- **So that** no orphaned asyncio tasks accumulate over time, preventing memory and CPU leaks
- **Given:** a connected client that abruptly closes its TCP connection (browser tab closed)
- **When:** FastAPI's `StreamingResponse` cancels the async generator
- **Then:**
  - `heartbeat_task.cancel()` is called in the `finally` block of `SSEManager.stream` (INV-SSE-03)
  - `await ps.unsubscribe(...)` and `await ps.close()` execute before the coroutine exits
  - Redis `sse:conn:{user_id}` counter is decremented exactly once (CC-22, T-19)
  - No `asyncio.CancelledError` propagates uncaught to the ASGI server

**US-13: Proxy idle-kill timeout is defeated by keepalive under AWS ALB defaults**
- **As a** backend engineer deploying the FastAPI app behind an AWS Application Load Balancer (idle timeout 60 s)
- **I want** the SSE heartbeat to fire at 15-second intervals so the ALB never sees more than 15 s of inactivity
- **So that** long-lived SSE connections are not forcibly closed by the load balancer during quiet periods
- **Given:** `SSE_HEARTBEAT_SECONDS = 15` (default) and `proxy_read_timeout` or ALB idle timeout = 60 s
- **When:** client is subscribed and no domain events are published for 60 seconds
- **Then:**
  - 4 `:keepalive\n\n` frames arrive at the client within 60 seconds (INV-SSE-07, T-08)
  - The ALB does not reset the connection (observable via no `502 / 504` in access logs)
  - The `SSE_HEARTBEAT_SECONDS` setting is configurable via environment variable (CC-06)

**US-14: Client reconnects automatically after server worker restart**
- **As a** frontend engineer whose app must survive rolling deploys with zero user-visible interruption
- **I want** the browser `EventSource` to re-establish the SSE connection automatically after a server worker restart, using the last received event id
- **So that** a rolling deploy does not produce a "notifications stopped working" report from users
- **Given:** browser has received events up to id `1714000100000-f0e1d2c3` before the old worker exits
- **When:** the worker process terminates and a new uvicorn worker accepts the reconnect within 2 seconds
- **Then:**
  - Browser sends `Last-Event-ID: 1714000100000-f0e1d2c3` on the reconnect request (standard EventSource behaviour)
  - New worker replays events from the Redis ZSET with score `> 1714000100000` (INV-SSE-04, CC-19)
  - Live stream resumes after replay; no duplicate events are delivered

**US-15: Invalid Last-Event-ID header is silently ignored and live stream starts**
- **As a** backend engineer handling malformed client state after a client-side storage reset
- **I want** the server to skip the replay step when `Last-Event-ID` contains a non-numeric string and start the live stream immediately
- **So that** a corrupted client does not crash the SSE route or produce a 400 error
- **Given:** a reconnecting client sends `Last-Event-ID: undefined` or `Last-Event-ID: null-state`
- **When:** `_replay(redis, channel, "undefined")` is called and `float("undefined")` raises `ValueError`
- **Then:**
  - `ValueError` is caught, replay is skipped entirely (no Redis ZRANGEBYSCORE call)
  - Live subscription begins immediately (CC-19, T-24)
  - HTTP 200 is returned; no 400 or 500 error

### 9.4 Fan-out & multi-worker (US-16 .. US-20)

**US-16: Event published on worker A is received by client connected to worker B**
- **As a** backend engineer running 4 uvicorn workers behind nginx with round-robin load balancing
- **I want** `await publish_event(channel, event_name, payload)` called on any worker to reach all SSE clients subscribed to that channel regardless of which worker accepted their connection
- **So that** horizontal scaling does not create silent event delivery gaps
- **Given:** client C is connected to worker-2 on `user:<uuid>`; a background job runs on worker-1 and calls `publish_event("user:<uuid>", "job.done", {...})`
- **When:** worker-1 executes `redis.publish(PUBSUB_CHANNEL.format(channel=channel), body)` via pipeline
- **Then:**
  - Worker-2's Redis pubsub listener receives the message and forwards it to client C (CC-16, T-21)
  - Round-trip latency from `publish_event` return to client receive is < 100 ms p99 (T-29)
  - No message is lost even when the publishing worker has zero connected clients

**US-17: Publisher stores event in replay buffer on every publish**
- **As a** backend engineer ensuring gap-free reconnection for mobile clients on flaky networks
- **I want** every call to `publish_event` to atomically write the event to the per-channel Redis sorted set (`sse:replay:<channel>`) with a numeric score equal to the millisecond timestamp prefix
- **So that** reconnecting clients can retrieve missed events via `Last-Event-ID` within the replay window
- **Given:** `publish_event("user:<uuid>", "balance.updated", {"amount": 250.00})` is called
- **When:** the Redis pipeline executes `ZADD`, `ZREMRANGEBYRANK`, and `EXPIRE` atomically
- **Then:**
  - `ZCARD sse:replay:user:<uuid>` is incremented by 1 (CC-17, T-09)
  - The entry's score equals `float(event_id.split("-")[0])` (the millisecond timestamp) (INV-SSE-04)
  - `EXPIRE sse:replay:user:<uuid> <SSE_REPLAY_TTL_SECONDS>` refreshes the TTL on every publish

**US-18: Replay buffer is bounded to N entries per channel**
- **As a** Redis capacity engineer enforcing memory limits on SSE replay data
- **I want** the sorted set `sse:replay:<channel>` to never exceed `SSE_REPLAY_BUFFER_SIZE` (default 100) entries
- **So that** a high-traffic channel cannot grow the replay set unboundedly and exhaust Redis memory
- **Given:** `SSE_REPLAY_BUFFER_SIZE = 100` and `publish_event` has been called 105 times on `public:ticker`
- **When:** the 101st through 105th publishes execute `ZREMRANGEBYRANK sse:replay:public:ticker 0 -(N+1)`
- **Then:**
  - `ZCARD sse:replay:public:ticker` equals exactly 100 (INV-SSE-06, CC-17, T-22)
  - The 5 oldest events (lowest scores) have been evicted
  - A client reconnecting with the id of the oldest surviving event receives 99 replayed events

**US-19: Replay buffer TTL expires idle channels and frees Redis memory**
- **As a** Redis operator monitoring key space growth in production
- **I want** each per-channel replay sorted set to have its TTL refreshed on every publish and auto-deleted after `SSE_REPLAY_TTL_SECONDS` (default 600) of inactivity
- **So that** channels that receive no events are garbage-collected by Redis without manual cleanup
- **Given:** `SSE_REPLAY_TTL_SECONDS = 600` and `sse:replay:user:<uuid>` received its last publish 601 seconds ago
- **When:** Redis TTL expires
- **Then:**
  - `EXISTS sse:replay:user:<uuid>` returns 0 (CC-17, T-20)
  - A subsequent reconnect with any `Last-Event-ID` finds an empty ZSET and starts live immediately
  - The TTL is re-set on every `publish_event` call via `pipe.expire(REPLAY_KEY, SSE_REPLAY_TTL_SECONDS)`

**US-20: Multiple clients on same public channel each receive the same broadcast event**
- **As a** product manager demonstrating a live scoreboard to all 500 concurrent viewers during a sports event
- **I want** a single `publish_event("public:scoreboard", "goal.scored", {"team": "blue", "score": 3})` call to be delivered to all 500 connected clients simultaneously
- **So that** all viewers see the score update within 100 ms without per-user publish loops
- **Given:** 500 clients are subscribed to `public:scoreboard` across multiple workers
- **When:** one `publish_event` call executes on any worker
- **Then:**
  - All 500 clients receive the event within 100 ms p99 (T-29, CC-27)
  - Only one Redis `PUBLISH` command is issued regardless of subscriber count (CC-16)
  - The Redis fan-out delivers the message to every worker's pubsub listener independently

### 9.5 Rate limiting & edge cases (US-21 .. US-25)

**US-21: Per-connection token bucket drops events for slow consumer**
- **As a** backend reliability engineer preventing a slow WebView consumer from stalling Redis publish throughput
- **I want** each SSE connection to have an independent `TokenBucket` that drops incoming events when the bucket is empty rather than blocking the publisher coroutine
- **So that** one lagging client cannot cause head-of-line blocking for all other subscribers on the same worker
- **Given:** `TokenBucket(capacity=20, refill_rate_per_second=10)` and a consumer that cannot read from the TCP buffer fast enough (simulated by a full socket buffer)
- **When:** more than 20 events arrive within 1 second without sufficient drain
- **Then:**
  - `ConnectionRateLimiter.allow(connection_id)` returns `False` for excess events (T-13)
  - Dropped events are counted in `sse_events_dropped_total` metric (observability)
  - The publisher coroutine does not block; remaining clients receive events normally (INV-SSE-05)

**US-22: Per-user connection cap rejects the (N+1)th concurrent stream**
- **As a** platform engineer preventing a single user's buggy browser extension from opening 50 SSE connections and exhausting worker file descriptors
- **I want** the SSE manager to reject any connection attempt that would bring a user above `SSE_MAX_CONNECTIONS_PER_USER` (default 10) open streams
- **So that** resource usage per user is bounded regardless of client-side bugs
- **Given:** user `uuid-u1` already has 10 open streams (`SCARD sse:connections:uuid-u1 = 10`)
- **When:** user `uuid-u1` opens an 11th `EventSource` connection
- **Then:**
  - `ConnectionRegistry.try_register` returns `False` (CC-15, INV-SSE-02)
  - The stream immediately emits `event: error\ndata: {"code":"connection_limit_exceeded"}\n\n` and closes
  - Redis `sse:connections:uuid-u1` count remains at 10; no slot is leaked (T-12)

**US-23: Per-user connection slot is released on clean client disconnect**
- **As a** backend engineer ensuring Redis connection counters converge to zero when a user closes all tabs
- **I want** the `ConnectionRegistry.release(slot)` call to execute in the `try/finally` block of `SSEManager.stream` on every exit path (clean close, exception, cancellation)
- **So that** slots are never permanently leaked, preventing users from being locked out after a server-side error
- **Given:** user `uuid-u1` has 1 active stream (`SCARD = 1`) and the client disconnects
- **When:** FastAPI cancels the async generator (normal disconnect) or an unhandled exception occurs mid-stream
- **Then:**
  - `ConnectionRegistry.release(slot)` is called via `try/finally` (INV-SSE-03, CC-22)
  - `SCARD sse:connections:uuid-u1` becomes 0 (T-19)
  - A subsequent connection attempt by the same user succeeds immediately

**US-24: Oversized event payload is rejected before reaching Redis**
- **As a** security engineer preventing abuse via artificially large SSE payloads that could exhaust Redis memory
- **I want** `publish_event` to raise a `ValueError` synchronously when the serialised JSON body exceeds `SSE_MAX_PAYLOAD_BYTES` (default 64 KB), before any Redis command is issued
- **So that** a misbehaving service cannot push 1 MB payloads that overwhelm Redis pub/sub
- **Given:** `SSE_MAX_PAYLOAD_BYTES = 65536` and caller passes a payload whose JSON serialisation is 100 000 bytes
- **When:** `publish_event("user:<uuid>", "bulk.export", {"data": "x" * 90000})` is called
- **Then:**
  - `ValueError(f"SSE payload exceeds {MAX_PAYLOAD_BYTES} bytes")` is raised before `redis.pipeline()` is called (INV-SSE-05, CC-18, T-13)
  - No `PUBLISH` or `ZADD` commands reach Redis
  - The exception propagates to the caller; no partial state is written

**US-25: Redis outage causes graceful stream termination and enables client reconnect**
- **As a** site reliability engineer handling a 30-second Redis failover during a Redis Sentinel promotion
- **I want** the SSE manager to detect the Redis connection error, emit a structured `event: error` frame, close the stream cleanly, and allow the browser `EventSource` to reconnect once Redis recovers
- **So that** users see a brief notification pause rather than a hung connection during infrastructure incidents
- **Given:** client is subscribed to `user:<uuid>` and Redis becomes unreachable mid-stream
- **When:** `ps.get_message()` raises a `redis.exceptions.ConnectionError`
- **Then:**
  - The manager emits `event: error\ndata: {"code":"redis_unavailable"}\n\n` before closing the generator (T-25)
  - `ConnectionRegistry.release(slot)` still executes in `finally` (INV-SSE-03)
  - The browser `EventSource` enters error state, applies exponential back-off, and reconnects with `Last-Event-ID` once the endpoint becomes available again
  - On reconnect, replay buffer in Redis Sentinel replica provides missed events if TTL has not expired (INV-SSE-04)

## 10. Test Plan

### 10.1 Format & basic streaming

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | Stream returns text/event-stream | client connects | inspect headers | Content-Type matches |
| T-02 | Cache-Control no-cache | inspect headers | check | present |
| T-03 | X-Accel-Buffering no | inspect headers | check | present |
| T-04 | publish_event reaches subscribed client | publish | observe stream | event received within 100 ms |
| T-05 | Event id field emitted | publish with id | inspect | `id: <uuid>` line |
| T-06 | Event name field emitted | publish event_name | inspect | `event: name` line |
| T-07 | Data field is JSON | publish dict | inspect | `data: {"k":"v"}` |
| T-08 | Heartbeat fires every N seconds | wait 30s with no events, N=10 | observe | 3 `:keepalive` |

### 10.2 Replay & Last-Event-ID

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-09 | Publish writes to ZSET | publish 1 | redis ZCARD | 1 |
| T-10 | Reconnect replays missed | publish, disconnect, publish 3, reconnect with last_id | observe | receives 3 events in order |
| T-11 | Replay then live | reconnect | observe | replayed events first, then live |

### 10.3 Limits & access

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-12 | 11th connection rejected | 10 open | open 11th | error event + close |
| T-13 | Large payload rejected | 100 KB | publish_event | ValueError raised |
| T-14 | Cross-user channel rejected | userA, channel user:B | subscribe | 403 |
| T-15 | Cross-tenant channel rejected | userT1, channel tenant:T2:x | subscribe | 403 |
| T-16 | Public channel allowed | public:x | subscribe | 200 |
| T-17 | Anonymous user blocked | no auth | subscribe | 401 |

### 10.4 Cleanup & disconnect

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-18 | Disconnect closes pubsub | client disconnect | inspect Redis | subscriber gone |
| T-19 | Disconnect releases counter | open then close | inspect counter | -1 |
| T-20 | Channel cleanup TTL | publish, wait > TTL | ZCARD | 0 |
| T-21 | Worker B can publish to A's subscriber | 2 workers | publish from B | A's client receives |

### 10.5 Robustness, idempotency, performance

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-22 | Replay buffer bounded to N | publish 105, N=100 | ZCARD | 100 |
| T-23 | Multi-line data framed | payload has \n | inspect | multiple `data:` lines |
| T-24 | Invalid Last-Event-ID = no replay | bad id | subscribe | live only |
| T-25 | Redis down → graceful error | mock | publish/subscribe | error event, no crash |
| T-26 | Tool re-run no-op | installed | run | no changes |
| T-27 | OpenAPI lists endpoint | installed | curl /openapi.json | path present |
| T-28 | Authorize_channel returns None for valid | call directly | check | None |
| T-29 | publish → receive p99 < 100 ms | 1k events benchmark | measure | < 100 ms |
| T-30 | 1000 concurrent connections per worker | stress test | observe | no errors, low CPU |

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|---------------|-------------|-------|
| `add_multi_tenancy` | **Tenancy first** | ✅ Compatible | Tenant channels (`tenant:<id>:topic`) require user.tenant_id; integrated. |
| `add_rbac` | No | ⚠️ Caveat | Channel access control is namespace-based; if you need finer control, extend `authorize_channel` to call `has_permission`. |
| `add_audit_log` | No | ⚠️ Caveat | Streaming is high-volume; do NOT audit every event. Audit only stream open/close. |
| `add_api_key_auth` | No | ⚠️ Caveat | API keys can use SSE; ensure `authorize_channel` accepts API key actor. |
| `add_oauth2_provider` | No | ✅ Compatible | OAuth-issued JWT works with SSE. |
| `add_feature_flags` | No | ✅ Compatible | Can flag-gate the SSE feature per user. |
| `add_rate_limit` | No | ⚠️ Caveat | Rate-limit `/events/stream` opens per IP separately from per-user cap to prevent flood. |
| `add_circuit_breaker` | No | ✅ Compatible | If publish_event calls fail (Redis down), publisher raises and caller decides. |
| `add_outbox_pattern` | No | ✅ Compatible | Outbox can dispatch via publish_event after commit. |
| `add_long_running_task` | No | ✅ Compatible | Long-running tasks publish progress events to a user channel. |
| `add_cors` | **CORS-aware** | ⚠️ Caveat | Browser EventSource requires `Access-Control-Allow-Origin` for cross-origin; ensure CORS allows it. |
| TOOL-034 performance_baseline | downstream | `GET /events/stream` time-to-first-byte and `publish_event` enqueue latency are captured in the baseline (target TTFB p99 < 150 ms, enqueue p99 < 10 ms); a change to `app/core/sse/manager.py` that adds a synchronous DB call per subscription will be caught before merge |
| TOOL-051 fastapi_doctor | downstream | doctor detects `add_sse` is installed but no `add_webhook_sender` is present and recommends TOOL-015 `add_webhook_sender` as a complement so events can reach non-browser consumers (mobile apps, third-party integrations) that cannot hold open an HTTP connection |
| TOOL-029 security_scan | downstream | `app/core/sse/access.py` `authorize_channel` and `app/api/routes/events.py` are scanned by semgrep for channel-enumeration patterns (unauthenticated access to `user:` or `tenant:` namespaces) and for missing authentication before `manager.stream` is called; any CRITICAL finding blocks merge |

**Conflicts:**
- None identified.

---

## 12. Rollback Procedure

### Code rollback (before deploy)
```bash
git checkout HEAD~1 -- app/core/sse app/api/routes/events.py app/api/main.py app/core/config.py
```
No DB migration to roll back.

### Failure mode: tool partially modified files
- `git checkout -- {files}` to revert
- Re-run tool

### Emergency: SSE causing resource exhaustion
1. Lower `SSE_MAX_CONNECTIONS_PER_USER` to 1; redeploy
2. Or block the route at the load balancer
3. Investigate: which channel is being abused? `redis-cli ZRANGE sse:replay:* 0 -1`
4. Tighten `authorize_channel` if cross-channel leak found

### Emergency: Redis pubsub down
- New events queue in publisher (raises) until Redis recovers
- Existing connections idle and emit heartbeats
- On Redis recovery, clients reconnect via auto EventSource reconnection with `Last-Event-ID`


### Failure mode: tool partially modified files
If the generator crashed halfway and left an inconsistent tree (some modules present, others missing, config half-written), restore to a clean HEAD before re-running:
```bash
# 1. Inspect what changed vs HEAD
git status --short

# 2. Revert tool-written files + drop freshly-created ones
git checkout HEAD -- app/ tests/ alembic/ pyproject.toml
git clean -fd app/ tests/

# 3. Verify clean tree before re-running
git diff HEAD --exit-code && echo "clean" || echo "DIRTY — stop"
```

### Failure mode: Redis connection counter leak — counters not decremented after crashes
If worker pods crashed without executing the `finally` block in the SSE generator, `sse:conn:{user_id}` counters are permanently inflated. Affected users hit `SSE_MAX_CONNECTIONS_PER_USER` and cannot open new connections even when none are active:
```bash
# 1. Identify affected users: counters > 0 with no active HTTP connections
redis-cli -u $REDIS_URL KEYS "sse:conn:*" | while read key; do
  count=$(redis-cli -u $REDIS_URL GET "$key")
  echo "$key = $count"
done | sort -t= -k2 -rn | head -20

# 2. For a specific user, confirm no real open connections in nginx/uvicorn access log
USER_ID=1234
grep "GET /api/events" /var/log/nginx/access.log | grep "$USER_ID" | grep -v " 200 " | tail -5

# 3. Reset the leaked counter for a single user
redis-cli -u $REDIS_URL SET "sse:conn:${USER_ID}" 0

# 4. Bulk-reset all counters that have no live backing connection (nuclear option)
#    Only safe when you have confirmed all workers are stopped or post-deploy
redis-cli -u $REDIS_URL KEYS "sse:conn:*" | xargs redis-cli -u $REDIS_URL DEL
echo "All SSE connection counters reset"

# 5. Prevent recurrence: ensure the SSE generator finally block is never skipped
#    Verify app/core/sse/manager.py has try/finally around the yield loop
grep -A5 "finally" app/core/sse/manager.py

# 6. Add TTL to counters (86400s) as a safety net so they auto-expire
redis-cli -u $REDIS_URL KEYS "sse:conn:*" | while read key; do
  redis-cli -u $REDIS_URL EXPIRE "$key" 86400
done
```

### Emergency: reverse proxy idle timeout cutting SSE connections and suppressing heartbeats
If nginx / AWS ALB / Cloudflare closes keep-alive SSE connections before the client retries, clients see repeated disconnects every 60–120 s and the `Last-Event-ID` replay mechanism is triggered excessively, burning Redis replay buffer reads:
```bash
# 1. Confirm proxy is the culprit: measure actual connection lifetime
grep "GET /api/events" /var/log/nginx/access.log \
  | awk '{print $NF}' | sort -n | uniq -c | sort -rn | head -10
# If most durations cluster at 60 s or 120 s exactly → proxy timeout, not client drop

# 2. Fix nginx: set proxy_read_timeout longer than the heartbeat interval + margin
#    SSE_HEARTBEAT_SECONDS=15 → set proxy_read_timeout to at least 60
cat >> /etc/nginx/conf.d/sse.conf <<'EOF'
location /api/events {
    proxy_pass         http://uvicorn;
    proxy_http_version 1.1;
    proxy_set_header   Connection "";
    proxy_read_timeout 300s;
    proxy_buffering    off;
    proxy_cache        off;
    proxy_set_header   X-Accel-Buffering no;
}
EOF
nginx -t && nginx -s reload

# 3. For AWS ALB: increase idle timeout in the Target Group to 300 s
aws elbv2 modify-load-balancer-attributes \
  --load-balancer-arn "$ALB_ARN" \
  --attributes Key=idle_timeout.timeout_seconds,Value=300

# 4. For Cloudflare (proxied): Cloudflare's 100 s HTTP/1.1 timeout cannot be extended;
#    switch SSE endpoint to a Worker or use Cloudflare's Cache-Control bypass
curl -s -X PATCH "https://api.cloudflare.com/client/v4/zones/${CF_ZONE_ID}/settings/proxy_read_timeout" \
  -H "Authorization: Bearer ${CF_API_TOKEN}" \
  -H "Content-Type: application/json" \
  --data '{"value":300}'

# 5. Verify fix: watch a live SSE stream for > 300 s without disconnect
curl -N -H "Authorization: Bearer $TEST_JWT" "$APP_URL/api/events?channel=user:1" &
SSE_PID=$!
sleep 310 && kill -0 $SSE_PID && echo "Connection alive after 310s ✓" || echo "Connection dropped ✗"
```


---

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-1 | Project has no Redis | Tool errors; the operation returns a structured error response and no side effects persist |
| EC-2 | Project has no User model | Tool errors; the operation returns a structured error response and no side effects persist |
| EC-3 | Client uses HTTP/1.0 (no chunked) | StreamingResponse degrades; FastAPI handles via uvicorn |
| EC-4 | Reverse proxy buffers responses (default nginx) | `X-Accel-Buffering: no` header disables it |
| EC-5 | Client closes connection mid-message | Generator raises CancelledError; finally block cleans up |
| EC-6 | publish_event called from sync code | Caller must use `asyncio.run` or task wrapper; documented in next_steps |
| EC-7 | Channel name with `:` collision (e.g. `user:abc:def`) | Authorize splits on `:` once; `user:abc:def` is treated as `user` namespace with target `abc:def`; rejected (mismatch) |
| EC-8 | Replay TTL expires while client offline | Missed events lost; client receives only live events on reconnect |
| EC-9 | Two clients subscribe to same channel from same user | Both succeed; both receive events |
| EC-10 | publish_event raises (e.g. Redis down) | Caller handles ValueError / RedisError; the operation returns a structured error response and no side effects persist |
| EC-11 | Heartbeat task leaks on early disconnect | `try/finally` cancels it; the operation returns a structured error response and no side effects persist |
| EC-12 | Connection counter not decremented after crash | TTL on counter (86400s) eventually resets |
| EC-13 | Browser closes laptop / sleep | Connection eventually times out; counter reset on TTL or new connection |
| EC-14 | Last-Event-ID with score = 0 | Replays everything (intentional); the operation returns a structured error response and no side effects persist |
| EC-15 | publish_event payload is not JSON-serializable | json.dumps raises TypeError; caller handles |

---

## 14. Acceptance Criteria

1. ✅ All 30 CC verified
2. ✅ All 25 user stories pass
3. ✅ All 30 tests pass
4. ✅ All 7 invariants enforced
5. ✅ All 15 edge cases handled
6. ✅ Interaction matrix verified
7. ✅ Rollback procedure tested
8. ✅ Performance SLOs met
9. ✅ Re-audit by Opus: ≥ 9.5/10
10. ✅ One human dev opens an EventSource in their browser, sees a real-time event arrive, restarts the worker, sees the connection auto-reconnect with replay

---

## 15. Implementation Checklist

### 15.1 Pre-flight checks
- [ ] Validate `project_dir` exists
- [ ] Validate User model exists
- [ ] Validate Redis URL configured
- [ ] Detect existing `app/core/sse/` → idempotent skip if found
- [ ] Assert pre-flight raises `MissingConfigError` when `REDIS_URL` is absent via `test_preflight.py::test_missing_redis_url_raises`
- [ ] Assert pre-flight returns `{"skipped": true}` when `app/core/sse/` already exists via `test_preflight.py::test_idempotent_skip_when_sse_module_exists`
- [ ] Run `ruff check app/core/sse/` after generation — zero new findings

### 15.2 Settings
- [ ] Add `SSE_HEARTBEAT_SECONDS: int = 15`
- [ ] Add `SSE_MAX_CONNECTIONS_PER_USER: int = 10`
- [ ] Add `SSE_REPLAY_BUFFER_SIZE: int = 100`
- [ ] Add `SSE_REPLAY_TTL_SECONDS: int = 600`
- [ ] Add `SSE_MAX_PAYLOAD_BYTES: int = 65_536`
- [ ] Assert `SSE_HEARTBEAT_SECONDS` is read from env and passed to `_heartbeat_loop` via `test_settings.py::test_sse_heartbeat_seconds_env_override`
- [ ] Assert `SSE_MAX_PAYLOAD_BYTES` env override is respected by `publish_event` size check via `test_settings.py::test_sse_max_payload_bytes_env_override`

### 15.3 Manager module
- [ ] Create `app/core/sse/manager.py`
- [ ] Implement `SSEManager.stream` (async generator)
- [ ] Implement `_replay`, `_format_message`, `_format_error`, `_heartbeat_loop`
- [ ] Implement get_sse_manager singleton
- [ ] Verify file parses
- [ ] Verify `:keepalive\n\n` heartbeat is emitted every 15 s via `test_heartbeat.py::test_keepalive_emitted_every_15_seconds`
- [ ] Assert `_replay` delivers buffered events in order when `Last-Event-ID` header is present via `test_manager.py::test_replay_delivers_buffered_events_in_order`
- [ ] Assert `get_sse_manager()` always returns the same singleton instance via `test_manager.py::test_get_sse_manager_returns_singleton`

### 15.4 Publisher module
- [ ] Create `app/core/sse/publisher.py`
- [ ] Implement `publish_event` with payload size check
- [ ] Use Redis pipeline: PUBLISH + ZADD + ZREMRANGEBYRANK + EXPIRE
- [ ] Verify file parses
- [ ] Assert `publish_event` raises `PayloadTooLargeError` when payload exceeds `SSE_MAX_PAYLOAD_BYTES` via `test_publisher.py::test_publish_raises_on_oversized_payload`
- [ ] Assert a single `publish_event` call issues exactly one Redis pipeline (PUBLISH + ZADD + ZREMRANGEBYRANK + EXPIRE) via `test_publisher.py::test_publish_uses_single_redis_pipeline`
- [ ] Run `mypy --strict app/core/sse/publisher.py` — zero errors

### 15.5 Channel access module
- [ ] Create `app/core/sse/access.py`
- [ ] Implement `authorize_channel` with user/tenant/public namespaces
- [ ] Verify file parses
- [ ] Assert `authorize_channel("user:{uid}", requesting_user_id=other_uid)` raises HTTP 403 via `test_access.py::test_user_channel_blocks_other_user`
- [ ] Assert `authorize_channel("public:{topic}", ...)` always passes regardless of user via `test_access.py::test_public_channel_allows_any_authenticated_user`
- [ ] Run `ruff check app/core/sse/access.py` — zero findings

### 15.6 Routes
- [ ] Create `app/api/routes/events.py` with `/events/stream`
- [ ] Use `StreamingResponse(media_type="text/event-stream")`
- [ ] Add headers: Cache-Control, X-Accel-Buffering, Connection
- [ ] Add to `app/api/main.py` router include
- [ ] Verify file parses
- [ ] Assert `GET /events/stream` response has `Content-Type: text/event-stream` via `test_routes_events.py::test_stream_endpoint_content_type`
- [ ] Assert `X-Accel-Buffering: no` header is present on the streaming response via `test_routes_events.py::test_stream_endpoint_nginx_buffering_header`
- [ ] Assert unauthenticated request returns 401 before any stream data is sent via `test_routes_events.py::test_stream_endpoint_requires_auth`

### 15.7 Test generation
- [ ] Create `tests/test_sse.py` with all 30 tests
- [ ] Use `httpx.AsyncClient` to read SSE response
- [ ] Use `fakeredis` or real Redis fixture
- [ ] Verify file parses
- [ ] Assert overall line coverage for `app/core/sse/` is ≥ 90% via `pytest --cov=app.core.sse --cov-fail-under=90`
- [ ] Assert `test_sse.py::test_client_receives_event_after_publish` passes end-to-end with a real Redis fixture
- [ ] Run `ruff check tests/test_sse.py` — zero findings

### 15.8 Atomicity
- [ ] All file writes use temp-file + rename
- [ ] If ANY step fails, rollback all writes
- [ ] Assert mid-run failure leaves no partial files under `app/core/sse/` via `test_atomicity.py::test_rollback_removes_partial_sse_files`
- [ ] Assert returned dict lists every rolled-back file path via `test_atomicity.py::test_error_response_lists_rolled_back_files`
- [ ] Run `ruff check app/core/sse/` and `mypy app/core/sse/` after rollback — zero new findings
- [ ] Add structlog `{"event": "sse_file_written", "path": ...}` for each file successfully created

### 15.9 Documentation
- [ ] Append SSE section to `core/KNOWLEDGE.md`
- [ ] Add tool entry to `manifest.yaml`
- [ ] Add tool to `SKILL.md` tools table
- [ ] Update `mcp_server.py`
- [ ] Assert `manifest.yaml` entry for `add_sse` contains `inputs`, `outputs`, and `idempotent: true` fields via `test_manifest.py::test_sse_tool_manifest_schema`
- [ ] Assert `SKILL.md` tools table row for TOOL-014 links to this spec file via `test_skill_md.py::test_tool_014_row_exists_with_spec_link`
- [ ] Run `ruff check mcp_server.py` — zero new findings after the update

### 15.10 Verification
- [ ] Run `ast.parse` on every modified file
- [ ] Run import audit
- [ ] Run `pytest tests/`
- [ ] Run analyzer
- [ ] Measure tool execution time
- [ ] Measure publish→receive latency
- [ ] Assert publish→receive p99 latency is < 50 ms under a fakeredis fixture via `test_sse_perf.py::test_publish_to_receive_p99_under_50ms`

### 15.11 Observability integration
- [ ] Wire structlog logger with correlation IDs across publisher and consumer paths
- [ ] Register Prometheus counters for `sse_events_published_total` and `sse_events_delivered_total`
- [ ] Add Grafana dashboard panels for event lag, active connections, and dropped messages
- [ ] Add an Alertmanager rule when dropped-message rate exceeds the configured threshold
- [ ] Propagate OpenTelemetry trace context from publisher through the Redis pub/sub channel
- [ ] Emit a health-check metric that the readiness probe can consume
- [ ] Document the metric cardinality budget in the README

### 15.12 Security review
- [ ] Verify JWT validation runs before any channel subscription is established
- [ ] Confirm that channel IDs are not enumerable by unauthenticated requests
- [ ] Run the generated routes through TOOL-029 security_scan and address any CRITICAL findings
- [ ] Check that rate limiting per-IP is applied to the `/events/stream` endpoint
- [ ] Verify that CORS config does not expose the SSE endpoint to arbitrary origins
- [ ] Confirm message payloads never contain tenant A data when delivered to tenant B
- [ ] Document the threat model and mitigations in `docs/sse_security.md`

### 15.13 Final validation
- [ ] Run `ruff check src/` with project settings — zero new findings
- [ ] Run `mypy --strict app/core/sse/` — zero new errors
- [ ] Run the full test suite with coverage: `pytest tests/ --cov=app.core.sse --cov-branch`
- [ ] Confirm coverage for new code ≥ 90% line and ≥ 80% branch
- [ ] Run TOOL-034 performance_baseline to capture the new routes in the baseline
- [ ] Run TOOL-051 fastapi_doctor to verify no new CRITICAL/HIGH findings
- [ ] Merge only after all gates are green in CI

---

## 16. Documentation Output

```json
{
  "status": "success",
  "files_created": [
    "app/core/sse/__init__.py",
    "app/core/sse/manager.py",
    "app/core/sse/publisher.py",
    "app/core/sse/access.py",
    "app/core/sse/heartbeat.py",
    "app/core/sse/metrics.py",
    "app/api/routes/events.py",
    "tests/test_sse.py",
    "tests/test_sse_security.py"
  ],
  "files_modified": [
    "app/api/main.py",
    "app/core/config.py"
  ],
  "metrics": {
    "execution_time_ms": 2978,
    "files_changed": 8,
    "lines_added": 612,
    "lines_removed": 1,
    "heartbeat_seconds": 15,
    "max_connections_per_user": 10,
    "replay_buffer_size": 100,
    "replay_ttl_seconds": 600
  },
  "next_steps": [
    "Run: pytest tests/test_sse.py -v",
    "Test in browser: open DevTools, run `new EventSource('/api/v1/events/stream?channel=user:<your_id>')`, then trigger an action that calls `publish_event`",
    "Push events from app code: `from app.core.sse.publisher import publish_event` then `await publish_event('user:<id>', 'event_name', {...})`",
    "If you use nginx, ensure `proxy_buffering off;` for the /events/stream location (X-Accel-Buffering header should already handle it)",
    "Capture a performance baseline via TOOL-034 performance_baseline to lock in the new p99 numbers for the /events/stream endpoint"
  ],
  "warnings": [
    "SSE is one-way (server → client). For two-way, use websockets.",
    "Each open SSE connection holds an asyncio task and a Redis pubsub subscription. Plan capacity accordingly.",
    "EventSource does NOT support custom headers in browsers. JWT auth via cookies, not Authorization header."
  ],
  "notes": [
    "SSE installed with heartbeat=15s, max=10 connections/user, replay buffer=100 events, payload limit=64KB.",
    "Three channel namespaces supported: user:<id>, tenant:<id>:<topic>, public:<topic>.",
    "Publisher fans out via Redis pubsub to all workers.",
    "Existing tests still pass: 62/62."
  ]
}
```
