# Module: WebSockets — Production Real-Time Communication for FastAPI

> The LLM generates: a bare `@app.websocket` with no auth, no heartbeat, no error handling, no rooms.
> The staff engineer knows: auth on connect, ping-pong heartbeat, Redis pub/sub for multi-worker broadcast, reconnection with backoff, connection limits, graceful shutdown.

---

## 1. WebSocket Auth — Validate JWT on Connect, Not on Every Message

### WHY
The browser WebSocket API does not support custom `Authorization` headers. You cannot use your regular `OAuth2PasswordBearer` dependency — it reads the `Authorization` header, which WebSocket handshake requests do not carry. The LLM generates WebSocket endpoints with no auth at all. The staff engineer validates the JWT during the initial connection handshake (via query parameter or first-message protocol) and rejects unauthorized connections before they consume server resources.

### HOW
```python
from fastapi import WebSocket, WebSocketDisconnect, Query, status
import jwt

async def authenticate_ws(websocket: WebSocket, token: str | None) -> dict | None:
    """Validate JWT token for WebSocket connection. Returns payload or None."""
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        if payload.get("type") != "access":
            return None
        return payload
    except jwt.InvalidTokenError:
        return None

@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str | None = Query(default=None),
):
    # Authenticate BEFORE accepting the connection
    payload = await authenticate_ws(websocket, token)
    if payload is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    user_id = payload["sub"]
    # ... message loop ...
```

### GOTCHA
The token is visible in the URL when passed as a query parameter (`wss://api.com/ws?token=eyJ...`). Use short-lived tokens (60 seconds) specifically for WS connection, not your regular 15-minute access token. Generate a one-time WS token via an authenticated HTTP endpoint: `POST /ws/ticket` returns a token valid for 60 seconds, single use.

---

## 2. Connection Lifecycle — Connect, Message Loop, Disconnect, Error Handling

### WHY
The LLM generates a bare `while True: data = await websocket.receive_text()` with no error handling. In production, WebSocket connections drop due to network issues, client crashes, idle timeouts, and server deploys. Every connection must have explicit handling for all lifecycle events, with proper cleanup of resources (remove from room, close DB connections, cancel background tasks).

### HOW
```python
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = Query()):
    payload = await authenticate_ws(websocket, token)
    if not payload:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    user_id = payload["sub"]
    manager.connect(user_id, websocket)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                message = WSMessage.model_validate_json(raw)
                await handle_message(user_id, message, websocket)
            except ValidationError as exc:
                await websocket.send_json({"error": "invalid_message", "detail": str(exc)})
    except WebSocketDisconnect:
        # Client disconnected normally (close frame received)
        pass
    except Exception:
        # Unexpected error — log and close
        import logging
        logging.exception(f"WebSocket error for user {user_id}")
    finally:
        # ALWAYS clean up, regardless of how the connection ended
        manager.disconnect(user_id)
```

### GOTCHA
`websocket.receive_text()` raises `WebSocketDisconnect` on clean close AND on network drop. But `websocket.send_text()` can also raise if the connection is already closed. Wrap ALL sends in try/except — a failed send during iteration over room members should not crash the broadcast loop for other members.

---

## 3. Heartbeat/Ping-Pong — Detect Dead Connections

### WHY
TCP connections can go half-open — the server thinks the client is connected, but packets are being silently dropped (NAT timeout, mobile switching networks, laptop lid close). Without heartbeat, these dead connections accumulate forever, consuming memory and connection slots. The server-side ping at regular intervals detects dead connections within one ping cycle.

### HOW
```python
import asyncio

HEARTBEAT_INTERVAL = 30  # seconds
HEARTBEAT_TIMEOUT = 10   # seconds to wait for pong

async def heartbeat_loop(websocket: WebSocket, user_id: str):
    """Send periodic pings. If pong is not received, connection is dead."""
    try:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            try:
                # WebSocket protocol-level ping (not application message)
                await asyncio.wait_for(
                    websocket.send_json({"type": "ping", "ts": time.time()}),
                    timeout=HEARTBEAT_TIMEOUT,
                )
            except (asyncio.TimeoutError, Exception):
                # Connection is dead — close it
                await websocket.close(code=1001)
                break
    except asyncio.CancelledError:
        pass  # Task cancelled during shutdown

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = Query()):
    # ... auth ...
    await websocket.accept()

    # Spawn heartbeat as background task
    heartbeat_task = asyncio.create_task(heartbeat_loop(websocket, user_id))

    try:
        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            if msg.get("type") == "pong":
                continue  # Heartbeat response — don't process
            await handle_message(user_id, msg, websocket)
    except WebSocketDisconnect:
        pass
    finally:
        heartbeat_task.cancel()  # ALWAYS cancel the heartbeat on disconnect
        manager.disconnect(user_id)
```

### GOTCHA
The WebSocket protocol has its own Ping/Pong frames (opcode 0x9/0xA), but Starlette/uvicorn handle these at the ASGI layer, and they are not always reliable through proxies. Application-level ping/pong (JSON messages) is more portable and gives you RTT measurement. Always cancel the heartbeat task in `finally` to prevent task leaks.

---

## 4. Rooms and Broadcast — Pub/Sub Pattern with Redis

### WHY
In-memory broadcast works with a single uvicorn worker. But `uvicorn --workers 4` means 4 separate processes, each with its own `ConnectionManager` instance. Client A on worker 1 sends a message to room "general" — clients on workers 2, 3, 4 never see it. Redis Pub/Sub bridges workers: every worker subscribes to room channels and relays messages to its local connections.

### HOW
```python
import redis.asyncio as redis

class ConnectionManager:
    def __init__(self):
        self._rooms: dict[str, dict[str, WebSocket]] = {}  # room -> {user_id: ws}
        self._redis: redis.Redis | None = None

    async def init_redis(self, redis_url: str = "redis://localhost:6379"):
        self._redis = redis.from_url(redis_url)

    def connect(self, user_id: str, room: str, websocket: WebSocket):
        if room not in self._rooms:
            self._rooms[room] = {}
        self._rooms[room][user_id] = websocket

    def disconnect(self, user_id: str, room: str):
        if room in self._rooms:
            self._rooms[room].pop(user_id, None)
            if not self._rooms[room]:
                del self._rooms[room]

    async def broadcast_to_room(self, room: str, message: dict, exclude: str | None = None):
        """Send to all local connections AND publish to Redis for other workers."""
        # Local delivery
        await self._send_local(room, message, exclude)
        # Cross-worker delivery via Redis Pub/Sub
        if self._redis:
            await self._redis.publish(f"ws:room:{room}", json.dumps(message))

    async def _send_local(self, room: str, message: dict, exclude: str | None = None):
        dead: list[str] = []
        for uid, ws in self._rooms.get(room, {}).items():
            if uid == exclude:
                continue
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(uid)
        for uid in dead:
            self.disconnect(uid, room)

    async def listen_redis(self):
        """Subscribe to Redis channels and relay to local connections."""
        pubsub = self._redis.pubsub()
        await pubsub.psubscribe("ws:room:*")
        async for message in pubsub.listen():
            if message["type"] != "pmessage":
                continue
            room = message["channel"].decode().split(":", 2)[-1]
            data = json.loads(message["data"])
            await self._send_local(room, data)
```

### GOTCHA
Redis Pub/Sub is fire-and-forget — if a worker is down when a message is published, it misses it. For guaranteed delivery, use Redis Streams instead of Pub/Sub. Also: `psubscribe("ws:room:*")` pattern matching is O(N) per published message where N is the number of patterns. Use exact `subscribe` per room if you have many rooms.

---

## 5. Reconnection with Backoff — Client-Side Pattern

### WHY
WebSocket connections drop. The server deploys, the user's WiFi blips, a proxy times out. The client must reconnect automatically. Without backoff, a disconnected client hammers the server with connection attempts every millisecond. With exponential backoff + jitter, reconnection spreads naturally and converges quickly once the server is healthy.

### HOW
```typescript
// Client-side TypeScript — include this pattern in your WS KNOWLEDGE
class ReconnectingWebSocket {
  private ws: WebSocket | null = null;
  private attempt = 0;
  private maxAttempts = 10;

  connect(url: string) {
    this.ws = new WebSocket(url);
    this.ws.onopen = () => {
      this.attempt = 0;  // Reset backoff on successful connect
      // Re-subscribe to rooms, send last event ID for gap fill
    };
    this.ws.onclose = (event) => {
      if (event.code === 1008) return;  // Auth rejected — don't retry
      this.scheduleReconnect(url);
    };
  }

  private scheduleReconnect(url: string) {
    if (this.attempt >= this.maxAttempts) return;
    // Exponential backoff: 1s, 2s, 4s, 8s, 16s, capped at 30s
    const delay = Math.min(30000, 1000 * Math.pow(2, this.attempt));
    const jitter = delay * 0.3 * Math.random();
    this.attempt++;
    setTimeout(() => this.connect(url), delay + jitter);
  }
}
```

```python
# Server-side: support reconnection with last-event-id
@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(),
    last_event_id: str | None = Query(default=None),
):
    # ... auth, accept ...
    if last_event_id:
        # Replay missed events from Redis Stream since last_event_id
        missed = await redis.xrange("events:user:{user_id}", min=last_event_id)
        for event_id, data in missed:
            await websocket.send_json({"event_id": event_id, **data})
    # ... normal message loop ...
```

### GOTCHA
On reconnect, the client needs a FRESH token (the old one may have expired during downtime). The reconnection flow should be: detect disconnect -> get new WS ticket via HTTP -> reconnect with new ticket + last_event_id. Close code 1008 (Policy Violation) means auth failed — don't retry.

---

## 6. Connection Limiting — Max Connections per User/IP

### WHY
Without limits, a single user can open 1000 WebSocket connections and exhaust server memory. A malicious actor can DoS your WebSocket endpoint by opening connections without sending data. Limit connections per user (typically 3-5 for multi-device) and per IP (higher, but bounded).

### HOW
```python
class ConnectionManager:
    MAX_PER_USER = 5
    MAX_PER_IP = 20

    def __init__(self):
        self._connections: dict[str, list[WebSocket]] = {}  # user_id -> [ws, ...]
        self._ip_counts: dict[str, int] = {}                # ip -> count

    async def can_connect(self, user_id: str, ip: str) -> tuple[bool, str]:
        user_count = len(self._connections.get(user_id, []))
        ip_count = self._ip_counts.get(ip, 0)

        if user_count >= self.MAX_PER_USER:
            return False, f"Max {self.MAX_PER_USER} connections per user"
        if ip_count >= self.MAX_PER_IP:
            return False, f"Max {self.MAX_PER_IP} connections per IP"
        return True, "ok"

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = Query()):
    payload = await authenticate_ws(websocket, token)
    if not payload:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    ip = websocket.client.host if websocket.client else "unknown"
    allowed, reason = await manager.can_connect(payload["sub"], ip)
    if not allowed:
        await websocket.close(code=status.WS_1013_TRY_AGAIN_LATER, reason=reason)
        return

    await websocket.accept()
    # ...
```

### GOTCHA
`websocket.client.host` returns the direct connection IP. Behind a reverse proxy, this is always the proxy's IP. Configure your proxy to pass `X-Forwarded-For` and read it from `websocket.headers.get("x-forwarded-for", "").split(",")[0].strip()`. Also: close code `1013 Try Again Later` tells the client it can retry — use `1008 Policy Violation` for permanent rejection (bad auth).

---

## 7. Message Validation — Pydantic Models for WS Messages

### WHY
The LLM generates `data = await websocket.receive_text()` and treats it as a raw string. In production, WebSocket messages need the same validation as HTTP request bodies: type checking, field constraints, enum validation. Without validation, malformed messages cause unhandled exceptions that crash the connection.

### HOW
```python
from pydantic import BaseModel, Field
from enum import Enum
from typing import Literal

class WSAction(str, Enum):
    SUBSCRIBE = "subscribe"
    UNSUBSCRIBE = "unsubscribe"
    MESSAGE = "message"
    TYPING = "typing"

class WSIncoming(BaseModel):
    """All incoming WebSocket messages must match this schema."""
    action: WSAction
    room: str = Field(max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    payload: dict | None = None

class WSOutgoing(BaseModel):
    """All outgoing WebSocket messages use this schema."""
    event: str
    room: str | None = None
    data: dict
    timestamp: float = Field(default_factory=time.time)

async def handle_ws_message(websocket: WebSocket, raw: str, user_id: str):
    try:
        msg = WSIncoming.model_validate_json(raw)
    except ValidationError as exc:
        await websocket.send_json({
            "event": "error",
            "data": {"code": "INVALID_MESSAGE", "detail": exc.errors()},
        })
        return

    match msg.action:
        case WSAction.SUBSCRIBE:
            manager.connect(user_id, msg.room, websocket)
        case WSAction.UNSUBSCRIBE:
            manager.disconnect(user_id, msg.room)
        case WSAction.MESSAGE:
            await manager.broadcast_to_room(msg.room, {
                "event": "message", "data": msg.payload, "from": user_id,
            })
```

### GOTCHA
Limit message size on the server side. Uvicorn's default WebSocket max message size is 16MB — set `--ws-max-size 65536` (64KB) for typical chat/notification use. Without this, a client can send a 16MB JSON payload and force your server to parse it.

---

## 8. Binary vs Text Messages — When to Use Which

### WHY
WebSocket supports two frame types: text (UTF-8 encoded) and binary (raw bytes). JSON over text frames is the default and easiest to debug. Binary frames (MessagePack, Protobuf) reduce bandwidth 30-60% and parse faster, but are harder to inspect in browser DevTools. Use text for human-readable protocols (chat, notifications) and binary for high-throughput data streams (live data feeds, file transfers).

### HOW
```python
import msgpack  # pip install msgpack

# Text mode — JSON (default, human-readable)
@app.websocket("/ws/chat")
async def chat_ws(websocket: WebSocket):
    await websocket.accept()
    while True:
        data = await websocket.receive_json()  # Automatic JSON parse
        await websocket.send_json({"echo": data})

# Binary mode — MessagePack (compact, fast)
@app.websocket("/ws/data-feed")
async def data_feed_ws(websocket: WebSocket):
    await websocket.accept()
    while True:
        raw = await websocket.receive_bytes()
        message = msgpack.unpackb(raw, raw=False)
        response = process_data(message)
        await websocket.send_bytes(msgpack.packb(response))
```

### GOTCHA
Do NOT mix text and binary frames on the same connection without a clear protocol. The client must know which type to expect. If you need both (e.g., JSON control messages + binary file chunks), use a type prefix byte in binary mode: `b'\x01' + json_bytes` for control, `b'\x02' + file_bytes` for data.

---

## 9. Graceful Shutdown — Drain WS Connections on Deploy

### WHY
When you deploy new code, uvicorn sends SIGTERM to workers. Without graceful shutdown, all WebSocket connections are killed instantly — clients see an error, not a clean close. Graceful shutdown sends close frames to all connected clients with a "going away" code, waits for acknowledgment, then shuts down. Clients with proper reconnection logic reconnect to the new worker automatically.

### HOW
```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await manager.init_redis("redis://localhost:6379")
    redis_listener = asyncio.create_task(manager.listen_redis())
    yield
    # Shutdown — gracefully close all WebSocket connections
    redis_listener.cancel()
    await manager.close_all_connections(code=1001, reason="Server shutting down")

async def close_all_connections(self, code: int = 1001, reason: str = ""):
    """Close all active connections gracefully."""
    tasks = []
    for room, connections in self._rooms.items():
        for user_id, ws in connections.items():
            tasks.append(self._safe_close(ws, code, reason))
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    self._rooms.clear()

async def _safe_close(self, ws: WebSocket, code: int, reason: str):
    try:
        await asyncio.wait_for(ws.close(code=code, reason=reason), timeout=5.0)
    except Exception:
        pass  # Connection already closed or unresponsive
```

### GOTCHA
Close code 1001 ("Going Away") tells the client this is a server-initiated shutdown, not an error. Well-behaved clients will reconnect. Set a uvicorn `--timeout-graceful-shutdown 30` to give connections 30 seconds to drain. Without this, uvicorn kills connections immediately after SIGTERM.

---

## 10. Testing WebSockets — pytest with httpx + TestClient

### WHY
WebSocket code is notoriously under-tested because the LLM doesn't generate WS tests. Starlette's `TestClient` supports WebSocket testing natively — no need for a running server. You can test connection auth, message handling, room broadcast, error cases, and close codes in fast, in-process tests.

### HOW
```python
import pytest
from fastapi.testclient import TestClient

def test_ws_auth_required():
    """Unauthenticated connection is rejected with 1008."""
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws"):  # No token
            pass
    # Connection should be rejected — check that it didn't accept
    # Note: exact behavior depends on close-before-accept vs accept-then-close

def test_ws_echo():
    """Authenticated connection can send and receive messages."""
    client = TestClient(app)
    token = create_test_token(user_id="test-user")
    with client.websocket_connect(f"/ws?token={token}") as ws:
        ws.send_json({"action": "message", "room": "test", "payload": {"text": "hello"}})
        response = ws.receive_json()
        assert response["event"] == "message"
        assert response["data"]["text"] == "hello"

def test_ws_invalid_message():
    """Invalid message format returns error, doesn't crash connection."""
    client = TestClient(app)
    token = create_test_token(user_id="test-user")
    with client.websocket_connect(f"/ws?token={token}") as ws:
        ws.send_text("not valid json {{{")
        response = ws.receive_json()
        assert response["event"] == "error"
        assert response["data"]["code"] == "INVALID_MESSAGE"
        # Connection should still be alive
        ws.send_json({"action": "message", "room": "test", "payload": {}})
        response = ws.receive_json()
        assert response["event"] == "message"
```

### GOTCHA
`TestClient.websocket_connect()` is synchronous (uses `anyio`). You cannot test true async behaviors (heartbeat timing, concurrent connections from multiple users) with `TestClient`. For those, use `pytest-asyncio` with `httpx.AsyncClient` and `websockets` library connecting to a real uvicorn instance.
