# TOOL-115 — add_dpop_tokens

## 1. Overview

| Field | Value |
|---|---|
| **Tool ID** | TOOL-115 |
| **MCP name** | `fastapi_add_dpop_tokens` |
| **Entry point** | `adapt/extend/auth_access/add_dpop_tokens.py::add_dpop_tokens` |
| **Tags** | `auth`, `dpop`, `tokens`, `rfc9449`, `fapi2`, `proof-of-possession` |
| **Input** | `ToolInput(project_dir, dry_run=False)` |
| **Output** | `ToolResult(status, files_created, files_modified, notes, next_steps, execution_time_ms)` |
| **Idempotency fingerprint** | `"DPoPVerifier" in app/core/dpop.py` |
| **Prerequisite check** | `app/` directory exists |
| **Files created (min)** | 3 (`dpop.py`, `dpop_deps.py`, `dpop_nonce.py`) |
| **Files modified (min)** | 2 (`app/core/config.py`, `requirements.txt`) |
| **Test file** | `adapt/extend/auth_access/test_add_dpop_tokens.py` |

---

## 2. Purpose

DPoP (Demonstrating Proof of Possession, RFC 9449) binds access tokens to a specific client key pair, preventing token theft. Even if an attacker intercepts a bearer token they cannot use it without the private key that created the proof. `add_dpop_tokens` installs full RFC 9449 / FAPI 2.0 DPoP support in three subsystems:

1. **`app/core/dpop.py`** — Core verifier. `DPoPVerifier.verify_proof()` validates the `DPoP` HTTP header:
   - `alg` must be in `_ALLOWED_ALGS = {"ES256", "RS256", "PS256", "ES384", "ES512", "EdDSA"}`
   - `jwk` (public key) must be embedded in the proof header
   - `htm` (HTTP method) and `htu` (HTTP URI) must match the incoming request
   - `iat` (issued-at) must be within `DPOP_CLOCK_SKEW_S` seconds of server time
   - `jti` (unique identifier) checked against `DPoPNonceStore` for replay prevention
   - `PyJWT` (`jwt`) is imported lazily inside `verify_proof()` — never at module top level

   `DPoPNonceStore` is a thread-safe TTL store backed by a `dict` + `threading.Lock`. It tracks:
   - Issued nonces (for the nonce endpoint)
   - Used JTI values (for replay prevention via `mark_jti()`)

   Helper functions `generate_dpop_key_pair()` and `jwk_from_public_key()` are exported for use in tests and client code.

2. **`app/core/dpop_deps.py`** — FastAPI dependency functions:
   - `require_dpop(request: Request) -> DPoPClaims` — synchronous dependency that validates the `DPoP` header and returns decoded claims
   - `require_dpop_async(request: Request) -> DPoPClaims` — async variant for use in async route handlers

3. **`app/api/routes/dpop_nonce.py`** — Nonce endpoint:
   - `POST /auth/dpop/nonce` returns a fresh nonce in the `DPoP-Nonce` response header, as required by RFC 9449 §8.

Config fields (`DPOP_ENABLED`, `DPOP_NONCE_TTL_S`, `DPOP_CLOCK_SKEW_S`) are injected into `app/core/config.py` inside the `Settings` class body with 4-space indent, anchored on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30`.

---

## 3. Performance SLOs

| Metric | Target |
|---|---|
| Tool execution time | < 2 s on a cold fixture project |
| `execution_time_ms` field | > 0 (always recorded) |
| DPoP proof verification latency | < 5 ms per request (local key verification) |
| `DPoPNonceStore` TTL eviction | O(n) on nonce insert; acceptable for < 100k active nonces |
| Files created | ≥ 3 |
| Files modified | ≥ 2 |
| Max function LOC in generated `app/` | ≤ 50 |

---

## 4. Before / After

### 4.1 Project state — before

```
app/
  core/
    config.py     # Settings class; no DPoP fields
  routes/
    __init__.py
requirements.txt  # no PyJWT entry
```

### 4.2 Project state — after

```
app/
  core/
    config.py          # DPOP_ENABLED, DPOP_NONCE_TTL_S, DPOP_CLOCK_SKEW_S injected
    dpop.py            # DPoPVerifier, DPoPNonceStore, generate_dpop_key_pair,
                       # jwk_from_public_key
    dpop_deps.py       # require_dpop, require_dpop_async
  api/
    routes/
      dpop_nonce.py    # POST /auth/dpop/nonce
  routes/
    __init__.py        # dpop nonce router registered
requirements.txt       # PyJWT>=2.9.0 appended
```

### 4.3 DPoPVerifier core (generated)

```python
# app/core/dpop.py
"""DPoP proof-of-possession verifier (RFC 9449 / FAPI 2.0)."""

from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from app.core.config import settings

_ALLOWED_ALGS = {"ES256", "RS256", "PS256", "ES384", "ES512", "EdDSA"}


@dataclass
class DPoPNonceStore:
    """Thread-safe TTL store for nonces and JTI replay prevention."""

    _nonces: dict[str, float] = field(default_factory=dict)
    _jtis: dict[str, float] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def mark_jti(self, jti: str, ttl: int) -> bool:
        """Return True if jti is new; False if already seen (replay)."""
        now = time.monotonic()
        with self._lock:
            self._evict(now)
            if jti in self._jtis:
                return False
            self._jtis[jti] = now + ttl
            return True

    def _evict(self, now: float) -> None:
        expired = [k for k, exp in self._jtis.items() if exp <= now]
        for k in expired:
            del self._jtis[k]
```

### 4.4 verify_proof with lazy PyJWT import

```python
class DPoPVerifier:
    """Validates DPoP proof headers against RFC 9449 rules."""

    def __init__(self, nonce_store: DPoPNonceStore) -> None:
        self._store = nonce_store

    def verify_proof(
        self,
        proof: str,
        expected_htm: str,
        expected_htu: str,
    ) -> dict[str, Any]:
        import jwt  # lazy: only imported when verification runs
        header = jwt.get_unverified_header(proof)
        alg = header.get("alg", "")
        if alg not in _ALLOWED_ALGS:
            raise ValueError(f"DPoP alg {alg!r} not in allowed set")
        # htm, htu, iat, jti validation follows ...
```

### 4.5 Config patch

```python
# app/core/config.py — injected block
    # --- DPoP tokens — added by add_dpop_tokens tool ---
    DPOP_ENABLED: bool = True
    DPOP_NONCE_TTL_S: int = 300
    DPOP_CLOCK_SKEW_S: int = 30
```

### 4.6 Nonce endpoint

```python
# app/api/routes/dpop_nonce.py (generated)
router = APIRouter(prefix="/auth/dpop", tags=["dpop"])

@router.post("/nonce")
async def issue_dpop_nonce() -> Response:
    """Issue a fresh DPoP nonce per RFC 9449 §8."""
    nonce = secrets.token_urlsafe(32)
    return Response(
        status_code=200,
        headers={"DPoP-Nonce": nonce},
    )
```

---

## 5. Quality Standards

| ID | Standard |
|---|---|
| QS-1 | `status == "success"` on first run against a fresh fixture project |
| QS-2 | Second run returns `status == "no_op"` with empty `files_created` and `files_modified` |
| QS-3 | `dry_run=True` returns success without writing any bytes to disk |
| QS-4 | `files_created` contains ≥ 3 entries; all paths exist on disk |
| QS-5 | `files_modified` contains ≥ 2 entries; all paths exist on disk |
| QS-6 | Every generated `.py` file passes `ast.parse()` without `SyntaxError` |
| QS-7 | No function in generated `app/` exceeds 50 LOC |
| QS-8 | `DPOP_ENABLED`, `DPOP_NONCE_TTL_S`, `DPOP_CLOCK_SKEW_S` present in `config.py` with 4-space indent |
| QS-9 | DPoP nonce router is registered in `app/routes/__init__.py` |
| QS-10 | `app/core/dpop.py` contains `DPoPVerifier` and `DPoPNonceStore` |
| QS-11 | `jwt` (PyJWT) is NOT imported at module top level in `dpop.py` |
| QS-12 | `app/core/dpop_deps.py` contains `require_dpop` and `require_dpop_async` |
| QS-13 | `app/api/routes/dpop_nonce.py` contains `/auth/dpop` or `dpop/nonce` and `DPoP-Nonce` header |
| QS-14 | `htm` and `htu` claim validation present in `dpop.py` |
| QS-15 | `mark_jti` method and `jti` claim referenced in `dpop.py` |
| QS-16 | `ES256` and `RS256` present in the allowed algorithms set |
| QS-17 | `generate_dpop_key_pair` and `jwk_from_public_key` helper functions present |
| QS-18 | `requirements.txt` contains `PyJWT` |

---

## 6. Completeness Criteria

| ID | Test function | What it verifies |
|---|---|---|
| CC-01 | `test_success_status` | Tool returns `status='success'` on a fresh project |
| CC-02 | `test_idempotent` | Second run returns `status='no_op'`; no files created or modified |
| CC-03 | `test_dry_run` | `dry_run=True` returns success without writing any bytes to disk |
| CC-04 | `test_files_created_count` | At least 3 files created; all exist on disk |
| CC-05 | `test_files_modified_count` | At least 2 files modified; all exist on disk |
| CC-06 | `test_all_py_parse` | Every generated `.py` file AST-parses clean |
| CC-07 | `test_no_function_over_50_loc` | No function in `app/` exceeds 50 LOC |
| CC-08 | `test_config_fields_patched` | `DPOP_ENABLED`, `DPOP_NONCE_TTL_S`, `DPOP_CLOCK_SKEW_S` present with 4-space indent |
| CC-09 | `test_routes_registered` | DPoP nonce router registered in `app/routes/__init__.py` |
| CC-10 | `test_dpop_core_file_exists` | `app/core/dpop.py` contains `DPoPVerifier` and `DPoPNonceStore` |
| CC-11 | `test_pyjwt_lazy_import` | `jwt` NOT imported at module top level in `dpop.py` |
| CC-12 | `test_require_dpop_dependency_exists` | `app/core/dpop_deps.py` contains `require_dpop` and `require_dpop_async` |
| CC-13 | `test_nonce_route_exists` | `dpop_nonce.py` exists with DPoP nonce endpoint and `DPoP-Nonce` header |
| CC-14 | `test_htm_htu_validation_present` | `htm` and `htu` claims validated in `dpop.py` |
| CC-15 | `test_nonce_store_replay_protection` | `mark_jti` method and `jti` claim present in `dpop.py` |
| CC-16 | `test_allowed_algorithms_present` | `ES256` and `RS256` in allowed algorithms set |
| CC-17 | `test_keygen_helpers_present` | `generate_dpop_key_pair` and `jwk_from_public_key` present in `dpop.py` |
| CC-18 | `test_requirements_pyjwt` | `requirements.txt` contains `PyJWT` |
| CC-19 | `test_execution_time_recorded` | `execution_time_ms > 0` |
| CC-20 | `test_next_steps_present` | `next_steps` non-empty; mentions `DPOP_ENABLED` or `DPoP` |
| CC-21 | `test_idempotent_project_still_parses` | All `.py` files parse after two consecutive runs |

---

## 7. Definition of Done

- [ ] All 21 tests in `test_add_dpop_tokens.py` pass
- [ ] `DPoPVerifier` with `verify_proof()` validates alg, jwk, htm, htu, iat, jti
- [ ] `DPoPNonceStore` implements TTL eviction and `mark_jti()` replay protection
- [ ] `_ALLOWED_ALGS` set includes ES256, RS256, PS256, ES384, ES512, EdDSA
- [ ] `jwt` (PyJWT) imported lazily inside `verify_proof()` — never at module top level
- [ ] `require_dpop` and `require_dpop_async` FastAPI dependencies in `dpop_deps.py`
- [ ] `POST /auth/dpop/nonce` endpoint returns `DPoP-Nonce` response header
- [ ] `generate_dpop_key_pair()` and `jwk_from_public_key()` helper functions present
- [ ] Config fields injected with 4-space indent; `requirements.txt` updated with `PyJWT`
- [ ] `next_steps` mentions `DPOP_ENABLED` or `DPoP`

---

## 8. Invariants

| ID | Invariant |
|---|---|
| INV-DPOP-001 | `jwt` (PyJWT) is NEVER imported at module top level in `dpop.py` |
| INV-DPOP-002 | `mark_jti()` MUST return `False` when a JTI has already been seen (replay attack) |
| INV-DPOP-003 | `htm` and `htu` claims MUST be validated against the actual request values |
| INV-DPOP-004 | `iat` MUST be within `DPOP_CLOCK_SKEW_S` seconds of server time |
| INV-DPOP-005 | `alg` MUST be checked against `_ALLOWED_ALGS` before decoding |
| INV-DPOP-006 | Idempotency fingerprint is `"DPoPVerifier" in app/core/dpop.py` |
| INV-DPOP-007 | Config block anchored on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` |
| INV-DPOP-008 | All generated `.py` files pass `ast.parse()` before `ToolResult` is returned |

---

## 9. User Stories

| ID | Story |
|---|---|
| US-01 | As a security architect, I want DPoP binding so that stolen access tokens cannot be replayed from a different client. |
| US-02 | As a developer, I want `require_dpop` as a FastAPI dependency so that I can add proof-of-possession to individual routes with a single decorator. |
| US-03 | As an API consumer, I want a `POST /auth/dpop/nonce` endpoint so that I can obtain fresh nonces as required by RFC 9449 §8. |
| US-04 | As a compliance engineer, I want `htm` and `htu` validation, so that proofs are bound to specific HTTP methods and URIs. |
| US-05 | As a platform engineer, I want `generate_dpop_key_pair()` and `jwk_from_public_key()` helpers, so that integration tests can create valid proofs without external tooling. |
| US-06 | As an app developer, I want `PyJWT` to be a lazy import, so that the app boots without it when DPoP is disabled. |

---

## 10. Design Decisions

| Decision | Rationale |
|---|---|
| Lazy `jwt` import inside `verify_proof()` | App boots without PyJWT when `DPOP_ENABLED=false` |
| `_ALLOWED_ALGS` as a frozenset-like constant | Prevents accidental mutation; easy to extend |
| `DPoPNonceStore` uses `threading.Lock` | ASGI apps may use sync endpoints; lock is always safe |
| TTL eviction on `mark_jti()` insert | Lazy eviction avoids background threads |
| `POST /auth/dpop/nonce` prefix `/auth/dpop` | Consistent with RFC 9449 §8 recommendation |
| `require_dpop_async` variant | FastAPI async routes need an async dependency |
| `generate_dpop_key_pair()` in core module | Enables self-contained integration tests |
| `DPoP-Nonce` in response header (not body) | Required by RFC 9449 — clients must read the header |

---

## 11. Dependencies

| Package | Version | Purpose | Import style |
|---|---|---|---|
| `PyJWT` | `>=2.9.0` | JWT decoding and header parsing | Lazy (inside `verify_proof()`) |
| `cryptography` | (PyJWT dep) | EC/RSA key operations | Transitive |
| `starlette` | (FastAPI dep) | `Request` type for dependency injection | Top-level |

---

## 12. Error Handling

| Scenario | Behavior |
|---|---|
| `dpop.py` already contains `DPoPVerifier` | Return `status="no_op"` immediately |
| `app/` directory missing | Return `status="error"` with descriptive `error` field |
| Generated `.py` has `SyntaxError` | Return `status="error"`; file NOT committed |
| `alg` not in `_ALLOWED_ALGS` | `verify_proof()` raises `ValueError` |
| `htm` or `htu` mismatch | `verify_proof()` raises `ValueError` |
| `iat` outside clock skew | `verify_proof()` raises `ValueError` |
| `jti` already seen (replay) | `verify_proof()` raises `ValueError` |
| `PyJWT` not installed at runtime | `ImportError` from lazy import inside `verify_proof()` |

---

## 13. Security Considerations

- `_ALLOWED_ALGS` must NOT include `none` or symmetric algorithms (`HS256`, `HS384`, `HS512`).
- `mark_jti()` MUST lock the store — without locking, concurrent requests can replay the same JTI.
- Clock skew (`DPOP_CLOCK_SKEW_S`) should be kept small (≤ 60 s) to prevent extended replay windows.
- The `jwk` embedded in the DPoP proof must match the key used to sign the proof — implementations must verify this.
- `POST /auth/dpop/nonce` must not be rate-limited below 1 req/s per client to avoid FAPI 2.0 flow failures.
- DPoP does NOT replace TLS. It is an additional binding layer — the connection must still be over HTTPS.

---

## 14. Testing Guide

```bash
# Run the full test suite
PYTHONPATH=. pytest adapt/extend/auth_access/test_add_dpop_tokens.py -v

# Run standalone (no pytest required)
PYTHONPATH=. python3 adapt/extend/auth_access/test_add_dpop_tokens.py

# Run a single test
PYTHONPATH=. pytest adapt/extend/auth_access/test_add_dpop_tokens.py::test_pyjwt_lazy_import -v

# Check that jwt is not at module top level
python3 -c "
import ast
from pathlib import Path
from adapt.contracts import ToolInput
from adapt.extend.auth_access.add_dpop_tokens import add_dpop_tokens
from tests.common.fixture_factory import create_fixture_project
p = create_fixture_project(name='dpop_manual')
add_dpop_tokens(ToolInput(project_dir=str(p)))
tree = ast.parse((p / 'app' / 'core' / 'dpop.py').read_text())
top_imports = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
print([getattr(n, 'module', None) or [a.name for a in n.names] for n in top_imports])
"
```

---

## 15. Files Reference

| File | Role |
|---|---|
| `adapt/extend/auth_access/add_dpop_tokens.py` | Tool entry point |
| `adapt/extend/auth_access/test_add_dpop_tokens.py` | 21-test structural test suite |
| `app/core/dpop.py` | DPoPVerifier, DPoPNonceStore, helpers |
| `app/core/dpop_deps.py` | require_dpop, require_dpop_async |
| `app/api/routes/dpop_nonce.py` | POST /auth/dpop/nonce |
| `app/core/config.py` | Patched with DPOP_ENABLED, DPOP_NONCE_TTL_S, DPOP_CLOCK_SKEW_S |
| `requirements.txt` | Patched with PyJWT>=2.9.0 |

---

## 16. Changelog

| Version | Date | Change |
|---|---|---|
| 1.0.0 | 2026-04-15 | Initial spec — 21 CCs, RFC 9449 / FAPI 2.0, lazy PyJWT, nonce endpoint |
