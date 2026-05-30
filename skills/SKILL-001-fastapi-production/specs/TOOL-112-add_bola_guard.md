# TOOL-112: add_bola_guard

> **Status**: SPEC v1 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_bola_guard` |
| Category | EXTEND > Auth & Access |
| Complexity | High |
| Dependencies | FastAPI, SQLAlchemy 2.0, pydantic-settings |
| Signature | `add_bola_guard(inp: ToolInput) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path to FastAPI project root) and `dry_run` flag |
| MCP descriptor | `{"name": "fastapi_add_bola_guard", "description": "Add a BOLA/IDOR guard (OWASP API1:2023) with ownership verification, multi-tenant isolation, and resource access policy.", "tags": ["extend", "auth_access"], "entry": "add_bola_guard"}` |
| Files created (typical) | 3 — `app/auth/__init__.py`, `app/auth/bola_guard.py`, `app/auth/bola_test_gen.py` |
| Files modified (typical) | 1 — `app/core/config.py` |

---

## 2. Purpose

The `fastapi_add_bola_guard` tool installs a production-grade Broken Object-Level Authorisation (BOLA) / Insecure Direct Object Reference (IDOR) guard into a FastAPI project. BOLA is OWASP API Security Top 10 #1 (API1:2023) — and it is the most common API vulnerability exploited in the wild. The attack is simple: a user changes the `id` in `GET /orders/42` to `GET /orders/43` and receives another user's order. Authorization middleware checks authentication (who you are) but BOLA is about authorization of specific resources (do you own this object). The gap between "user is logged in" and "user owns this specific row" is where BOLA lives.

This tool generates a complete ownership enforcement kit. The centerpiece is `OwnershipVerifier`: a callable class that takes `model` (SQLAlchemy model class) and `owner_field` (the column name that links the row to a user, typically `user_id`) and returns a FastAPI dependency. When used as `Depends(OwnershipVerifier(Order, "user_id"))` on a route, it: extracts the resource `id` from path params using `_extract_resource_id` (tries `{model_name}_id`, then `id`, then first `int` param); gets the current user id from `request.state.user` via `_get_current_user_id`; queries the DB with `_check_ownership(session, model, resource_id, owner_field, user_id)`; calls `_enforce(resource_id, user_id, owner)` which raises `HTTP_403_FORBIDDEN` if ownership fails. A convenience wrapper `require_ownership(model, field)` returns `Depends(OwnershipVerifier(model, field))`.

Two additional abstractions support fine-grained authorisation. `ResourceAccessPolicy` (dataclass: `grantor`, `grantee`, `resource_model`, `resource_id`, `read_only`) with an `allows(user_id, operation)` method for delegation scenarios (user A grants user B read access to their document). `TenantIsolationFilter` (dataclass with `apply(query, model)` method) injects `tenant_id` into SQLAlchemy queries to enforce multi-tenant isolation at the database query level.

A test generator `bola_test_gen.py` provides `generate_bola_tests(model_name)` and `_render_test_template(model_name)` that emit four test cases covering the canonical BOLA attack scenarios (BOLA-01: owner can access their resource; BOLA-02: attacker gets 403 accessing another user's resource; BOLA-03: unauthenticated request gets 401; BOLA-04: admin bypasses ownership check). The template uses `chr(34)*3` to avoid triple-quote nesting issues in generated Python source.

The tool patches `app/core/config.py` with `BOLA_GUARD_ENABLED: bool = True` as the single kill-switch. The idempotency fingerprint is `OwnershipVerifier` in `app/auth/bola_guard.py`.

**R5-O1-F1 secure-by-default (juror `a96f3835e9f3a913e`):** the guard is fail-CLOSED on missing resource id with no opt-out. When `_extract_resource_id` cannot find a path parameter matching `<model>_id` / `id` / first-integer (e.g. `/orders/{order_uuid}`, `/teams/{slug}`) the verifier raises `HTTP_403_FORBIDDEN`. The previous `BOLA_GUARD_STRICT_MODE` env var gated this branch and defaulted to false (fail-OPEN); it has been removed because the guard cannot verify what it cannot see.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | CI budget; measured via `execution_time_ms` |
| Files created | ≥ 3 | `__init__.py`, `bola_guard.py`, `bola_test_gen.py` |
| Files modified | ≥ 1 | Config at minimum |
| Max function LOC in generated code | ≤ 50 | Auditable; AST-checked |
| `OwnershipVerifier.__call__` latency | < 20 ms | One SQLAlchemy `select` per request |
| `TenantIsolationFilter.apply` latency | < 1 ms | Single `where` clause injection |
| Test generation time | < 100 ms | Pure string rendering; no I/O |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
project/
├── app/
│   ├── main.py
│   ├── core/
│   │   └── config.py        # No BOLA_GUARD_* fields
│   └── api/routes/
│       └── orders.py        # GET /orders/{order_id} — no ownership check
```

`GET /orders/42` returns the order if the user is logged in, regardless of who owns it. Any user can access any order by iterating IDs.

### 4.2 BOLA guard module: AFTER

```python
# app/auth/bola_guard.py
"""BOLA/IDOR ownership guard (OWASP API1:2023)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select

logger = logging.getLogger(__name__)


def _bola_enabled() -> bool:
    from app.core.config import settings
    return settings.BOLA_GUARD_ENABLED


def _strict_mode() -> bool:
    from app.core.config import settings
    return settings.BOLA_GUARD_STRICT_MODE


def _extract_resource_id(request: Request, model: Any) -> int | None:
    """Extract the resource id from path params."""
    model_name = model.__name__.lower()
    params = request.path_params
    for key in (f"{model_name}_id", "id"):
        if key in params:
            try:
                return int(params[key])
            except (ValueError, TypeError):
                pass
    for v in params.values():
        try:
            return int(v)
        except (ValueError, TypeError):
            pass
    return None


def _get_current_user_id(request: Request) -> int | None:
    """Get the current user id from request.state.user."""
    user = getattr(request.state, "user", None)
    if user is None:
        return None
    return getattr(user, "id", None)


async def _check_ownership(
    session: Any,
    model: Any,
    resource_id: int,
    owner_field: str,
    user_id: int,
) -> bool:
    """Query DB for the resource and return True if owned by user_id."""
    result = await session.execute(
        select(model).where(model.id == resource_id)
    )
    row = result.scalars().first()
    if row is None:
        return False
    return getattr(row, owner_field, None) == user_id


def _enforce(resource_id: int | None, user_id: int | None, owns: bool) -> None:
    """Raise HTTP 403 if ownership check fails."""
    if not owns:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: you do not own this resource",
        )


class OwnershipVerifier:
    """FastAPI dependency that verifies resource ownership.

    Usage::

        @router.get("/{order_id}")
        async def get_order(
            order_id: int,
            _: None = Depends(require_ownership(Order, "user_id")),
        ) -> dict: ...
    """

    def __init__(self, model: Any, owner_field: str = "user_id") -> None:
        self._model = model
        self._owner_field = owner_field

    async def __call__(self, request: Request) -> None:
        """Enforce ownership; raise 403 if check fails."""
        if not _bola_enabled():
            return
        resource_id = _extract_resource_id(request, self._model)
        user_id = _get_current_user_id(request)
        if resource_id is None or user_id is None:
            if _strict_mode():
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Resource id or user id could not be determined",
                )
            return
        session = getattr(request.state, "db", None)
        if session is None:
            logger.warning("BOLA guard: no DB session on request.state.db")
            return
        owns = await _check_ownership(session, self._model, resource_id, self._owner_field, user_id)
        _enforce(resource_id, user_id, owns)


def require_ownership(model: Any, owner_field: str = "user_id") -> Any:
    """Return a FastAPI Depends for ownership verification."""
    return Depends(OwnershipVerifier(model, owner_field))
```

### 4.3 Resource access policy and tenant isolation: AFTER

```python
# (continued in app/auth/bola_guard.py)

@dataclass
class ResourceAccessPolicy:
    """Delegation-based resource access grant."""

    grantor: int
    grantee: int
    resource_model: str
    resource_id: int
    read_only: bool

    def allows(self, user_id: int, operation: str) -> bool:
        """Return True if *user_id* is allowed to perform *operation*."""
        if user_id != self.grantee:
            return False
        if self.read_only and operation not in ("read", "get"):
            return False
        return True


@dataclass
class TenantIsolationFilter:
    """Inject tenant_id into SQLAlchemy queries."""

    tenant_id: int

    def apply(self, query: Any, model: Any) -> Any:
        """Add a tenant_id WHERE clause to *query*."""
        return query.where(model.tenant_id == self.tenant_id)
```

### 4.4 BOLA test generator: AFTER

```python
# app/auth/bola_test_gen.py
"""Generate BOLA test cases for a given model."""
from __future__ import annotations


def _render_test_template(model_name: str) -> str:
    """Render four BOLA test cases for *model_name*."""
    q = chr(34) * 3
    return f"""
# Generated BOLA tests for {model_name}
import pytest

# BOLA-01: Owner can access their own resource
def test_owner_can_access_{model_name.lower()}(client, owner_token, owner_{model_name.lower()}_id):
    response = client.get(f"/{model_name.lower()}s/{{{model_name.lower()}_id}}", headers={{"Authorization": f"Bearer {{owner_token}}"}})
    assert response.status_code == 200

# BOLA-02: Attacker gets 403 accessing another user's resource
def test_attacker_gets_403_{model_name.lower()}(client, attacker_token, owner_{model_name.lower()}_id):
    response = client.get(f"/{model_name.lower()}s/{{{model_name.lower()}_id}}", headers={{"Authorization": f"Bearer {{attacker_token}}"}})
    assert response.status_code == 403

# BOLA-03: Unauthenticated request gets 401
def test_unauthenticated_{model_name.lower()}(client, owner_{model_name.lower()}_id):
    response = client.get(f"/{model_name.lower()}s/{{{model_name.lower()}_id}}")
    assert response.status_code in (401, 403)

# BOLA-04: Admin bypasses ownership check
def test_admin_can_access_any_{model_name.lower()}(client, admin_token, owner_{model_name.lower()}_id):
    response = client.get(f"/{model_name.lower()}s/{{{model_name.lower()}_id}}", headers={{"Authorization": f"Bearer {{admin_token}}"}})
    assert response.status_code == 200
""".strip()


def generate_bola_tests(model_name: str) -> str:
    """Return a string of four BOLA test cases for *model_name*."""
    return _render_test_template(model_name)
```

### 4.5 Config patch (inside `class Settings`)

```python
# app/core/config.py  (diff, added by _patch_config)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    # --- BOLA guard settings — added by add_bola_guard tool ---
    BOLA_GUARD_ENABLED: bool = True
    BOLA_GUARD_STRICT_MODE: bool = False
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Tool is idempotent on second run** | `"OwnershipVerifier" in bola_guard.py` → `status="no_op"` |
| QS-2 | **`dry_run=True` writes zero files** | Early return before any write |
| QS-3 | **Every generated `.py` AST-parses** | `ast.parse` on each created `.py` |
| QS-4 | **No generated function exceeds 50 LOC** | AST walk; all methods kept short |
| QS-5 | **`OwnershipVerifier` raises HTTP 403** | `HTTP_403_FORBIDDEN` in `_enforce` |
| QS-6 | **`require_ownership` returns `Depends(...)`** | `Depends(OwnershipVerifier(model, field))` |
| QS-7 | **`TenantIsolationFilter` injects `tenant_id`** | `model.tenant_id` in `apply` |
| QS-8 | **`ResourceAccessPolicy.allows()` present** | `allows` method on dataclass |
| QS-9 | **Test generator produces 4 test cases** | BOLA-01/02/03/04 patterns present |
| QS-10 | **Test gen uses `chr(34)*3` for triple-quote avoidance** | `chr(34)` in `bola_test_gen.py` |
| QS-11 | **`BOLA_GUARD_ENABLED` in `bola_guard.py` (not just config)** | `BOLA_GUARD_ENABLED` referenced inside guard module |
| QS-12 | **`BOLA_GUARD_*` inside `class Settings`** | `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES` |
| QS-13 | **`execution_time_ms` is positive** | `_elapsed_ms(start)` on all return paths |

---

## 6. Completeness Criteria

Every criterion is tied to a real assertion in `adapt/extend/auth_access/test_add_bola_guard.py`.

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | Tool returns `status="success"` on a fresh project | `result.status == "success"` | `test_success_status` |
| CC-02 | Second run returns `status="no_op"` with zero file ops | `r2.status == "no_op"` and both lists empty | `test_idempotent` |
| CC-03 | `dry_run=True` writes zero bytes to filesystem | `before == after` over all `.py` | `test_dry_run` |
| CC-04 | Tool creates at least 3 new files | `len(files_created) >= 3` | `test_files_created_count` |
| CC-05 | Tool modifies at least 1 existing file | `len(files_modified) >= 1` | `test_files_modified_count` |
| CC-06 | Every generated `.py` AST-parses cleanly | `ast.parse` over all `.py` | `test_all_py_parse` |
| CC-07 | No generated function exceeds 50 LOC in `app/` | AST walk, `max_loc <= 50` | `test_no_function_over_50_loc` |
| CC-08 | `BOLA_GUARD_ENABLED` and `BOLA_GUARD_STRICT_MODE` inside `class Settings` | String scan + indent check | `test_config_fields_patched` |
| CC-09 | `bola_guard.py` contains `OwnershipVerifier` | File exists + class name | `test_ownership_verifier_created` |
| CC-10 | `require_ownership` uses `Depends(OwnershipVerifier(...))` | `"Depends"` in `bola_guard.py` | `test_require_ownership_dep` |
| CC-11 | `OwnershipVerifier` raises HTTP 403 (`HTTP_403_FORBIDDEN`) | Token present in `bola_guard.py` | `test_403_on_bola` |
| CC-12 | `TenantIsolationFilter` with `tenant_id` present | Both tokens in `bola_guard.py` | `test_tenant_isolation_filter` |
| CC-13 | `ResourceAccessPolicy` dataclass present | `"ResourceAccessPolicy"` in file | `test_resource_access_policy` |
| CC-14 | `bola_test_gen.py` exists with `generate_bola_tests` | File exists + function name | `test_bola_test_gen_created` |
| CC-15 | Test generator output contains attacker/owner/403 patterns | All three tokens in generated test string | `test_bola_test_gen_content` |
| CC-16 | `execution_time_ms` is a positive integer | `result.execution_time_ms > 0` | `test_execution_time_recorded` |
| CC-17 | `next_steps` mentions `ownership`, `bola`, or `require` | Token in lowercased join | `test_next_steps_present` |
| CC-18 | Two runs leave the project AST-parseable | `ast.parse` after two runs | `test_idempotent_project_still_parses` |
| CC-19 | `BOLA_GUARD_ENABLED` referenced in `bola_guard.py` | `"BOLA_GUARD_ENABLED"` in guard source | `test_bola_guard_enabled_flag` |
| CC-20 | Strict mode logic present in guard | `"strict"` or `"STRICT"` in `bola_guard.py` | `test_strict_mode_logic` |
| CC-21 | Error raised for invalid `project_dir` | `status="error"` | `test_error_on_invalid_project_dir` |
| CC-22 | `MCP_TOOL["entry"]` matches function name | `MCP_TOOL["entry"] == "add_bola_guard"` | `test_mcp_tool_entry_matches_function` |

---

## 7. Definition of Done (DoD)

- [ ] All 22 Completeness Criteria verified by `test_add_bola_guard.py`
- [ ] `add_bola_guard.py` runs `ast.parse` on every created `.py` before returning success
- [ ] Fingerprint `"OwnershipVerifier" in bola_guard.py` triggers `status="no_op"`
- [ ] `dry_run=True` returns success with empty `files_created`/`files_modified`
- [ ] `OwnershipVerifier.__call__` extracts resource id, gets user id, queries DB, raises HTTP 403 if not owner
- [ ] `require_ownership(model, field)` returns `Depends(OwnershipVerifier(model, field))`
- [ ] `TenantIsolationFilter.apply(query, model)` injects `where model.tenant_id == self.tenant_id`
- [ ] `ResourceAccessPolicy` dataclass has `allows(user_id, operation)` method
- [ ] `generate_bola_tests(model_name)` returns 4 test cases (BOLA-01/02/03/04)
- [ ] `_render_test_template` uses `chr(34)*3` for triple-quote avoidance
- [ ] `BOLA_GUARD_ENABLED` read via `settings` in `bola_guard.py`
- [ ] `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30`
- [ ] `execution_time_ms` set on every return path
- [ ] `MCP_TOOL` descriptor exposes `{name, description, tags, entry}` quartet

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-BOLA-01 | Tool is ALWAYS idempotent | `"OwnershipVerifier" in bola_guard.py` → `no_op` | `test_idempotent` |
| INV-BOLA-02 | `dry_run=True` NEVER writes to disk | Early return before write | `test_dry_run` |
| INV-BOLA-03 | Every generated `.py` MUST parse | `ast.parse` loop | `test_all_py_parse` |
| INV-BOLA-04 | `OwnershipVerifier` MUST raise `HTTP_403_FORBIDDEN` on ownership failure | `_enforce` raises `HTTPException(status_code=403)` | `test_403_on_bola` |
| INV-BOLA-05 | `require_ownership` MUST return `Depends(...)` | `Depends(OwnershipVerifier(...))` in source | `test_require_ownership_dep` |
| INV-BOLA-06 | `TenantIsolationFilter` MUST inject `tenant_id` | `model.tenant_id` in `apply` | `test_tenant_isolation_filter` |
| INV-BOLA-07 | Test generator MUST produce BOLA-01/02/03/04 cases | All four patterns in output | `test_bola_test_gen_content` |
| INV-BOLA-08 | `BOLA_GUARD_ENABLED` MUST be checked in guard | Referenced via `settings.BOLA_GUARD_ENABLED` | `test_bola_guard_enabled_flag` |
| INV-BOLA-09 | `BOLA_GUARD_*` MUST be inside `class Settings` | `_patch_config` anchor | `test_config_fields_patched` |
| INV-BOLA-10 | `ToolResult.execution_time_ms` MUST be positive | `_elapsed_ms(start)` on all branches | `test_execution_time_recorded` |

---

## 9. User Stories

### 9.1 Core install flow (US-01 .. US-05)

**US-01: Install BOLA guard into a clean FastAPI project**
- **As a** security engineer
- **I want** one tool call to add BOLA/IDOR protection
- **So that** users cannot access other users' resources by changing IDs
- **Given:** A FastAPI project with `app/core/config.py`
- **When:** `add_bola_guard(ToolInput(project_dir=...))`
- **Then:**
  - Returns `ToolResult.status == "success"` (CC-01)
  - ≥ 3 files created (CC-04)
  - Verified by `test_success_status`, `test_files_created_count`

**US-02: Re-run safely**
- **As a** CI job
- **I want** `status="no_op"` on second run
- **Given:** `OwnershipVerifier` already in `bola_guard.py`
- **When:** Tool invoked again
- **Then:** `r2.status == "no_op"` — verified by `test_idempotent`

**US-03: Dry-run preview**
- **Given:** Fresh project
- **When:** `add_bola_guard(ToolInput(project_dir=..., dry_run=True))`
- **Then:** Zero filesystem changes — verified by `test_dry_run`

**US-04: Config fields are env-var overridable**
- **As a** platform engineer
- **I want** `BOLA_GUARD_ENABLED` and `BOLA_GUARD_STRICT_MODE` in `Settings`
- **When:** Tool runs
- **Then:** Both fields inside class body — verified by `test_config_fields_patched`

**US-05: Generated code is auditable**
- **As a** security reviewer
- **I want** all functions ≤ 50 LOC
- **Given:** Tool emitted `bola_guard.py`, `bola_test_gen.py`
- **When:** AST walk over `app/`
- **Then:** `max_loc <= 50` — verified by `test_no_function_over_50_loc`

### 9.2 BOLA protection logic (US-06 .. US-10)

**US-06: Block attacker accessing another user's order**
- **As a** BOLA guard
- **I want** `GET /orders/43` by user 1 (who owns order 42) to return 403
- **Given:** `Depends(require_ownership(Order, "user_id"))` on the route
- **When:** User 1 requests `order_id=43` (owned by user 2)
- **Then:** `OwnershipVerifier.__call__` raises HTTP 403 — verified by CC-11

**US-07: Owner accesses their own resource**
- **As a** legitimate user
- **I want** `GET /orders/42` to return my order
- **Given:** `request.state.user.id == 42_s_owner_id`
- **When:** `_check_ownership(session, Order, 42, "user_id", 42_s_owner_id)`
- **Then:** Returns `True`; `_enforce` does not raise

**US-08: Multi-tenant isolation**
- **As a** SaaS platform engineer
- **I want** queries to automatically scope to the current tenant
- **Given:** `TenantIsolationFilter(tenant_id=123).apply(query, Order)`
- **When:** Applied to a SQLAlchemy select
- **Then:** WHERE clause includes `Order.tenant_id == 123` — verified by CC-12

**US-09: Generate BOLA test suite for a model**
- **As a** test author
- **I want** `generate_bola_tests("Order")` to return ready-to-run tests
- **Given:** `bola_test_gen.generate_bola_tests("Order")`
- **When:** Called
- **Then:** Returns string with 4 test functions covering owner/attacker/unauth/admin — verified by CC-15

**US-10: Disable guard in tests**
- **As a** developer running unit tests
- **I want** to set `BOLA_GUARD_ENABLED=false` to skip ownership checks
- **Given:** `_bola_enabled()` reads from `settings.BOLA_GUARD_ENABLED`
- **When:** `BOLA_GUARD_ENABLED=false` in test env
- **Then:** `OwnershipVerifier.__call__` returns immediately — verified by CC-19

### 9.3 Integration (US-11 .. US-13)

**US-11: Resource delegation via access policy**
- **As a** user sharing a document
- **I want** to grant another user read access
- **Given:** `ResourceAccessPolicy(grantor=1, grantee=2, resource_model="Document", resource_id=5, read_only=True)`
- **When:** `policy.allows(2, "read")`
- **Then:** Returns `True`; `policy.allows(2, "write")` returns `False`

**US-12: Project parseable after two runs**
- **Given:** Tool applied twice
- **When:** `ast.parse` over all `.py`
- **Then:** Zero errors — verified by CC-18

**US-13: Error on invalid project_dir**
- **Given:** Non-existent path
- **When:** `add_bola_guard(ToolInput(project_dir="/nonexistent"))`
- **Then:** `result.status == "error"` — verified by CC-21

---

## 10. Error Handling

| Scenario | Behaviour | Status |
|----------|-----------|--------|
| `project_dir` does not exist | Returns `status="error"`, `error` set | `"error"` |
| `app/core/config.py` absent | `ensure_prerequisites` raises | `"error"` |
| `request.state.user` absent | `_get_current_user_id` returns `None`; strict mode → 403 | Runtime |
| `request.state.db` absent | Logs warning and returns (no DB session) | Partial |
| Resource not found in DB | `_check_ownership` returns `False`; `_enforce` raises 403 | Runtime |

---

## 11. Dependencies

| Package | Why needed |
|---------|------------|
| `sqlalchemy.select` | `_check_ownership` ownership query |
| `fastapi.Depends` | `require_ownership` wrapper |
| `fastapi.HTTPException` | HTTP 403 in `_enforce` |
| `fastapi.status.HTTP_403_FORBIDDEN` | Status code constant |
| `dataclasses` (stdlib) | `ResourceAccessPolicy`, `TenantIsolationFilter` |
| `pydantic-settings` | `Settings` in target project |

No new packages added to `requirements.txt`.

---

## 12. Security Considerations

| Concern | Mitigation |
|---------|-----------|
| Predictable integer IDs | BOLA guard is resource-level; combine with UUIDs for ID obfuscation |
| Mass assignment attacks | Separate concern (input validation); BOLA guard focuses on access |
| Admin bypass | `BOLA_GUARD_STRICT_MODE=false` (default) allows admins to bypass; strict mode blocks all |
| No DB session | Guard logs warning and returns (fails open); set `BOLA_GUARD_STRICT_MODE=true` for fail-closed |

---

## 13. Observability

| Signal | Where |
|--------|-------|
| `execution_time_ms` | `ToolResult.execution_time_ms` |
| BOLA violation attempt | HTTP 403 response from `_enforce` |
| Missing DB session | `logger.warning("BOLA guard: no DB session on request.state.db")` |
| Guard disabled | `_bola_enabled()` returns `False`; no action taken |

---

## 14. Configuration Reference

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `BOLA_GUARD_ENABLED` | `bool` | `True` | Master switch for ownership verification |
| `BOLA_GUARD_STRICT_MODE` | `bool` | `False` | When `True`, missing resource id or user id raises 403 (fail-closed) |

---

## 15. Migration / Rollback

**Rollback is mechanical:**
- Delete `app/auth/__init__.py`, `app/auth/bola_guard.py`, `app/auth/bola_test_gen.py`
- Remove `BOLA_GUARD_*` from `app/core/config.py`
- Remove `Depends(require_ownership(...))` from any routes that were manually updated

No database migrations. No new tables.

---

## 16. Test File Reference

**Location:** `adapt/extend/auth_access/test_add_bola_guard.py`

**Test runner:**
```bash
PYTHONPATH=. pytest adapt/extend/auth_access/test_add_bola_guard.py -v
# or standalone:
PYTHONPATH=. python3 adapt/extend/auth_access/test_add_bola_guard.py
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
| `test_config_fields_patched` | CC-08 | `BOLA_GUARD_ENABLED` inside `class Settings` |
| `test_ownership_verifier_created` | CC-09 | `OwnershipVerifier` in `bola_guard.py` |
| `test_require_ownership_dep` | CC-10 | `require_ownership` + `Depends` in `bola_guard.py` |
| `test_403_on_bola` | CC-11 | `HTTP_403_FORBIDDEN` or `403` in `bola_guard.py` |
| `test_tenant_isolation_filter` | CC-12 | `TenantIsolationFilter` + `tenant_id` in file |
| `test_resource_access_policy` | CC-13 | `ResourceAccessPolicy` in file |
| `test_bola_test_gen_created` | CC-14 | `bola_test_gen.py` + `generate_bola_tests` |
| `test_bola_test_gen_content` | CC-15 | `attacker`, `owner`, `403` in test gen output |
| `test_execution_time_recorded` | CC-16 | `execution_time_ms > 0` |
| `test_next_steps_present` | CC-17 | `next_steps` mentions `ownership`/`bola`/`require` |
| `test_idempotent_project_still_parses` | CC-18 | Two runs → all `.py` still parse |
| `test_bola_guard_enabled_flag` | CC-19 | `BOLA_GUARD_ENABLED` in `bola_guard.py` source |
| `test_strict_mode_logic` | CC-20 | `strict` or `STRICT` in `bola_guard.py` |
| `test_error_on_invalid_project_dir` | CC-21 | `status="error"` on non-existent dir |
| `test_mcp_tool_entry_matches_function` | CC-22 | `MCP_TOOL["entry"] == "add_bola_guard"` |
