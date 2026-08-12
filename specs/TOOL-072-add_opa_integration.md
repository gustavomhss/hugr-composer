---
spec_id: "TOOL-072"
tool_name: "add_opa_integration"
version: "1.0.0"
status: "ratified"
invariants:
  - "INV-OPA-01"
  - "INV-OPA-02"
  - "INV-OPA-03"
  - "INV-OPA-04"
  - "INV-OPA-05"
  - "INV-OPA-06"
  - "INV-OPA-07"
  - "INV-OPA-08"
  - "INV-OPA-09"
  - "INV-OPA-10"
  - "INV-OPA-11"
  - "INV-OPA-12"
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
  - "T-32"
  - "T-33"
  - "T-34"
  - "T-35"
tags:
  - "performance"
  - "data"
  - "resiliency"
  - "realtime"
  - "compliance"
---
# TOOL-072: add_opa_integration

> **Status**: SPEC v1 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_opa_integration` |
| Category | EXTEND > Auth & Access |
| Complexity | High |
| Dependencies | FastAPI, Starlette, Pydantic v2, httpx>=0.28.0 (lazy), OPA sidecar (external) |
| Signature | `add_opa_integration(inp: ToolInput) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path to FastAPI project root) and `dry_run` flag |
| MCP descriptor | `{"name": "fastapi_add_opa_integration", "description": "Add Open Policy Agent (OPA) integration with circuit breaker, middleware, example Rego policies, and management endpoints.", "tags": ["extend", "auth_access"], "entry": "add_opa_integration"}` |
| Files created (typical) | 7 — `app/authz/__init__.py`, `app/authz/opa_models.py`, `app/authz/opa_client.py`, `app/authz/opa_middleware.py`, `app/authz/policies/authz.rego`, `app/authz/policies/data.json`, `app/authz/policies/authz_test.rego`, `app/api/routes/opa.py` |
| Files modified (typical) | 3 — `app/core/config.py`, `app/routes/__init__.py`, `requirements.txt` |

---

## 2. Purpose

The `fastapi_add_opa_integration` tool installs a production-grade **Open Policy Agent (OPA)** authorization integration into a FastAPI project using **httpx** for HTTP calls to the OPA sidecar. OPA is a CNCF-graduated policy engine used across Kubernetes RBAC, Envoy, and API gateways. Teams reach for it when they need a language-agnostic policy server shared across multiple services: a single Rego policy bundle can gate admission to a Kubernetes cluster, filter API responses in FastAPI, and enforce CI/CD pipeline decisions — all from one source of truth.

The core problem OPA solves in FastAPI is the same one Cedar solves (see TOOL-071), but from a different operational angle: rather than in-process evaluation, OPA runs as a **sidecar** that the FastAPI application calls via HTTP. This separation of concerns lets the policy team deploy Rego bundles independently of application deployments, gives operations a dedicated process to profile and scale, and allows a single OPA instance to serve multiple upstream services. The trade-off is the network round-trip: every authorization decision becomes an HTTP POST to `{OPA_URL}/v1/data/{policy_path}`.

This tool generates the entire OPA client-side kit: (a) `app/authz/opa_models.py` with two Pydantic v2 models — `OPAInput` (subject, action, resource, context) and `OPADecision` (allow, reason, policy_path) — that mirror the OPA `/v1/data` request/response contract; (b) `app/authz/opa_client.py` containing `OPAClient`, a fully async HTTP client built on `httpx.AsyncClient` (lazy import so the app boots without httpx installed), a `_CircuitBreaker` inner class that opens after `OPA_CB_THRESHOLD` consecutive failures and remains open for `OPA_CB_RESET_S` seconds, and a `get_opa_client()` FastAPI dependency that reads all OPA settings from `app.core.config.settings`; (c) `app/authz/opa_middleware.py` with `OPAMiddleware`, a Starlette `BaseHTTPMiddleware` that queries OPA per-request and returns HTTP 403 JSON on denial; (d) three example Rego files (`authz.rego`, `data.json`, `authz_test.rego`) using the `rego.v1` import for forward compatibility; (e) `app/api/routes/opa.py` with `POST /authz/opa/check` (on-demand policy evaluation) and `GET /authz/opa/health` (sidecar liveness probe), both using FastAPI dependency injection to receive the `OPAClient`.

Key design decisions: `httpx` is **imported lazily inside async methods** (`_post_opa`, `health`) so the application boots without it installed and teams can add it incrementally; the **circuit breaker** prevents hammering an unavailable OPA sidecar — after `threshold` consecutive failures the circuit opens and returns `fail_open` immediately without network I/O; `OPA_FAIL_OPEN` controls the fail-open / fail-closed policy on circuit-open so teams can choose between availability (allow on OPA down) and security (deny on OPA down); the tool generates the **client side only** — it does not start or configure an OPA process; the tool is idempotent by fingerprint detection (`"class OPAClient" in app/authz/opa_client.py`) and returns `status="no_op"` on second invocation.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | Must complete within CI step budget; measured via `execution_time_ms` (T-27) |
| Files created | >= 5 | Minimum: authz init, models, client, middleware, routes (T-29) |
| Files modified | >= 2 | config, routes_init (at minimum); requirements is optional if httpx already present |
| Max function LOC in generated code | <= 50 | Each generated function stays auditable; asserted by AST walk (T-30) |
| `OPAClient.query()` latency | < OPA_TIMEOUT_MS + network RTT | Bounded by `httpx.AsyncClient(timeout=...)` per-request timeout |
| `OPAClient.health()` latency | < 2 s | Fixed 2-second timeout on GET /health |
| Circuit breaker open threshold | Default: 3 consecutive failures | Configurable via `OPA_CB_THRESHOLD` |
| Circuit breaker reset | Default: 30 s | Configurable via `OPA_CB_RESET_S` |
| `POST /authz/opa/check` latency | OPA round-trip + < 5 ms overhead | Includes one OPAClient.query() call |
| `GET /authz/opa/health` latency | < 2.1 s | OPAClient.health() + FastAPI routing overhead |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
project/
├── app/
│   ├── main.py              # FastAPI app, no OPA integration
│   ├── core/
│   │   └── config.py        # Settings class, no OPA_* fields
│   ├── routes/
│   │   └── __init__.py      # api_router, no OPA router
│   └── api/
│       └── routes/          # Domain routes
├── requirements.txt         # no httpx (or httpx without OPA config)
```

Authorization logic is ad-hoc: no centralized policy engine, no audit trail of authorization decisions, no ability to update policies without redeploying the application.

### 4.2 OPA Pydantic models: AFTER

```python
# app/authz/opa_models.py
"""Pydantic models for OPA (Open Policy Agent) requests and responses."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class OPAInput(BaseModel):
    """Input document sent to OPA for policy evaluation."""

    model_config = ConfigDict(from_attributes=True)

    subject: str = Field(..., description="Authenticated user identifier.")
    action: str = Field(..., description="Action being performed.")
    resource: str = Field(..., description="Resource being accessed.")
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional extra context passed verbatim to OPA.",
    )


class OPADecision(BaseModel):
    """Decision returned by OPA policy evaluation."""

    model_config = ConfigDict(from_attributes=True)

    allow: bool = Field(..., description="True when the policy grants access.")
    reason: str | None = Field(default=None, description="Optional explanation.")
    policy_path: str = Field(..., description="OPA rule path that was evaluated.")
```

### 4.3 OPAClient (lazy httpx, circuit breaker): AFTER

```python
# app/authz/opa_client.py  (key methods)
"""OPA HTTP client with lazy httpx import and circuit breaker."""

class _CircuitBreaker:
    """Lightweight circuit breaker: closed -> half-open -> open."""

    def __init__(self, threshold: int = 3, reset_s: float = 30.0) -> None:
        self.threshold = threshold
        self.reset_s = reset_s
        self._failures = 0
        self._opened_at: float | None = None

    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        if time.monotonic() - self._opened_at >= self.reset_s:
            self._opened_at = None
            self._failures = 0
            return False
        return True

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.threshold:
            self._opened_at = time.monotonic()


class OPAClient:
    """Async OPA HTTP client."""

    async def query(self, opa_input: OPAInput, policy_path: str | None = None) -> OPADecision:
        path = (policy_path or self.policy_path).strip("/")
        url = f"{self.opa_url}/v1/data/{path}"
        if self._cb.is_open():
            return OPADecision(allow=self.fail_open, reason="circuit_open", policy_path=path)
        payload: dict[str, Any] = {"input": opa_input.model_dump()}
        try:
            data = await _post_opa(url, payload, self.timeout_ms / 1000.0)
            self._cb.record_success()
        except Exception as exc:
            self._cb.record_failure()
            return OPADecision(allow=self.fail_open, reason="opa_unavailable", policy_path=path)
        return _parse_opa_result(data, path)

    async def health(self) -> bool:
        import httpx  # lazy import
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{self.opa_url}/health")
            return resp.status_code == 200
        except Exception:
            return False
```

### 4.4 OPAMiddleware (per-request enforcement): AFTER

```python
# app/authz/opa_middleware.py
class OPAMiddleware(BaseHTTPMiddleware):
    """Request-level OPA enforcement middleware."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if any(path.startswith(pfx) for pfx in _SKIP_PREFIXES):
            return await call_next(request)
        subject = request.headers.get("X-User-Id", "anonymous")
        opa_input = OPAInput(
            subject=subject,
            action=request.method,
            resource=path,
            context={"query": str(request.query_params)},
        )
        client = get_opa_client()
        decision = await client.query(opa_input)
        if not decision.allow:
            return JSONResponse(status_code=403, content={"detail": "Forbidden by policy"})
        return await call_next(request)
```

### 4.5 Example Rego policies: AFTER

```rego
# authz.rego — Example OPA policy for HTTP API authorization.
package authz

import rego.v1

default allow := false

allow if {
    data.roles[input.subject] == "superuser"
}

allow if {
    input.action == "GET"
    input.subject != "anonymous"
}

allow if {
    input.action in {"POST", "PUT", "DELETE", "PATCH"}
    data.roles[input.subject] == "writer"
}
```

```json
// data.json
{
    "roles": {
        "admin@example.com": "superuser",
        "writer@example.com": "writer",
        "reader@example.com": "reader"
    }
}
```

```rego
# authz_test.rego — OPA unit tests
# Run: opa test authz.rego data.json authz_test.rego -v
package authz_test

import rego.v1
import data.authz

test_superuser_allowed if { authz.allow with input as {...} }
test_anonymous_get_denied if { not authz.allow with input as {...} }
```

### 4.6 Management API routes: AFTER

```python
# app/api/routes/opa.py
router = APIRouter(prefix="/authz/opa", tags=["opa"])

@router.post("/check", response_model=OPADecision)
async def check_policy(
    opa_input: OPAInput,
    client: OPAClient = Depends(get_opa_client),
) -> OPADecision:
    """Evaluate an OPA policy rule for the given input document."""
    decision = await client.query(opa_input)
    if decision.reason == "opa_unavailable" and not client.fail_open:
        raise HTTPException(status_code=503, detail="OPA sidecar unavailable")
    return decision

@router.get("/health")
async def opa_health(client: OPAClient = Depends(get_opa_client)) -> dict[str, str]:
    """Probe the OPA sidecar's /health endpoint."""
    healthy = await client.health()
    return {"status": "ok" if healthy else "unavailable"}
```

### 4.7 Config patch (fields inside `class Settings`)

```python
# app/core/config.py  (diff, added by _patch_config)
    OPA_URL: str = "http://localhost:8181"
    OPA_ENABLED: bool = False
    OPA_POLICY_PATH: str = "authz/allow"
    OPA_TIMEOUT_MS: int = 500
    OPA_FAIL_OPEN: bool = False

settings = Settings()
```

All five fields are inserted before `settings = Settings()` so they land at 4-space indent inside the `Settings` class body.

### 4.8 Router registration patch

```python
# app/routes/__init__.py  (appended by _patch_routes_init)
from app.api.routes.opa import router as opa_router
api_router.include_router(opa_router)
```

### 4.9 requirements.txt patch

```
# requirements.txt  (appended by _patch_requirements)
httpx>=0.28.0
```

### 4.10 Typical caller usage (after install)

```python
# app/api/routes/items.py
from fastapi import APIRouter, Depends, HTTPException
from app.authz.opa_client import OPAClient, get_opa_client
from app.authz.opa_models import OPAInput

router = APIRouter()

@router.get("/items/{item_id}")
async def get_item(
    item_id: str,
    current_user: str = Depends(get_current_user_id),
    opa: OPAClient = Depends(get_opa_client),
):
    decision = await opa.query(OPAInput(
        subject=current_user,
        action="GET",
        resource=f"/items/{item_id}",
    ))
    if not decision.allow:
        raise HTTPException(status_code=403, detail="Forbidden")
    return {"item_id": item_id}
```

```bash
# Start OPA sidecar
docker run -p 8181:8181 \
    -v $(pwd)/app/authz/policies:/policies \
    openpolicyagent/opa run --server /policies/authz.rego /policies/data.json
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-01 | **Tool is idempotent on second run** | `add_opa_integration` checks `"class OPAClient" in opa_client_file.read_text()` and returns `status="no_op"` with empty lists |
| QS-02 | **`dry_run=True` writes zero files** | Early return before any filesystem write when `inp.dry_run` is truthy |
| QS-03 | **Every generated `.py` file AST-parses** | Final loop over `files_created` runs `ast.parse` on each `.py` before returning success |
| QS-04 | **No generated function exceeds 50 LOC** | Every helper in `opa_client.py`, `opa_middleware.py`, `opa_models.py`, `routes/opa.py` kept small by construction; asserted by AST walk in T-30 |
| QS-05 | **`httpx` is never imported at module top level** | `import httpx` lives inside `_post_opa()` and `health()` bodies only; verified by AST inspection of top-level nodes in T-12 (CC-09) |
| QS-06 | **Circuit breaker prevents hammering an unavailable sidecar** | `_CircuitBreaker.is_open()` short-circuits to fail_open without network I/O when open |
| QS-07 | **`OPA_FAIL_OPEN` controls fail-open / fail-closed behavior** | `OPAClient.fail_open` read from `settings.OPA_FAIL_OPEN`; returned on circuit_open and opa_unavailable paths |
| QS-08 | **No dead imports in generated `app/authz/` code** | `ruff check --select F401` passes on `app/authz/` directory (T-32) |
| QS-09 | **OPA routes use FastAPI dependency injection** | `client: OPAClient = Depends(get_opa_client)` in both route handlers |
| QS-10 | **Rego policies use `rego.v1` import** | `authz.rego` contains `import rego.v1` for forward compatibility with OPA 1.x |
| QS-11 | **Pydantic models use `ConfigDict`** | `OPAInput` and `OPADecision` use `model_config = ConfigDict(from_attributes=True)` (T-35) |
| QS-12 | **`authz.rego` has `default allow := false`** | Deny-by-default pattern; verified in T-16 (CC-13) |
| QS-13 | **`_write_authz_init` is idempotent** | Checks `dest.exists()` before writing to avoid overwriting a Cedar `__init__.py` |
| QS-14 | **Tool records execution time on every return path** | `_elapsed_ms(start)` appears on success, no_op, dry_run, and error branches |
| QS-15 | **`next_steps` mention OPA sidecar** | Hard-coded `docker run openpolicyagent/opa ...` in success branch |
| QS-16 | **`MCP_TOOL` descriptor exposes `{name, description, tags, entry}` quartet** | Module-level `MCP_TOOL` dict is importable by the skill registry |

---

## 6. Completeness Criteria

Every criterion is tied to a real assertion in `test_add_opa_integration.py`.

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | `app/authz/__init__.py` exists and re-exports `OPAClient`, `OPAMiddleware` | `"OPAClient" in content` and `"OPAMiddleware" in content` | T-04 (`test_authz_init_created`) |
| CC-02 | `app/authz/opa_models.py` exists with `OPAInput` and `OPADecision` | File exists + class name checks | T-05 (`test_opa_models_file_created`) |
| CC-03 | `OPAInput` has `subject`, `action`, `resource`, `context` fields | All four field names present in file | T-06 (`test_opa_input_has_required_fields`) |
| CC-04 | `OPADecision` has `allow` bool field | `"allow"` and `"bool"` present in models file | T-07 (`test_opa_decision_has_allow_field`) |
| CC-05 | `app/authz/opa_client.py` exists with `OPAClient` class | File exists + `"class OPAClient" in content` | T-08 (`test_opa_client_file_created`) |
| CC-06 | `OPAClient` has `async query()` method | `"async def query" in content` | T-09 (`test_opa_client_has_query_method`) |
| CC-07 | `OPAClient` has `async health()` method | `"async def health" in content` | T-10 (`test_opa_client_has_health_method`) |
| CC-08 | `opa_client.py` contains circuit breaker logic | `"circuit" in content.lower()` or `"_CircuitBreaker" in content` | T-11 (`test_opa_client_circuit_breaker`) |
| CC-09 | `httpx` is NOT imported at module top level in `opa_client.py` | AST walk of top-level `ast.Import`/`ast.ImportFrom` nodes | T-12 (`test_opa_client_lazy_httpx`) |
| CC-10 | `app/authz/opa_middleware.py` exists with `OPAMiddleware` class | File exists + `"class OPAMiddleware" in content` | T-13 (`test_opa_middleware_file_created`) |
| CC-11 | `OPAMiddleware` returns HTTP 403 on denied requests | `"403" in content` or `"HTTP_403_FORBIDDEN" in content` | T-14 (`test_opa_middleware_returns_403`) |
| CC-12 | `app/authz/policies/` contains `authz.rego`, `data.json`, `authz_test.rego` | Three file existence checks | T-15 (`test_rego_policies_created`) |
| CC-13 | `authz.rego` contains `default allow := false` | Substring check on Rego file | T-16 (`test_authz_rego_default_deny`) |
| CC-14 | `app/api/routes/opa.py` exists with `/authz/opa` prefix | File exists + prefix string check | T-17 (`test_opa_routes_file_created`) |
| CC-15 | `opa.py` has `POST /authz/opa/check` endpoint | `"/check" in content` and `"async def check_policy" in content` | T-18 (`test_opa_routes_check_endpoint`) |
| CC-16 | `opa.py` has `GET /authz/opa/health` endpoint | `"/health" in content` | T-19 (`test_opa_routes_health_endpoint`) |
| CC-17 | All 5 OPA fields in `app/core/config.py` at 4-space indent | All five names present + indent check | T-20 (`test_config_fields_patched`) |
| CC-18 | `app/routes/__init__.py` imports and includes `opa_router` | Import line and `include_router` line both present | T-21 (`test_routes_init_patched`) |
| CC-19 | `requirements.txt` contains `httpx` | `"httpx" in content` | T-22 (`test_requirements_patched`) |
| CC-20 | Every generated `.py` AST-parses cleanly | `ast.parse` over all `.py` files in project tree | T-23 (`test_all_py_files_parse`) |
| CC-21 | Second run returns `status="no_op"` with zero file ops | `r2.status == "no_op"` and both lists empty | T-24 (`test_idempotent_returns_no_op`) |
| CC-22 | No generated function exceeds 50 LOC in `app/authz/` and `routes/opa.py` | AST walk of all generated functions | T-30 (`test_no_function_over_50_loc`) |
| CC-23 | `opa_client.py` exposes `get_opa_client` FastAPI dependency | `"def get_opa_client" in content` | T-31 (`test_get_opa_client_dependency`) |
| CC-24 | `opa_client.py` supports `fail_open` configuration | `"fail_open" in content` | T-33 (`test_fail_open_configurable`) |
| CC-25 | Circuit breaker has `is_open`, `record_failure`, `record_success` | All three method names present | T-34 (`test_circuit_breaker_in_client`) |

---

## 7. Definition of Done (DoD)

- [ ] All 25 Completeness Criteria verified by `test_add_opa_integration.py`
- [ ] `add_opa_integration.py` runs `ast.parse` on every created `.py` file before returning success
- [ ] `add_opa_integration.py` detects `"class OPAClient"` fingerprint and returns `status="no_op"` on second run
- [ ] `dry_run=True` returns success with empty `files_created`/`files_modified`
- [ ] `httpx` is imported lazily inside `_post_opa()` and `health()` method bodies — not at module top level
- [ ] `_CircuitBreaker` implements `is_open()`, `record_success()`, `record_failure()` with configurable threshold and reset period
- [ ] `OPA_FAIL_OPEN` controls behaviour on circuit-open and opa_unavailable paths
- [ ] `OPAMiddleware` returns HTTP 403 JSON `{"detail": "Forbidden by policy"}` on denial
- [ ] `_SKIP_PREFIXES` defaults include `/healthz`, `/docs`, `/redoc`, `/openapi.json`, `/api/v1/login`
- [ ] Three Rego files: `authz.rego` (with `import rego.v1` and `default allow := false`), `data.json`, `authz_test.rego`
- [ ] `POST /authz/opa/check` and `GET /authz/opa/health` use FastAPI `Depends(get_opa_client)`
- [ ] `_patch_config` inserts all five `OPA_*` fields inside the `Settings` class body (4-space indent)
- [ ] `_patch_routes_init` is idempotent: checks both import and include_router before appending
- [ ] `_patch_requirements` appends `httpx>=0.28.0` only when `httpx` is absent from requirements
- [ ] `execution_time_ms` is set on every return path (success, no_op, dry_run, error)
- [ ] Tool exits within 5 s on a fresh fixture project
- [ ] `MCP_TOOL` descriptor exposes `{name, description, tags, entry}` quartet

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-OPA-01 | The tool is ALWAYS idempotent on second invocation | Fingerprint check `"class OPAClient" in opa_client_file.read_text()` short-circuits to `status="no_op"` | T-24, T-25 |
| INV-OPA-02 | `dry_run=True` NEVER writes to disk | Early return guarded by `if inp.dry_run:` before any write | T-26 |
| INV-OPA-03 | Every generated `.py` file MUST parse as valid Python | Final loop `for path in files_created: ast.parse(content)` | T-23, T-25 |
| INV-OPA-04 | `httpx` MUST be imported lazily (not at module top level) | `import httpx` inside `_post_opa()` and `health()` bodies; AST-verified | T-12 |
| INV-OPA-05 | No generated function MUST exceed 50 LOC | Enforced by construction and tested by AST walk | T-30 |
| INV-OPA-06 | `ToolResult.execution_time_ms` MUST be positive on every return path | `_elapsed_ms(start)` called on success, no_op, dry_run, and error branches | T-27 |
| INV-OPA-07 | `OPA_*` settings MUST land inside `class Settings` body (4-space indent) | `_patch_config` inserts before `settings = Settings()` sentinel | T-20 |
| INV-OPA-08 | `OPAMiddleware` MUST return HTTP 403 JSON on OPA denial | `JSONResponse(status_code=403, content={"detail": "Forbidden by policy"})` in `dispatch` | T-14 |
| INV-OPA-09 | Circuit breaker MUST have `is_open`, `record_success`, `record_failure` | `_CircuitBreaker` class implements all three methods | T-34 |
| INV-OPA-10 | `next_steps` MUST reference OPA sidecar startup command | Hard-coded `docker run openpolicyagent/opa ...` string in success branch | T-28 |
| INV-OPA-11 | `authz.rego` MUST contain `default allow := false` | Deny-by-default is a security invariant of the example policy | T-16 |
| INV-OPA-12 | `_write_authz_init` MUST be idempotent (skip if file already exists) | `if dest.exists(): return` guard in `_write_authz_init` | CC-01 |

---

## 9. User Stories

### 9.1 Core install flow (US-01 .. US-05)

**US-01: Install OPA client into a clean FastAPI project**
- **As a** backend engineer adopting policy-as-code
- **I want** to run one tool call and get a complete OPA client kit
- **So that** I stop writing custom HTTP clients to the OPA sidecar
- **Given:** A FastAPI project with `app/core/config.py`, `app/models/base.py`, `app/routes/__init__.py`, `requirements.txt`
- **When:** `add_opa_integration(ToolInput(project_dir=...))`
- **Then:**
  - Returns `ToolResult.status == "success"` (INV-OPA-01)
  - `files_created` contains >= 5 paths, each existing on disk (CC-05)
  - `files_modified` contains >= 2 paths
  - Verified by T-01, T-02, T-03, T-29

**US-02: Re-run the tool on an already-installed project**
- **As a** CI job that re-runs tooling on every commit
- **I want** the tool to skip work when OPA is already installed
- **So that** I do not corrupt existing OPA configurations
- **Given:** Project where `app/authz/opa_client.py` already contains `class OPAClient`
- **When:** `add_opa_integration(...)` invoked a second time
- **Then:**
  - Returns `status="no_op"` (INV-OPA-01)
  - `files_created == []` and `files_modified == []`
  - All `.py` files still AST-parse (INV-OPA-03)
  - Verified by T-24, T-25

**US-03: Dry-run to preview changes**
- **As a** developer reviewing a tool invocation
- **I want** to see what would change without touching files
- **So that** I can audit before committing
- **Given:** Fresh FastAPI fixture project
- **When:** `add_opa_integration(ToolInput(project_dir=..., dry_run=True))`
- **Then:**
  - Returns `status="success"` with informational `notes`
  - `files_created == []` and `files_modified == []`
  - Filesystem byte-identical before and after (INV-OPA-02)
  - Verified by T-26

**US-04: Activate OPA via environment variable**
- **As a** platform engineer enabling OPA in production
- **I want** `OPA_ENABLED=true` to be the only deploy change
- **So that** OPA can be toggled without code changes
- **Given:** OPA client installed, `Settings` has `OPA_ENABLED: bool = False`
- **When:** `.env` sets `OPA_ENABLED=true` and `OPA_URL=http://opa-sidecar:8181`
- **Then:**
  - `get_opa_client()` constructs `OPAClient(opa_url="http://opa-sidecar:8181", ...)`
  - Every `query()` call posts to the OPA sidecar
  - Verified by CC-17, INV-OPA-07

**US-05: Generated project stays auditable**
- **As a** code reviewer
- **I want** every generated function to be short
- **So that** I can read and approve it in one sitting
- **Given:** Tool just emitted `opa_client.py`, `opa_models.py`, `opa_middleware.py`, `routes/opa.py`
- **When:** I AST-walk `app/authz/` and `app/api/routes/opa.py` for functions
- **Then:**
  - No `FunctionDef`/`AsyncFunctionDef` has `end_lineno - lineno + 1 > 50` (QS-04)
  - Verified by T-30

### 9.2 OPA client and circuit breaker (US-06 .. US-10)

**US-06: Query OPA for an authorization decision**
- **As a** developer enforcing fine-grained access control
- **I want** `await opa_client.query(OPAInput(...))` to return a typed decision
- **So that** I can branch on `decision.allow` in route handlers
- **Given:** OPA sidecar running at `OPA_URL`
- **When:** `await client.query(OPAInput(subject="alice", action="GET", resource="/items"))`
- **Then:**
  - Returns `OPADecision(allow=True/False, reason=..., policy_path="authz/allow")`
  - Verified by CC-05, CC-06

**US-07: Circuit breaker opens after threshold failures**
- **As an** operator whose OPA sidecar crashes
- **I want** the circuit breaker to stop sending requests after N failures
- **So that** the FastAPI application does not accumulate `httpx` timeouts
- **Given:** OPA sidecar is down; `_CircuitBreaker.threshold = 3`
- **When:** Three consecutive `query()` calls fail
- **Then:**
  - `_cb._failures` reaches threshold; `_cb._opened_at` is set
  - Fourth call: `_cb.is_open()` returns `True`; returns `OPADecision(allow=fail_open, reason="circuit_open", ...)`
  - No HTTP call is made
  - Verified by CC-08, CC-25, INV-OPA-09

**US-08: Fail-open allows all requests when OPA is down**
- **As an** availability-first operator
- **I want** `OPA_FAIL_OPEN=true` to allow requests when OPA is unreachable
- **So that** a sidecar restart does not cause a complete service outage
- **Given:** `OPAClient(fail_open=True)` and circuit is open
- **When:** `query()` is called
- **Then:**
  - Returns `OPADecision(allow=True, reason="circuit_open", ...)`
  - Verified by CC-24, INV-OPA-09

**US-09: Fail-closed denies all requests when OPA is down**
- **As a** security-first operator
- **I want** `OPA_FAIL_OPEN=false` to deny requests when OPA is unreachable
- **So that** an OPA outage does not silently open the authorization gate
- **Given:** `OPAClient(fail_open=False)` and circuit is open
- **When:** `query()` is called
- **Then:**
  - Returns `OPADecision(allow=False, reason="circuit_open", ...)`
  - Verified by CC-24, QS-07

**US-10: httpx boots without installation**
- **As a** developer bootstrapping a new project
- **I want** the application to boot without `httpx` installed
- **So that** I can install dependencies incrementally
- **Given:** `httpx` is not in the virtualenv
- **When:** Module `opa_client` is imported
- **Then:**
  - No `ImportError` at import time (lazy import inside methods)
  - Verified by INV-OPA-04, T-12

### 9.3 OPAMiddleware (US-11 .. US-15)

**US-11: Middleware blocks unauthorized requests with HTTP 403**
- **As a** security reviewer
- **I want** unauthorized requests to return 403, not 200 or 500
- **So that** clients receive a standard RFC 7231 Forbidden response
- **Given:** `OPA_ENABLED=true` and a deny policy is active
- **When:** A request reaches `OPAMiddleware.dispatch`
- **Then:**
  - `decision.allow` is `False`
  - Response is `HTTP 403` with `{"detail": "Forbidden by policy"}`
  - Verified by T-14, INV-OPA-08

**US-12: Login and health paths bypass OPA**
- **As a** developer relying on `/api/v1/login` to authenticate users
- **I want** login to not require OPA authorization
- **So that** users can acquire tokens without a circular dependency
- **Given:** `_SKIP_PREFIXES` includes `/api/v1/login`, `/healthz`, `/docs`, `/redoc`, `/openapi.json`
- **When:** A request hits any skip prefix
- **Then:**
  - Middleware calls `call_next(request)` without touching `get_opa_client()`
  - Verified by source inspection of `_SKIP_PREFIXES`

**US-13: Subject derived from X-User-Id header**
- **As a** JWT-authenticated API where the subject is known to be trusted
- **I want** the middleware to use `X-User-Id` for the OPA subject
- **So that** downstream services can inject their identity without JWT decode overhead
- **Given:** Request carries `X-User-Id: alice@example.com`
- **When:** `OPAMiddleware.dispatch` calls `get_opa_client()` and builds `OPAInput`
- **Then:**
  - `subject = "alice@example.com"` passed to OPA
  - Falls back to `"anonymous"` when header is absent
  - Verified by source code of `dispatch`

**US-14: Query parameters are included in OPA context**
- **As a** policy author who needs query parameters to make decisions
- **I want** `context` to include query string data
- **So that** Rego rules can inspect `input.context.query`
- **Given:** Request has query string `?tenant=acme`
- **When:** `OPAMiddleware.dispatch` builds `OPAInput`
- **Then:**
  - `context={"query": "tenant=acme"}` passed to OPA
  - Verified by source code of `dispatch`

**US-15: 503 raised when OPA unavailable and fail_open=false**
- **As a** resilient API client
- **I want** a 503 when OPA is down and fail-closed is configured
- **So that** I can distinguish authorization failure from OPA unavailability
- **Given:** `POST /authz/opa/check` and `reason == "opa_unavailable"` and `fail_open=False`
- **When:** `check_policy()` route handler receives the `OPADecision`
- **Then:**
  - Raises `HTTPException(status_code=503, detail="OPA sidecar unavailable")`
  - Verified by CC-15 route handler source

### 9.4 Rego policies (US-16 .. US-20)

**US-16: Load authz.rego + data.json into OPA sidecar**
- **As an** operator activating OPA
- **I want** a ready-to-use policy bundle
- **So that** I can start the sidecar with zero policy authoring
- **Given:** `opa run --server authz.rego data.json`
- **When:** Policies are loaded
- **Then:**
  - `authz.rego` uses `package authz` and `import rego.v1`
  - `data.json` defines a `roles` map with three example entries
  - `default allow := false` denies by default
  - Verified by CC-12, CC-13, T-15, T-16

**US-17: Run OPA unit tests**
- **As a** policy author
- **I want** `authz_test.rego` to provide passing unit tests
- **So that** I can verify my policy changes with `opa test`
- **Given:** `opa test authz.rego data.json authz_test.rego -v`
- **When:** Tests run
- **Then:**
  - `test_superuser_allowed` passes (superuser is always allowed)
  - `test_anonymous_get_denied` passes (anonymous GET is denied)
  - `test_reader_get_allowed` passes (authenticated GET is allowed)
  - `test_reader_post_denied` passes (non-writer POST is denied)
  - Verified by `authz_test.rego` content (CC-12)

**US-18: Superuser bypasses all rules**
- **As a** policy author
- **I want** `data.roles[subject] == "superuser"` to permit all actions unconditionally
- **So that** admin accounts are never accidentally blocked
- **Given:** `authz.rego` has an unconditional superuser permit rule
- **When:** OPA evaluates a superuser request
- **Then:**
  - `allow` is `true` regardless of `action` or `resource`
  - Verified by policy source and `test_superuser_allowed`

**US-19: Writers can mutate resources**
- **As a** policy author implementing RBAC on top of OPA
- **I want** `data.roles[subject] == "writer"` to allow `POST`/`PUT`/`DELETE`/`PATCH`
- **So that** write-role users can mutate data
- **Given:** `authz.rego` has a write-role permit rule
- **When:** OPA evaluates a POST request from a writer
- **Then:**
  - `allow` is `true`
  - Verified by `test_reader_post_denied` (non-writer denied) and policy source

**US-20: Readers can only read**
- **As a** policy author enforcing read-only access for basic users
- **I want** `data.roles[subject] == "reader"` to permit only `GET`
- **So that** readers cannot mutate data
- **Given:** `authz.rego` GET-only rule for non-anonymous authenticated users
- **When:** Reader makes a POST request
- **Then:**
  - `allow` is `false` (no write rule matches `"reader"` role)
  - Verified by `test_reader_post_denied`

### 9.5 Config, routes, and operator experience (US-21 .. US-25)

**US-21: Five OPA settings are pydantic-settings compatible**
- **As a** pydantic-settings user
- **I want** all five `OPA_*` fields to be environment-bindable Settings fields
- **So that** I can configure OPA with environment variables in any deployment
- **Given:** `_patch_config` inserts fields before `settings = Settings()`
- **When:** The application boots
- **Then:**
  - All five fields at 4-space indent inside `class Settings` body
  - `settings.OPA_URL` reads from `OPA_URL` env var
  - Verified by T-20, INV-OPA-07

**US-22: Router is registered without duplicate entries**
- **As a** CI job running the tool multiple times
- **I want** `_patch_routes_init` to be idempotent
- **So that** the router is not included twice
- **Given:** `routes/__init__.py` already contains `opa_router` import and include
- **When:** `_patch_routes_init` runs again
- **Then:**
  - Both import line and include_router line appear exactly once
  - Verified by T-21 (import + include both present) and idempotency guard

**US-23: httpx added to requirements.txt once**
- **As a** requirements file consumer
- **I want** `httpx>=0.28.0` to appear once in `requirements.txt`
- **So that** pip install is repeatable
- **Given:** `_patch_requirements` checks `"httpx" in content`
- **When:** Tool runs; requirements already has `httpx`
- **Then:**
  - No duplicate line is added
  - Verified by T-22

**US-24: next_steps guide operator through activation**
- **As an** operator receiving the tool output
- **I want** `next_steps` to tell me exactly what to do after install
- **So that** I can activate OPA without reading source code
- **Given:** Tool returns `status="success"`
- **When:** Operator reads `result.next_steps`
- **Then:**
  - Includes OPA sidecar start command (`docker run ... openpolicyagent/opa`)
  - Includes `Set OPA_URL=http://localhost:8181 in your .env`
  - Includes `Set OPA_ENABLED=true` instruction
  - Verified by T-28

**US-25: Prerequisites prevent partial installs**
- **As an** engineer who forgets to generate the base project first
- **I want** a clear error if prerequisites are missing
- **So that** I am not left with a half-configured project
- **Given:** `project_dir` lacks `app/models/base.py` or `app/core/config.py`
- **When:** `add_opa_integration(...)` runs
- **Then:**
  - Returns `status="error"` with prerequisite list
  - `notes` recommend `fastapi_generate_project` as the fix
  - Verified by prerequisite guard in `add_opa_integration`

---

## 10. Test Plan

### 10.1 Test inventory

| ID | Name | CC | Description |
|----|------|----|-------------|
| T-01 | `test_success_status` | — | Tool returns `status="success"` on fresh project |
| T-02 | `test_files_created_all_exist` | CC-05 | Every path in `files_created` exists on disk |
| T-03 | `test_files_modified_all_exist` | — | Every path in `files_modified` exists on disk |
| T-04 | `test_authz_init_created` | CC-01 | `app/authz/__init__.py` has `OPAClient` and `OPAMiddleware` |
| T-05 | `test_opa_models_file_created` | CC-02 | `opa_models.py` has `OPAInput` and `OPADecision` |
| T-06 | `test_opa_input_has_required_fields` | CC-03 | All four `OPAInput` fields present |
| T-07 | `test_opa_decision_has_allow_field` | CC-04 | `OPADecision` has `allow` bool field |
| T-08 | `test_opa_client_file_created` | CC-05 | `opa_client.py` has `class OPAClient` |
| T-09 | `test_opa_client_has_query_method` | CC-06 | `async def query` present |
| T-10 | `test_opa_client_has_health_method` | CC-07 | `async def health` present |
| T-11 | `test_opa_client_circuit_breaker` | CC-08 | Circuit breaker logic present in `opa_client.py` |
| T-12 | `test_opa_client_lazy_httpx` | CC-09 | `httpx` NOT imported at module top level |
| T-13 | `test_opa_middleware_file_created` | CC-10 | `opa_middleware.py` has `class OPAMiddleware` |
| T-14 | `test_opa_middleware_returns_403` | CC-11 | `403` or `HTTP_403_FORBIDDEN` present in middleware |
| T-15 | `test_rego_policies_created` | CC-12 | Three policy files exist in `app/authz/policies/` |
| T-16 | `test_authz_rego_default_deny` | CC-13 | `default allow` present in `authz.rego` |
| T-17 | `test_opa_routes_file_created` | CC-14 | `routes/opa.py` exists with `/authz/opa` prefix |
| T-18 | `test_opa_routes_check_endpoint` | CC-15 | `/check` and `check_policy` in routes file |
| T-19 | `test_opa_routes_health_endpoint` | CC-16 | `/health` in routes file |
| T-20 | `test_config_fields_patched` | CC-17 | All 5 `OPA_*` fields at 4-space indent in config |
| T-21 | `test_routes_init_patched` | CC-18 | Import + include_router in `routes/__init__.py` |
| T-22 | `test_requirements_patched` | CC-19 | `httpx` in `requirements.txt` |
| T-23 | `test_all_py_files_parse` | CC-20 | `ast.parse` passes on all project `.py` files |
| T-24 | `test_idempotent_returns_no_op` | CC-21 | Second run returns `no_op` with empty lists |
| T-25 | `test_idempotent_project_still_parses` | — | Two runs; project still fully parseable |
| T-26 | `test_dry_run_writes_nothing` | — | `dry_run=True`; filesystem unchanged |
| T-27 | `test_execution_time_recorded` | — | `execution_time_ms > 0` |
| T-28 | `test_next_steps_present` | — | `next_steps` non-empty; contains `opa` or `openpolicyagent` |
| T-29 | `test_minimum_files_created` | CC-05 | `len(files_created) >= 5` |
| T-30 | `test_no_function_over_50_loc` | CC-22 | No generated function > 50 LOC |
| T-31 | `test_get_opa_client_dependency` | CC-23 | `def get_opa_client` in `opa_client.py` |
| T-32 | `test_no_dead_imports_ruff` | QS-08 | `ruff check --select F401` passes on `app/authz/` |
| T-33 | `test_fail_open_configurable` | CC-24 | `fail_open` in `opa_client.py` |
| T-34 | `test_circuit_breaker_in_client` | CC-25 | `is_open`, `record_failure`, `record_success` all present |
| T-35 | `test_pydantic_models_use_config_dict` | QS-11 | `ConfigDict` in `opa_models.py` |

### 10.2 Running tests

```bash
# From skill root
PYTHONPATH=. pytest adapt/extend/auth_access/test_add_opa_integration.py -v

# Standalone (no pytest)
PYTHONPATH=. python3 adapt/extend/auth_access/test_add_opa_integration.py
```

### 10.3 Minimum pass criteria

All 35 tests must pass with 0 skipped. The circuit breaker, lazy httpx, and idempotency tests are the most critical for production safety.

---

## 11. Error Handling

| Scenario | Tool Response | User Action |
|----------|---------------|-------------|
| `project_dir` does not exist or is not a directory | `status="error"`, `error` from `validate_project_dir` | Pass a valid absolute path |
| Prerequisites missing (`app/models/base.py`, `app/core/config.py`, etc.) | `status="error"` with list of missing prerequisites | Run `fastapi_generate_project` first |
| Generated `.py` file has a `SyntaxError` (defensive) | `status="error"`, `error="Generated file has syntax error: <path>: <exc>"` | File a bug report |
| `app/authz/opa_client.py` already contains `class OPAClient` | `status="no_op"`, `notes=["OPA integration already present — skipped."]` | No action needed |
| `dry_run=True` | `status="success"`, informational `notes`, no files written | Re-run without `dry_run=True` to apply |
| `httpx` not installed at runtime | `_post_opa()` catches `ImportError`; circuit records failure | `pip install httpx>=0.28.0` |
| OPA sidecar is down (network error) | `_cb.record_failure()` increments; after threshold circuit opens; returns `fail_open` decision | Check OPA sidecar; inspect `OPA_FAIL_OPEN` setting |
| OPA returns non-2xx | `resp.raise_for_status()` raises; caught by except in `query()`; circuit records failure | Check Rego policy syntax; verify `OPA_POLICY_PATH` |

---

## 12. Integration Notes

### 12.1 OPA sidecar setup

The tool generates the **client side only**. The OPA sidecar must be started separately:

```bash
# Development
docker run -p 8181:8181 \
    -v $(pwd)/app/authz/policies:/policies \
    openpolicyagent/opa run --server /policies/authz.rego /policies/data.json

# Production (Kubernetes sidecar)
# Add to app pod spec as a sidecar container
# Mount policy ConfigMap at /policies/
```

### 12.2 httpx lazy import

`httpx` is imported inside `_post_opa()` and `health()` async method bodies only. This means:

- The application boots cleanly without `httpx` installed
- If `httpx` is missing at call time, the method raises `ImportError`, the circuit records a failure, and the `fail_open` decision is returned — no crash

### 12.3 Circuit breaker state

The `_CircuitBreaker` is an instance variable on each `OPAClient` instance. `get_opa_client()` creates a **new instance per call** (not cached). For production use, the circuit breaker state should be shared across requests by caching the client instance at application startup on `app.state.opa_client`.

### 12.4 Relationship to TOOL-071 (Cedar)

See TOOL-071 section 12.4 for the Cedar/OPA comparison table. OPA is preferable when a shared, language-agnostic policy server is required. Cedar is preferable when in-process evaluation without a sidecar is the goal.

### 12.5 `_write_authz_init` idempotency

`_write_authz_init` checks `dest.exists()` before writing. This prevents overwriting a Cedar `__init__.py` when both TOOL-071 and TOOL-072 are applied to the same project. If Cedar is already installed, the OPA init is skipped, and the Cedar re-exports are preserved.

---

## 13. Assumptions

1. OPA runs as a sidecar; this tool generates only the FastAPI client.
2. `OPA_ENABLED` defaults to `False` — OPA integration is opt-in.
3. The subject extraction uses `X-User-Id` header as a pragmatic default; production teams should wire their JWT library result.
4. `get_opa_client()` creates a new `OPAClient` instance on every FastAPI DI resolution. Teams with high-throughput workloads should cache the client on `app.state`.
5. The `_CircuitBreaker` is per-`OPAClient` instance; per-process shared state requires caching the client.
6. Rego policies are loaded by the OPA sidecar, not by the FastAPI application.

---

## 14. Dependencies

| Package | Version | Role |
|---------|---------|------|
| `httpx` | `>=0.28.0` | Async HTTP client for OPA sidecar calls (lazy import) |
| `fastapi` | existing | APIRouter, HTTPException, Depends, status |
| `starlette` | existing | BaseHTTPMiddleware, Request, JSONResponse |
| `pydantic` | `v2+` | `BaseModel`, `Field`, `ConfigDict` for request/response models |

No new runtime dependencies beyond `httpx`. All other imports are Python stdlib.

---

## 15. Known Limitations

1. **Per-call client construction**: `get_opa_client()` builds a new `OPAClient` on each FastAPI DI resolution. Circuit breaker state is not shared across requests in this default configuration.
2. **No bundle loading**: The tool generates example Rego files but does not configure OPA bundle polling or push. Teams must load policies into OPA separately.
3. **Subject extraction is a starter**: `X-User-Id` header is a simple default; real deployments typically use JWT sub from a decoded token on `request.state.user`.
4. **`rego.v1` import requires OPA >= 0.59**: `authz.rego` uses `import rego.v1`. Teams on older OPA versions must remove this import.
5. **`data.json` is static**: The role data is a static file. Production deployments should use OPA's data API or bundle mechanism to load dynamic role data.

---

## 16. File Layout (Post-install)

```
project/
├── app/
│   ├── authz/
│   │   ├── __init__.py              # Re-exports: OPAClient, OPAMiddleware, OPADecision, OPAInput
│   │   ├── opa_models.py            # OPAInput, OPADecision Pydantic v2 models
│   │   ├── opa_client.py            # OPAClient, _CircuitBreaker, get_opa_client()
│   │   ├── opa_middleware.py        # OPAMiddleware (Starlette BaseHTTPMiddleware)
│   │   └── policies/
│   │       ├── authz.rego           # Example Rego policy (default deny, superuser, writer)
│   │       ├── data.json            # Static role data for example policy
│   │       └── authz_test.rego      # OPA unit tests (opa test ...)
│   ├── api/
│   │   └── routes/
│   │       └── opa.py               # POST /authz/opa/check, GET /authz/opa/health
│   └── core/
│       └── config.py               # + OPA_URL, OPA_ENABLED, OPA_POLICY_PATH, OPA_TIMEOUT_MS, OPA_FAIL_OPEN
├── app/routes/
│   └── __init__.py                  # + opa_router import + include_router
└── requirements.txt                 # + httpx>=0.28.0
```
