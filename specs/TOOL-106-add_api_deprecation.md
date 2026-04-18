# TOOL-106: add_api_deprecation

> **Status**: SPEC v1 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_api_deprecation` |
| Category | EXTEND > API Design |
| Complexity | High |
| Dependencies | FastAPI, pydantic-settings, Starlette middleware |
| Signature | `add_api_deprecation(inp: ToolInput) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path to FastAPI project root) and `dry_run` flag |
| MCP descriptor | `{"name": "fastapi_add_api_deprecation", "description": "Add API deprecation lifecycle management with RFC 8594 Sunset headers, @deprecated decorator, and usage reporting.", "tags": ["extend", "api_design"], "entry": "add_api_deprecation"}` |
| Files created (typical) | 4 — `app/deprecation/__init__.py`, `app/deprecation/middleware.py`, `app/deprecation/reporter.py`, `app/api/routes/deprecation.py` |
| Files modified (typical) | 3 — `app/routes/__init__.py`, `app/main.py` (adds DeprecationMiddleware), `app/core/config.py` |

---

## 2. Purpose

The `fastapi_add_api_deprecation` tool installs a production-grade API deprecation lifecycle system into a FastAPI project. APIs evolve: endpoints get renamed, response shapes change, authentication mechanisms are replaced. The industry handles this through versioning (`/v1`, `/v2`) and deprecation notices, but most teams implement deprecation ad-hoc — a comment in the code, a Slack message, hoping consumers notice. This tool formalises the lifecycle.

The system has four moving parts. First, a `DeprecationRegistry` (module-level singleton `registry`) that stores `DeprecationEntry` objects keyed by `(path, method)`. Each entry carries `path`, `method`, `sunset_date` (`date`), `replacement` (string URL or path), a `days_until_sunset` computed property (`(sunset_date - date.today()).days`), a `should_warn` property (True when `days_until_sunset <= settings.DEPRECATION_WARN_DAYS_BEFORE_SUNSET`), and a `to_dict()` method. The registry exposes `register(path, method, sunset_date, replacement)`, `get(path, method) -> DeprecationEntry | None`, and `list_all() -> list[DeprecationEntry]`.

Second, a `@deprecated(sunset, replacement)` decorator that registers the endpoint with the global registry and logs a warning at decoration time. Third, `DeprecationMiddleware` (Starlette `BaseHTTPMiddleware`) that on every request checks the registry for a matching entry and — when found — injects three RFC-compliant response headers: `Sunset: <HTTP-date>` (RFC 8594), `Deprecation: true`, and `Link: <replacement>; rel="successor-version"`. Fourth, `DeprecationReporter` (singleton `reporter`) that `record(path, method)` on every call to a deprecated endpoint (call counting), `get_count(path, method) -> int`, and `usage_report() -> list[dict]` returning usage stats for all registered deprecated endpoints. A `GET /deprecations` route lists all deprecated endpoints combined with usage stats for operator dashboards.

The tool patches `app/core/config.py` with `DEPRECATION_WARN_DAYS_BEFORE_SUNSET: int = 30` inside `class Settings`, adds `DeprecationMiddleware` to `app/main.py`, and registers the deprecation router in `app/routes/__init__.py`. It is idempotent: `DeprecationRegistry` in `app/deprecation/__init__.py` is the fingerprint.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | CI budget; measured via `execution_time_ms` |
| Files created | ≥ 4 | Registry, middleware, reporter, route |
| Files modified | ≥ 1 | Config patch at minimum |
| Max function LOC in generated code | ≤ 50 | Auditable; AST-checked |
| Middleware header injection overhead | < 1 ms | Dict lookup + 3 header assignments |
| `GET /deprecations` latency | < 20 ms | In-memory registry + usage report |
| `@deprecated` decoration time | < 1 ms | One `registry.register()` call |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
project/
├── app/
│   ├── main.py              # FastAPI app, no deprecation middleware
│   ├── core/
│   │   └── config.py        # Settings, no DEPRECATION_* fields
│   └── api/routes/
│       └── users.py         # No @deprecated decorator
└── app/routes/__init__.py   # No deprecation router
```

Deprecated endpoints are documented only in Confluence. Consumers discover breakage after the sunset date, not before.

### 4.2 Registry and decorator: AFTER

```python
# app/deprecation/__init__.py
"""API deprecation registry, entry model, and @deprecated decorator."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from functools import wraps
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class DeprecationEntry:
    """A registered deprecated API endpoint."""

    path: str
    method: str
    sunset_date: date
    replacement: str

    @property
    def days_until_sunset(self) -> int:
        """Number of days remaining until the sunset date."""
        return (self.sunset_date - date.today()).days

    @property
    def should_warn(self) -> bool:
        """True when within the configured warning window."""
        from app.core.config import settings
        return self.days_until_sunset <= settings.DEPRECATION_WARN_DAYS_BEFORE_SUNSET

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-safe dict."""
        return {
            "path": self.path,
            "method": self.method,
            "sunset_date": self.sunset_date.isoformat(),
            "replacement": self.replacement,
            "days_until_sunset": self.days_until_sunset,
        }


class DeprecationRegistry:
    """In-memory store of deprecated API endpoints."""

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], DeprecationEntry] = {}

    def register(
        self,
        path: str,
        method: str,
        sunset_date: date,
        replacement: str,
    ) -> DeprecationEntry:
        """Register an endpoint as deprecated."""
        entry = DeprecationEntry(
            path=path,
            method=method.upper(),
            sunset_date=sunset_date,
            replacement=replacement,
        )
        self._entries[(path, method.upper())] = entry
        logger.warning("Endpoint deprecated: %s %s → %s", method, path, replacement)
        return entry

    def get(self, path: str, method: str) -> DeprecationEntry | None:
        """Look up a deprecated entry or return None."""
        return self._entries.get((path, method.upper()))

    def list_all(self) -> list[DeprecationEntry]:
        """Return all registered deprecated entries."""
        return list(self._entries.values())


registry = DeprecationRegistry()


def deprecated(
    sunset: date,
    replacement: str,
    method: str = "GET",
) -> Callable:
    """Decorator to mark an API endpoint as deprecated.

    Args:
        sunset: Date on which the endpoint will be removed.
        replacement: Path or URL of the successor endpoint.
        method: HTTP method (default: GET).
    """
    def decorator(func: Callable) -> Callable:
        registry.register(func.__name__, method, sunset, replacement)

        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            return await func(*args, **kwargs)

        return wrapper
    return decorator
```

### 4.3 Middleware (RFC 8594 headers): AFTER

```python
# app/deprecation/middleware.py
"""DeprecationMiddleware — injects RFC 8594 Sunset headers."""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.deprecation import registry


class DeprecationMiddleware(BaseHTTPMiddleware):
    """Add Sunset, Deprecation, and Link headers for deprecated endpoints."""

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        response = await call_next(request)
        path = request.url.path
        method = request.method
        entry = registry.get(path, method)
        if entry is not None:
            response.headers["Deprecation"] = "true"
            response.headers["Sunset"] = entry.sunset_date.strftime(
                "%a, %d %b %Y 00:00:00 GMT"
            )
            response.headers["Link"] = (
                f'<{entry.replacement}>; rel="successor-version"'
            )
        return response
```

### 4.4 Reporter: AFTER

```python
# app/deprecation/reporter.py
"""DeprecationReporter — tracks usage of deprecated endpoints."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.deprecation import registry


class DeprecationReporter:
    """Count and report calls to deprecated endpoints."""

    def __init__(self) -> None:
        self._counts: dict[tuple[str, str], int] = defaultdict(int)

    def record(self, path: str, method: str) -> None:
        """Increment the call count for a deprecated endpoint."""
        self._counts[(path, method.upper())] += 1

    def get_count(self, path: str, method: str) -> int:
        """Return the call count for a specific deprecated endpoint."""
        return self._counts.get((path, method.upper()), 0)

    def usage_report(self) -> list[dict[str, Any]]:
        """Return usage stats for all registered deprecated endpoints."""
        return [
            {**entry.to_dict(), "call_count": self.get_count(entry.path, entry.method)}
            for entry in registry.list_all()
        ]

    def reset(self) -> None:
        """Reset all call counts (useful in tests)."""
        self._counts.clear()


reporter = DeprecationReporter()
```

### 4.5 Listing route: AFTER

```python
# app/api/routes/deprecation.py
"""GET /deprecations — list all deprecated endpoints with usage stats."""
from __future__ import annotations

from fastapi import APIRouter

from app.deprecation.reporter import reporter

router = APIRouter(prefix="", tags=["deprecation"])


@router.get("/deprecations")
async def list_deprecations() -> dict:
    """List all registered deprecated endpoints and their usage."""
    return {"data": reporter.usage_report(), "count": len(reporter.usage_report())}
```

### 4.6 Config patch (inside `class Settings`)

```python
# app/core/config.py  (diff, added by _patch_config)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    # --- deprecation settings — added by add_api_deprecation tool ---
    DEPRECATION_WARN_DAYS_BEFORE_SUNSET: int = 30
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Tool is idempotent on second run** | `"DeprecationRegistry" in app/deprecation/__init__.py` → `status="no_op"` |
| QS-2 | **`dry_run=True` writes zero files** | Early return before any filesystem write |
| QS-3 | **Every generated `.py` file AST-parses** | `ast.parse` on each created `.py` before returning |
| QS-4 | **No generated function exceeds 50 LOC** | All methods and helpers kept short |
| QS-5 | **Middleware adds all three RFC headers** | `Sunset`, `Deprecation`, `Link` with `successor-version` |
| QS-6 | **`@deprecated` decorator has `sunset` and `replacement` params** | Both parameters present in `deprecated()` signature |
| QS-7 | **Module-level `registry` singleton exported** | `registry = DeprecationRegistry()` at module level |
| QS-8 | **`days_until_sunset` is a computed property** | `@property` on `DeprecationEntry` |
| QS-9 | **`DEPRECATION_WARN_DAYS_BEFORE_SUNSET` inside `class Settings`** | `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES` |
| QS-10 | **No hardcoded secrets in generated templates** | No `password=`, `secret=`, `api_key=` literals |
| QS-11 | **`execution_time_ms` is positive** | `_elapsed_ms(start)` on every return path |
| QS-12 | **`GET /deprecations` route lists all deprecated endpoints** | Route present in `app/api/routes/deprecation.py` |
| QS-13 | **`MCP_TOOL` descriptor is complete** | `entry == "add_api_deprecation"` |

---

## 6. Completeness Criteria

Every criterion is tied to a real assertion in `adapt/extend/api_design/test_add_api_deprecation.py`.

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | Tool returns `status="success"` on a fresh project | `result.status == "success"` | `test_success_status` |
| CC-02 | Second run returns `status="no_op"` with zero file ops | `r2.status == "no_op"` and both lists empty | `test_idempotent` |
| CC-03 | `dry_run=True` writes zero bytes to filesystem | `before == after` dict over every `.py` | `test_dry_run` |
| CC-04 | Tool creates at least 4 new files | `len(result.files_created) >= 4` and each exists | `test_files_created_count` |
| CC-05 | Tool modifies at least 1 existing file | `len(result.files_modified) >= 1` and each exists | `test_files_modified_count` |
| CC-06 | Every generated `.py` AST-parses cleanly | `ast.parse` over all `.py` files | `test_all_py_parse` |
| CC-07 | No generated function exceeds 50 LOC in `app/` | AST walk, `max_loc <= 50` | `test_no_function_over_50_loc` |
| CC-08 | `DEPRECATION_WARN_DAYS_BEFORE_SUNSET` exists inside `class Settings` body with 4-space indent | String scan + indent check | `test_config_fields_patched` |
| CC-10 | Deprecation router registered in `app/routes/__init__.py` | `"deprecation" in content.lower()` | `test_routes_registered` |
| CC-11 | `app/deprecation/__init__.py` contains `DeprecationRegistry` and `DeprecationEntry` | Both names in file | `test_deprecation_registry_created` |
| CC-12 | `@deprecated` decorator exported with `sunset` and `replacement` params | `"def deprecated("`, `"sunset"`, `"replacement"` | `test_deprecated_decorator_created` |
| CC-13 | `app/deprecation/middleware.py` contains `DeprecationMiddleware` and `Sunset` header | File exists + both tokens | `test_deprecation_middleware_created` |
| CC-14 | Middleware adds `"Sunset"`, `"Deprecation"`, and `"successor-version"` | All three tokens in middleware source | `test_rfc_8594_sunset_header` |
| CC-15 | `app/deprecation/reporter.py` contains `DeprecationReporter` with `record` and `usage_report` | File exists + three tokens | `test_deprecation_reporter_created` |
| CC-16 | `app/api/routes/deprecation.py` contains `/deprecations` route | `"/deprecations"` in route file | `test_deprecations_listing_route_created` |
| CC-17 | `registry = DeprecationRegistry()` singleton exported from `app/deprecation/__init__.py` | Exact string present | `test_singleton_registry_exported` |
| CC-18 | `DeprecationEntry` has `days_until_sunset` property | `"days_until_sunset"` in registry module | `test_days_until_sunset_property` |
| CC-19 | No hardcoded secrets in generated files | Scans for `password="`, `secret="`, `api_key="` | `test_no_hardcoded_secrets` |
| CC-N-1 | `execution_time_ms` is a positive integer | `result.execution_time_ms > 0` | `test_execution_time_recorded` |
| CC-N | `next_steps` mentions `@deprecated` | Lowercased join contains `"deprecated"` | `test_next_steps_present` |
| CC-LAST | Running the tool twice leaves the project AST-parseable | `ast.parse` over all `.py` after two runs | `test_idempotent_project_still_parses` |
| INV-10 | `MCP_TOOL["entry"]` matches the actual function name | `MCP_TOOL["entry"] == "add_api_deprecation"` | `test_mcp_tool_entry_matches_function` |

---

## 7. Definition of Done (DoD)

- [ ] All 22 Completeness Criteria verified by `test_add_api_deprecation.py`
- [ ] `add_api_deprecation.py` runs `ast.parse` on every created `.py` before returning success
- [ ] Fingerprint `"DeprecationRegistry" in app/deprecation/__init__.py` triggers `status="no_op"`
- [ ] `dry_run=True` returns success with empty `files_created`/`files_modified`
- [ ] `DeprecationMiddleware` injects `Sunset` (RFC 8594), `Deprecation`, and `Link` headers
- [ ] `@deprecated(sunset, replacement)` registers with global `registry`
- [ ] `registry = DeprecationRegistry()` at module level in `__init__.py`
- [ ] `reporter = DeprecationReporter()` at module level in `reporter.py`
- [ ] `DeprecationEntry.days_until_sunset` is a `@property`
- [ ] `GET /deprecations` returns combined registry + usage stats
- [ ] `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30`
- [ ] `execution_time_ms` set on every return path
- [ ] `MCP_TOOL` descriptor exposes `{name, description, tags, entry}` quartet

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-DEP-01 | Tool is ALWAYS idempotent on second invocation | `"DeprecationRegistry" in __init__.py` → `status="no_op"` | `test_idempotent`, `test_idempotent_project_still_parses` |
| INV-DEP-02 | `dry_run=True` NEVER writes to disk | Early return before write | `test_dry_run` |
| INV-DEP-03 | Every generated `.py` MUST parse as valid Python | `ast.parse` loop | `test_all_py_parse`, `test_idempotent_project_still_parses` |
| INV-DEP-04 | Middleware MUST add `"Sunset"`, `"Deprecation"`, `"successor-version"` | All three tokens in `middleware.py` | `test_rfc_8594_sunset_header` |
| INV-DEP-05 | `@deprecated` MUST have `sunset` and `replacement` params | Both in decorator signature | `test_deprecated_decorator_created` |
| INV-DEP-06 | `registry` singleton MUST be module-level | `"registry = DeprecationRegistry()"` in `__init__.py` | `test_singleton_registry_exported` |
| INV-DEP-07 | `days_until_sunset` MUST be a computed property | `@property` decorator on `DeprecationEntry` | `test_days_until_sunset_property` |
| INV-DEP-08 | `DEPRECATION_WARN_DAYS_BEFORE_SUNSET` MUST land inside `class Settings` | `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES` | `test_config_fields_patched` |
| INV-DEP-09 | No hardcoded credentials | Scan for `password="`, `secret="`, `api_key="` | `test_no_hardcoded_secrets` |
| INV-DEP-10 | `ToolResult.execution_time_ms` MUST be positive | `_elapsed_ms(start)` on all branches | `test_execution_time_recorded` |

---

## 9. User Stories

### 9.1 Core install flow (US-01 .. US-05)

**US-01: Install deprecation system into a clean FastAPI project**
- **As a** platform engineer managing API lifecycle
- **I want** one tool call to scaffold the full deprecation kit
- **So that** API consumers receive standard RFC headers automatically
- **Given:** A FastAPI project with `app/core/config.py` and `app/main.py`
- **When:** `add_api_deprecation(ToolInput(project_dir=...))`
- **Then:**
  - Returns `ToolResult.status == "success"` (CC-01)
  - ≥ 4 files created (CC-04)
  - Verified by `test_success_status`, `test_files_created_count`

**US-02: Re-run the tool safely**
- **As a** CI job
- **I want** `status="no_op"` on second run
- **Given:** `DeprecationRegistry` already in `app/deprecation/__init__.py`
- **When:** Tool invoked again
- **Then:** `r2.status == "no_op"`, no file ops — verified by `test_idempotent`

**US-03: Dry-run preview**
- **As a** developer
- **I want** `dry_run=True` to leave filesystem unchanged
- **Given:** Fresh project
- **When:** `add_api_deprecation(ToolInput(project_dir=..., dry_run=True))`
- **Then:** Zero filesystem changes — verified by `test_dry_run`

**US-04: Consumers see RFC headers on deprecated calls**
- **As a** API consumer
- **I want** to receive `Sunset`, `Deprecation`, and `Link` headers
- **Given:** `DeprecationMiddleware` registered in `app/main.py`
- **When:** Client calls a deprecated endpoint
- **Then:** All three RFC headers present in response (INV-DEP-04)

**US-05: Config field overridable via env var**
- **As a** platform engineer
- **I want** `DEPRECATION_WARN_DAYS_BEFORE_SUNSET` in `Settings`
- **Given:** `ACCESS_TOKEN_EXPIRE_MINUTES` present in config
- **When:** Tool runs
- **Then:** Field inside class body — verified by `test_config_fields_patched`

### 9.2 Deprecation lifecycle (US-06 .. US-10)

**US-06: Mark an endpoint as deprecated**
- **As a** developer removing an old endpoint
- **I want** `@deprecated(sunset=date(2026, 12, 31), replacement="/v2/users")`
- **Given:** `@deprecated` decorator available from `app.deprecation`
- **When:** Decorator applied to a route handler
- **Then:** Entry registered in `registry` — verified by CC-12

**US-07: Count calls to deprecated endpoints**
- **As an** ops engineer
- **I want** to know how many clients still call deprecated endpoints
- **Given:** `DeprecationReporter` with `record()` and `usage_report()`
- **When:** `GET /deprecations`
- **Then:** Response includes `call_count` per entry — verified by CC-15, CC-16

**US-08: Know days remaining until sunset**
- **As a** consumer of a deprecated endpoint
- **I want** `days_until_sunset` in the deprecation listing
- **Given:** `DeprecationEntry.days_until_sunset` property
- **When:** `GET /deprecations`
- **Then:** `days_until_sunset` in each entry's dict — verified by CC-18

**US-09: Reset reporter state in tests**
- **As a** test author
- **I want** `reporter.reset()` to clear all call counts
- **Given:** `DeprecationReporter` with `reset()` method
- **When:** Called between test cases
- **Then:** All counts reset to 0

**US-10: No next-step guidance forgotten**
- **As a** developer reading post-install instructions
- **I want** `next_steps` to mention `@deprecated`
- **Given:** Successful install
- **When:** `result.next_steps`
- **Then:** `"deprecated"` in lowercased join — verified by CC-N

### 9.3 Integration (US-11 .. US-13)

**US-11: Routes init updated**
- **As a** FastAPI developer
- **I want** the deprecation router registered in `routes/__init__.py`
- **Given:** Router generated
- **When:** Tool runs
- **Then:** `"deprecation"` in `routes/__init__.py` — verified by CC-10

**US-12: Project parseable after two runs**
- **As a** CI system
- **I want** two consecutive runs to leave project intact
- **Given:** Tool applied twice
- **When:** `ast.parse` over all `.py`
- **Then:** Zero errors — verified by CC-LAST

**US-13: No secrets in generated code**
- **As a** security auditor
- **I want** no credentials in generated files
- **Given:** Deprecation system installed
- **When:** Scan for credential patterns
- **Then:** Zero occurrences — verified by CC-19

---

## 10. Error Handling

| Scenario | Behaviour | Status |
|----------|-----------|--------|
| `project_dir` does not exist | Returns `status="error"`, `error` field set | `"error"` |
| `app/core/config.py` absent | `ensure_prerequisites` raises; `status="error"` | `"error"` |
| `app/main.py` absent | Middleware patch skipped with warning | Partial |
| `app/routes/__init__.py` absent | Router patch skipped with warning | Partial |

---

## 11. Dependencies

| Package | Why needed |
|---------|------------|
| `starlette.middleware.base` | `BaseHTTPMiddleware` for `DeprecationMiddleware` |
| `functools.wraps` (stdlib) | `@deprecated` wrapper preserves function metadata |
| `collections.defaultdict` (stdlib) | Usage count storage in `DeprecationReporter` |
| `datetime.date` (stdlib) | `sunset_date`, `days_until_sunset` |
| `pydantic-settings` | `Settings` in target project |

No new packages added to `requirements.txt`.

---

## 12. Security Considerations

| Concern | Mitigation |
|---------|-----------|
| `GET /deprecations` exposes internal endpoint map | Consider adding auth dependency if endpoint map is sensitive |
| Sunset date in response headers | Header is public by design (RFC 8594); no sensitive data |
| No hardcoded credentials | Verified by CC-19 |

---

## 13. Observability

| Signal | Where |
|--------|-------|
| `execution_time_ms` | `ToolResult.execution_time_ms` |
| Deprecated endpoint hit | `Deprecation: true` header + `reporter.record()` |
| Usage counts | `GET /deprecations` response |
| Days until sunset | `DeprecationEntry.days_until_sunset` |

---

## 14. Configuration Reference

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `DEPRECATION_WARN_DAYS_BEFORE_SUNSET` | `int` | `30` | Days before sunset when `should_warn` becomes True |

---

## 15. Migration / Rollback

**Rollback is mechanical:**
- Delete `app/deprecation/` (3 files)
- Delete `app/api/routes/deprecation.py`
- Remove `DeprecationMiddleware` from `app/main.py`
- Remove deprecation import from `app/routes/__init__.py`
- Remove `DEPRECATION_WARN_DAYS_BEFORE_SUNSET` from `app/core/config.py`

No database migrations. No external services.

---

## 16. Test File Reference

**Location:** `adapt/extend/api_design/test_add_api_deprecation.py`

**Test runner:**
```bash
PYTHONPATH=. pytest adapt/extend/api_design/test_add_api_deprecation.py -v
# or standalone:
PYTHONPATH=. python3 adapt/extend/api_design/test_add_api_deprecation.py
```

**Full test inventory:**

| Test function | CC ID | What it asserts |
|---------------|-------|-----------------|
| `test_success_status` | CC-01 | `result.status == "success"` on fresh project |
| `test_idempotent` | CC-02 | Second run → `status="no_op"`, no file ops |
| `test_dry_run` | CC-03 | `dry_run=True` → zero filesystem changes |
| `test_files_created_count` | CC-04 | `len(files_created) >= 4`, all paths exist |
| `test_files_modified_count` | CC-05 | `len(files_modified) >= 1`, all paths exist |
| `test_all_py_parse` | CC-06 | All generated `.py` pass `ast.parse` |
| `test_no_function_over_50_loc` | CC-07 | No function in `app/` exceeds 50 LOC |
| `test_config_fields_patched` | CC-08 | `DEPRECATION_WARN_DAYS_BEFORE_SUNSET` inside class body |
| `test_routes_registered` | CC-10 | `"deprecation"` in `routes/__init__.py` |
| `test_deprecation_registry_created` | CC-11 | `DeprecationRegistry` + `DeprecationEntry` in `__init__.py` |
| `test_deprecated_decorator_created` | CC-12 | `def deprecated(`, `sunset`, `replacement` present |
| `test_deprecation_middleware_created` | CC-13 | `DeprecationMiddleware` + `Sunset` in middleware |
| `test_rfc_8594_sunset_header` | CC-14 | `"Sunset"`, `"Deprecation"`, `"successor-version"` in middleware |
| `test_deprecation_reporter_created` | CC-15 | `DeprecationReporter`, `record`, `usage_report` in reporter |
| `test_deprecations_listing_route_created` | CC-16 | `/deprecations` in route file |
| `test_singleton_registry_exported` | CC-17 | `"registry = DeprecationRegistry()"` in `__init__.py` |
| `test_days_until_sunset_property` | CC-18 | `"days_until_sunset"` in registry module |
| `test_no_hardcoded_secrets` | CC-19 | No credential literals in generated files |
| `test_execution_time_recorded` | CC-N-1 | `execution_time_ms > 0` |
| `test_next_steps_present` | CC-N | `next_steps` contains `"deprecated"` |
| `test_idempotent_project_still_parses` | CC-LAST | Two runs → all `.py` still parse |
| `test_mcp_tool_entry_matches_function` | INV-10 | `MCP_TOOL["entry"] == "add_api_deprecation"` |
