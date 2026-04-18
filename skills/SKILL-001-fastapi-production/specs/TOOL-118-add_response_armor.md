# TOOL-118 — add_response_armor

## 1. Overview

| Field | Value |
|---|---|
| **Tool ID** | TOOL-118 |
| **MCP name** | `fastapi_add_response_armor` |
| **Entry point** | `adapt/extend/infrastructure/add_response_armor.py::add_response_armor` |
| **Tags** | `security`, `response`, `armor`, `breach`, `crlf`, `timing-safe`, `error-sanitization` |
| **Input** | `ToolInput(project_dir, dry_run=False)` |
| **Output** | `ToolResult(status, files_created, files_modified, notes, next_steps, execution_time_ms)` |
| **Idempotency fingerprint** | `"ResponseArmorMiddleware" in app/middleware/response_armor.py` |
| **Prerequisite check** | `app/` directory exists |
| **Files created (min)** | 3 (`response_armor.py` core, `timing_safe.py`, `response_armor.py` middleware) |
| **Files modified (min)** | 2 (`app/core/config.py`, `app/main.py`) |
| **Test file** | `adapt/extend/infrastructure/test_add_response_armor.py` |

---

## 2. Purpose

API responses carry security signals in their structure: stack traces in error messages, secret substrings in body text, CRLF sequences that enable header injection, and missing `Cache-Control` headers that allow sensitive error responses to be cached. `add_response_armor` installs a 5-layer response hardening system:

1. **Error sanitization** — `sanitize_error(status_code, detail, request_id)` in `app/core/response_armor.py` returns a generic, client-safe message from `_GENERIC_MESSAGES` and logs the real detail at `logger.error` with event key `armor.error_sanitized`. The real stack trace never reaches the client.

2. **BREACH mitigation** — `breach_padding(max_bytes=32)` appends a random number of bytes (0–32) to compressed responses, breaking the length oracle that BREACH requires. Randomness comes from `os.urandom` (CSPRNG).

3. **CRLF injection prevention** — `strip_crlf(value)` removes `\r` and `\n` characters from all response header values before they are forwarded to clients.

4. **Cache-Control enforcement** — Middleware unconditionally sets `Cache-Control: no-store` on all 4xx and 5xx responses (`status_code >= 400`).

5. **Server header removal** — Middleware removes the `"server"` header from all responses to prevent framework fingerprinting.

A separate utility module `app/core/timing_safe.py` provides `compare_tokens(a, b)` which delegates exclusively to `hmac.compare_digest` — never `==`. This prevents timing-based token comparison attacks.

Config fields (`RESPONSE_ARMOR_ENABLED`, `RESPONSE_ARMOR_SANITIZE_ERRORS`, `RESPONSE_ARMOR_TIMING_SAFE`) are injected into `app/core/config.py` inside the `Settings` class body with 4-space indent. `register_response_armor(app)` is appended AFTER `app = FastAPI(...)` in `main.py`.

---

## 3. Performance SLOs

| Metric | Target |
|---|---|
| Tool execution time | < 2 s on a cold fixture project |
| `execution_time_ms` field | > 0 (always recorded) |
| BREACH padding overhead | < 0.1 ms per response (single `os.urandom` call) |
| CRLF strip overhead | < 0.1 ms per response header (string replace) |
| Files created | ≥ 3 |
| Files modified | ≥ 2 |
| Max function LOC in generated `app/` | ≤ 50 |

---

## 4. Before / After

### 4.1 Project state — before

```
app/
  core/
    config.py    # No RESPONSE_ARMOR_* fields
  main.py        # app = FastAPI(...); no armor middleware
```

### 4.2 Project state — after

```
app/
  core/
    config.py              # 3 RESPONSE_ARMOR_* fields injected
    response_armor.py      # sanitize_error, breach_padding, strip_crlf
    timing_safe.py         # compare_tokens via hmac.compare_digest
  middleware/
    response_armor.py      # ResponseArmorMiddleware,
                           # register_response_armor
  main.py                  # register_response_armor(app) appended
```

### 4.3 sanitize_error — generic messages + logging

```python
# app/core/response_armor.py (generated)
_GENERIC_MESSAGES: dict[int, str] = {
    400: "Bad request.",
    401: "Authentication required.",
    403: "Forbidden.",
    404: "Not found.",
    409: "Conflict.",
    422: "Unprocessable entity.",
    429: "Too many requests.",
    500: "An unexpected error occurred.",
    502: "Bad gateway.",
    503: "Service unavailable.",
}
_DEFAULT_GENERIC = "An error occurred."


def sanitize_error(status_code: int, detail: object, request_id: str = "") -> str:
    """Return a safe client-facing message; log the real detail.

    Args:
        status_code: HTTP status code.
        detail: Original exception detail (never sent to client).
        request_id: Optional request ID for correlation.

    Returns:
        Generic client-safe error message string.
    """
    logger.error(
        "armor.error_sanitized",
        extra={"status": status_code, "request_id": request_id, "detail_type": type(detail).__name__},
    )
    return _GENERIC_MESSAGES.get(status_code, _DEFAULT_GENERIC)
```

### 4.4 timing_safe — compare_tokens

```python
# app/core/timing_safe.py (generated)
import hmac


def compare_tokens(a: str, b: str) -> bool:
    """Compare two tokens in constant time using hmac.compare_digest.

    Args:
        a: First token string.
        b: Second token string.

    Returns:
        True if the tokens are equal; False otherwise.
    """
    return hmac.compare_digest(
        a.encode("utf-8") if isinstance(a, str) else a,
        b.encode("utf-8") if isinstance(b, str) else b,
    )
```

### 4.5 breach_padding and strip_crlf

```python
def breach_padding(max_bytes: int = 32) -> bytes:
    """Return random 0-max_bytes BREACH padding (CSPRNG)."""
    n = int.from_bytes(os.urandom(1), "big") % (max_bytes + 1)
    return os.urandom(n)


def strip_crlf(value: str) -> str:
    """Remove CR (\\r) and LF (\\n) from header values."""
    return value.replace("\r", "").replace("\n", "")
```

### 4.6 ResponseArmorMiddleware

```python
class ResponseArmorMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        # 1. Remove server header
        response.headers.pop("server", None)
        # 2. CRLF strip all headers
        for key, value in list(response.headers.items()):
            response.headers[key] = strip_crlf(value)
        # 3. Cache-Control on errors
        if response.status_code >= 400:
            response.headers["Cache-Control"] = "no-store"
        return response
```

### 4.7 Config patch (3 fields)

```python
    # --- Response armor — added by add_response_armor tool ---
    RESPONSE_ARMOR_ENABLED: bool = True
    RESPONSE_ARMOR_SANITIZE_ERRORS: bool = True
    RESPONSE_ARMOR_TIMING_SAFE: bool = True
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
| QS-8 | All 3 `RESPONSE_ARMOR_*` fields present in `config.py` with 4-space indent |
| QS-9 | `app/core/response_armor.py` contains `sanitize_error`, `breach_padding`, `strip_crlf` |
| QS-10 | `app/core/timing_safe.py` contains `hmac`, `compare_digest`, `def compare_tokens` |
| QS-11 | `app/middleware/response_armor.py` contains `ResponseArmorMiddleware` and `register_response_armor` |
| QS-12 | Middleware calls `strip_crlf` and references `crlf` in a comment or log |
| QS-13 | Middleware sets `Cache-Control: no-store` when `status_code >= 400` |
| QS-14 | Middleware removes the `"server"` header |
| QS-15 | `breach_padding` uses `os.urandom` or `secrets` (CSPRNG) |
| QS-16 | `sanitize_error` calls `logger.error` with event key `armor.error_sanitized` |
| QS-17 | `main.py` imports and calls `register_response_armor(app)` |
| QS-18 | `compare_tokens` delegates to `hmac.compare_digest` (verified by AST walk) |
| QS-19 | `register_response_armor(app)` appears AFTER `app = FastAPI(...)` in `main.py` |
| QS-20 | `strip_crlf` explicitly handles both `\r` and `\n` characters |

---

## 6. Completeness Criteria

| ID | Test function | What it verifies |
|---|---|---|
| CC-01 | `test_success_status` | Tool returns `status='success'` on a fresh project |
| CC-02 | `test_idempotent` | Second run returns `status='no_op'`; no files created or modified |
| CC-03 | `test_dry_run` | `dry_run=True` returns success without writing any bytes |
| CC-04 | `test_files_created_count` | At least 3 files created; all exist on disk |
| CC-05 | `test_files_modified_count` | At least 2 files modified; all exist on disk |
| CC-06 | `test_all_py_parse` | Every generated `.py` file AST-parses clean |
| CC-07 | `test_no_function_over_50_loc` | No function in `app/` exceeds 50 LOC |
| CC-08 | `test_config_fields_patched` | All 3 `RESPONSE_ARMOR_*` fields present with 4-space indent |
| CC-09 | `test_armor_core_created` | `sanitize_error`, `breach_padding`, `strip_crlf` present in core |
| CC-10 | `test_timing_safe_module_created` | `hmac`, `compare_digest`, `def compare_tokens` present in `timing_safe.py` |
| CC-11 | `test_middleware_created` | `ResponseArmorMiddleware` and `register_response_armor` present |
| CC-12 | `test_crlf_protection_in_middleware` | `strip_crlf` called; `crlf` referenced in middleware |
| CC-13 | `test_cache_control_enforced_on_error_responses` | `no-store`, `Cache-Control`, `>= 400` all present in middleware |
| CC-14 | `test_server_header_removed` | `"server"` or `'server'` present (header removal) |
| CC-15 | `test_breach_padding_uses_random_bytes` | `os.urandom` or `secrets` present in core |
| CC-16 | `test_sanitize_error_uses_logging` | `logger.error` and `armor.error_sanitized` present in core |
| CC-17 | `test_main_registers_armor` | `main.py` imports and calls `register_response_armor` |
| CC-18 | `test_execution_time_recorded` | `execution_time_ms > 0` |
| CC-19 | `test_next_steps_present` | `next_steps` mentions `response_armor` and `compare_tokens` |
| CC-20 | `test_idempotent_project_still_parses` | All `.py` files parse after two consecutive runs |
| CC-21 | `test_three_config_fields_exactly` | Exactly 3 `RESPONSE_ARMOR_*` field lines in `config.py` |
| CC-22 | `test_compare_tokens_uses_hmac_compare_digest` | AST walk confirms `compare_tokens` body contains `compare_digest` |
| CC-23 | `test_register_armor_positioned_after_fastapi` | `register_response_armor(app)` index > `app = FastAPI(` index |
| CC-24 | `test_strip_crlf_removes_both_cr_and_lf` | `\r` and `\n` both handled in `strip_crlf` |
| CC-25 | `test_no_files_mutated_outside_scope` | No file outside `files_created`/`files_modified` was changed |

---

## 7. Definition of Done

- [ ] All 25 tests in `test_add_response_armor.py` pass
- [ ] `sanitize_error`, `breach_padding`, `strip_crlf` generated in `app/core/response_armor.py`
- [ ] `compare_tokens` in `timing_safe.py` uses only `hmac.compare_digest` — never `==`
- [ ] `ResponseArmorMiddleware` strips CRLF from headers, removes `server` header, sets `Cache-Control: no-store` on 4xx/5xx
- [ ] `breach_padding` uses `os.urandom` (CSPRNG) for random byte count
- [ ] `sanitize_error` logs real detail at `logger.error` with `armor.error_sanitized` event
- [ ] Exactly 3 `RESPONSE_ARMOR_*` config fields with 4-space indent
- [ ] `register_response_armor(app)` injected into `main.py` AFTER `app = FastAPI(...)`

---

## 8. Invariants

| ID | Invariant |
|---|---|
| INV-RA-001 | `compare_tokens` MUST use `hmac.compare_digest` — NEVER `==` |
| INV-RA-002 | `breach_padding` MUST use a CSPRNG (`os.urandom` or `secrets`) |
| INV-RA-003 | `strip_crlf` MUST remove both `\r` and `\n` |
| INV-RA-004 | `sanitize_error` MUST log the real detail before returning the generic message |
| INV-RA-005 | Middleware MUST set `Cache-Control: no-store` when `status_code >= 400` |
| INV-RA-006 | Idempotency fingerprint is `"ResponseArmorMiddleware" in app/middleware/response_armor.py` |
| INV-RA-007 | Exactly 3 `RESPONSE_ARMOR_*` field lines in `config.py` |
| INV-RA-008 | `register_response_armor(app)` MUST appear after `app = FastAPI(...)` in `main.py` |

---

## 9. User Stories

| ID | Story |
|---|---|
| US-01 | As a security engineer, I want `sanitize_error` so that production stack traces never leak to clients. |
| US-02 | As a platform engineer, I want `breach_padding` so that BREACH compression oracle attacks are mitigated. |
| US-03 | As a developer, I want `compare_tokens` using `hmac.compare_digest` so that authentication comparisons are timing-safe. |
| US-04 | As a security engineer, I want automatic CRLF header stripping so that response-splitting attacks are prevented. |
| US-05 | As an SRE, I want the `server` header removed so that framework version fingerprinting is harder. |
| US-06 | As a compliance engineer, I want `Cache-Control: no-store` on error responses so that sensitive error details are not cached by proxies. |

---

## 10. Design Decisions

| Decision | Rationale |
|---|---|
| `compare_tokens` in separate `timing_safe.py` | Clean separation; easy to audit for timing-safety |
| `os.urandom` for BREACH padding | CSPRNG required; predictable padding is useless |
| `_GENERIC_MESSAGES` dict keyed by status code | Consistent generic messages across all error types |
| Log event key `armor.error_sanitized` | Structured log key enables alerting on sanitization events |
| `Cache-Control: no-store` on 4xx/5xx | Prevents proxy/browser caching of sensitive error details |
| Server header removal | Zero-cost fingerprinting reduction |
| `strip_crlf` as pure function | Testable without middleware; callable from route handlers too |

---

## 11. Dependencies

| Package | Version | Purpose | Import style |
|---|---|---|---|
| `hmac` | stdlib | `compare_digest` in `timing_safe.py` | Top-level |
| `os` | stdlib | `urandom` for BREACH padding | Top-level |
| `secrets` | stdlib | Alternative CSPRNG (fallback) | Optional |
| `starlette` | (FastAPI dep) | `BaseHTTPMiddleware`, `Response` | Top-level |

---

## 12. Error Handling

| Scenario | Behavior |
|---|---|
| `response_armor.py` already contains `ResponseArmorMiddleware` | Return `status="no_op"` |
| `app/` directory missing | Return `status="error"` with descriptive message |
| Generated `.py` has `SyntaxError` | Return `status="error"`; file NOT committed |
| `sanitize_error` called with unknown status code | Returns `_DEFAULT_GENERIC = "An error occurred."` |
| `strip_crlf` called with non-string | `replace` raises `AttributeError` — caller must ensure string type |
| Middleware exception during request processing | Exception propagates; no silent swallowing |

---

## 13. Security Considerations

- `compare_tokens` must NEVER fall back to `==` — even in error paths. An exception from `compare_digest` must be propagated, not caught with a fallback comparison.
- `breach_padding` randomness must be unpredictable. Using `random.randint` instead of `os.urandom` is a critical security defect.
- `sanitize_error` must log the real detail server-side — silently discarding it would hamper incident response.
- The `server` header removal is defense-in-depth; it does not prevent determined fingerprinting.
- `Cache-Control: no-store` on error responses prevents proxy caching but does not prevent the client from caching. TLS is still required.

---

## 14. Testing Guide

```bash
# Run full test suite
PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_response_armor.py -v

# Run standalone
PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_response_armor.py

# Verify compare_tokens uses hmac.compare_digest (AST check)
python3 -c "
import ast
from pathlib import Path
from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_response_armor import add_response_armor
from tests.common.fixture_factory import create_fixture_project
p = create_fixture_project(name='ra_manual')
add_response_armor(ToolInput(project_dir=str(p)))
content = (p / 'app' / 'core' / 'timing_safe.py').read_text()
tree = ast.parse(content)
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name == 'compare_tokens':
        body = ast.unparse(node)
        print('compare_digest in body:', 'compare_digest' in body)
"
```

---

## 15. Files Reference

| File | Role |
|---|---|
| `adapt/extend/infrastructure/add_response_armor.py` | Tool entry point |
| `adapt/extend/infrastructure/test_add_response_armor.py` | 25-test structural test suite |
| `app/core/response_armor.py` | sanitize_error, breach_padding, strip_crlf |
| `app/core/timing_safe.py` | compare_tokens via hmac.compare_digest |
| `app/middleware/response_armor.py` | ResponseArmorMiddleware, register_response_armor |
| `app/core/config.py` | Patched with RESPONSE_ARMOR_ENABLED, RESPONSE_ARMOR_SANITIZE_ERRORS, RESPONSE_ARMOR_TIMING_SAFE |
| `app/main.py` | Patched with register_response_armor(app) |

---

## 16. Changelog

| Version | Date | Change |
|---|---|---|
| 1.0.0 | 2026-04-15 | Initial spec — 25 CCs, 5-layer hardening, BREACH mitigation, timing-safe comparison |
