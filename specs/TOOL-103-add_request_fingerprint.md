---
spec_id: "TOOL-103"
tool_name: "add_request_fingerprint"
version: "1.0.0"
status: "ratified"
invariants:
  - "INV-FP-01"
  - "INV-FP-02"
  - "INV-FP-03"
  - "INV-FP-04"
  - "INV-FP-05"
  - "INV-FP-06"
  - "INV-FP-07"
  - "INV-FP-08"
  - "INV-FP-09"
  - "INV-FP-10"
completeness_criteria:
  - "CC-01"
  - "CC-02"
  - "CC-03"
  - "CC-04"
  - "CC-05"
  - "CC-06"
  - "CC-07"
  - "CC-08"
  - "CC-09"
  - "CC-10"
  - "CC-11"
  - "CC-12"
  - "CC-13"
  - "CC-14"
  - "CC-15"
  - "CC-16"
  - "CC-17"
  - "CC-18"
  - "CC-19"
  - "CC-20"
  - "CC-21"
  - "CC-22"
  - "CC-23"
  - "CC-24"
  - "CC-25"
quality_standards:
  - "QS-1"
  - "QS-10"
  - "QS-11"
  - "QS-12"
  - "QS-2"
  - "QS-3"
  - "QS-4"
  - "QS-5"
  - "QS-6"
  - "QS-7"
  - "QS-8"
  - "QS-9"
test_plan:
  - "T-01"
  - "T-02"
  - "T-03"
  - "T-04"
  - "T-05"
  - "T-06"
  - "T-07"
  - "T-08"
  - "T-09"
  - "T-10"
  - "T-11"
  - "T-12"
  - "T-13"
  - "T-14"
  - "T-15"
  - "T-16"
  - "T-17"
  - "T-18"
  - "T-19"
  - "T-20"
  - "T-21"
  - "T-22"
  - "T-23"
  - "T-24"
  - "T-25"
tags:
  - "performance"
  - "payments"
  - "data"
  - "resiliency"
  - "realtime"
---
# TOOL-103: add_request_fingerprint

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_request_fingerprint` |
| Category | EXTEND > Infrastructure |
| Complexity | Medium |
| Dependencies | FastAPI, Redis (lazy import only), pydantic-settings |
| Signature | `add_request_fingerprint(inp: ToolInput) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path to FastAPI project root) and optional `dry_run` flag |
| MCP descriptor | `{"name": "fastapi_add_request_fingerprint", "description": "Add SHA-256 request fingerprinting for deduplication of duplicate POST/PUT/PATCH requests with Redis primary and in-memory fallback store.", "tags": ["extend", "infrastructure"], "entry": "add_request_fingerprint"}` |
| Files created (typical) | 4 — `app/fingerprint/__init__.py`, `app/fingerprint/hasher.py`, `app/fingerprint/store.py`, `app/middleware/fingerprint.py` |
| Files modified (typical) | 1 — `app/core/config.py` |

---

## 2. Purpose

The `fastapi_add_request_fingerprint` tool installs idempotent request deduplication into a FastAPI project using SHA-256 content fingerprinting. Idempotent write APIs — REST `PUT`, payment submissions, form registrations — are vulnerable to duplicate submissions from several sources simultaneously: browser double-clicks before the first response arrives, mobile client retry-on-reconnect logic after a network interruption, load balancer retransmissions, and automated API clients with misconfigured exponential backoff that retransmit before receiving the first response. An explicit `Idempotency-Key` header solves this for API callers who know to send it, but most clients do not, and "just check for duplicates in the database" is too application-coupled and too slow to work as a general middleware solution.

The generated `RequestFingerprinter` computes a 64-character hex SHA-256 digest from `f"{user_id}:{method.upper()}:{path}:{normalized_body}"`. The body is normalized by parsing with `json.loads` then re-serializing with `json.dumps(sort_keys=True, separators=(",", ":"))` so that `{"a":1,"b":2}` and `{"b":2,"a":1}` produce identical fingerprints. Non-JSON bodies are passed through as UTF-8 strings. `user_id` is extracted from `request.state.user.id` when auth middleware has set it; otherwise falls back to `"anonymous"` which provides path-level deduplication. User isolation is critical: two different users submitting the same payload to the same endpoint must get different fingerprints and different responses.

`FingerprintStore` has a Redis primary path and an in-process `_MemoryStore` fallback. The Redis path uses `SET key "1" NX EX ttl_s` — atomic SET if Not eXists with TTL. `is_duplicate(fingerprint)` returns `True` if the key already existed (duplicate) or `False` and atomically marks the fingerprint as seen (first-time). If Redis returns an error, the store transparently falls back to the `_MemoryStore`. `init_store()` imports `redis.asyncio` lazily — there is no top-level `import redis` in `store.py`. The `_MemoryStore` uses a `dict[str, float]` mapping fingerprint to expiry timestamp with a `threading.Lock` for thread safety; it prunes expired entries when the map exceeds 10 000 entries.

`FingerprintMiddleware` only processes HTTP methods in `_DEFAULT_METHODS = {"POST", "PUT", "PATCH"}` (configurable via `FINGERPRINT_METHODS`). For first-time requests: calls `call_next`, reads the `body_iterator`, caches `(status_code, body, content_type)` in `_response_cache`, and returns the response. For duplicate requests: returns the cached response immediately with `Idempotent-Replayed: true` header — no route handler is called. The response cache is pruned when it exceeds 5 000 entries (oldest 1 000 entries removed) to prevent unbounded memory growth.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | CI budget |
| Files created | ≥ 4 | fingerprint package (3 files) + middleware (CC-04) |
| Files modified | ≥ 1 | Config patch (CC-05) |
| Max function LOC | ≤ 50 | AST walk enforced |
| SHA-256 fingerprint computation | < 0.1 ms | `hashlib.sha256` is C-accelerated |
| Redis `SET NX EX` round-trip | < 5 ms | Single atomic Redis command |
| Memory store `is_duplicate` | < 0.01 ms | Dict lookup + `time.monotonic()` comparison |
| Response replay from cache | < 0.5 ms | Dict lookup + `Response(...)` construction |
| Response cache max entries | 5 000 | Pruned to 4 000 on overflow |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
app/
├── main.py
├── core/config.py        # No FINGERPRINT_* settings
└── middleware/            # No FingerprintMiddleware
```

No deduplication. A mobile client retries a payment POST on network reconnect → double charge. A browser double-click on a form submits two identical records → duplicate user registration.

### 4.2 `RequestFingerprinter` (SHA-256, sort_keys normalization): AFTER

```python
# app/fingerprint/hasher.py
"""RequestFingerprinter: SHA-256 hash of user_id+method+path+sorted(body)."""
from __future__ import annotations

import hashlib
import json
import logging

logger = logging.getLogger(__name__)


class RequestFingerprinter:
    """Compute a deterministic SHA-256 fingerprint for an HTTP request.

    Deterministic: same input always produces same hash.
    Collision-resistant: JSON body key order does not affect fingerprint.
    User-isolated: different user IDs produce different fingerprints.
    """

    def compute(self, user_id: str | None, method: str, path: str,
                body: bytes | str) -> str:
        """Compute a 64-char hex fingerprint.

        Args:
            user_id: Authenticated user ID, or None for anonymous.
            method: HTTP method (uppercase).
            path: Full request path including query string.
            body: Raw request body bytes or string.

        Returns:
            64-character lowercase hex SHA-256 digest.
        """
        uid = user_id or "anonymous"
        norm_body = self._normalize_body(body)
        raw = f"{uid}:{method.upper()}:{path}:{norm_body}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _normalize_body(self, body: bytes | str) -> str:
        """Normalize body to canonical string for hashing.

        JSON dicts normalized with sorted keys so that
        {"b":1,"a":2} and {"a":2,"b":1} produce the same hash.
        """
        text = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else body
        if not text:
            return ""
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                return json.dumps(obj, sort_keys=True, separators=(",", ":"))
            return json.dumps(obj, separators=(",", ":"))
        except Exception:
            return text
```

### 4.3 `_MemoryStore` and `FingerprintStore`: AFTER

```python
# app/fingerprint/store.py
"""FingerprintStore: Redis SET with TTL, in-memory fallback."""
from __future__ import annotations

import logging
import time
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)

_store: "FingerprintStore | None" = None
_REDIS_KEY_PREFIX = "fingerprint:"


class _MemoryStore:
    """In-memory fingerprint store (single-process fallback)."""

    def __init__(self) -> None:
        self._data: dict[str, float] = {}  # fingerprint -> expiry timestamp
        self._lock = Lock()

    async def exists(self, key: str) -> bool:
        with self._lock:
            exp = self._data.get(key)
            if exp is None:
                return False
            if time.monotonic() > exp:
                del self._data[key]
                return False
            return True

    async def set(self, key: str, ttl_s: int) -> None:
        with self._lock:
            self._data[key] = time.monotonic() + ttl_s
            if len(self._data) > 10000:
                now = time.monotonic()
                self._data = {k: v for k, v in self._data.items() if v > now}


class FingerprintStore:
    """Redis primary + _MemoryStore fallback."""

    def __init__(self, redis: Any | None = None, ttl_s: int = 60) -> None:
        self._redis = redis
        self._ttl_s = ttl_s
        self._memory = _MemoryStore()

    async def is_duplicate(self, fingerprint: str) -> bool:
        """Return True if fingerprint was seen within TTL; also records first-time."""
        key = _REDIS_KEY_PREFIX + fingerprint
        if self._redis is not None:
            try:
                was_set = await self._redis.set(key, "1", nx=True, ex=self._ttl_s)
                return was_set is None or was_set is False  # None = already existed
            except Exception:
                logger.warning("FingerprintStore Redis error — falling back to memory",
                               exc_info=True)
        already_seen = await self._memory.exists(fingerprint)
        if not already_seen:
            await self._memory.set(fingerprint, self._ttl_s)
        return already_seen


def get_store() -> "FingerprintStore | None":
    return _store


async def init_store(redis_url: str | None = None, ttl_s: int = 60) -> None:
    """Initialise global store. Redis imported lazily here."""
    global _store
    redis = None
    if redis_url:
        try:
            from redis.asyncio import Redis  # lazy — not at module top-level
            redis = Redis.from_url(redis_url, decode_responses=True)
        except Exception:
            logger.warning("FingerprintStore: Redis init failed, using memory",
                           exc_info=True)
    _store = FingerprintStore(redis=redis, ttl_s=ttl_s)
```

### 4.4 `FingerprintMiddleware` (dedup + replay): AFTER

```python
# app/middleware/fingerprint.py
"""FingerprintMiddleware: auto-dedup unsafe methods, replay cached response."""
from __future__ import annotations

import logging
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from app.fingerprint.hasher import RequestFingerprinter
from app.fingerprint.store import get_store

logger = logging.getLogger(__name__)

_FINGERPRINTER = RequestFingerprinter()
_DEFAULT_METHODS = {"POST", "PUT", "PATCH"}


class FingerprintMiddleware(BaseHTTPMiddleware):
    """Deduplicate requests by fingerprint; return cached response on duplicate."""

    def __init__(self, app, enabled_methods: set[str] | None = None) -> None:
        super().__init__(app)
        self._methods = enabled_methods or _DEFAULT_METHODS
        self._response_cache: dict[str, tuple[int, str, str]] = {}

    def _replay_cached(self, fp: str) -> Response:
        """Return cached Response with Idempotent-Replayed: true header."""
        cached = self._response_cache.get(fp)
        if cached:
            status_code, content, media_type = cached
            return Response(content=content, status_code=status_code,
                            media_type=media_type,
                            headers={"Idempotent-Replayed": "true"})
        return Response(content="", status_code=200,
                        headers={"Idempotent-Replayed": "true"})

    async def _capture_and_cache(self, fp: str, response: Response) -> Response:
        """Read body_iterator, cache (status, body, content_type), return Response."""
        chunks: list[bytes] = []
        async for chunk in response.body_iterator:  # type: ignore[attr-defined]
            chunks.append(chunk if isinstance(chunk, bytes) else chunk.encode())
        resp_body = b"".join(chunks).decode(errors="replace")
        self._response_cache[fp] = (
            response.status_code, resp_body,
            response.media_type or "application/json",
        )
        if len(self._response_cache) > 5000:
            for k in list(self._response_cache.keys())[:1000]:
                del self._response_cache[k]
        return Response(content=resp_body.encode(), status_code=response.status_code,
                        headers=dict(response.headers), media_type=response.media_type)

    async def dispatch(self, request: Request,
                       call_next: RequestResponseEndpoint) -> Response:
        if request.method.upper() not in self._methods:
            return await call_next(request)
        store = get_store()
        if store is None:
            return await call_next(request)
        try:
            body = await request.body()
        except Exception:
            body = b""
        user_id = str(request.state.user.id) if hasattr(request.state, "user") else None
        fp = _FINGERPRINTER.compute(user_id=user_id, method=request.method,
                                    path=str(request.url), body=body)
        if await store.is_duplicate(fp):
            return self._replay_cached(fp)
        response = await call_next(request)
        try:
            return await self._capture_and_cache(fp, response)
        except Exception:
            logger.debug("FingerprintMiddleware: body capture failed", exc_info=True)
            return response
```

### 4.5 Config patch: AFTER

```python
# app/core/config.py (fragment)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    # Request fingerprinting — added by add_request_fingerprint tool
    FINGERPRINT_ENABLED: bool = False
    FINGERPRINT_TTL_S: int = 60
    FINGERPRINT_METHODS: str = "POST,PUT,PATCH"
```

### 4.6 FastAPI lifespan wiring (caller pattern)

```python
# app/main.py (after tool runs)
import os
from contextlib import asynccontextmanager
from app.fingerprint.store import init_store
from app.middleware.fingerprint import FingerprintMiddleware


@asynccontextmanager
async def lifespan(app):
    if os.getenv("FINGERPRINT_ENABLED", "false").lower() == "true":
        await init_store(
            redis_url=os.getenv("REDIS_URL") or None,
            ttl_s=int(os.getenv("FINGERPRINT_TTL_S", "60")),
        )
    yield


app = FastAPI(lifespan=lifespan)
methods = set(os.getenv("FINGERPRINT_METHODS", "POST,PUT,PATCH").split(","))
app.add_middleware(FingerprintMiddleware, enabled_methods=methods)
```

### 4.7 Client-side experience: first vs duplicate request

```python
# First POST — processed normally
r1 = client.post("/api/v1/payments", json={"amount": 100, "currency": "USD"})
assert r1.status_code == 201
assert "Idempotent-Replayed" not in r1.headers

# Identical POST within TTL — deduplicated
r2 = client.post("/api/v1/payments", json={"currency": "USD", "amount": 100})
assert r2.status_code == 201
assert r2.headers["Idempotent-Replayed"] == "true"
# Note: same fingerprint because sort_keys normalization makes both bodies equal
```

### 4.8 JSON key order normalization demonstration

```python
from app.fingerprint.hasher import RequestFingerprinter

fp = RequestFingerprinter()

# These two bodies produce the same fingerprint
fp1 = fp.compute("u1", "POST", "/payments", b'{"a":1,"b":2}')
fp2 = fp.compute("u1", "POST", "/payments", b'{"b":2,"a":1}')
assert fp1 == fp2  # True — sort_keys normalization

# Different user → different fingerprint
fp3 = fp.compute("u2", "POST", "/payments", b'{"a":1,"b":2}')
assert fp1 != fp3  # True — user isolation
```

### 4.9 Memory fallback behavior without Redis

```python
# No Redis URL — init_store falls back to _MemoryStore
await init_store(redis_url=None, ttl_s=60)
store = get_store()
assert store is not None
assert store._redis is None  # Redis not connected
assert store._memory is not None  # _MemoryStore active

# Deduplication still works
fp = "abc123" * 10 + "abcd"  # 64 chars
assert await store.is_duplicate(fp) is False  # first-time
assert await store.is_duplicate(fp) is True   # duplicate
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | Idempotent on second run | `"RequestFingerprinter" in fingerprint/hasher.py` → `no_op` |
| QS-2 | `dry_run=True` zero writes | Early return before any `Path.write_text()` |
| QS-3 | All `.py` AST-parse clean | `_assert_parses` loop after creation |
| QS-4 | No function > 50 LOC | AST walk over all generated files |
| QS-5 | Redis imported lazily inside `init_store()` | No `import redis` at module top-level in `store.py` |
| QS-6 | JSON body normalized with `sort_keys=True` | `json.dumps(sort_keys=True)` in `_normalize_body()` |
| QS-7 | `Idempotent-Replayed: true` header on cache hit | `headers={"Idempotent-Replayed": "true"}` in `_replay_cached()` |
| QS-8 | `_MemoryStore` fallback when Redis absent or failing | Fallback in `is_duplicate()` after Redis error |
| QS-9 | User isolation via `user_id` in fingerprint | `f"{uid}:{method}:{path}:{body}"` in `compute()` |
| QS-10 | Config 4-space indent | `_patch_config` anchored on `ACCESS_TOKEN_EXPIRE_MINUTES` |
| QS-11 | `execution_time_ms` positive | `_elapsed_ms(start)` with `time.monotonic()` |
| QS-12 | Response cache pruned at 5 000 entries | Delete oldest 1 000 when `len > 5000` |

---

## 6. Completeness Criteria

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | `status="success"` on fresh project | `result.status == "success"` | T-01 |
| CC-02 | Second run → `no_op` | `r2.status == "no_op"` | T-02 |
| CC-03 | `dry_run=True` → zero writes | `before_tree == after_tree` | T-03 |
| CC-04 | ≥ 4 files created | `len(files_created) >= 4` | T-04 |
| CC-05 | ≥ 1 file modified | `len(files_modified) >= 1` | T-05 |
| CC-06 | All `.py` in `app/fingerprint/` parse | `ast.parse` loop | T-06 |
| CC-07 | No function > 50 LOC | AST walk | T-07 |
| CC-08 | `FINGERPRINT_ENABLED` in config, 4-space indent | Substring + indent check | T-08 |
| CC-09 | `models/__init__.py` not broken by install | Still parseable | T-09 |
| CC-10 | `FingerprintMiddleware` in `app/middleware/fingerprint.py` | Symbol search | T-10 |
| CC-11 | `RequestFingerprinter`, `sha256`, `hashlib` all in `hasher.py` | All three substrings | T-11 |
| CC-12 | `sort_keys` in `hasher.py` | JSON normalization present | T-12 |
| CC-13 | `FingerprintStore`, `_MemoryStore`, `is_duplicate` all in `store.py` | All three symbols | T-13 |
| CC-14 | Redis NOT at top-level in `store.py` | No `import redis` at module scope | T-14 |
| CC-15 | `is_duplicate` and `Idempotent-Replayed` both in middleware | Substring checks | T-15 |
| CC-16 | `POST`, `PUT`, `enabled_methods` all in middleware | Method filter present | T-16 |
| CC-17 | `fingerprint/__init__.py` exports `RequestFingerprinter`, `FingerprintStore` | Both symbols | T-17 |
| CC-18 | `ttl_s` or `TTL` in `store.py` | TTL expiry present | T-18 |
| CC-19 | All three `FINGERPRINT_*` config fields present | All three substring checks | T-19 |
| CC-20 | `user_id` in `hasher.py` | User isolation present | T-20 |
| CC-21 | `_MemoryStore` or memory fallback without Redis | Fallback path in `store.py` | T-21 |
| CC-22 | `notes` mention deduplication, idempotent, fingerprint, or SHA-256 | Token check | T-22 |
| CC-23 | `execution_time_ms > 0` | Positive integer check | T-23 |
| CC-24 | `next_steps` contains "fingerprint" or "FINGERPRINT" token | Token in joined string | T-24 |
| CC-25 | Second run leaves all `.py` parseable | `ast.parse` on all fingerprint + middleware files | T-25 |

---

## 7. Definition of Done (DoD)

- [ ] All CC-01 through CC-25 verified by `test_add_request_fingerprint.py`
- [ ] `RequestFingerprinter.compute()` normalizes JSON dicts with `sort_keys=True`
- [ ] Same JSON body with different key order produces identical fingerprint
- [ ] SHA-256 produces exactly 64-character hex digest
- [ ] `FingerprintStore.is_duplicate()` uses `SET NX EX` in Redis
- [ ] `_MemoryStore` fallback works when Redis is `None` or fails
- [ ] Redis imported lazily inside `init_store()` body only
- [ ] `FingerprintMiddleware` only deduplicates `POST`, `PUT`, `PATCH` by default
- [ ] `Idempotent-Replayed: true` header returned on cache hit
- [ ] `user_id` included in fingerprint computation for user isolation
- [ ] Response cache pruned to 4 000 entries when exceeding 5 000
- [ ] Config fields use 4-space indent inside `class Settings` body
- [ ] `execution_time_ms` is a positive integer
- [ ] `MCP_TOOL` descriptor present in source module

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-FP-01 | Idempotent on re-run | Fingerprint `"RequestFingerprinter"` in `hasher.py` → `no_op` | T-02, T-25 |
| INV-FP-02 | `dry_run=True` never writes | Early return before `Path.write_text()` | T-03 |
| INV-FP-03 | All generated `.py` pass `ast.parse` | `_assert_parses` loop | T-06, T-25 |
| INV-FP-04 | Redis NOT at module top-level | Lazy import inside `init_store()` | T-14, B-05 |
| INV-FP-05 | JSON body normalized with `sort_keys=True` | `json.dumps(sort_keys=True)` in `_normalize_body()` | T-12, B-02 |
| INV-FP-06 | `Idempotent-Replayed: true` on duplicate | `headers={"Idempotent-Replayed": "true"}` | T-15, B-08 |
| INV-FP-07 | Config inside `class Settings` body | 4-space indent enforcement | T-08 |
| INV-FP-08 | `execution_time_ms` MUST be positive | `_elapsed_ms(start)` | T-23 |
| INV-FP-09 | User isolation — `user_id` in fingerprint | `uid` included in raw hash input | T-20, B-09 |
| INV-FP-10 | Response cache pruned at 5 000 | Oldest 1 000 deleted on overflow | T-10 |

---

## 9. User Stories

### 9.1 Core installation (US-01 .. US-05)

**US-01: Successful install on fresh project**
- **Given:** A valid FastAPI project without fingerprint deduplication
- **When:** `add_request_fingerprint(ToolInput(project_dir="/path"))` is called
- **Then:** `result.status == "success"`, `len(result.files_created) >= 4` (CC-01, CC-04)

**US-02: Idempotent CI re-run**
- **Given:** Fingerprint deduplication already installed (first run succeeded)
- **When:** The tool is called a second time
- **Then:** `result.status == "no_op"`, no files modified (INV-FP-01)

**US-03: Dry-run preview**
- **Given:** A valid project
- **When:** `add_request_fingerprint(ToolInput(project_dir="/path", dry_run=True))` is called
- **Then:** `result.status == "success"`, filesystem is unchanged (INV-FP-02)

**US-04: All generated files syntactically valid**
- **Given:** A tool run that returns `status="success"`
- **When:** Each `files_created` path is loaded with `ast.parse()`
- **Then:** No `SyntaxError` raised (INV-FP-03)

**US-05: Redis not importable at module load time**
- **Given:** `redis-py` not installed in the Python environment
- **When:** `from app.fingerprint.store import FingerprintStore, get_store` is executed
- **Then:** No `ImportError` — Redis only imported inside `init_store()` (INV-FP-04)

### 9.2 Fingerprint computation mechanics (US-06 .. US-10)

**US-06: JSON body key order does not affect fingerprint**
- **Given:** Two requests with bodies `{"a":1,"b":2}` and `{"b":2,"a":1}`
- **When:** `RequestFingerprinter.compute()` called with both
- **Then:** Fingerprints are identical (INV-FP-05)

**US-07: Fingerprint is exactly 64 hexadecimal characters**
- **Given:** Any valid request input
- **When:** `compute(user_id, method, path, body)` returns
- **Then:** `len(fingerprint) == 64` and all characters are `[0-9a-f]`

**US-08: Non-JSON bodies passed through as-is**
- **Given:** Request body is plain text `"hello world"` (not JSON)
- **When:** `_normalize_body(b"hello world")` is called
- **Then:** Returns `"hello world"` — no exception raised

**US-09: `user_id=None` falls back to `"anonymous"`**
- **Given:** Request has no `request.state.user` attribute
- **When:** `FingerprintMiddleware` computes fingerprint
- **Then:** `uid = "anonymous"` — fingerprint is valid path-level deduplication

**US-10: Two users same body → different fingerprints (user isolation)**
- **Given:** Users `u1` and `u2` both send `POST /payments` with identical body
- **When:** Fingerprints computed for each
- **Then:** `fp(u1, ...) != fp(u2, ...)` — u1's request does not suppress u2's (INV-FP-09)

### 9.3 Store mechanics (US-11 .. US-15)

**US-11: Redis `SET NX EX` used for atomic first-write**
- **Given:** Redis connected, fingerprint not yet seen
- **When:** `is_duplicate(fp)` called
- **Then:** `SET fingerprint:... "1" NX EX ttl_s` executed; returns `True` (not duplicate, was recorded)

**US-12: Redis key already exists → duplicate detected**
- **Given:** Redis connected, `SET NX` returns `None` (key existed)
- **When:** `is_duplicate(fp)` called
- **Then:** Returns `True` — duplicate detected

**US-13: Redis failure falls back to `_MemoryStore`**
- **Given:** Redis raises an exception during `SET`
- **When:** `is_duplicate(fp)` called
- **Then:** Exception caught, warning logged, `_MemoryStore.exists()` called as fallback (QS-8)

**US-14: `_MemoryStore` deduplication works without Redis**
- **Given:** `init_store(redis_url=None)` — no Redis URL provided
- **When:** Two identical fingerprints submitted within TTL
- **Then:** Second `is_duplicate()` returns `True` — pure in-memory deduplication (CC-21)

**US-15: `_MemoryStore` prunes expired entries at 10 000 entries**
- **Given:** 10 001 entries added to `_MemoryStore`
- **When:** The 10 001st `set()` call runs
- **Then:** Map pruned to remove all expired entries; fresh entries retained

### 9.4 Middleware behavior (US-16 .. US-20)

**US-16: GET requests not fingerprinted**
- **Given:** `_DEFAULT_METHODS = {"POST", "PUT", "PATCH"}`
- **When:** `GET /items` processed by `FingerprintMiddleware`
- **Then:** Middleware passes through without fingerprint check (CC-16)

**US-17: First POST processed normally; second returns cached response**
- **Given:** Store initialised, `FINGERPRINT_ENABLED=true`
- **When:** First POST with body `{"amount": 100}` → 201 Created; second identical POST within TTL
- **Then:** Second returns 201 with `Idempotent-Replayed: true` header (INV-FP-06)

**US-18: GET `/healthz` never gets fingerprinted**
- **Given:** Any fingerprint configuration
- **When:** `GET /healthz` processed
- **Then:** Method `GET` not in `_DEFAULT_METHODS`; middleware passes through immediately

**US-19: Response cache pruned at 5 000 entries**
- **Given:** 5 001 unique fingerprints in `_response_cache`
- **When:** The 5 001st entry is added
- **Then:** Oldest 1 000 entries deleted; cache size returns to 4 000 (INV-FP-10)

**US-20: `store=None` — middleware passes through unchanged**
- **Given:** `init_store()` never called; `get_store()` returns `None`
- **When:** POST request arrives at `FingerprintMiddleware`
- **Then:** Middleware passes all requests through — no deduplication, no error

### 9.5 Ops and integration (US-21 .. US-25)

**US-21: Distributed deduplication across multiple pods with Redis**
- **Given:** 3 FastAPI pods all configured with same `REDIS_URL`
- **When:** Same client sends duplicate POST to pod A and then pod B within TTL
- **Then:** Pod B's Redis `SET NX` returns `None` — duplicate detected cross-pod

**US-22: In-memory store provides per-pod protection without Redis**
- **Given:** No `REDIS_URL` configured (development/testing)
- **When:** Same client sends duplicate POST twice within TTL to the same pod
- **Then:** Second request deduplicated by `_MemoryStore` — no Redis required

**US-23: Compatible with API replay debugger**
- **Given:** Both `RecorderMiddleware` and `FingerprintMiddleware` active
- **When:** Duplicate POST detected
- **Then:** `RecorderMiddleware` records the `Idempotent-Replayed: true` response; replay debugger shows dedup behavior

**US-24: Second run is idempotent and leaves files parseable**
- **Given:** First run succeeded
- **When:** Tool runs a second time (no_op), then all `.py` re-parsed
- **Then:** All fingerprint and middleware files pass `ast.parse()` (INV-FP-01, INV-FP-03)

**US-25: `execution_time_ms` positive in all outcomes**
- **Given:** Tool called in any mode (success, no_op, dry_run, error)
- **When:** `result.execution_time_ms` is read
- **Then:** Value is an integer > 0 (INV-FP-08)

---

## 10. Test Plan

### 10.1 Structural tests (`test_add_request_fingerprint.py`)

| # | Test ID | Test name | Expected |
|---|---------|-----------|----------|
| T-01 | CC-01 | `test_success_on_fresh_project` | `status="success"` |
| T-02 | CC-02 | `test_idempotent_second_run` | `status="no_op"` |
| T-03 | CC-03 | `test_dry_run_zero_writes` | Filesystem unchanged |
| T-04 | CC-04 | `test_files_created_count` | `len(files_created) >= 4` |
| T-05 | CC-05 | `test_files_modified_count` | `len(files_modified) >= 1` |
| T-06 | CC-06 | `test_fingerprint_py_files_parse` | All `.py` in `app/fingerprint/` parse |
| T-07 | CC-07 | `test_no_function_exceeds_50_loc` | AST walk: max function body ≤ 50 |
| T-08 | CC-08 | `test_fingerprint_config_fields_4space` | `FINGERPRINT_ENABLED` present, 4-space indent |
| T-09 | CC-09 | `test_models_init_not_broken` | `models/__init__.py` still parseable |
| T-10 | CC-10 | `test_middleware_created` | `FingerprintMiddleware` + `BaseHTTPMiddleware` |
| T-11 | CC-11 | `test_hasher_uses_sha256` | `RequestFingerprinter`, `sha256`, `hashlib` |
| T-12 | CC-12 | `test_hasher_normalizes_body_keys` | `sort_keys` in `hasher.py` |
| T-13 | CC-13 | `test_store_has_redis_and_memory_fallback` | `FingerprintStore`, `_MemoryStore`, `is_duplicate` |
| T-14 | CC-14 | `test_redis_sdk_lazy_in_store` | No top-level `import redis` in `store.py` |
| T-15 | CC-15 | `test_middleware_idempotent_replayed_header` | `is_duplicate` and `Idempotent-Replayed` |
| T-16 | CC-16 | `test_middleware_only_dedup_unsafe_methods` | `POST`, `PUT`, `enabled_methods` |
| T-17 | CC-17 | `test_fingerprint_init_exports` | Both symbols in `__init__` |
| T-18 | CC-18 | `test_store_has_ttl` | `ttl_s` or `TTL` in `store.py` |
| T-19 | CC-19 | `test_config_has_all_fingerprint_fields` | All three `FINGERPRINT_*` fields |
| T-20 | CC-20 | `test_hasher_includes_user_id` | `user_id` in `hasher.py` |
| T-21 | CC-21 | `test_store_works_without_redis` | `None` and `_MemoryStore` in `store.py` |
| T-22 | CC-22 | `test_notes_mention_dedup_and_idempotency` | Token check |
| T-23 | CC-23 | `test_execution_time_positive` | `execution_time_ms > 0` |
| T-24 | CC-24 | `test_next_steps_mention_fingerprint` | "fingerprint" or "FINGERPRINT" in `next_steps` |
| T-25 | CC-25 | `test_second_run_files_still_parse` | All fingerprint + middleware `.py` parse after second run |

### 10.2 Behavior tests (`test_add_request_fingerprint_behavior.py`)

| # | Test ID | Test name | Assertion |
|---|---------|-----------|-----------|
| B-01 | QS-1 | `test_healthz_returns_200` | `GET /healthz` → 200 OK |
| B-02 | INV-FP-05 | `test_hasher_deterministic_and_sort_keys` | Same body different order → same fp; `len(fp) == 64` |
| B-03 | CC-13 | `test_store_importable` | `FingerprintStore`, `get_store`, `init_store` importable |
| B-04 | CC-19 | `test_fingerprint_enabled_in_config` | `FINGERPRINT_ENABLED` in config source |
| B-05 | INV-FP-04 | `test_redis_not_at_top_level` | No `import redis` at module scope in `store.py` |
| B-06 | CC-07 | `test_no_function_exceeds_50_loc` | AST walk on all generated files |
| B-07 | CC-08 | `test_config_4space_indent` | Fields inside `class Settings` body |
| B-08 | INV-FP-06 | `test_idempotent_replayed_header_in_middleware` | `Idempotent-Replayed` header constant |
| B-09 | INV-FP-09 | `test_user_isolation` | Different user IDs → different fingerprints |
| B-10 | INV-FP-10 | `test_response_cache_pruned_at_5000` | Cache prune at 5 000 entries |

---

## 11. Interaction Matrix

| Other tool | Interaction type | Notes |
|------------|-----------------|-------|
| Explicit `Idempotency-Key` header | ⚠️ Overlap | Fingerprint deduplicates without client cooperation; idempotency keys require client to send header; use both for defence-in-depth |
| `add_api_replay_debugger` (TOOL-101) | ✅ Complementary | Stable SHA-256 fingerprint IDs useful as replay record references |
| `add_graceful_shutdown` (TOOL-100) | ✅ Neutral | Drain clears in-flight requests; cached response dict not Redis-backed so persists across drain |
| `add_chaos_testing` (TOOL-099) | ✅ Neutral | Chaos errors on first request; fingerprint marks it seen; replay returns cached error response |
| `add_anomaly_detector` (TOOL-102) | ✅ Neutral | Both use middleware; no direct interaction |
| `add_rate_limiting` | ✅ Complementary | Rate limiting by user+path; fingerprinting by content — orthogonal mechanisms |
| `add_load_shedding` (TOOL-095) | ⚠️ Caveat | Load-shed 429 for first-time request gets cached; duplicate gets 429 replayed — acceptable behavior |
| `generate_project` | ✅ Prerequisite | Requires `app/core/config.py` with `class Settings` |
| Second `add_request_fingerprint` call | ✅ Idempotent | `no_op` — `RequestFingerprinter` already in `hasher.py` |
| `add_bulkhead_isolation` (TOOL-097) | ✅ Neutral | Bulkhead 503 on first-time gets cached; duplicate gets 503 replayed |

---

## 12. Rollback Procedure

### 12.1 Remove fingerprint package

```bash
rm -rf app/fingerprint/
```

### 12.2 Remove fingerprint middleware

```bash
rm -f app/middleware/fingerprint.py
```

### 12.3 Restore config

```bash
git checkout HEAD -- app/core/config.py
```

Or manually remove `FINGERPRINT_ENABLED`, `FINGERPRINT_TTL_S`, `FINGERPRINT_METHODS` from `app/core/config.py`.

### 12.4 Remove wiring from `main.py`

```bash
git checkout HEAD -- app/main.py
```

Or manually remove:
- `from app.fingerprint.store import init_store`
- `from app.middleware.fingerprint import FingerprintMiddleware`
- `app.add_middleware(FingerprintMiddleware, ...)`
- `await init_store(...)` call in lifespan

### 12.5 Verify rollback

```bash
python -c "from app.main import app; print('OK')"
pytest tests/ -x --tb=short
```

### 12.6 Re-run to restore

```bash
python -c "
from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_request_fingerprint import add_request_fingerprint
r = add_request_fingerprint(ToolInput(project_dir='$(pwd)'))
print(r.status, r.files_created)
"
```

---

## 13. Edge Cases

| # | Scenario | Expected behaviour |
|---|----------|--------------------|
| EC-01 | `"RequestFingerprinter"` already in `app/fingerprint/hasher.py` | `status="no_op"`, no files modified |
| EC-02 | `dry_run=True` on any valid project | `status="success"`, zero writes |
| EC-03 | Non-JSON body (e.g., plain text, XML) | `_normalize_body()` returns raw UTF-8 string — no exception |
| EC-04 | `FINGERPRINT_ENABLED=false` (default) | `init_store()` not called; `get_store()` returns `None`; middleware passes all requests through |
| EC-05 | Response cache > 5 000 entries | Oldest 1 000 entries deleted; cache returns to 4 000 (INV-FP-10) |
| EC-06 | Redis connection lost mid-flight | `except Exception` in `is_duplicate()` logs warning; falls back to `_MemoryStore` |
| EC-07 | `user_id` not set on `request.state` | Falls back to `"anonymous"` — path-level deduplication still active |
| EC-08 | `FINGERPRINT_METHODS=""` (empty string) | `set("".split(",")) = {""}` — no real methods matched; no deduplication |
| EC-09 | `body_iterator` raises exception in `_capture_and_cache` | Exception caught and logged at DEBUG; original `response` returned without caching |
| EC-10 | `app/core/config.py` not found | Config patch skipped; `files_modified` is empty |
| EC-11 | Empty request body `b""` | `_normalize_body(b"")` returns `""` — valid fingerprint computed |
| EC-12 | Very large JSON body (1 MB) | `json.loads` + `json.dumps(sort_keys=True)` processes in memory; no truncation in hasher |
| EC-13 | `_MemoryStore` data expires after TTL | `exists()` detects `time.monotonic() > exp` and deletes key; `set()` re-adds with fresh TTL |
| EC-14 | Redis `SET NX EX` returns `False` (vs `None`) | `was_set is None or was_set is False` — covers both Redis client return conventions |
| EC-15 | `FINGERPRINT_TTL_S=0` | TTL of 0 seconds means fingerprints expire immediately; effectively no deduplication window |

---

## 14. Acceptance Criteria (Final Sign-off)

1. ✅ All CC-01 through CC-25 pass in `test_add_request_fingerprint.py`
2. ✅ `RequestFingerprinter.compute()` normalizes JSON with `sort_keys=True`
3. ✅ Same JSON body with different key order produces identical fingerprint
4. ✅ Fingerprint is exactly 64 hexadecimal characters
5. ✅ `FingerprintStore.is_duplicate()` uses `SET key "1" NX EX ttl_s` in Redis
6. ✅ `_MemoryStore` fallback active when Redis is `None` or fails mid-flight
7. ✅ Redis imported lazily inside `init_store()` body only — not at module level
8. ✅ `FingerprintMiddleware` only deduplicates `POST`, `PUT`, `PATCH` by default
9. ✅ `Idempotent-Replayed: true` header returned on cache hit
10. ✅ `user_id` included in fingerprint computation — different users get different fingerprints
11. ✅ Response cache pruned when exceeding 5 000 entries
12. ✅ All generated `.py` files pass `ast.parse()` with no `SyntaxError`
13. ✅ No generated function exceeds 50 LOC (AST walk)
14. ✅ Config fields have 4-space indent inside `class Settings` body

---

## 15. Implementation Checklist

### 15.1 Pre-flight checks

- [ ] Validate `project_dir` with `validate_project_dir()` — return error if invalid
- [ ] Run `ensure_prerequisites(Prereq.CONFIG_SETTINGS, Prereq.REQUIREMENTS_TXT)` — return error if not met
- [ ] Check idempotency: `"RequestFingerprinter" in (app/fingerprint/hasher.py)` → return `no_op` if true
- [ ] If `dry_run=True`, return early success with notes about 3 would-be changes

### 15.2 Fingerprint package creation

- [ ] Create `app/fingerprint/` directory with `mkdir(parents=True, exist_ok=True)`
- [ ] Write `app/fingerprint/__init__.py` via `_write_fp_init()`: re-export `RequestFingerprinter`, `FingerprintStore`, `get_store`, `init_store`
- [ ] Write `app/fingerprint/hasher.py` via `_write_hasher()`:
  - [ ] `RequestFingerprinter.compute(user_id, method, path, body)` returning 64-char hex
  - [ ] `_normalize_body()` with `json.loads` + `json.dumps(sort_keys=True)` + plain text fallback
  - [ ] `uid = user_id or "anonymous"` — never `None` in hash input
- [ ] Write `app/fingerprint/store.py` via `_write_store()`:
  - [ ] `_MemoryStore` with `dict[str, float]`, `Lock`, `exists()`, `set()` (prune at 10 000)
  - [ ] `FingerprintStore` with `_redis`, `_ttl_s`, `_memory`, `is_duplicate()` (Redis NX EX primary + fallback)
  - [ ] `get_store()` returning module-level `_store`
  - [ ] `init_store()` with lazy `from redis.asyncio import Redis` import

### 15.3 Middleware

- [ ] Create `app/middleware/` if not exists
- [ ] Write `app/middleware/fingerprint.py` via `_write_fp_middleware()`:
  - [ ] `_DEFAULT_METHODS = {"POST", "PUT", "PATCH"}` module constant
  - [ ] `FingerprintMiddleware(BaseHTTPMiddleware)` with `_methods`, `_response_cache`
  - [ ] `_replay_cached(fp)` returning `Response(headers={"Idempotent-Replayed": "true"})`
  - [ ] `_capture_and_cache(fp, response)` reading `body_iterator` and storing in `_response_cache`
  - [ ] Cache prune: when `len > 5000`, delete oldest 1 000 entries
  - [ ] `dispatch()` with method check, `get_store()` None guard, fingerprint computation, duplicate check

### 15.4 Config patch

- [ ] Patch `app/core/config.py` with all three `FINGERPRINT_*` fields, 4-space indent
- [ ] Skip if `"FINGERPRINT_ENABLED"` already in file

### 15.5 Validation and result construction

- [ ] Loop over `files_created`: `ast.parse(path.read_text())` — return error on `SyntaxError`
- [ ] Return `ToolResult` with `status="success"`, `notes` mentioning "SHA-256", "deduplication", "fingerprint", `next_steps` mentioning "FINGERPRINT", `execution_time_ms`

---

## 16. Documentation Output

### 16.1 Success (fresh project)

```json
{
  "status": "success",
  "files_created": [
    "/project/app/fingerprint/__init__.py",
    "/project/app/fingerprint/hasher.py",
    "/project/app/fingerprint/store.py",
    "/project/app/middleware/fingerprint.py"
  ],
  "files_modified": ["/project/app/core/config.py"],
  "notes": [
    "Request fingerprinting added: SHA-256 hash of user_id+method+path+sorted(body).",
    "FingerprintStore: Redis primary with in-memory fallback (works without Redis).",
    "FingerprintMiddleware: deduplicates POST/PUT (configurable), adds Idempotent-Replayed header.",
    "Duplicate detection within FINGERPRINT_TTL_S window (default: 60 s)."
  ],
  "next_steps": [
    "Set FINGERPRINT_ENABLED=true in .env (default: false).",
    "Optional: set FINGERPRINT_TTL_S (default: 60 seconds).",
    "Optional: set FINGERPRINT_METHODS=POST,PUT,PATCH (comma-separated).",
    "pip install 'redis[hiredis]' for Redis store (falls back to memory without Redis)."
  ],
  "execution_time_ms": 83
}
```

### 16.2 No-op (already installed)

```json
{
  "status": "no_op",
  "files_created": [],
  "files_modified": [],
  "notes": [
    "RequestFingerprinter already present — fingerprinting already enabled, skipped."
  ],
  "next_steps": [],
  "execution_time_ms": 3
}
```

### 16.3 Dry run

```json
{
  "status": "success",
  "files_created": [],
  "files_modified": [],
  "notes": [
    "[dry_run] Would create app/fingerprint/ package with hasher, store.",
    "[dry_run] Would add FingerprintMiddleware to app/main.py.",
    "[dry_run] Would patch app/core/config.py with FINGERPRINT_* fields."
  ],
  "next_steps": [
    "Re-run without dry_run=True to apply changes."
  ],
  "execution_time_ms": 2
}
```

### 16.4 Error (invalid project directory)

```json
{
  "status": "error",
  "error": "project_dir '/nonexistent/path' does not exist or is not a directory.",
  "files_created": [],
  "files_modified": [],
  "notes": [],
  "next_steps": [],
  "execution_time_ms": 1
}
```

---
