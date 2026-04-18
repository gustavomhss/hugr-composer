# TOOL-088: add_cors_config

> **Status**: SPEC v1 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_cors_config` |
| Category | EXTEND > Infrastructure |
| Complexity | Low |
| Dependencies | FastAPI, Starlette (bundled with FastAPI) |
| Signature | `add_cors_config(inp: ToolInput) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path to FastAPI project root) and `dry_run` flag |
| MCP descriptor | `{"name": "fastapi_add_cors_config", "description": "Upgrade CORS middleware with env-var configurable origins, wildcard warnings, preflight cache, and a /cors/config debug endpoint.", "tags": ["extend", "infrastructure", "security"], "entry": "add_cors_config"}` |
| Files created (typical) | 3 — `app/middleware/__init__.py`, `app/middleware/cors_config.py`, `app/api/routes/cors_debug.py` |
| Files modified (typical) | 2 — `app/core/config.py`, `app/main.py` |

---

## 2. Purpose

The `fastapi_add_cors_config` tool upgrades CORS configuration from a hardcoded middleware setup to an env-var driven one using `CORSConfigMiddleware`. Most FastAPI starters ship with `add_middleware(CORSMiddleware, allow_origins=["*"])` locked in at app creation time with no way to change it without a code deploy. In production, this means either shipping with a wildcard origin (a security hole) or baking an allowlist that breaks every time the frontend domain changes. The tool replaces that pattern with `CORS_ALLOWED_ORIGINS` (comma-separated environment variable), automatically parses the list, warns when wildcard is detected in non-local environments, adds a `CORS_MAX_AGE` knob for preflight cache duration (default 600 s), and exposes a `GET /cors/config` debug endpoint so frontend developers can verify what origins are accepted at runtime without reading deployment configs.

Three design decisions are worth noting. First, the middleware wraps the existing Starlette `CORSMiddleware` rather than reimplementing it, so all RFC 7231 and Fetch spec edge cases are handled by a battle-tested implementation. Second, wildcard detection is environment-aware: `*` is allowed in `local` and `test` environments (developer convenience) but triggers a `logger.warning` in any other environment, producing an auditable trail in log aggregators without crashing the app. Third, the tool is idempotent via `"CORSConfigMiddleware" in cors_config_file.read_text()` fingerprint detection, so re-running it in CI after it has already been applied returns `status="no_op"` without modifying any file.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | Must complete within CI step budget; measured via `execution_time_ms` in `ToolResult` |
| Files created | ≥ 1 | Middleware file at minimum |
| Files modified | ≥ 1 | At least `config.py` must receive the `CORS_*` fields |
| Max function LOC in generated code | ≤ 50 | Each generated function stays auditable; enforced by AST walk |
| Preflight cache | = `CORS_MAX_AGE` seconds | Configurable via env var, default 600 |
| Wildcard warning latency | 0 ms overhead | Pure logging call, no I/O |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
project/
├── app/
│   ├── main.py              # app.add_middleware(CORSMiddleware, allow_origins=["*"])
│   ├── core/
│   │   └── config.py        # Settings class, no CORS_* fields
│   └── api/
│       └── routes/
└── requirements.txt
```

Origins are hardcoded. Changing them requires a code change and redeploy. Wildcard `*` silently allows any domain in every environment.

### 4.2 Middleware module: AFTER

```python
# app/middleware/cors_config.py
"""CORSConfigMiddleware — env-var driven CORS with wildcard warnings."""

from __future__ import annotations
import logging
import os

from fastapi.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)


def _parse_origins(raw: str) -> list[str]:
    """Parse comma-separated origin string into a cleaned list."""
    return [o.strip() for o in raw.split(",") if o.strip()]


def _warn_if_wildcard(origins: list[str], environment: str) -> None:
    """Log a warning when wildcard is configured in non-local environments."""
    if "*" in origins and environment not in ("local", "test"):
        logger.warning(
            "CORS wildcard '*' is active in environment=%s — "
            "this disables origin protection.",
            environment,
        )


class CORSConfigMiddleware:
    """ASGI wrapper that installs CORSMiddleware from env-var settings."""

    def __init__(self, app: ASGIApp) -> None:
        raw_origins = os.getenv("CORS_ALLOWED_ORIGINS", "*")
        origins = _parse_origins(raw_origins)
        environment = os.getenv("ENVIRONMENT", "local")
        allow_credentials = (
            os.getenv("CORS_ALLOW_CREDENTIALS", "false").lower() == "true"
        )
        max_age = int(os.getenv("CORS_MAX_AGE", "600"))
        _warn_if_wildcard(origins, environment)
        self._app = CORSMiddleware(
            app=app,
            allow_origins=origins,
            allow_credentials=allow_credentials,
            allow_methods=["*"],
            allow_headers=["*"],
            max_age=max_age,
        )

    async def __call__(self, scope, receive, send) -> None:
        await self._app(scope, receive, send)
```

### 4.3 Debug route: AFTER

```python
# app/api/routes/cors_debug.py
"""GET /cors/config — debug endpoint showing active CORS configuration."""
from fastapi import APIRouter
import os

router = APIRouter(prefix="/cors", tags=["cors"])


@router.get("/config")
async def cors_config() -> dict:
    """Return the active CORS configuration from environment variables."""
    raw_origins = os.getenv("CORS_ALLOWED_ORIGINS", "*")
    origins = [o.strip() for o in raw_origins.split(",") if o.strip()]
    environment = os.getenv("ENVIRONMENT", "local")
    allow_credentials = os.getenv("CORS_ALLOW_CREDENTIALS", "false").lower() == "true"
    max_age = int(os.getenv("CORS_MAX_AGE", "600"))
    wildcard_warning = "*" in origins and environment not in ("local", "test")
    return {
        "allowed_origins": origins,
        "allow_credentials": allow_credentials,
        "max_age": max_age,
        "environment": environment,
        "wildcard_warning": wildcard_warning,
    }
```

### 4.4 Config patch: AFTER

```python
# app/core/config.py  (diff, added by _patch_config)
    # CORS configuration — added by add_cors_config tool
    CORS_ALLOWED_ORIGINS: str = "*"
    CORS_ALLOW_CREDENTIALS: bool = False
    CORS_MAX_AGE: int = 600
```

### 4.5 main.py patch: AFTER

```python
# app/main.py  (diff, added by _patch_main)
from fastapi import FastAPI
from app.middleware.cors_config import CORSConfigMiddleware  # noqa: F401 — configurable CORS
from app.api.routes.cors_debug import router as _cors_debug_router
# ...
# Configurable CORS + debug endpoint — added by add_cors_config tool
app.add_middleware(CORSConfigMiddleware)
app.include_router(_cors_debug_router)
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Tool is idempotent on second run** | Fingerprint check `"CORSConfigMiddleware" in cors_config_file.read_text()` returns `status="no_op"` |
| QS-2 | **`dry_run=True` writes zero files** | Early return before any filesystem write |
| QS-3 | **Every generated `.py` file AST-parses** | `ast.parse` loop over `files_created` before success return |
| QS-4 | **No generated function exceeds 50 LOC** | All helper functions kept small; asserted by AST walk in test harness |
| QS-5 | **Origins read from `CORS_ALLOWED_ORIGINS` env var** | `os.getenv("CORS_ALLOWED_ORIGINS", "*")` in `CORSConfigMiddleware.__init__` |
| QS-6 | **Wildcard triggers warning in non-local environments** | `_warn_if_wildcard` checks `environment not in ("local", "test")` |
| QS-7 | **Wraps standard `CORSMiddleware`** | `CORSConfigMiddleware` delegates to `fastapi.middleware.cors.CORSMiddleware` |
| QS-8 | **`CORS_*` fields live inside `class Settings` with 4-space indent** | `_patch_config` ensures 4-space-indented fields inside the class body |
| QS-9 | **`GET /cors/config` endpoint returns active config** | `cors_debug.py` reads env vars and returns JSON dict |
| QS-10 | **`execution_time_ms` set on every return path** | `_elapsed_ms(start)` on success, no_op, dry_run, and error branches |

---

## 6. Completeness Criteria

Every criterion is tied to a real assertion in `test_add_cors_config.py`.

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | Tool returns `status="success"` on a fresh project | `result.status == "success"` | `test_success_status` |
| CC-02 | Second run returns `status="no_op"` with zero file ops | `r2.status == "no_op"` and both lists empty | `test_idempotent` |
| CC-03 | `dry_run=True` writes zero bytes to the filesystem | `before == after` dict over every `.py` in tree | `test_dry_run` |
| CC-04 | Tool creates at least 1 new file | `len(result.files_created) >= 1` and each path exists | `test_files_created_count` |
| CC-05 | Tool modifies at least 1 existing file | `len(result.files_modified) >= 1` and each path exists | `test_files_modified_count` |
| CC-06 | Every generated `.py` AST-parses cleanly | `ast.parse` over all `.py` files in project tree | `test_all_py_parse` |
| CC-07 | No generated function exceeds 50 LOC | AST walk, `max_loc <= 50` | `test_no_function_over_50_loc` |
| CC-08 | `CORS_ALLOWED_ORIGINS`, `CORS_ALLOW_CREDENTIALS`, `CORS_MAX_AGE` in `config.py` with 4-space indent | String scan + indent check | `test_config_fields_patched` |
| CC-09 | `app/middleware/cors_config.py` created with `CORSConfigMiddleware` | File exists + `"CORSConfigMiddleware" in content` | `test_cors_config_middleware_file_created` |
| CC-10 | `CORSConfigMiddleware` reads origins from env var, not hardcoded | `"CORS_ALLOWED_ORIGINS" in content or "getenv" in content` | `test_cors_origins_read_from_env` |
| CC-11 | Wildcard warning present in middleware code | `"warning" in content.lower()` and `"*" in content` | `test_wildcard_warning_present` |
| CC-12 | `app/api/routes/cors_debug.py` created with `GET /cors/config` | File exists + `"router" in content` | `test_debug_route_created` |
| CC-13 | `CORS_MAX_AGE` configurable via env var | `"CORS_MAX_AGE" in content or "max_age" in content` | `test_cors_max_age_configurable` |
| CC-14 | `app/main.py` patched to register `CORSConfigMiddleware` | `"CORSConfigMiddleware" in main.py` | `test_main_py_patched_with_cors_middleware` |
| CC-15 | `execution_time_ms` is a positive integer | `result.execution_time_ms > 0` | `test_execution_time_recorded` |
| CC-16 | `next_steps` non-empty and mention CORS or origins | `len(result.next_steps) > 0` and `"cors" in combined or "origin" in combined` | `test_next_steps_present` |

---

## 7. Definition of Done (DoD)

- [ ] All 16 Completeness Criteria verified by `test_add_cors_config.py`
- [ ] `add_cors_config.py` runs `ast.parse` on every created `.py` file before returning success
- [ ] `add_cors_config.py` detects `"CORSConfigMiddleware"` fingerprint and returns `status="no_op"` on second run
- [ ] `dry_run=True` returns success with empty `files_created`/`files_modified`
- [ ] `CORSConfigMiddleware` reads from `CORS_ALLOWED_ORIGINS` env var — never hardcoded origins
- [ ] `_warn_if_wildcard` fires for `environment not in ("local", "test")`
- [ ] `CORSConfigMiddleware` wraps standard `fastapi.middleware.cors.CORSMiddleware`
- [ ] `CORS_*` fields inserted with 4-space indent inside `class Settings` body
- [ ] `GET /cors/config` returns `allowed_origins`, `allow_credentials`, `max_age`, `wildcard_warning`
- [ ] `execution_time_ms` is set on every return path (success, no_op, dry_run, error)
- [ ] Tool exits within 5 s on a fresh fixture project
- [ ] `MCP_TOOL` descriptor exposes `{name, description, tags, entry}` quartet

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-CORS-01 | Tool is ALWAYS idempotent on second invocation | `"CORSConfigMiddleware" in cors_config_file.read_text()` short-circuits to `status="no_op"` | `test_idempotent`, `test_idempotent_project_still_parses` |
| INV-CORS-02 | `dry_run=True` NEVER writes to disk | Early return before any write | `test_dry_run` |
| INV-CORS-03 | Every generated `.py` file MUST parse as valid Python | `ast.parse` loop before success return | `test_all_py_parse`, `test_idempotent_project_still_parses` |
| INV-CORS-04 | Origins MUST be read from `CORS_ALLOWED_ORIGINS` env var | `os.getenv("CORS_ALLOWED_ORIGINS", "*")` in `CORSConfigMiddleware` | `test_cors_origins_read_from_env` |
| INV-CORS-05 | Wildcard `*` MUST trigger a warning log in non-local environments | `_warn_if_wildcard` checks `environment not in ("local", "test")` | `test_wildcard_warning_present` |
| INV-CORS-06 | `CORS_*` fields MUST be 4-space indented inside `class Settings` | `_patch_config` enforces indent | `test_config_fields_patched` |
| INV-CORS-07 | `ToolResult.execution_time_ms` MUST be positive on every return path | `_elapsed_ms(start)` on all branches | `test_execution_time_recorded` |
| INV-CORS-08 | `next_steps` MUST reference CORS or origins | Hard-coded guidance strings in success branch | `test_next_steps_present` |

---

## 9. User Stories

### 9.1 Core install flow (US-01 .. US-04)

**US-01: Replace hardcoded CORS with env-var config**
- **As a** backend engineer deploying to multiple environments
- **I want** CORS origins to be configurable without code changes
- **So that** I can change the allowed origin list via `.env` and restart
- **Given:** A FastAPI project with hardcoded `allow_origins=["*"]`
- **When:** `add_cors_config(ToolInput(project_dir=...))`
- **Then:** `CORS_ALLOWED_ORIGINS` env var controls origins; wildcard triggers warning

**US-02: Re-run safely on already-configured project**
- **As a** CI pipeline re-running tools every commit
- **I want** the tool to skip work when already applied
- **So that** I do not corrupt existing CORS config
- **Given:** `app/middleware/cors_config.py` already contains `CORSConfigMiddleware`
- **When:** `add_cors_config(...)` invoked a second time
- **Then:** Returns `status="no_op"`, no files written, project still parseable

**US-03: Preview changes without writing files**
- **As a** developer reviewing a tool invocation
- **I want** to see what would change without touching files
- **Given:** Fresh FastAPI fixture project
- **When:** `add_cors_config(ToolInput(project_dir=..., dry_run=True))`
- **Then:** Returns `status="success"` with notes, zero files written

**US-04: Debug CORS configuration at runtime**
- **As a** frontend developer diagnosing CORS issues
- **I want** to call `GET /cors/config` to see what origins are allowed
- **So that** I do not have to read deployment environment files
- **Given:** Project with `add_cors_config` applied
- **When:** `GET /cors/config`
- **Then:** Returns `allowed_origins`, `allow_credentials`, `max_age`, `wildcard_warning`

---

## 10. Edge Cases

| Edge Case | Handling |
|-----------|----------|
| `CORS_ALLOWED_ORIGINS` contains spaces around commas | `_parse_origins` strips whitespace from each token |
| `CORS_ALLOWED_ORIGINS` is empty string | `_parse_origins` returns empty list; Starlette blocks all origins |
| `CORS_MAX_AGE` is not a valid integer | `int(os.getenv(..., "600"))` raises `ValueError` at startup — operator must fix config |
| `app/api/routes/` directory does not exist | `cors_debug.py` skipped; tool still succeeds with just middleware + config |
| `app/main.py` does not contain `from fastapi import FastAPI` | Import injected at top of file as fallback |
| Running from inside Docker where `ENVIRONMENT=production` | Wildcard `*` triggers warning log; app continues running |
| `app/core/config.py` already has `CORS_ALLOWED_ORIGINS` | `_patch_config` detects token and skips, no duplicate insertion |

---

## 11. Dependencies and Prerequisites

| Dependency | Version | Role | Install? |
|------------|---------|------|---------|
| FastAPI | any | `CORSMiddleware` import | Already present |
| Starlette | bundled | `ASGIApp`, `CORSMiddleware` | Already present |

**Prerequisites** (checked by `ensure_prerequisites`):
- `Prereq.CONFIG_SETTINGS` — `app/core/config.py` with `class Settings`
- `Prereq.REQUIREMENTS_TXT` — `requirements.txt` exists

No new packages are added to `requirements.txt`.

---

## 12. File Map

```
project/
├── app/
│   ├── middleware/
│   │   ├── __init__.py              [CREATED] Package marker
│   │   └── cors_config.py           [CREATED] CORSConfigMiddleware
│   ├── api/
│   │   └── routes/
│   │       └── cors_debug.py        [CREATED] GET /cors/config
│   ├── core/
│   │   └── config.py                [MODIFIED] CORS_* fields added
│   └── main.py                      [MODIFIED] Middleware + router registered
```

---

## 13. Rollback

To remove the CORS upgrade:

1. Delete `app/middleware/cors_config.py` and `app/middleware/__init__.py`
2. Delete `app/api/routes/cors_debug.py`
3. Remove `CORS_ALLOWED_ORIGINS`, `CORS_ALLOW_CREDENTIALS`, `CORS_MAX_AGE` from `app/core/config.py`
4. Remove `CORSConfigMiddleware` import and `app.add_middleware(CORSConfigMiddleware)` from `app/main.py`
5. Remove `_cors_debug_router` import and `app.include_router(_cors_debug_router)` from `app/main.py`
6. Re-add original `CORSMiddleware` setup if needed

---

## 14. Security Considerations

| Concern | Mitigation |
|---------|-----------|
| Wildcard `*` in production exposes API to all origins | `_warn_if_wildcard` logs a warning; `next_steps` advises against wildcard |
| `CORS_ALLOW_CREDENTIALS=true` with wildcard | Browsers reject `credentials: true` + wildcard per Fetch spec — safe by spec |
| `GET /cors/config` exposes origin list | Endpoint reveals config only (no secrets); acceptable for debugging |
| Environment value read from `ENVIRONMENT` env var | Consistent with existing settings pattern; no hardcoded environment names except `"local"` and `"test"` |

---

## 15. Observability

| Signal | Where | Content |
|--------|-------|---------|
| `logger.warning` | `_warn_if_wildcard` | `"CORS wildcard '*' is active in environment=%s"` |
| `ToolResult.notes` | Success return | CORS upgrade summary, wildcard warning guidance |
| `ToolResult.next_steps` | Success return | `CORS_ALLOWED_ORIGINS` configuration guidance |
| `ToolResult.execution_time_ms` | All branches | Wall-clock milliseconds |

---

## 16. Test Coverage Map

| Test | CC | Description |
|------|----|-------------|
| `test_success_status` | CC-01 | Returns `status="success"` on fresh project |
| `test_idempotent` | CC-02 | Second run returns `no_op`, no files written |
| `test_dry_run` | CC-03 | `dry_run=True` writes nothing |
| `test_files_created_count` | CC-04 | At least 1 file created, all exist on disk |
| `test_files_modified_count` | CC-05 | At least 1 file modified, exists on disk |
| `test_all_py_parse` | CC-06 | All `.py` files parse cleanly after tool |
| `test_no_function_over_50_loc` | CC-07 | No function > 50 LOC (AST walk) |
| `test_config_fields_patched` | CC-08 | `CORS_*` fields in `config.py` with 4-space indent |
| `test_cors_config_middleware_file_created` | CC-09 | `cors_config.py` created with `CORSConfigMiddleware` |
| `test_cors_origins_read_from_env` | CC-10 | Origins from env var, not hardcoded |
| `test_wildcard_warning_present` | CC-11 | Warning logic for wildcard present |
| `test_debug_route_created` | CC-12 | `cors_debug.py` created with router |
| `test_cors_max_age_configurable` | CC-13 | `max_age` configurable via env |
| `test_main_py_patched_with_cors_middleware` | CC-14 | `main.py` patched with `CORSConfigMiddleware` |
| `test_execution_time_recorded` | CC-15 | `execution_time_ms > 0` |
| `test_next_steps_present` | CC-16 | Non-empty `next_steps` mentioning CORS |
| `test_idempotent_project_still_parses` | INV-CORS-01/03 | After two runs all `.py` still parseable |
| `test_notes_mention_wildcard_or_origins` | INV-CORS-08 | Notes describe wildcard or origins |
| `test_cors_config_file_uses_starlette_cors` | INV-CORS-04 | Wraps `CORSMiddleware` |
| `test_debug_route_returns_active_config` | CC-12 | `/cors/config` returns `allowed_origins` and `allow_credentials` |
| `test_cors_config_parses_comma_separated_origins` | CC-10 | Comma-separated origin parsing present |
