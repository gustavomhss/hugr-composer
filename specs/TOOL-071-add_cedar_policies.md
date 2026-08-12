---
spec_id: "TOOL-071"
tool_name: "add_cedar_policies"
version: "1.0.0"
status: "ratified"
invariants:
  - "INV-CEDAR-01"
  - "INV-CEDAR-02"
  - "INV-CEDAR-03"
  - "INV-CEDAR-04"
  - "INV-CEDAR-05"
  - "INV-CEDAR-06"
  - "INV-CEDAR-07"
  - "INV-CEDAR-08"
  - "INV-CEDAR-09"
  - "INV-CEDAR-10"
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
quality_standards:
  - "QS-01"
  - "QS-02"
  - "QS-03"
  - "QS-04"
  - "QS-05"
  - "QS-06"
  - "QS-07"
  - "QS-08"
  - "QS-09"
  - "QS-10"
  - "QS-11"
  - "QS-12"
  - "QS-13"
  - "QS-14"
  - "QS-15"
  - "QS-16"
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
  - "T-26"
  - "T-27"
  - "T-28"
  - "T-29"
  - "T-30"
  - "T-31"
tags:
  - "performance"
  - "data"
  - "resiliency"
  - "realtime"
  - "compliance"
---
# TOOL-071: add_cedar_policies

> **Status**: SPEC v1 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_cedar_policies` |
| Category | EXTEND > Auth & Access |
| Complexity | High |
| Dependencies | FastAPI, Starlette, Pydantic v2, cedarpy>=0.4.0 |
| Signature | `add_cedar_policies(inp: ToolInput) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path to FastAPI project root) and `dry_run` flag |
| MCP descriptor | `{"name": "fastapi_add_cedar_policies", "description": "Add AWS Cedar policy-as-code ABAC authorization to a FastAPI project. Generates CedarEngine, middleware, example .cedar policies, and /authz endpoints.", "tags": ["extend", "auth_access"], "entry": "add_cedar_policies"}` |
| Files created (typical) | 7+ — `app/authz/__init__.py`, `app/authz/engine.py`, `app/authz/models.py`, `app/authz/middleware.py`, `app/authz/policies/admin_full_access.cedar`, `app/authz/policies/owner_read_write.cedar`, `app/authz/policies/default_deny.cedar`, `app/api/routes/authz.py` |
| Files modified (typical) | 3 — `app/core/config.py`, `app/routes/__init__.py`, `requirements.txt` |

---

## 2. Purpose

The `fastapi_add_cedar_policies` tool installs a production-grade **Cedar policy-as-code ABAC authorization** layer into a FastAPI project using **cedarpy** — the Python binding for AWS Cedar, the same policy language powering Amazon Verified Permissions. Most FastAPI applications start with role-based access control (RBAC), then discover that RBAC cannot express "only the resource owner may write this record" without embedding ownership logic in every route handler or middleware. The alternative — custom Python `if` trees scattered across hundreds of route handlers — is unauditable, unrefactorable, and invisible to compliance tools. Cedar solves this by giving the team a single, human-readable policy file that an external auditor can reason about without reading Python source code. The Cedar policy language enforces deny-by-default: no `forbid` rule is needed to block a request; it is blocked unless a `permit` rule explicitly allows it.

This tool generates the entire Cedar authorization kit a real service needs so developers do not assemble it by hand. It emits: (a) `app/authz/engine.py` containing `CedarEngine`, a file-based policy loader that reads every `*.cedar` file from a configurable directory and evaluates authorization requests via `cedarpy.is_authorized`; the engine is wrapped by a `get_cedar_engine()` singleton that initialises lazily on first call and respects `CEDAR_ENABLED` so the application starts cleanly even before the sidecar or cedarpy is installed; (b) `app/authz/models.py` with two Pydantic v2 models — `AuthzRequest` (principal, action, resource, context) and `AuthzResponse` (allowed, principal, action, resource, reason) — that serve as the public wire contract for the management API; (c) `app/authz/middleware.py` containing `CedarAuthzMiddleware`, a Starlette `BaseHTTPMiddleware` that calls `get_cedar_engine().is_authorized()` on every request, returns HTTP 403 with a JSON body on denial, and respects a configurable `skip_paths` frozenset defaulting to health-check and documentation endpoints; (d) three example Cedar policy files (`admin_full_access.cedar`, `owner_read_write.cedar`, `default_deny.cedar`) that demonstrate the permit/forbid vocabulary and give teams a concrete starting point; (e) `app/api/routes/authz.py` with `POST /authz/check` (evaluate a policy decision on-demand) and `GET /authz/policies` (list the names of loaded `.cedar` files) behind the `/authz` prefix.

Key design decisions: `cedarpy` is **imported lazily inside method bodies** (`is_authorized`, `health`) so the application boots without it installed — teams can install Cedar incrementally without a hard deployment gate; `CEDAR_ENABLED=false` (the default) is a complete no-op bypass so the middleware adds zero overhead before activation; Cedar is explicitly designed to run **after RBAC**: if both are installed the RBAC middleware executes first (rejecting role violations) and Cedar then provides the ABAC layer (evaluating attribute-based policies). The tool is idempotent by fingerprint detection (`"class CedarEngine" in app/authz/engine.py`) and returns `status="no_op"` on second invocation without touching any file.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | Must complete within CI step budget; measured via `execution_time_ms` in `ToolResult` (T-24) |
| Files created | >= 6 | Minimum: authz `__init__`, engine, models, middleware, 3 policy files, routes (T-26) |
| Files modified | >= 3 | config, routes_init, requirements (T-27) |
| Max function LOC in generated code | <= 50 | Each generated function stays auditable; asserted by AST walk in test harness (T-28) |
| `is_authorized()` latency | < 1 ms | Pure Python policy evaluation — no network round-trip required by cedarpy |
| `CedarEngine.load_policies()` startup | < 100 ms | Reads O(10) small `.cedar` files at startup; cached in `_policies` string |
| `POST /authz/check` latency | < 5 ms | Single in-process Cedar evaluation with no external I/O |
| `GET /authz/policies` latency | < 5 ms | Directory glob over a single `app/authz/policies/` directory |
| Middleware overhead per request | < 2 ms | One `is_authorized` call; bypasses skip_paths without evaluation |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
project/
├── app/
│   ├── main.py              # FastAPI app, no Cedar middleware
│   ├── core/
│   │   └── config.py        # Settings class, no CEDAR_* fields
│   ├── routes/
│   │   └── __init__.py      # api_router, no authz router
│   └── api/
│       └── routes/          # Domain routes, no /authz routes
├── requirements.txt         # no cedarpy
```

Authorization logic is scattered: ownership checks live inside route handlers, role checks are duplicated across three modules, and there is no audit trail showing which policy allowed or denied a request.

### 4.2 CedarEngine (lazy cedarpy, singleton): AFTER

```python
# app/authz/engine.py
"""CedarEngine: load Cedar policies from .cedar files and evaluate requests.

cedarpy is imported lazily so the application boots without the package
installed.  Install with ``pip install cedarpy>=0.4.0`` to activate
policy enforcement.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_engine_singleton: "CedarEngine | None" = None


class CedarEngine:
    """File-based Cedar policy engine."""

    def __init__(self, policy_dir: str | Path) -> None:
        self._policy_dir = Path(policy_dir)
        self._policies: str = ""
        self._loaded: bool = False

    def load_policies(self, directory: str | Path | None = None) -> None:
        """Load all .cedar files from directory."""
        target = Path(directory) if directory else self._policy_dir
        if not target.is_dir():
            logger.warning("Cedar policy dir not found: %s", target)
            return
        parts: list[str] = []
        for policy_file in sorted(target.glob("*.cedar")):
            text = policy_file.read_text(encoding="utf-8")
            parts.append(text)
        self._policies = "\n".join(parts)
        self._loaded = bool(parts)

    def is_authorized(
        self,
        principal: str,
        action: str,
        resource: str,
        context: dict | None = None,
    ) -> bool:
        """Evaluate a Cedar authorization decision."""
        from app.core.config import settings  # noqa: PLC0415

        if not getattr(settings, "CEDAR_ENABLED", False):
            return True
        if not self._loaded:
            effect = getattr(settings, "CEDAR_DEFAULT_EFFECT", "deny")
            return effect == "allow"
        try:
            import cedarpy  # noqa: PLC0415

            req = cedarpy.AuthorizationRequest(
                principal=principal,
                action=action,
                resource=resource,
                context=context or {},
            )
            decision = cedarpy.is_authorized(self._policies, req)
            return decision.allowed
        except Exception as exc:
            logger.error("Cedar evaluation error: %s", exc)
            return False


def get_cedar_engine() -> "CedarEngine":
    """Return the process-wide CedarEngine singleton."""
    global _engine_singleton
    if _engine_singleton is None:
        from app.core.config import settings  # noqa: PLC0415

        policy_dir = getattr(settings, "CEDAR_POLICY_DIR", "app/authz/policies")
        _engine_singleton = CedarEngine(policy_dir=policy_dir)
        _engine_singleton.load_policies()
    return _engine_singleton
```

### 4.3 Pydantic models (AuthzRequest / AuthzResponse): AFTER

```python
# app/authz/models.py
"""Pydantic models for Cedar authorization requests and responses."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AuthzRequest(BaseModel):
    """Payload for a Cedar authorization check."""

    principal: str = Field(..., examples=['User::"alice"'])
    action: str = Field(..., examples=['Action::"read"'])
    resource: str = Field(..., examples=['Resource::"report-42"'])
    context: dict = Field(default_factory=dict)


class AuthzResponse(BaseModel):
    """Response from a Cedar authorization check."""

    allowed: bool
    principal: str
    action: str
    resource: str
    reason: str
```

### 4.4 CedarAuthzMiddleware (skip_paths, 403 on deny): AFTER

```python
# app/authz/middleware.py
"""CedarAuthzMiddleware: intercept every request and enforce Cedar policies."""

from __future__ import annotations

import json
import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

_DEFAULT_SKIP: frozenset[str] = frozenset({
    "/healthz", "/readyz", "/metrics",
    "/docs", "/redoc", "/openapi.json", "/api/v1/openapi.json",
})


class CedarAuthzMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that enforces Cedar policies on every request."""

    def __init__(self, app, skip_paths: frozenset[str] | None = None) -> None:
        super().__init__(app)
        self.skip_paths = skip_paths if skip_paths is not None else _DEFAULT_SKIP

    async def dispatch(self, request: Request, call_next) -> Response:
        from app.core.config import settings  # noqa: PLC0415

        if not getattr(settings, "CEDAR_ENABLED", False):
            return await call_next(request)
        if request.url.path in self.skip_paths:
            return await call_next(request)

        principal = self._extract_principal(request)
        action = f'Action::"{request.method.lower()}"'
        resource = f'Resource::"{request.url.path}"'

        from app.authz.engine import get_cedar_engine  # noqa: PLC0415

        allowed = get_cedar_engine().is_authorized(principal, action, resource)
        if not allowed:
            body = json.dumps({"detail": "Forbidden by Cedar policy"})
            return Response(content=body, status_code=403, media_type="application/json")
        return await call_next(request)

    @staticmethod
    def _extract_principal(request: Request) -> str:
        """Extract a Cedar principal string from the request."""
        user = getattr(request.state, "user", None)
        if user and hasattr(user, "id"):
            return f'User::"{user.id}"'
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            return 'User::"jwt-user"'
        return 'User::"anonymous"'
```

### 4.5 Example Cedar policy files: AFTER

```cedar
# admin_full_access.cedar
permit(
    principal in Role::"admin",
    action,
    resource
);
```

```cedar
# owner_read_write.cedar
permit(
    principal,
    action in [Action::"get", Action::"post", Action::"put", Action::"patch", Action::"delete"],
    resource
) when {
    resource.owner == principal
};
```

```cedar
# default_deny.cedar
forbid(
    principal,
    action,
    resource
) unless {
    principal in Role::"admin"
};
```

### 4.6 Management API endpoints (/authz/check, /authz/policies): AFTER

```python
# app/api/routes/authz.py
"""Cedar authz API endpoints."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, status

from app.authz.engine import get_cedar_engine
from app.authz.models import AuthzRequest, AuthzResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/authz", tags=["authz"])


@router.post("/check", response_model=AuthzResponse, status_code=status.HTTP_200_OK)
def check_authorization(payload: AuthzRequest) -> AuthzResponse:
    """Evaluate a Cedar authorization decision for the given request."""
    engine = get_cedar_engine()
    allowed = engine.is_authorized(
        principal=payload.principal,
        action=payload.action,
        resource=payload.resource,
        context=payload.context,
    )
    reason = "permit" if allowed else "forbid (no matching permit policy)"
    return AuthzResponse(
        allowed=allowed,
        principal=payload.principal,
        action=payload.action,
        resource=payload.resource,
        reason=reason,
    )


@router.get("/policies", response_model=list[str], status_code=status.HTTP_200_OK)
def list_policies() -> list[str]:
    """Return the names of all .cedar policy files currently loaded."""
    engine = get_cedar_engine()
    if not engine._policy_dir.is_dir():
        return []
    return sorted(p.stem for p in engine._policy_dir.glob("*.cedar"))
```

### 4.7 Config patch (fields inside `class Settings`)

```python
# app/core/config.py  (diff, added by _patch_config)
    CEDAR_ENABLED: bool = False
    CEDAR_POLICY_DIR: str = "app/authz/policies"
    CEDAR_DEFAULT_EFFECT: str = "deny"

settings = Settings()
```

All three fields are inserted before `settings = Settings()` so they land at 4-space indent **inside** the `Settings` class body, ensuring pydantic-settings reads them from environment variables.

### 4.8 Router registration patch

```python
# app/routes/__init__.py  (appended by _patch_routes_init)
from app.api.routes.authz import router as authz_router
api_router.include_router(authz_router)
```

### 4.9 requirements.txt patch

```
# requirements.txt  (appended by _patch_requirements)
cedarpy>=0.4.0
```

### 4.10 Typical caller usage (after install)

```python
# In any route or service
from app.authz.engine import get_cedar_engine

engine = get_cedar_engine()
allowed = engine.is_authorized(
    principal='User::"alice"',
    action='Action::"delete"',
    resource='Resource::"report-42"',
    context={"department": "finance"},
)
if not allowed:
    raise HTTPException(status_code=403, detail="Forbidden")
```

```python
# Or via the management API (POST /authz/check)
payload = {
    "principal": 'User::"alice"',
    "action": 'Action::"delete"',
    "resource": 'Resource::"report-42"',
    "context": {"department": "finance"}
}
response = client.post("/authz/check", json=payload)
# {"allowed": true, "principal": "User::\"alice\"", ...}
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-01 | **Tool is idempotent on second run** | `add_cedar_policies` checks `"class CedarEngine" in engine_file.read_text()` and returns `status="no_op"` with empty `files_created`/`files_modified` |
| QS-02 | **`dry_run=True` writes zero files** | Early return before any filesystem write when `inp.dry_run` is truthy |
| QS-03 | **Every generated `.py` file AST-parses** | Final loop `for path in files_created: if .py: ast.parse(content)` before returning success |
| QS-04 | **No generated function exceeds 50 LOC** | Every helper in `engine.py`, `models.py`, `middleware.py`, `routes/authz.py` kept small by construction; asserted by AST walk in T-28 |
| QS-05 | **`cedarpy` is never imported at module top level** | `import cedarpy` lives inside `is_authorized()` body only; verified by AST inspection of top-level nodes in T-05 |
| QS-06 | **`CEDAR_ENABLED=false` (default) is a complete bypass** | Middleware and engine both check `getattr(settings, "CEDAR_ENABLED", False)` before any evaluation |
| QS-07 | **Cedar coexists with RBAC without conflict** | Middleware runs after RBAC (both use `add_middleware` stacking); Cedar provides ABAC on top |
| QS-08 | **No dead imports in generated code** | `ruff check --select F401` passes on `app/authz/` directory (T-29) |
| QS-09 | **`CEDAR_DEFAULT_EFFECT` controls behaviour when no policies loaded** | Engine falls back to `effect == "allow"` check when `_loaded` is `False` |
| QS-10 | **Three policy files provide working examples** | `admin_full_access.cedar`, `owner_read_write.cedar`, `default_deny.cedar` cover the most common patterns |
| QS-11 | **`AuthzResponse.allowed` is a bool field** | Verified in T-31; consumers can branch on `response.allowed` without string comparison |
| QS-12 | **Router uses `/authz` prefix** | `APIRouter(prefix="/authz", tags=["authz"])` — verified in T-14 |
| QS-13 | **Prerequisites are validated before any write** | `ensure_prerequisites(CONFIG_SETTINGS, ROUTES_INIT, REQUIREMENTS_TXT)` runs first |
| QS-14 | **Tool records execution time on every return path** | `_elapsed_ms(start)` appears on success, no_op, dry_run, and error branches |
| QS-15 | **`next_steps` mention cedarpy install** | Hard-coded `"pip install cedarpy>=0.4.0"` in success branch |
| QS-16 | **`MCP_TOOL` descriptor exposes `{name, description, tags, entry}` quartet** | Module-level `MCP_TOOL` dict is importable by the skill registry |

---

## 6. Completeness Criteria

Every criterion is tied to a real assertion in `test_add_cedar_policies.py`.

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | Tool returns `status="success"` on a fresh project | `result.status == "success"` | T-01 (`test_success_status`) |
| CC-02 | Second run returns `status="no_op"` with zero file ops | `r2.status == "no_op"` and both lists empty | T-21 (`test_idempotent_returns_no_op`) |
| CC-03 | `dry_run=True` writes zero bytes to the filesystem | `before == after` dict over every `.py` in tree | T-23 (`test_dry_run_writes_nothing`) |
| CC-04 | Tool creates at least 6 new files | `len(result.files_created) >= 6` and each path exists | T-26 (`test_minimum_files_created`) |
| CC-05 | Tool modifies at least 3 existing files | `len(result.files_modified) >= 3` and each path exists | T-27 (`test_minimum_files_modified`) |
| CC-06 | Every generated `.py` AST-parses cleanly | `ast.parse` over all `.py` files in project tree | T-20 (`test_all_py_files_parse`) |
| CC-07 | No generated function exceeds 50 LOC in `app/` | AST walk of `FunctionDef`/`AsyncFunctionDef`, `max_loc <= 50` | T-28 (`test_no_function_over_50_loc`) |
| CC-08 | `CEDAR_ENABLED`, `CEDAR_POLICY_DIR`, `CEDAR_DEFAULT_EFFECT` exist inside `class Settings` body at 4-space indent | Substring check + indent check on field lines | T-15 / T-16 (`test_config_patched`, `test_config_fields_inside_settings_class`) |
| CC-09 | `app/authz/__init__.py` re-exports `CedarEngine`, `get_cedar_engine`, `AuthzRequest`, `AuthzResponse` | All four names present in `__init__.py` | T-19 (`test_authz_init_reexports`) |
| CC-10 | Cedar router is registered in `app/routes/__init__.py` | `"authz_router"` and `"include_router"` in `routes/__init__.py` | T-17 (`test_routes_init_patched`) |
| CC-11 | `app/authz/engine.py`, `models.py`, `middleware.py`, `app/api/routes/authz.py` all exist | File existence checks | T-04, T-06, T-08, T-13 |
| CC-12 | `requirements.txt` contains `cedarpy` | `"cedarpy" in content` of `requirements.txt` | T-18 (`test_requirements_patched`) |
| CC-13 | `execution_time_ms` is a positive integer on the success path | `result.execution_time_ms > 0` | T-24 (`test_execution_time_recorded`) |
| CC-14 | `next_steps` is non-empty and mentions cedarpy | `any("cedarpy" in s for s in result.next_steps)` | T-25 (`test_next_steps_present`) |
| CC-15 | Running the tool twice leaves the project AST-parseable | `ast.parse` over all `.py` files after two runs | T-22 (`test_idempotent_project_still_parses`) |
| CC-16 | `app/authz/policies/` contains exactly 3 `.cedar` files | `len(list(policies_dir.glob("*.cedar"))) == 3` | T-11 (`test_policies_dir_created`) |
| CC-17 | `cedarpy` is NOT imported at module top level in `engine.py` | AST walk of top-level `ast.Import`/`ast.ImportFrom` nodes | T-05 (`test_engine_lazy_cedarpy_import`) |

---

## 7. Definition of Done (DoD)

- [ ] All 17 Completeness Criteria verified by `test_add_cedar_policies.py`
- [ ] `add_cedar_policies.py` runs `ast.parse` on every created `.py` file before returning success
- [ ] `add_cedar_policies.py` detects `"class CedarEngine"` fingerprint and returns `status="no_op"` on second run
- [ ] `dry_run=True` returns success with empty `files_created`/`files_modified`
- [ ] `cedarpy` is imported lazily inside `is_authorized()` body — not at module top level
- [ ] `CEDAR_ENABLED=false` (default) bypasses all Cedar evaluation with zero overhead
- [ ] `CedarAuthzMiddleware` returns HTTP 403 with JSON `{"detail": "Forbidden by Cedar policy"}` on deny
- [ ] `skip_paths` defaults to health, metrics, and documentation paths
- [ ] Three example `.cedar` files cover admin full access, owner read/write, and default deny patterns
- [ ] `POST /authz/check` and `GET /authz/policies` are registered on the `/authz` prefix
- [ ] `_patch_config` inserts all three `CEDAR_*` fields inside the `Settings` class body (4-space indent)
- [ ] `_patch_routes_init` appends the `authz_router` import and `include_router` call idempotently
- [ ] `_patch_requirements` appends `cedarpy>=0.4.0` only when absent
- [ ] `execution_time_ms` is set on every return path (success, no_op, dry_run, error)
- [ ] Tool exits within 5 s on a fresh fixture project
- [ ] `MCP_TOOL` descriptor exposes `{name, description, tags, entry}` quartet

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-CEDAR-01 | The tool is ALWAYS idempotent on second invocation | Fingerprint check `"class CedarEngine" in engine_file.read_text()` short-circuits to `status="no_op"` | T-21, T-22 |
| INV-CEDAR-02 | `dry_run=True` NEVER writes to disk | Early return guarded by `if inp.dry_run:` before any write | T-23 |
| INV-CEDAR-03 | Every generated `.py` file MUST parse as valid Python | Final loop `for path in files_created: ast.parse(content)` | T-20, T-22 |
| INV-CEDAR-04 | `cedarpy` MUST be imported lazily (not at module top level) | `import cedarpy` lives inside `is_authorized()` body; verified by AST walk of top-level nodes | T-05 |
| INV-CEDAR-05 | No generated function MUST exceed 50 LOC | Enforced by construction and tested by AST walk | T-28 |
| INV-CEDAR-06 | `ToolResult.execution_time_ms` MUST be positive on every return path | `_elapsed_ms(start)` called on success, no_op, dry_run, and error branches | T-24 |
| INV-CEDAR-07 | `CEDAR_*` settings MUST land inside `class Settings` body (4-space indent) | `_patch_config` inserts before `settings = Settings()` sentinel | T-15, T-16 |
| INV-CEDAR-08 | Middleware MUST return HTTP 403 JSON on Cedar deny | `Response(content=json.dumps(...), status_code=403)` in `dispatch` | T-09 |
| INV-CEDAR-09 | `GET /authz/policies` MUST list `.cedar` stems without extension | `sorted(p.stem for p in engine._policy_dir.glob("*.cedar"))` | T-13, T-14 |
| INV-CEDAR-10 | `next_steps` MUST reference `cedarpy` install so operators know the post-install step | Hard-coded `"pip install cedarpy>=0.4.0"` string in success branch | T-25 |

---

## 9. User Stories

### 9.1 Core install flow (US-01 .. US-05)

**US-01: Install Cedar into a clean FastAPI project**
- **As a** backend engineer who needs ABAC authorization
- **I want** to run one tool call and get a full Cedar authz kit
- **So that** I stop hand-rolling ownership checks inside route handlers
- **Given:** A FastAPI project with `app/core/config.py`, `app/routes/__init__.py`, `requirements.txt`
- **When:** `add_cedar_policies(ToolInput(project_dir=...))`
- **Then:**
  - Returns `ToolResult.status == "success"` (INV-CEDAR-01)
  - `files_created` contains >= 6 paths, each existing on disk (CC-04)
  - `files_modified` contains >= 3 paths (CC-05)
  - Verified by T-01, T-26, T-27

**US-02: Re-run the tool on an already-installed project**
- **As a** CI job that re-runs tooling on every commit
- **I want** the tool to skip work when Cedar is already applied
- **So that** I do not corrupt existing policies
- **Given:** Project where `app/authz/engine.py` already contains `class CedarEngine`
- **When:** `add_cedar_policies(...)` invoked a second time
- **Then:**
  - Returns `status="no_op"` (INV-CEDAR-01)
  - `files_created == []` and `files_modified == []`
  - All `.py` files still AST-parse (INV-CEDAR-03)
  - Verified by T-21, T-22

**US-03: Dry-run to preview changes**
- **As a** developer reviewing a tool invocation
- **I want** to see what would change without touching files
- **So that** I can audit before committing
- **Given:** Fresh FastAPI fixture project
- **When:** `add_cedar_policies(ToolInput(project_dir=..., dry_run=True))`
- **Then:**
  - Returns `status="success"` with informational `notes`
  - `files_created == []` and `files_modified == []`
  - Filesystem byte-identical before and after (INV-CEDAR-02)
  - Verified by T-23

**US-04: Activate Cedar via environment variable**
- **As a** platform engineer enabling Cedar in production
- **I want** `CEDAR_ENABLED=true` to be the only deploy change
- **So that** Cedar can be toggled without code changes
- **Given:** Cedar authz installed, `Settings` class has `CEDAR_ENABLED: bool = False`
- **When:** `.env` sets `CEDAR_ENABLED=true`
- **Then:**
  - `get_cedar_engine().is_authorized()` runs live policy evaluation
  - `CedarAuthzMiddleware.dispatch` performs Cedar check on every non-skip-path request
  - Verified by CC-08, INV-CEDAR-07

**US-05: Generated project stays auditable**
- **As a** code reviewer
- **I want** every generated function to be short
- **So that** I can read and approve it in one sitting
- **Given:** Tool just emitted `engine.py`, `models.py`, `middleware.py`, `routes/authz.py`
- **When:** I AST-walk `app/authz/` and `app/api/routes/authz.py` for functions
- **Then:**
  - No `FunctionDef`/`AsyncFunctionDef` has `end_lineno - lineno + 1 > 50` (QS-04)
  - Verified by T-28

### 9.2 Policy engine (US-06 .. US-10)

**US-06: Load policies from a custom directory**
- **As a** DevOps engineer deploying Cedar policies from a mounted volume
- **I want** `CEDAR_POLICY_DIR` to point at an arbitrary path
- **So that** I can version policies separately from application code
- **Given:** `CEDAR_POLICY_DIR=/etc/cedar/policies` in `.env`
- **When:** `get_cedar_engine()` initialises
- **Then:**
  - `CedarEngine(policy_dir="/etc/cedar/policies")` is constructed
  - `load_policies()` reads `*.cedar` files from that directory
  - Verified by CC-08

**US-07: Graceful degradation when cedarpy is not installed**
- **As a** developer bootstrapping a new project
- **I want** the application to boot without cedarpy
- **So that** I can install dependencies incrementally
- **Given:** `cedarpy` is not in the virtualenv
- **When:** Application boots and `CEDAR_ENABLED=false`
- **Then:**
  - `is_authorized()` returns `True` (all allowed) without touching cedarpy
  - Module top-level import does not raise `ImportError`
  - Verified by INV-CEDAR-04, T-05

**US-08: Deny-by-default when no policies are loaded**
- **As a** security-first operator
- **I want** `CEDAR_DEFAULT_EFFECT=deny` to block all requests if policies fail to load
- **So that** a misconfigured policy directory does not open the system
- **Given:** `CEDAR_ENABLED=true` and `CEDAR_POLICY_DIR` points at an empty directory
- **When:** `is_authorized()` is called
- **Then:**
  - `self._loaded` is `False`; `getattr(settings, "CEDAR_DEFAULT_EFFECT", "deny")` returns `"deny"`
  - `is_authorized()` returns `False`
  - Verified by QS-09

**US-09: Evaluate policy on-demand via the management API**
- **As a** developer debugging an authorization decision
- **I want** `POST /authz/check` to evaluate a policy rule interactively
- **So that** I can test policies without sending real traffic
- **Given:** Cedar authz installed and `/authz/check` endpoint registered
- **When:** `POST /authz/check` with `{"principal": "User::\"alice\"", "action": "Action::\"delete\"", ...}`
- **Then:**
  - Response has `allowed` bool and human-readable `reason`
  - Verified by CC-11, T-13, T-14

**US-10: List loaded policy files**
- **As an** operator auditing the active policy set
- **I want** `GET /authz/policies` to return the names of loaded `.cedar` files
- **So that** I can confirm my policy changes are active
- **Given:** Three `.cedar` files in `app/authz/policies/`
- **When:** `GET /authz/policies`
- **Then:**
  - Response is a sorted list of stem names (`["admin_full_access", "default_deny", "owner_read_write"]`)
  - Verified by CC-16, INV-CEDAR-09

### 9.3 Middleware (US-11 .. US-15)

**US-11: Middleware blocks unauthorized requests with HTTP 403**
- **As a** security reviewer
- **I want** unauthorized requests to return 403, not 200 or 500
- **So that** clients receive a standard RFC 7231 Forbidden response
- **Given:** `CEDAR_ENABLED=true` and a deny policy is active
- **When:** A request reaches `CedarAuthzMiddleware.dispatch`
- **Then:**
  - `get_cedar_engine().is_authorized()` returns `False`
  - Response is `HTTP 403` with `{"detail": "Forbidden by Cedar policy"}`
  - Verified by T-09, INV-CEDAR-08

**US-12: Health-check and docs paths bypass Cedar**
- **As a** platform engineer running Kubernetes health probes
- **I want** `/healthz` and `/docs` to never trigger Cedar evaluation
- **So that** probes work even when no policies are loaded
- **Given:** `skip_paths` defaults include `/healthz`, `/docs`, `/redoc`, `/openapi.json`
- **When:** A request hits any skip path
- **Then:**
  - Middleware calls `call_next(request)` without touching `get_cedar_engine()`
  - Verified by T-10, QS-06

**US-13: Custom skip_paths at middleware construction time**
- **As a** developer with non-standard health endpoints
- **I want** to pass a custom `skip_paths` frozenset when adding the middleware
- **So that** my internal probe endpoints are excluded
- **Given:** `app.add_middleware(CedarAuthzMiddleware, skip_paths=frozenset({"/internal/ready"}))`
- **When:** A request hits `/internal/ready`
- **Then:**
  - Middleware uses the provided set, not `_DEFAULT_SKIP`
  - Verified by QS-06, CC-11

**US-14: Principal extraction from JWT sub claim**
- **As a** JWT-authenticated API
- **I want** the principal to be derived from the JWT sub or user state
- **So that** Cedar policies reference real user identities
- **Given:** `request.state.user` has an `.id` attribute
- **When:** `_extract_principal(request)` is called
- **Then:**
  - Returns `'User::"<user.id>"'`
  - Falls back to `'User::"jwt-user"'` for Bearer tokens without state
  - Falls back to `'User::"anonymous"'` for unauthenticated requests
  - Verified by source code of `_extract_principal`

**US-15: Middleware adds zero overhead when Cedar is disabled**
- **As a** performance-conscious operator
- **I want** `CEDAR_ENABLED=false` to short-circuit immediately
- **So that** the middleware has literally zero policy evaluation cost
- **Given:** `CEDAR_ENABLED=false` (the default)
- **When:** Any request passes through `CedarAuthzMiddleware.dispatch`
- **Then:**
  - `not getattr(settings, "CEDAR_ENABLED", False)` is `True` → `call_next` immediately
  - No Cedar evaluation, no policy file reads
  - Verified by QS-06

### 9.4 Config and requirements (US-16 .. US-20)

**US-16: Config fields land inside the Settings class**
- **As a** pydantic-settings user
- **I want** `CEDAR_ENABLED`, `CEDAR_POLICY_DIR`, `CEDAR_DEFAULT_EFFECT` to be Settings fields
- **So that** they are populated from environment variables automatically
- **Given:** `_patch_config` inserts fields before `settings = Settings()`
- **When:** The application boots
- **Then:**
  - All three fields are at 4-space indent inside `class Settings` body
  - `settings.CEDAR_ENABLED` reads from `CEDAR_ENABLED` env var
  - Verified by T-15, T-16, INV-CEDAR-07

**US-17: Router is registered without duplicate entries**
- **As a** CI job running the tool multiple times
- **I want** `_patch_routes_init` to be idempotent
- **So that** the router is not included twice
- **Given:** `routes/__init__.py` already contains `authz_router`
- **When:** Tool runs a second time (in a partial second-run scenario)
- **Then:**
  - Import and include_router lines appear exactly once
  - Verified by T-17

**US-18: cedarpy added to requirements.txt once**
- **As a** requirements file consumer
- **I want** `cedarpy>=0.4.0` to appear once in `requirements.txt`
- **So that** pip install is repeatable
- **Given:** Tool adds the line; a second run calls `_patch_requirements` again
- **When:** `_patch_requirements` checks `"cedarpy" in content`
- **Then:**
  - Line appears exactly once (idempotent guard)
  - Verified by T-18

**US-19: Prerequisites prevent partial installs**
- **As an** engineer who forgets to generate the base project first
- **I want** a clear error if prerequisites are missing
- **So that** I am not left with a half-configured project
- **Given:** `project_dir` lacks `app/core/config.py` and `app/routes/__init__.py`
- **When:** `add_cedar_policies(...)` runs
- **Then:**
  - Returns `status="error"` with a descriptive message
  - `notes` recommend `fastapi_generate_project` as the fix
  - Verified by prerequisite guard in `add_cedar_policies`

**US-20: next_steps guide operator through activation**
- **As an** operator receiving the tool output
- **I want** `next_steps` to tell me exactly what to do after install
- **So that** I can activate Cedar without reading source code
- **Given:** Tool returns `status="success"`
- **When:** Operator reads `result.next_steps`
- **Then:**
  - Includes `"pip install cedarpy>=0.4.0"` (T-25, QS-15)
  - Includes `"Set CEDAR_ENABLED=true in your .env / Settings."`
  - Includes `"Set CEDAR_POLICY_DIR=app/authz/policies"`
  - Includes guidance on editing `.cedar` files

### 9.5 Example policy files (US-21 .. US-25)

**US-21: Admin full access policy is syntactically valid Cedar**
- **As a** Cedar evaluator
- **I want** `admin_full_access.cedar` to contain a valid `permit` rule
- **So that** OPA (or cedarpy) can load it without parse errors
- **Given:** `admin_full_access.cedar` written by `_write_cedar_policies`
- **When:** File is read
- **Then:**
  - Contains `permit(` keyword
  - Targets `principal in Role::"admin"`
  - Verified by T-12

**US-22: Default deny policy is syntactically valid Cedar**
- **As a** security reviewer
- **I want** `default_deny.cedar` to contain a `forbid` rule
- **So that** all unmatched requests are denied by Cedar's own evaluation
- **Given:** `default_deny.cedar` written by `_write_cedar_policies`
- **When:** File is read
- **Then:**
  - Contains `forbid(` keyword
  - Verified by T-12

**US-23: Owner read/write policy covers standard HTTP methods**
- **As a** developer writing resource-ownership ABAC
- **I want** `owner_read_write.cedar` to cover GET, POST, PUT, PATCH, DELETE
- **So that** the example covers all standard mutation methods
- **Given:** `owner_read_write.cedar` written by `_write_cedar_policies`
- **When:** File is read
- **Then:**
  - Contains all five action strings in an action list
  - Has a `when { resource.owner == principal }` condition
  - Verified by T-12

**US-24: Policy directory is created automatically**
- **As a** first-time Cedar user
- **I want** the `app/authz/policies/` directory to exist after the tool run
- **So that** I can immediately add my own `.cedar` files
- **Given:** Fresh project with no `app/authz/` directory
- **When:** `add_cedar_policies(...)` runs
- **Then:**
  - `app/authz/policies/` is a directory (`is_dir()` is `True`)
  - Contains exactly 3 `.cedar` files
  - Verified by T-11

**US-25: `__init__.py` provides clean public API**
- **As a** developer importing Cedar symbols
- **I want** `from app.authz import CedarEngine, AuthzRequest` to work
- **So that** I do not need to know the internal module layout
- **Given:** `app/authz/__init__.py` written by `_write_authz_init`
- **When:** Import statement is executed
- **Then:**
  - All four symbols available: `CedarEngine`, `get_cedar_engine`, `AuthzRequest`, `AuthzResponse`
  - Verified by T-19

---

## 10. Test Plan

### 10.1 Test inventory

| ID | Name | CC | Description |
|----|------|----|-------------|
| T-01 | `test_success_status` | CC-01 | Tool returns `status="success"` on a fresh project |
| T-02 | `test_files_created_all_exist` | CC-04 | Every path in `files_created` exists on disk |
| T-03 | `test_files_modified_all_exist` | CC-05 | Every path in `files_modified` exists on disk |
| T-04 | `test_engine_file_created` | CC-11 | `app/authz/engine.py` has `CedarEngine`, `load_policies`, `is_authorized` |
| T-05 | `test_engine_lazy_cedarpy_import` | CC-17 | `cedarpy` is NOT imported at module top level in `engine.py` |
| T-06 | `test_models_file_created` | CC-11 | `app/authz/models.py` has `AuthzRequest` and `AuthzResponse` |
| T-07 | `test_models_pydantic_fields` | — | `AuthzRequest` has all four fields: principal, action, resource, context |
| T-08 | `test_middleware_file_created` | CC-11 | `app/authz/middleware.py` has `CedarAuthzMiddleware` and `dispatch` |
| T-09 | `test_middleware_returns_403_on_deny` | CC-11 | Middleware source contains `403` and deny-related strings |
| T-10 | `test_middleware_skip_paths_present` | CC-11 | `skip_paths` and `/healthz` are present in middleware source |
| T-11 | `test_policies_dir_created` | CC-16 | `app/authz/policies/` exists with exactly 3 `.cedar` files |
| T-12 | `test_cedar_policy_files_content` | CC-16 | Each named `.cedar` file exists; `admin` has `permit`, `deny` has `forbid` |
| T-13 | `test_authz_routes_file_created` | CC-11 | `app/api/routes/authz.py` exists with `check` and `policies` references |
| T-14 | `test_authz_routes_prefix` | — | Router declares `prefix="/authz"` |
| T-15 | `test_config_patched` | CC-08 | All three `CEDAR_*` fields are in `app/core/config.py` |
| T-16 | `test_config_fields_inside_settings_class` | CC-08 | Each `CEDAR_*` field line starts with 4 spaces |
| T-17 | `test_routes_init_patched` | CC-10 | `app/routes/__init__.py` contains `authz_router` and `include_router` |
| T-18 | `test_requirements_patched` | CC-12 | `requirements.txt` contains `cedarpy` |
| T-19 | `test_authz_init_reexports` | CC-09 | `app/authz/__init__.py` re-exports all four symbols |
| T-20 | `test_all_py_files_parse` | CC-06 | `ast.parse` passes on all `.py` files in the project |
| T-21 | `test_idempotent_returns_no_op` | CC-02 | Second run returns `status="no_op"` with empty lists |
| T-22 | `test_idempotent_project_still_parses` | CC-15 | After two runs, all `.py` files still parse |
| T-23 | `test_dry_run_writes_nothing` | CC-03 | `dry_run=True` writes no files; filesystem identical |
| T-24 | `test_execution_time_recorded` | CC-13 | `execution_time_ms > 0` |
| T-25 | `test_next_steps_present` | CC-14 | `next_steps` non-empty; contains `"cedarpy"` |
| T-26 | `test_minimum_files_created` | CC-04 | `len(files_created) >= 6` |
| T-27 | `test_minimum_files_modified` | CC-05 | `len(files_modified) >= 3` |
| T-28 | `test_no_function_over_50_loc` | CC-07 | No function in generated code exceeds 50 LOC |
| T-29 | `test_no_dead_imports_in_generated_code` | QS-08 | `ruff check --select F401` passes on `app/authz/` |
| T-30 | `test_engine_has_singleton_getter` | — | `engine.py` exposes `def get_cedar_engine` |
| T-31 | `test_authz_response_has_allowed_field` | — | `AuthzResponse.allowed` is a bool field |

### 10.2 Running tests

```bash
# From skill root
PYTHONPATH=. pytest adapt/extend/auth_access/test_add_cedar_policies.py -v

# Standalone (no pytest)
PYTHONPATH=. python3 adapt/extend/auth_access/test_add_cedar_policies.py
```

### 10.3 Minimum pass criteria

All 31 tests must pass with 0 skipped. `dry_run` and idempotency tests are the most critical for production safety.

---

## 11. Error Handling

| Scenario | Tool Response | User Action |
|----------|---------------|-------------|
| `project_dir` does not exist or is not a directory | `status="error"`, `error` from `validate_project_dir` | Pass a valid absolute path to an existing FastAPI project root |
| Prerequisites missing (no `app/core/config.py`, no `routes/__init__.py`) | `status="error"` with list of missing prerequisites and note to run `fastapi_generate_project` | Run `fastapi_generate_project` first or create the missing files |
| Generated `.py` file has a `SyntaxError` (defensive) | `status="error"`, `error="Generated file has syntax error: <path>: <exc>"` | File a bug report with the tool version; do not deploy the project |
| `app/authz/engine.py` already contains `class CedarEngine` | `status="no_op"`, `notes=["Cedar authz engine already present — skipped."]` | No action needed; Cedar is already installed |
| `dry_run=True` | `status="success"`, informational `notes`, no files written | Review the notes; re-run without `dry_run=True` to apply |
| `cedarpy` not installed at runtime | `is_authorized()` catches `ImportError` and logs an error, returns `False` | `pip install cedarpy>=0.4.0` and restart the application |
| Cedar policy directory is empty or missing | `load_policies()` logs a warning; `_loaded` remains `False`; `CEDAR_DEFAULT_EFFECT` controls outcome | Check `CEDAR_POLICY_DIR` in `.env` and verify the directory path |

---

## 12. Integration Notes

### 12.1 Cedar + RBAC coexistence

Cedar is explicitly designed to run **after** RBAC when both are installed. The middleware stacking order in `app/main.py` controls evaluation sequence:

```python
# app/main.py
app.add_middleware(CedarAuthzMiddleware)  # runs SECOND (inner)
app.add_middleware(RBACMiddleware)        # runs FIRST (outer)
```

In Starlette's middleware chain, the outermost middleware added last executes first. If RBAC denies the request, Cedar never sees it. Cedar then provides ABAC enforcement on top of RBAC.

### 12.2 cedarpy lazy import

`cedarpy` is imported inside `is_authorized()` method bodies only. This means:

- The application boots cleanly without `cedarpy` installed
- `CEDAR_ENABLED=false` (default) means `cedarpy` is never imported at all
- Teams can install `cedarpy` independently of the application deployment

### 12.3 Principal extraction pipeline

The `_extract_principal` static method in `CedarAuthzMiddleware` implements a three-tier fallback:

1. `request.state.user.id` — set by JWT middleware upstream (preferred)
2. `Bearer` token present → `'User::"jwt-user"'` (opaque, for policies that just check authenticated/anonymous)
3. No auth header → `'User::"anonymous"'`

Production teams should wire `request.state.user` from their JWT dependency to get full user-identity-based Cedar evaluation.

### 12.4 Relationship to TOOL-072 (OPA)

Both TOOL-071 (Cedar) and TOOL-072 (OPA) provide policy-as-code ABAC for FastAPI. They differ in their execution model:

| Aspect | TOOL-071 (Cedar) | TOOL-072 (OPA) |
|--------|-----------------|----------------|
| Execution | In-process (cedarpy) | Out-of-process sidecar (OPA server) |
| Policy language | Cedar (.cedar files) | Rego (.rego files) |
| Network dependency | None | OPA sidecar HTTP |
| Latency | < 1 ms | Network RTT to sidecar |
| Ecosystem | AWS Cedar / Amazon Verified Permissions | CNCF / Kubernetes RBAC |

Teams should choose Cedar when they want in-process evaluation without a sidecar, and OPA when they want a language-agnostic policy server that can be shared across multiple services.

---

## 13. Assumptions

1. The project follows the standard FastAPI layout: `app/core/config.py` with a `Settings` class and `settings = Settings()` instantiation, `app/routes/__init__.py` with an `api_router` object.
2. `CEDAR_ENABLED` defaults to `False` — Cedar is opt-in and does not affect existing deployments.
3. The tool generates the **client side** only — it does not embed an OPA-style server; Cedar evaluation is in-process via cedarpy.
4. Policy files are plain text `.cedar` files loaded from a configurable directory at startup. Dynamic policy reload requires application restart.
5. `cedarpy` package must be installed separately (`pip install cedarpy>=0.4.0`) — the tool does not install it for the target project, only adds it to `requirements.txt`.
6. The principal extraction in `_extract_principal` is a starter implementation; production deployments should wire `request.state.user` from their auth middleware.

---

## 14. Dependencies

| Package | Version | Role |
|---------|---------|------|
| `cedarpy` | `>=0.4.0` | Cedar policy evaluation (lazy import) |
| `fastapi` | existing | APIRouter, HTTPException, status |
| `starlette` | existing | BaseHTTPMiddleware, Request, Response |
| `pydantic` | `v2+` | `BaseModel`, `Field` for request/response models |

No new runtime dependencies are added to the application beyond `cedarpy` — all other imports (`logging`, `json`, `pathlib`) are Python stdlib.

---

## 15. Known Limitations

1. **In-process only**: Cedar evaluation runs in the same process as the FastAPI application. A CPU-intensive policy set (hundreds of policies with complex conditions) will block the event loop briefly on each evaluation.
2. **No hot reload**: Policy changes require an application restart; `CedarEngine` does not watch for `.cedar` file changes at runtime.
3. **`_extract_principal` is a starter**: The default implementation uses `request.state.user.id` or the presence of a `Bearer` token. Full principal extraction requires integration with the project's specific JWT library.
4. **Cedar entity data**: The example policies use `resource.owner == principal` but cedarpy requires entity data to evaluate attribute conditions. Teams must extend `is_authorized()` to pass entity dictionaries for production ABAC.
5. **`GET /authz/policies` accesses private `_policy_dir`**: The route uses `engine._policy_dir` (name-mangled). This is a pragmatic choice kept consistent with the source implementation; production hardening may expose a public property.

---

## 16. File Layout (Post-install)

```
project/
├── app/
│   ├── authz/
│   │   ├── __init__.py              # Re-exports: CedarEngine, AuthzRequest, AuthzResponse
│   │   ├── engine.py                # CedarEngine class + get_cedar_engine() singleton
│   │   ├── models.py                # AuthzRequest, AuthzResponse Pydantic models
│   │   ├── middleware.py            # CedarAuthzMiddleware (Starlette BaseHTTPMiddleware)
│   │   └── policies/
│   │       ├── admin_full_access.cedar
│   │       ├── owner_read_write.cedar
│   │       └── default_deny.cedar
│   ├── api/
│   │   └── routes/
│   │       └── authz.py             # POST /authz/check, GET /authz/policies
│   └── core/
│       └── config.py               # + CEDAR_ENABLED, CEDAR_POLICY_DIR, CEDAR_DEFAULT_EFFECT
├── app/routes/
│   └── __init__.py                  # + authz_router import + include_router
└── requirements.txt                 # + cedarpy>=0.4.0
```
