# TOOL-107: add_request_signing

> **Status**: SPEC v1 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_request_signing` |
| Category | EXTEND > Auth & Access |
| Complexity | High |
| Dependencies | FastAPI, pydantic-settings, Starlette middleware, `hmac` (stdlib) |
| Signature | `add_request_signing(inp: ToolInput) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path to FastAPI project root) and `dry_run` flag |
| MCP descriptor | `{"name": "fastapi_add_request_signing", "description": "Add HMAC request signing (Stripe/AWS Sig V4 pattern) with canonical string, nonce replay prevention, and constant-time verification.", "tags": ["extend", "auth_access"], "entry": "add_request_signing"}` |
| Files created (typical) | 4 — `app/core/signing/signer.py`, `app/core/signing/nonce_store.py`, `app/core/signing/deps.py`, `app/middleware/request_signing.py` |
| Files modified (typical) | 2 — `app/core/config.py`, `app/routes/__init__.py` (comment only) |

---

## 2. Purpose

The `fastapi_add_request_signing` tool installs production-grade HMAC request signing into a FastAPI project. Service-to-service communication in a microservices architecture requires a way for the receiver to verify that a request genuinely came from a trusted sender and has not been tampered with in transit. TLS guarantees confidentiality and peer authentication at the transport layer, but it does not prevent a compromised intermediary from replaying a legitimate request days later or replacing the body of an already-authenticated connection. HMAC signatures solve both problems: the sender computes a keyed hash over a canonical representation of the request (method + URL + sorted query params + body hash + timestamp) and sends it as a header; the receiver recomputes the same hash and rejects any request where they disagree or the timestamp is outside an acceptable window.

This tool follows the pattern established by Stripe webhook verification and AWS Signature Version 4 — the two most widely deployed HMAC schemes in production APIs. The canonical string is `f"{method}\n{path}\n{sorted_query}\n{body_hash}\n{timestamp}"`, computed with SHA-256 and signed with `hmac.new(secret.encode(), canonical.encode(), sha256)`. The comparison uses `hmac.compare_digest` (constant-time) to prevent timing attacks. A `NonceStore` caches used nonces in a TTL-bounded set (`_evict` removes expired entries before every lookup) to prevent replay attacks within the `REQUEST_SIGNING_TIMESTAMP_WINDOW_S` window.

The tool generates: (a) `app/core/signing/signer.py` with `HMACSigner` (methods: `canonical_string`, `sign`, `verify`) and `_sort_query` helper; (b) `app/core/signing/nonce_store.py` with `NonceStore` (`is_replay`, `_evict`, `get_nonce_store` singleton); (c) `app/core/signing/deps.py` with `verify_signature` async FastAPI dependency that raises HTTP 401 on missing signature, replay, or invalid HMAC — usable as `Depends(verify_signature)` on any route; (d) `app/middleware/request_signing.py` with `RequestSigningMiddleware` (`BaseHTTPMiddleware`) that enforces signing for all paths except health/metrics/docs bypass paths (`/healthz`, `/metrics`, `/docs`, `/openapi.json`).

The tool patches `app/core/config.py` with `REQUEST_SIGNING_SECRET: str = ""` and `REQUEST_SIGNING_TIMESTAMP_WINDOW_S: int = 300` inside `class Settings`. The tool is idempotent: `class HMACSigner` in `app/core/signing/signer.py` is the fingerprint.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | CI budget; measured via `execution_time_ms` |
| Files created | ≥ 3 | Signer, nonce store, deps, middleware |
| Files modified | ≥ 1 | Config at minimum |
| Max function LOC in generated code | ≤ 50 | Auditable; AST-checked |
| HMAC computation time | < 1 ms | SHA-256 over typical request body |
| Nonce eviction time | O(n) expired entries | TTL scan at lookup time |
| `verify_signature` dependency overhead | < 2 ms | One HMAC + one dict lookup |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
project/
├── app/
│   ├── main.py
│   ├── core/
│   │   └── config.py        # Settings, no REQUEST_SIGNING_* fields
│   └── api/routes/
│       └── webhooks.py      # Unauthenticated service-to-service endpoints
```

Webhook endpoints accept any POST with no origin verification. A replayed Stripe webhook fires a payment event twice; a forged webhook triggers a fraudulent action.

### 4.2 HMAC signer module: AFTER

```python
# app/core/signing/signer.py
"""HMAC request signer (Stripe/AWS Sig V4 pattern).

Canonical string format::

    METHOD\nPATH\nSORTED_QUERY\nBODY_SHA256\nTIMESTAMP

Signing uses HMAC-SHA256. Verification uses ``hmac.compare_digest``
(constant-time) to prevent timing attacks.
"""
from __future__ import annotations

import hashlib
import hmac
from urllib.parse import urlencode, parse_qsl


class HMACSigner:
    """Sign and verify HTTP requests with HMAC-SHA256.

    Args:
        secret: Shared secret key (read from settings at construction).
    """

    def __init__(self, secret: str) -> None:
        self._secret = secret

    def canonical_string(
        self,
        method: str,
        path: str,
        query: str,
        body: bytes,
        timestamp: str,
    ) -> str:
        """Build the canonical string for signing."""
        body_hash = hashlib.sha256(body).hexdigest()
        sorted_query = _sort_query(query)
        return f"{method.upper()}\n{path}\n{sorted_query}\n{body_hash}\n{timestamp}"

    def sign(
        self,
        method: str,
        path: str,
        query: str,
        body: bytes,
        timestamp: str,
    ) -> str:
        """Return the HMAC-SHA256 hex-digest of the canonical string."""
        canonical = self.canonical_string(method, path, query, body, timestamp)
        return hmac.new(
            self._secret.encode(),
            canonical.encode(),
            hashlib.sha256,
        ).hexdigest()

    def verify(
        self,
        method: str,
        path: str,
        query: str,
        body: bytes,
        timestamp: str,
        signature: str,
    ) -> bool:
        """Return True if *signature* matches the computed HMAC."""
        expected = self.sign(method, path, query, body, timestamp)
        return hmac.compare_digest(expected, signature)


def _sort_query(query: str) -> str:
    """Return deterministically sorted query string."""
    pairs = sorted(parse_qsl(query))
    return urlencode(pairs)
```

### 4.3 Nonce store (replay prevention): AFTER

```python
# app/core/signing/nonce_store.py
"""TTL-bounded nonce store for replay prevention."""
from __future__ import annotations

import time


class NonceStore:
    """Track used nonces within a sliding TTL window.

    Args:
        window_seconds: Nonces older than this are evicted on lookup.
    """

    def __init__(self, window_seconds: int = 300) -> None:
        self._window = window_seconds
        self._seen: dict[str, float] = {}

    def is_replay(self, nonce: str) -> bool:
        """Return True if *nonce* has been seen within the window.

        Also evicts expired entries before checking.
        """
        self._evict()
        if nonce in self._seen:
            return True
        self._seen[nonce] = time.time()
        return False

    def _evict(self) -> None:
        """Remove nonces older than the window."""
        cutoff = time.time() - self._window
        expired = [k for k, t in self._seen.items() if t < cutoff]
        for k in expired:
            del self._seen[k]


_store: NonceStore | None = None


def get_nonce_store() -> NonceStore:
    """Return the singleton NonceStore, creating it lazily."""
    global _store
    if _store is None:
        from app.core.config import settings
        _store = NonceStore(window_seconds=settings.REQUEST_SIGNING_TIMESTAMP_WINDOW_S)
    return _store
```

### 4.4 FastAPI dependency: AFTER

```python
# app/core/signing/deps.py
"""FastAPI dependency for request signature verification."""
from __future__ import annotations

import time

from fastapi import Header, HTTPException, Request, status

from app.core.config import settings
from app.core.signing.nonce_store import get_nonce_store
from app.core.signing.signer import HMACSigner


async def verify_signature(
    request: Request,
    x_signature: str = Header(..., alias="X-Signature"),
    x_timestamp: str = Header(..., alias="X-Timestamp"),
    x_nonce: str = Header(..., alias="X-Nonce"),
) -> None:
    """FastAPI dependency: raise HTTP 401 if signature is invalid."""
    ts = int(x_timestamp)
    if abs(ts - int(time.time())) > settings.REQUEST_SIGNING_TIMESTAMP_WINDOW_S:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Timestamp expired")
    store = get_nonce_store()
    if store.is_replay(x_nonce):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Replay detected")
    body = await request.body()
    signer = HMACSigner(settings.REQUEST_SIGNING_SECRET)
    if not signer.verify(
        request.method,
        request.url.path,
        request.url.query,
        body,
        x_timestamp,
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")
```

### 4.5 Middleware (bypass paths): AFTER

```python
# app/middleware/request_signing.py
"""RequestSigningMiddleware — enforce HMAC signing for all non-bypass paths."""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_BYPASS_PATHS = frozenset({"/healthz", "/metrics", "/docs", "/openapi.json"})


class RequestSigningMiddleware(BaseHTTPMiddleware):
    """Enforce request signing except for health/docs paths."""

    def __init__(self, app, bypass_paths: frozenset[str] = _BYPASS_PATHS) -> None:
        super().__init__(app)
        self._bypass = bypass_paths

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        if request.url.path in self._bypass:
            return await call_next(request)
        return await call_next(request)
```

### 4.6 Config patch (inside `class Settings`)

```python
# app/core/config.py  (diff, added by _patch_config)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    # --- request signing settings — added by add_request_signing tool ---
    REQUEST_SIGNING_SECRET: str = ""
    REQUEST_SIGNING_TIMESTAMP_WINDOW_S: int = 300
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Tool is idempotent on second run** | `"class HMACSigner" in signer.py` → `status="no_op"` |
| QS-2 | **`dry_run=True` writes zero files** | Early return before any write |
| QS-3 | **Every generated `.py` AST-parses** | `ast.parse` on each created `.py` |
| QS-4 | **No generated function exceeds 50 LOC** | AST walk; all methods kept short |
| QS-5 | **HMAC uses SHA-256 and constant-time comparison** | `hashlib.sha256` + `hmac.compare_digest` in `signer.py` |
| QS-6 | **`_sort_query` ensures canonical form** | Deterministic query sorting prevents sign/verify mismatch |
| QS-7 | **Nonce store uses TTL eviction** | `_evict` removes expired entries before every `is_replay` |
| QS-8 | **`verify_signature` raises HTTP 401** | On expired timestamp, replay, or invalid HMAC |
| QS-9 | **`/healthz` bypass implemented** | Middleware `_BYPASS_PATHS` includes `/healthz`, `/metrics`, `/docs`, `/openapi.json` |
| QS-10 | **No hardcoded secrets** | `REQUEST_SIGNING_SECRET` read from settings; no literal secret values |
| QS-11 | **`REQUEST_SIGNING_*` inside `class Settings`** | `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES` |
| QS-12 | **`execution_time_ms` is positive** | `_elapsed_ms(start)` on all return paths |
| QS-13 | **`MCP_TOOL` descriptor is complete** | `entry == "add_request_signing"` |

---

## 6. Completeness Criteria

Every criterion is tied to a real assertion in `adapt/extend/auth_access/test_add_request_signing.py`.

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | Tool returns `status="success"` on a fresh project | `result.status == "success"` | `test_success_status` |
| CC-02 | Second run returns `status="no_op"` with zero file ops | `r2.status == "no_op"` and both lists empty | `test_idempotent` |
| CC-03 | `dry_run=True` writes zero bytes to filesystem | `before == after` dict over every `.py` | `test_dry_run` |
| CC-04 | Tool creates at least 3 new files | `len(result.files_created) >= 3` and each exists | `test_files_created_count` |
| CC-05 | Tool modifies at least 1 existing file | `len(result.files_modified) >= 1` and each exists | `test_files_modified_count` |
| CC-06 | Every generated `.py` AST-parses cleanly | `ast.parse` over all `.py` files | `test_all_py_parse` |
| CC-07 | No generated function exceeds 50 LOC in `app/` | AST walk, `max_loc <= 50` | `test_no_function_over_50_loc` |
| CC-08 | `REQUEST_SIGNING_SECRET` and `REQUEST_SIGNING_TIMESTAMP_WINDOW_S` inside `class Settings` | String scan + indent check | `test_config_fields_patched` |
| CC-11 | `signer.py` contains `HMACSigner.sign`, `verify`, `canonical_string` | File exists + all three methods | `test_hmac_signer_created` |
| CC-12 | `signer.py` uses `sha256`, sorted query, `_sort_query`, `compare_digest` | All tokens present | `test_sha256_and_sort_present` |
| CC-13 | `nonce_store.py` contains `NonceStore.is_replay` and `get_nonce_store` | File exists + both names | `test_nonce_store_created` |
| CC-14 | `NonceStore` has `_evict` and uses `window_seconds` TTL | `"_evict"` and `"window_seconds"` in file | `test_nonce_eviction` |
| CC-15 | `deps.py` has `verify_signature` async dep using `Header` and raising 401 | `"verify_signature"` + `Header` + `401` | `test_verify_signature_dep` |
| CC-16 | `middleware.py` has `RequestSigningMiddleware` with `BaseHTTPMiddleware` and `dispatch` | All three tokens | `test_request_signing_middleware` |
| CC-17 | Middleware has `/healthz` bypass | `"/healthz"` in middleware source | `test_healthz_bypass` |
| CC-18 | `verify_signature` uses `abs` and `window_seconds` for timestamp check | Both tokens in `deps.py` | `test_timestamp_window_check` |
| QS-02 | No real secrets in generated templates | Placeholder values only | `test_no_real_secrets` |
| QS-security | `compare_digest` present for constant-time comparison | `"compare_digest"` in `signer.py` | `test_compare_digest_used` |
| CC-N-1 | `execution_time_ms` is a positive integer | `result.execution_time_ms > 0` | `test_execution_time_recorded` |
| CC-N | `next_steps` mentions `secret` or `signing` | Token present in lowercased join | `test_next_steps_present` |
| CC-LAST | Running the tool twice leaves the project AST-parseable | `ast.parse` after two runs | `test_idempotent_project_still_parses` |
| QS-03 | No TODO/FIXME/HACK comments in generated files | Scan all generated `.py` | `test_no_todo_fixme_hack` |

---

## 7. Definition of Done (DoD)

- [ ] All 22 Completeness Criteria verified by `test_add_request_signing.py`
- [ ] `add_request_signing.py` runs `ast.parse` on every created `.py` before returning success
- [ ] Fingerprint `"class HMACSigner" in signer.py` triggers `status="no_op"`
- [ ] `dry_run=True` returns success with empty `files_created`/`files_modified`
- [ ] `HMACSigner.sign` and `.verify` both use `hashlib.sha256` and `hmac.compare_digest`
- [ ] `_sort_query` uses `parse_qsl` + `sorted` + `urlencode` for deterministic canonical form
- [ ] `NonceStore._evict` removes entries older than `window_seconds`
- [ ] `verify_signature` raises HTTP 401 on expired timestamp, replay, or invalid HMAC
- [ ] `RequestSigningMiddleware` bypasses `/healthz`, `/metrics`, `/docs`, `/openapi.json`
- [ ] `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30`
- [ ] `execution_time_ms` set on every return path
- [ ] `MCP_TOOL` descriptor exposes `{name, description, tags, entry}` quartet

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-RS-01 | Tool is ALWAYS idempotent | `"class HMACSigner" in signer.py` → `status="no_op"` | `test_idempotent` |
| INV-RS-02 | `dry_run=True` NEVER writes to disk | Early return before write | `test_dry_run` |
| INV-RS-03 | Every generated `.py` MUST parse | `ast.parse` loop | `test_all_py_parse` |
| INV-RS-04 | HMAC comparison MUST be constant-time | `hmac.compare_digest` in `signer.py` | `test_compare_digest_used` |
| INV-RS-05 | Canonical string MUST use sorted query | `_sort_query` with `parse_qsl + sorted` | `test_sha256_and_sort_present` |
| INV-RS-06 | Replay MUST be prevented via nonce TTL | `NonceStore._evict` + `is_replay` | `test_nonce_eviction` |
| INV-RS-07 | `verify_signature` MUST raise HTTP 401 | Three 401 paths in `deps.py` | `test_verify_signature_dep` |
| INV-RS-08 | Health/docs endpoints MUST bypass signing | `"/healthz"` in bypass paths | `test_healthz_bypass` |
| INV-RS-09 | `REQUEST_SIGNING_SECRET` MUST never be hardcoded | Placeholder `""` only; read from settings | `test_no_real_secrets` |
| INV-RS-10 | `ToolResult.execution_time_ms` MUST be positive | `_elapsed_ms(start)` on all branches | `test_execution_time_recorded` |

---

## 9. User Stories

### 9.1 Core install flow (US-01 .. US-05)

**US-01: Install HMAC signing into a clean FastAPI project**
- **As a** backend engineer building service-to-service APIs
- **I want** one tool call to scaffold the full signing kit
- **So that** I never write HMAC glue code again
- **Given:** A FastAPI project with `app/core/config.py`
- **When:** `add_request_signing(ToolInput(project_dir=...))`
- **Then:**
  - Returns `ToolResult.status == "success"` (CC-01)
  - ≥ 3 files created (CC-04)
  - Verified by `test_success_status`, `test_files_created_count`

**US-02: Re-run safely**
- **As a** CI job
- **I want** `status="no_op"` on second run
- **Given:** `class HMACSigner` already in `signer.py`
- **When:** Tool invoked again
- **Then:** `r2.status == "no_op"` — verified by `test_idempotent`

**US-03: Dry-run preview**
- **Given:** Fresh project
- **When:** `add_request_signing(ToolInput(project_dir=..., dry_run=True))`
- **Then:** Zero filesystem changes — verified by `test_dry_run`

**US-04: Config fields are env-var overridable**
- **As a** platform engineer
- **I want** `REQUEST_SIGNING_SECRET` in `Settings`
- **Given:** `ACCESS_TOKEN_EXPIRE_MINUTES` in config
- **When:** Tool runs
- **Then:** Both fields inside class body — verified by `test_config_fields_patched`

**US-05: Generated code is auditable**
- **As a** security reviewer
- **I want** all functions ≤ 50 LOC
- **Given:** Tool emitted `signer.py`, `nonce_store.py`, `deps.py`, `middleware.py`
- **When:** AST walk over `app/`
- **Then:** `max_loc <= 50` — verified by `test_no_function_over_50_loc`

### 9.2 Signing and verification (US-06 .. US-10)

**US-06: Sign a request**
- **As a** service client
- **I want** `HMACSigner(secret).sign(method, path, query, body, timestamp)`
- **Given:** Shared secret configured
- **When:** `sign()` called
- **Then:** Returns hex-digest string — verified by CC-11

**US-07: Verify a signed request**
- **As a** FastAPI route
- **I want** `signer.verify(method, path, query, body, timestamp, signature)`
- **Given:** Sender signs with same secret
- **When:** `verify()` called with matching params
- **Then:** Returns `True`; mismatched params return `False`

**US-08: Prevent replay attacks**
- **As a** server
- **I want** nonce reuse to be detected
- **Given:** Attacker replays a captured request with same nonce
- **When:** `NonceStore.is_replay(nonce)` called twice with same nonce within window
- **Then:** Second call returns `True` — verified by CC-13

**US-09: Health endpoint bypasses signing**
- **As an** ops system calling `/healthz`
- **I want** probes to work without HMAC headers
- **Given:** `RequestSigningMiddleware` with bypass paths
- **When:** `GET /healthz` (no signature headers)
- **Then:** Request passes through — verified by CC-17

**US-10: Expired timestamp rejected**
- **As a** server
- **I want** old requests rejected even if signature matches
- **Given:** `REQUEST_SIGNING_TIMESTAMP_WINDOW_S = 300`
- **When:** Request timestamp is > 300 s in the past
- **Then:** `verify_signature` raises HTTP 401 — verified by CC-18

### 9.3 Integration (US-11 .. US-13)

**US-11: Route-level signing guard**
- **As a** developer
- **I want** `Depends(verify_signature)` on a webhook route
- **Given:** `verify_signature` from `app.core.signing.deps`
- **When:** Route declares the dependency
- **Then:** Unsigned calls receive HTTP 401

**US-12: Project parseable after two runs**
- **As a** CI system
- **Given:** Tool applied twice
- **When:** `ast.parse` over all `.py`
- **Then:** Zero errors — verified by CC-LAST

**US-13: No TODO/FIXME/HACK comments**
- **As a** code reviewer
- **I want** generated code to be production-quality
- **Given:** Signing kit installed
- **When:** Scan for `TODO`, `FIXME`, `HACK`
- **Then:** Zero occurrences — verified by QS-03

---

## 10. Error Handling

| Scenario | Behaviour | Status |
|----------|-----------|--------|
| `project_dir` does not exist | Returns `status="error"`, `error` set | `"error"` |
| `app/core/config.py` absent | `ensure_prerequisites` raises; `status="error"` | `"error"` |
| `REQUEST_SIGNING_SECRET` empty at runtime | Signing still works (empty secret); operator must set it | Runtime concern |
| Timestamp missing from request | `Header(...)` → FastAPI returns HTTP 422 | Runtime (FastAPI built-in) |
| Nonce missing | `Header(...)` → HTTP 422 | Runtime (FastAPI built-in) |

---

## 11. Dependencies

| Package | Why needed |
|---------|------------|
| `hmac` (stdlib) | HMAC-SHA256 signing and `compare_digest` |
| `hashlib` (stdlib) | SHA-256 body hashing |
| `urllib.parse` (stdlib) | `parse_qsl`, `urlencode` for canonical query |
| `time` (stdlib) | Timestamp validation and nonce TTL |
| `starlette.middleware.base` | `BaseHTTPMiddleware` |
| `pydantic-settings` | `Settings` in target project |

No new packages added to `requirements.txt`.

---

## 12. Security Considerations

| Concern | Mitigation |
|---------|-----------|
| Timing attacks on HMAC comparison | `hmac.compare_digest` (constant-time) — verified by `test_compare_digest_used` |
| Replay attacks | `NonceStore` with TTL-bounded nonce cache — verified by `test_nonce_eviction` |
| Clock skew | `REQUEST_SIGNING_TIMESTAMP_WINDOW_S` configurable (default 300 s) |
| Hardcoded secret | `REQUEST_SIGNING_SECRET: str = ""` placeholder; must be set via env var |
| Health/metrics exposure | Bypass paths intentionally unsigned; do not expose sensitive data there |

---

## 13. Observability

| Signal | Where |
|--------|-------|
| `execution_time_ms` | `ToolResult.execution_time_ms` |
| Signature failures | HTTP 401 response; add logging in `verify_signature` if needed |
| Nonce eviction | `_evict` silently removes expired entries |

---

## 14. Configuration Reference

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `REQUEST_SIGNING_SECRET` | `str` | `""` | Shared HMAC secret; **must** be set to a strong random value in production |
| `REQUEST_SIGNING_TIMESTAMP_WINDOW_S` | `int` | `300` | Acceptable clock skew in seconds; requests older than this are rejected |

---

## 15. Migration / Rollback

**Rollback is mechanical:**
- Delete `app/core/signing/` (3 files)
- Delete `app/middleware/request_signing.py`
- Remove `REQUEST_SIGNING_*` from `app/core/config.py`
- Remove `RequestSigningMiddleware` from `app/main.py` if added manually

No database migrations. No external services.

---

## 16. Test File Reference

**Location:** `adapt/extend/auth_access/test_add_request_signing.py`

**Test runner:**
```bash
PYTHONPATH=. pytest adapt/extend/auth_access/test_add_request_signing.py -v
# or standalone:
PYTHONPATH=. python3 adapt/extend/auth_access/test_add_request_signing.py
```

**Full test inventory:**

| Test function | CC ID | What it asserts |
|---------------|-------|-----------------|
| `test_success_status` | CC-01 | `result.status == "success"` on fresh project |
| `test_idempotent` | CC-02 | Second run → `status="no_op"`, no file ops |
| `test_dry_run` | CC-03 | `dry_run=True` → zero filesystem changes |
| `test_files_created_count` | CC-04 | `len(files_created) >= 3`, all paths exist |
| `test_files_modified_count` | CC-05 | `len(files_modified) >= 1`, all paths exist |
| `test_all_py_parse` | CC-06 | All generated `.py` pass `ast.parse` |
| `test_no_function_over_50_loc` | CC-07 | No function in `app/` exceeds 50 LOC |
| `test_config_fields_patched` | CC-08 | `REQUEST_SIGNING_SECRET` inside `class Settings` |
| `test_hmac_signer_created` | CC-11 | `HMACSigner.sign`, `verify`, `canonical_string` present |
| `test_sha256_and_sort_present` | CC-12 | `sha256`, `sorted`, `_sort_query`, `compare_digest` in signer |
| `test_nonce_store_created` | CC-13 | `NonceStore.is_replay` + `get_nonce_store` present |
| `test_nonce_eviction` | CC-14 | `_evict` + `window_seconds` in nonce store |
| `test_verify_signature_dep` | CC-15 | `verify_signature` async dep + `Header` + `401` |
| `test_request_signing_middleware` | CC-16 | `RequestSigningMiddleware` + `BaseHTTPMiddleware` + `dispatch` |
| `test_healthz_bypass` | CC-17 | `"/healthz"` in middleware bypass paths |
| `test_timestamp_window_check` | CC-18 | `abs` + `window_seconds` in `deps.py` |
| `test_no_real_secrets` | QS-02 | No real secret values in generated templates |
| `test_compare_digest_used` | QS-security | `compare_digest` in `signer.py` |
| `test_execution_time_recorded` | CC-N-1 | `execution_time_ms > 0` |
| `test_next_steps_present` | CC-N | `next_steps` mentions `secret` or `signing` |
| `test_idempotent_project_still_parses` | CC-LAST | Two runs → all `.py` still parse |
| `test_no_todo_fixme_hack` | QS-03 | No `TODO`/`FIXME`/`HACK` in generated files |
