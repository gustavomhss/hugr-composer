---
spec_id: "TOOL-089"
tool_name: "add_csrf_protection"
version: "1.0.0"
status: "ratified"
invariants:
  - "INV-CSRF-01"
  - "INV-CSRF-02"
  - "INV-CSRF-03"
  - "INV-CSRF-04"
  - "INV-CSRF-05"
  - "INV-CSRF-06"
  - "INV-CSRF-07"
  - "INV-CSRF-08"
  - "INV-CSRF-09"
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
tags:
  - "performance"
  - "payments"
  - "realtime"
  - "compliance"
  - "api"
---
# TOOL-089: add_csrf_protection

> **Status**: SPEC v1 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_csrf_protection` |
| Category | EXTEND > Infrastructure |
| Complexity | Medium |
| Dependencies | FastAPI, Starlette (bundled); stdlib `hmac`, `hashlib`, `secrets` — no new packages |
| Signature | `add_csrf_protection(inp: ToolInput) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path to FastAPI project root) and `dry_run` flag |
| MCP descriptor | `{"name": "fastapi_add_csrf_protection", "description": "Add CSRF token protection with double-submit cookie pattern to FastAPI.", "tags": ["extend", "infrastructure"], "entry": "add_csrf_protection"}` |
| Files created (typical) | 4 — `app/security/__init__.py`, `app/security/csrf.py`, `app/security/csrf_middleware.py`, `app/api/routes/csrf.py` |
| Files modified (typical) | 2 — `app/core/config.py`, `app/main.py` |

---

## 2. Purpose

The `fastapi_add_csrf_protection` tool adds cross-site request forgery protection to a FastAPI project using the **double-submit cookie pattern** — zero external dependencies, pure Python stdlib (`hmac`, `hashlib`, `secrets`). CSRF vulnerabilities are in the OWASP Top 10 for a reason: any state-mutating endpoint reachable from a browser is vulnerable when the session is cookie-based, and most FastAPI tutorials skip CSRF entirely because they assume JWT Bearer tokens in headers (which are same-origin by construction). The moment a project adds cookie auth, session auth, or any authentication that browsers replay automatically, CSRF becomes a real attack surface.

The double-submit cookie pattern is the right choice here because it requires no server-side session storage. The client receives a signed HMAC-SHA256 token via `GET /csrf/token`, stores it as a `SameSite=Strict` cookie, and sends it back in an `X-CSRF-Token` request header for every unsafe method (POST/PUT/PATCH/DELETE). The middleware compares cookie and header tokens, verifies the HMAC signature, and checks token age against `_TOKEN_MAX_AGE_SECONDS`. A forged token fails signature verification. A cross-origin request cannot read the cookie (SameSite=Strict) and cannot forge the header from a third-party origin — both vectors blocked.

Key design decisions: (a) `CSRFProtection` is a plain class accepting a `secret_key`, `cookie_name`, `header_name`, and `max_age` so it can be instantiated anywhere without FastAPI context; (b) `CSRFMiddleware` reads settings lazily from `app.core.config.settings` at dispatch time (not at class creation) so the settings module does not need to be importable at middleware instantiation; (c) exempt paths are an explicit list (prefix matching) so webhooks and health checks can bypass CSRF; (d) the `GET /csrf/token` endpoint issues a new token on every call and sets the cookie, making it safe to call from SPA `useEffect`; (e) no external deps means the tool can be applied to any Python 3.10+ project without pip changes.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | CI step budget |
| Files created | ≥ 4 | Security package: init, csrf, middleware, route |
| Files modified | ≥ 1 | `config.py` at minimum |
| Max function LOC in generated code | ≤ 50 | Auditable functions |
| CSRF validation overhead | < 1 ms | HMAC-SHA256 of a small payload |
| Token generation time | < 1 ms | `secrets.token_hex(16)` + HMAC |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
project/
├── app/
│   ├── main.py              # FastAPI app, no CSRF middleware
│   ├── core/
│   │   └── config.py        # Settings class, no CSRF_* fields
│   └── api/
│       └── routes/
└── requirements.txt
```

Any state-mutating endpoint is vulnerable to CSRF. A forged POST from `evil.com` using a victim's browser cookies would succeed if the API uses cookie-based auth.

### 4.2 CSRF core (token generation / validation): AFTER

```python
# app/security/csrf.py
"""CSRF token generation and validation — double-submit cookie pattern."""
from __future__ import annotations
import hashlib, hmac, logging, secrets, time
from starlette.responses import Response

logger = logging.getLogger(__name__)
_TOKEN_SEPARATOR = "."


class CSRFProtection:
    """CSRF protection using HMAC-signed tokens."""

    def __init__(self, secret_key: str, cookie_name: str = "csrftoken",
                 header_name: str = "X-CSRF-Token", max_age: int = 3600) -> None:
        self._secret = secret_key.encode()
        self.cookie_name = cookie_name
        self.header_name = header_name
        self.max_age = max_age

    def generate_token(self) -> str:
        """Generate a new HMAC-signed CSRF token."""
        random_part = secrets.token_hex(16)
        timestamp = str(int(time.time()))
        payload = f"{random_part}{_TOKEN_SEPARATOR}{timestamp}"
        sig = self._sign(payload)
        return f"{payload}{_TOKEN_SEPARATOR}{sig}"

    def validate_token(self, token: str) -> bool:
        """Validate a CSRF token: checks signature and expiry."""
        parts = token.split(_TOKEN_SEPARATOR)
        if len(parts) != 3:
            return False
        random_part, ts_str, sig = parts
        payload = f"{random_part}{_TOKEN_SEPARATOR}{ts_str}"
        if not hmac.compare_digest(sig, self._sign(payload)):
            return False
        try:
            if int(time.time()) - int(ts_str) > self.max_age:
                return False
        except ValueError:
            return False
        return True

    def get_csrf_cookie(self, response: Response, token: str) -> None:
        """Set the CSRF token as SameSite=Strict cookie."""
        response.set_cookie(key=self.cookie_name, value=token,
                            httponly=False, samesite="strict", max_age=self.max_age)

    def _sign(self, payload: str) -> str:
        return hmac.new(self._secret, payload.encode(), hashlib.sha256).hexdigest()
```

### 4.3 CSRF middleware: AFTER

```python
# app/security/csrf_middleware.py
"""CSRFMiddleware — validates tokens on unsafe HTTP methods."""
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class CSRFMiddleware(BaseHTTPMiddleware):
    """Double-submit CSRF protection middleware."""
    def __init__(self, app, exempt_paths=None):
        super().__init__(app)
        self._exempt = exempt_paths or []

    async def dispatch(self, request, call_next):
        if request.method not in _UNSAFE_METHODS:
            return await call_next(request)
        if any(request.url.path.startswith(p) for p in self._exempt):
            return await call_next(request)
        # ... validate cookie + header tokens, return 403 on failure
```

### 4.4 Token endpoint: AFTER

```python
# app/api/routes/csrf.py
router = APIRouter(prefix="/csrf", tags=["csrf"])

@router.get("/token")
async def get_csrf_token() -> JSONResponse:
    """Issue a new CSRF token and set the SameSite cookie."""
    from app.core.config import settings
    from app.security.csrf import CSRFProtection
    protection = CSRFProtection(secret_key=settings.CSRF_SECRET_KEY, ...)
    token = protection.generate_token()
    response = JSONResponse(content={"csrf_token": token})
    protection.get_csrf_cookie(response, token)
    return response
```

### 4.5 Config patch: AFTER

```python
# app/core/config.py  (diff, 4-space indented inside class Settings)
    # --- CSRF Protection (added by add_csrf_protection tool) ---
    CSRF_ENABLED: bool = True
    CSRF_SECRET_KEY: str = "change-this-csrf-secret-key-min-32-chars!"
    CSRF_COOKIE_NAME: str = "csrftoken"
    CSRF_HEADER_NAME: str = "X-CSRF-Token"
    CSRF_EXEMPT_PATHS: list[str] = []
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Tool is idempotent on second run** | Fingerprint check `"CSRFProtection" in csrf_file.read_text()` returns `status="no_op"` |
| QS-2 | **`dry_run=True` writes zero files** | Early return before any filesystem write |
| QS-3 | **Every generated `.py` file AST-parses** | `ast.parse` loop over `files_created` |
| QS-4 | **No generated function exceeds 50 LOC** | All helpers kept ≤ 50 lines; AST walk asserts |
| QS-5 | **No external dependencies** | Only stdlib `hmac`, `hashlib`, `secrets` — no `cryptography`, `itsdangerous`, `passlib` |
| QS-6 | **Double-submit pattern: cookie AND header must match** | `_validate_csrf_tokens` checks both tokens are identical and HMAC-valid |
| QS-7 | **HMAC-SHA256 used for signing** | `hmac.new(..., hashlib.sha256)` in `_sign` |
| QS-8 | **`SameSite=Strict` cookie prevents cross-origin read** | `response.set_cookie(..., samesite="strict")` in `get_csrf_cookie` |
| QS-9 | **Unsafe methods checked: POST/PUT/PATCH/DELETE** | `_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})` |
| QS-10 | **Returns 403 on invalid CSRF token** | `JSONResponse(status_code=403, ...)` in `_check_csrf` |
| QS-11 | **`CSRF_*` fields 4-space indented inside `class Settings`** | `_patch_config` enforces indent |
| QS-12 | **`execution_time_ms` set on every return path** | `_elapsed_ms(start)` on all branches |

---

## 6. Completeness Criteria

Every criterion is tied to a real assertion in `test_add_csrf_protection.py`.

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | Tool returns `status="success"` on a fresh project | `result.status == "success"` | `test_success_status` |
| CC-02 | Second run returns `status="no_op"` with zero file ops | `r2.status == "no_op"` and both lists empty | `test_idempotent` |
| CC-03 | `dry_run=True` writes zero bytes to the filesystem | `before == after` dict | `test_dry_run` |
| CC-04 | Tool creates at least 4 new files | `len(result.files_created) >= 4` | `test_files_created_count` |
| CC-05 | Tool modifies at least 1 existing file | `len(result.files_modified) >= 1` | `test_files_modified_count` |
| CC-06 | Every generated `.py` AST-parses cleanly | `ast.parse` over all `.py` in project | `test_all_py_parse` |
| CC-07 | No generated function exceeds 50 LOC | AST walk, `loc <= 50` | `test_no_function_over_50_loc` |
| CC-08 | `CSRF_ENABLED`, `CSRF_SECRET_KEY`, `CSRF_COOKIE_NAME`, `CSRF_HEADER_NAME`, `CSRF_EXEMPT_PATHS` in `config.py` with 4-space indent | String scan + indent check | `test_config_fields_patched` |
| CC-09 | `app/api/routes/csrf.py` created with `router` | File exists + `"router" in src` | `test_routes_registered` |
| CC-10 | `app/security/__init__.py` created and exports `CSRFProtection` | File exists + `"CSRFProtection" in src` | `test_csrf_security_init_created` |
| CC-11 | `app/security/csrf.py` created with `class CSRFProtection` | File exists + `"class CSRFProtection" in src` | `test_csrf_core_file_created` |
| CC-12 | `generate_token()` method present | `"def generate_token" in src` | `test_csrf_generate_token_method` |
| CC-13 | `validate_token()` method present | `"def validate_token" in src` | `test_csrf_validate_token_method` |
| CC-14 | `get_csrf_cookie()` method present | `"def get_csrf_cookie" in src` | `test_csrf_get_csrf_cookie_method` |
| CC-15 | `app/security/csrf_middleware.py` with `class CSRFMiddleware` | File exists + `"class CSRFMiddleware" in src` | `test_csrf_middleware_file_created` |
| CC-16 | `execution_time_ms` is a positive integer | `result.execution_time_ms > 0` | `test_execution_time_recorded` |

---

## 7. Definition of Done (DoD)

- [ ] All 16 Completeness Criteria verified by `test_add_csrf_protection.py`
- [ ] `add_csrf_protection.py` runs `ast.parse` on every created `.py` file before returning success
- [ ] Fingerprint check `"CSRFProtection" in csrf.py` returns `status="no_op"` on second run
- [ ] `dry_run=True` returns success with empty `files_created`/`files_modified`
- [ ] `CSRFProtection` uses only stdlib `hmac`, `hashlib`, `secrets` — no external crypto
- [ ] Token format: `{random}.{timestamp}.{hmac}`; `validate_token` verifies all three parts
- [ ] `CSRFMiddleware` checks POST/PUT/PATCH/DELETE and returns 403 on failure
- [ ] `SameSite=Strict` set on the CSRF cookie
- [ ] `CSRF_*` fields inserted with 4-space indent inside `class Settings` body
- [ ] `GET /csrf/token` endpoint issues token and sets cookie
- [ ] `execution_time_ms` set on every return path
- [ ] `MCP_TOOL` descriptor exposes `{name, description, tags, entry}` quartet

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-CSRF-01 | Tool is ALWAYS idempotent on second invocation | `"CSRFProtection" in csrf_file.read_text()` → `status="no_op"` | `test_idempotent` |
| INV-CSRF-02 | `dry_run=True` NEVER writes to disk | Early return before any write | `test_dry_run` |
| INV-CSRF-03 | Every generated `.py` MUST parse as valid Python | `ast.parse` loop | `test_all_py_parse` |
| INV-CSRF-04 | MUST use only stdlib for crypto — no external deps | Checked by `test_csrf_no_external_deps` | `test_csrf_no_external_deps` |
| INV-CSRF-05 | MUST check both cookie and header tokens (double-submit) | `_validate_csrf_tokens` requires both | `test_csrf_middleware_double_submit_pattern` |
| INV-CSRF-06 | MUST return 403 when CSRF token missing | `JSONResponse(status_code=403, ...)` | `test_csrf_403_on_missing_token` |
| INV-CSRF-07 | MUST set `SameSite=Strict` cookie | `samesite="strict"` in `set_cookie` | `test_csrf_samesite_cookie` |
| INV-CSRF-08 | `CSRF_*` fields MUST be 4-space indented inside `class Settings` | `_patch_config` enforces indent | `test_config_fields_patched` |
| INV-CSRF-09 | `ToolResult.execution_time_ms` MUST be positive on every return path | `_elapsed_ms(start)` on all branches | `test_execution_time_recorded` |

---

## 9. User Stories

### 9.1 Core install flow (US-01 .. US-05)

**US-01: Add CSRF protection to a FastAPI project**
- **As a** security-conscious backend engineer
- **I want** CSRF tokens with double-submit cookie pattern
- **So that** state-mutating endpoints are protected from cross-origin forgery
- **Given:** FastAPI project with cookie-based auth
- **When:** `add_csrf_protection(ToolInput(project_dir=...))`
- **Then:** `CSRFMiddleware` and `CSRFProtection` installed, `GET /csrf/token` available

**US-02: Re-run safely on already-protected project**
- **Given:** `app/security/csrf.py` already contains `CSRFProtection`
- **When:** `add_csrf_protection(...)` invoked again
- **Then:** Returns `status="no_op"`, no files written

**US-03: Preview changes without writing files**
- **Given:** Fresh project
- **When:** `add_csrf_protection(ToolInput(project_dir=..., dry_run=True))`
- **Then:** Returns `status="success"` with notes, zero files written

**US-04: Frontend integration — fetch token then send header**
- **As a** frontend developer integrating CSRF
- **I want** a clear token endpoint and header protocol
- **Given:** `add_csrf_protection` applied
- **When:** `GET /csrf/token` (on app load), then `X-CSRF-Token: <token>` on POST
- **Then:** Server validates double-submit and processes the request

**US-05: Exempt webhooks from CSRF checks**
- **As a** backend engineer receiving Stripe webhooks
- **I want** to exempt `/webhooks/stripe` from CSRF validation
- **Given:** `CSRFMiddleware(app, exempt_paths=["/webhooks/stripe"])`
- **Then:** Webhook POST bypasses CSRF check; all other POSTs are protected

---

## 10. Edge Cases

| Edge Case | Handling |
|-----------|----------|
| Token with wrong number of separator parts | `validate_token` returns `False` (len check) |
| Expired token (age > `max_age`) | `validate_token` returns `False` |
| Tampered HMAC signature | `hmac.compare_digest` constant-time comparison returns `False` |
| `CSRF_SECRET_KEY` is less than 32 chars | No enforcement at tool level; `next_steps` advise min 32 chars |
| Both cookie and header present but don't match | `_validate_csrf_tokens` returns mismatch error → 403 |
| `app/api/routes/` directory does not exist | `csrf.py` route skipped; tool still succeeds with security package only |

---

## 11. Dependencies and Prerequisites

| Dependency | Version | Role | Install? |
|------------|---------|------|---------|
| Python stdlib | 3.10+ | `hmac`, `hashlib`, `secrets` | Already present |
| FastAPI | any | `BaseHTTPMiddleware`, `JSONResponse` | Already present |
| Starlette | bundled | `Request`, `Response` | Already present |

**Prerequisites** (checked by `ensure_prerequisites`):
- `Prereq.CONFIG_SETTINGS` — `app/core/config.py` with `class Settings`
- `Prereq.REQUIREMENTS_TXT` — `requirements.txt` exists

No new packages added to `requirements.txt`.

---

## 12. File Map

```
project/
├── app/
│   ├── security/
│   │   ├── __init__.py              [CREATED] Exports CSRFProtection
│   │   ├── csrf.py                  [CREATED] CSRFProtection class
│   │   └── csrf_middleware.py       [CREATED] CSRFMiddleware
│   ├── api/
│   │   └── routes/
│   │       └── csrf.py              [CREATED] GET /csrf/token
│   ├── core/
│   │   └── config.py                [MODIFIED] CSRF_* fields added
│   └── main.py                      [MODIFIED] CSRF router comment added
```

---

## 13. Rollback

To remove CSRF protection:

1. Delete `app/security/csrf.py`, `app/security/csrf_middleware.py`, `app/security/__init__.py`
2. Delete `app/api/routes/csrf.py`
3. Remove `CSRF_*` fields from `app/core/config.py`
4. Remove CSRF router and middleware registration from `app/main.py`

---

## 14. Security Considerations

| Concern | Mitigation |
|---------|-----------|
| Timing attack on HMAC comparison | `hmac.compare_digest` used — constant-time |
| Token entropy | `secrets.token_hex(16)` = 128 bits entropy |
| Cookie readable by same-origin JS (needed for double-submit) | `httponly=False` intentional; SameSite=Strict blocks cross-origin reads |
| `CSRF_SECRET_KEY` default value in config | Default is clearly marked as insecure placeholder; `next_steps` require changing it |

---

## 15. Observability

| Signal | Where | Content |
|--------|-------|---------|
| `logger.warning` | `validate_token` | Signature mismatch and expired token warnings |
| `logger.warning` | `_validate_csrf_tokens` | Missing token and mismatch warnings |
| `logger.debug` | `get_csrf_token` route | Token issued |
| `ToolResult.notes` | Success return | CSRF setup summary |
| `ToolResult.next_steps` | Success return | `CSRF_SECRET_KEY`, middleware registration, frontend guide |
| `ToolResult.execution_time_ms` | All branches | Wall-clock milliseconds |

---

## 16. Test Coverage Map

| Test | CC | Description |
|------|----|-------------|
| `test_success_status` | CC-01 | Returns `status="success"` on fresh project |
| `test_idempotent` | CC-02 | Second run returns `no_op` |
| `test_dry_run` | CC-03 | `dry_run=True` writes nothing |
| `test_files_created_count` | CC-04 | At least 4 files created |
| `test_files_modified_count` | CC-05 | At least 1 file modified |
| `test_all_py_parse` | CC-06 | All `.py` parse cleanly |
| `test_no_function_over_50_loc` | CC-07 | No function > 50 LOC |
| `test_config_fields_patched` | CC-08 | `CSRF_*` fields with 4-space indent |
| `test_routes_registered` | CC-09 | `csrf.py` route created |
| `test_csrf_security_init_created` | CC-10 | `security/__init__.py` exports `CSRFProtection` |
| `test_csrf_core_file_created` | CC-11 | `csrf.py` with `class CSRFProtection` |
| `test_csrf_generate_token_method` | CC-12 | `generate_token()` present |
| `test_csrf_validate_token_method` | CC-13 | `validate_token()` present |
| `test_csrf_get_csrf_cookie_method` | CC-14 | `get_csrf_cookie()` present |
| `test_csrf_middleware_file_created` | CC-15 | `csrf_middleware.py` with `class CSRFMiddleware` |
| `test_execution_time_recorded` | CC-16 | `execution_time_ms > 0` |
| `test_csrf_middleware_checks_unsafe_methods` | INV-CSRF-05 | POST/PUT/PATCH/DELETE checked |
| `test_csrf_middleware_double_submit_pattern` | INV-CSRF-05 | Cookie and header both checked |
| `test_csrf_token_route_get_endpoint` | CC-09 | `GET /token` defined |
| `test_csrf_no_external_deps` | INV-CSRF-04 | Only stdlib crypto |
| `test_csrf_samesite_cookie` | INV-CSRF-07 | `SameSite` attribute set |
| `test_csrf_403_on_missing_token` | INV-CSRF-06 | 403 on missing token |
| `test_next_steps_present` | CC-16 | Non-empty `next_steps` |
| `test_idempotent_project_still_parses` | INV-CSRF-01/03 | After two runs all `.py` parseable |
