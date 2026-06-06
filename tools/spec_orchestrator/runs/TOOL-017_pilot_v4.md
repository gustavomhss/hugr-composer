<!--
{
  "tool_num": "017",
  "tool_name": "add_api_versioning",
  "model": "deepseek/deepseek-chat",
  "elapsed_seconds": 625.0173762809718,
  "prompt_tokens": 46138,
  "completion_tokens": 9771,
  "cost_usd": 0.025256900000000006,
  "calls": 6
}
-->

# TOOL-017: add_api_versioning

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-08

---

## 1. Overview

| Property | Value |
|----------|-------|
| Tool name | `fastapi_add_api_versioning` |
| Category | EXTEND > API Design |
| Complexity | High |
| Dependencies | FastAPI, Starlette, Alembic (optional) |
| Signature | `add_api_versioning(project_dir: str, current_version: str = "v1", new_version: str = "v2", strategy: Literal["path", "header"] = "path", deprecation_period_days: int = 180) -> dict` |
| Parameters | `project_dir`: Absolute path to project root (e.g. `/code/myapp`)<br>`current_version`: Existing API version label (default `v1`)<br>`new_version`: New version label (default `v2`)<br>`strategy`: `path` for `/api/v1/...` URLs or `header` for `Accept` negotiation<br>`deprecation_period_days`: Days until v1 removal (default 180) |

## 2. Purpose

This tool adds production-grade API versioning to FastAPI applications, enabling multiple API versions to coexist during migration periods. It solves the critical need for backward compatibility when evolving APIs in production by creating isolated versioned routers, schemas, and OpenAPI docs. The implementation uses either path-based routing (default) or header negotiation, with automatic deprecation headers and sunset dates for older versions. All versioning logic integrates through FastAPI's router system and Starlette middleware.

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 6s | Multiple files require parsing and validation |
| Files modified | ≤ 6 | Global config, main router, and core files |
| Files created | ≥ 8 | Version routers, schemas, middleware, tests |
| Routing overhead | < 0.1 ms | FastAPI's router is highly optimized |
| Header parsing | < 0.5 ms | Accept header parsing adds minimal latency |
| Migration runtime | 0s | Pure code changes, no DB migrations |
| OpenAPI generation | < 200 ms per version | Separate doc generation per version |
| Memory overhead | < 1 MB per worker | Versioned routers add minimal memory |
| Response size | < 5% increase | Deprecation headers add minimal bytes |

---

## 4. Code Examples (Before / After)

### 4.1 Main router: BEFORE
```python
# app/api/main.py
from fastapi import APIRouter
from app.api.endpoints import items, users

router = APIRouter()
router.include_router(items.router, prefix="/items", tags=["items"])
router.include_router(users.router, prefix="/users", tags=["users"])
```

### 4.2 Main router: AFTER
```python
# app/api/main.py
from fastapi import APIRouter
from app.api.v1.main import router as v1_router
from app.api.v2.main import router as v2_router
from app.core.config import settings

router = APIRouter()
router.include_router(v1_router, prefix="/api/v1")
router.include_router(v2_router, prefix="/api/v2")
```

### 4.3 Versioned router (NEW)
```python
# app/api/v1/main.py
from fastapi import APIRouter
from app.api.v1.endpoints import items, users

router = APIRouter()
router.include_router(items.router, prefix="/items", tags=["items"])
router.include_router(users.router, prefix="/users", tags=["users"])
```

### 4.4 Deprecation middleware (NEW)
```python
# app/api/middleware/deprecation.py
from datetime import datetime
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from app.core.config import settings

class DeprecationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        if request.url.path.startswith("/api/v1"):
            sunset_date = settings.API_SUNSET_DATES["v1"]
            response.headers["Deprecation"] = "true"
            response.headers["Sunset"] = sunset_date.isoformat()
            response.headers["Link"] = f'<{request.url.replace(path="/api/v2" + request.url.path[6:])}>; rel="successor-version"'
        return response
```

### 4.5 Versioned schema (NEW)
```python
# app/schemas/v2/item.py
from pydantic import BaseModel
from datetime import datetime
from uuid import UUID

class ItemCreate(BaseModel):
    title: str
    description: str | None = None

class ItemOut(BaseModel):
    id: UUID
    title: str
    description: str | None
    created_at: datetime
    owner_id: UUID
```

### 4.6 Version dependency (NEW)
```python
# app/api/deps_version.py
from fastapi import Header, HTTPException
from app.core.config import settings

async def get_api_version(accept: str | None = Header(default=None)) -> str:
    if accept is None:
        return settings.API_CURRENT_VERSION
    
    for version in settings.API_SUPPORTED_VERSIONS:
        if f"application/vnd.app.{version}+json" in accept:
            return version
    
    return settings.API_CURRENT_VERSION
```

### 4.7 Migration: versioning setup
```python
# alembic/versions/0009_add_api_versioning.py
"""add api versioning

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-08
"""
from alembic import op
from datetime import datetime, timedelta
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"

def upgrade() -> None:
    # Add API version config table
    op.create_table(
        "api_versions",
        sa.Column("version", sa.String(16), primary_key=True),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("sunset_date", sa.DateTime(), nullable=True),
    )
    
    # Insert initial versions
    sunset_date = datetime.utcnow() + timedelta(days=180)
    op.execute(
        "INSERT INTO api_versions (version, is_current, sunset_date) VALUES "
        f"('v1', false, '{sunset_date.isoformat()}'), "
        "('v2', true, null)"
    )

def downgrade() -> None:
    op.drop_table("api_versions")

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Versioned routes NEVER leak across versions** | Separate `APIRouter` instances with isolated prefix mounts in `app/api/v1/main.py` and `app/api/v2/main.py` |
| QS-2 | **Deprecation headers ALWAYS appear on deprecated routes** | `DeprecationMiddleware` adds headers unconditionally for paths starting with `/api/v1` |
| QS-3 | **Sunset date is computed exactly once at migration time** | `settings.API_SUNSET_DATES` is initialized in `app/core/config.py` with `datetime.utcnow() + timedelta(days=deprecation_period_days)` |
| QS-4 | **Header strategy defaults to current version when no Accept header matches** | `get_api_version()` dependency in `app/api/deps_version.py` falls back to `settings.API_CURRENT_VERSION` |
| QS-5 | **OpenAPI per version contains ONLY that version's routes** | Separate OpenAPI routers in `app/api/v1/main.py` and `app/api/v2/main.py` with isolated tags and paths |
| QS-6 | **Versioned schemas are isolated per directory** | Strict directory separation between `app/schemas/v1/` and `app/schemas/v2/` with no shared imports |
| QS-7 | **Deprecation middleware runs AFTER auth middleware** | Middleware registration order in `app/main.py` ensures auth runs first |
| QS-8 | **Link header points to the exact successor resource** | `DeprecationMiddleware` constructs URL by replacing `/api/v1` with `/api/v2` in the path |
| QS-9 | **Health check route remains unversioned** | Explicit exclusion of `/health` from versioned routers in `app/main.py` |
| QS-10 | **Versioning adds < 1ms overhead per request** | Benchmark tests in `tests/test_api_versioning.py` verify routing latency |
| QS-11 | **Tool execution is idempotent** | Tool checks for existing version directories before creating new ones |

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | `app/api/v1/main.py` exists with all legacy routes | File exists, routes match original layout |
| CC-02 | `app/api/v2/main.py` exists with copied routes | File exists, routes match v1 layout initially |
| CC-03 | `app/core/api_version.py` exists with sunset date computation | File exists, contains `API_SUNSET_DATES` |
| CC-04 | `DeprecationMiddleware` registered in `app/main.py` | grep `app.add_middleware(DeprecationMiddleware)` |
| CC-05 | Versioned routers mounted at `/api/v1` and `/api/v2` | Inspect `app/main.py` router mounts |
| CC-06 | `app/api/deps_version.py` exists with header parsing | File exists, contains `get_api_version()` |
| CC-07 | `app/schemas/v1/` and `app/schemas/v2/` directories exist | Directory listing |
| CC-08 | `settings.API_CURRENT_VERSION` set to `v2` | Inspect `app/core/config.py` |
| CC-09 | `settings.API_DEPRECATED_VERSIONS` contains `v1` | Inspect `app/core/config.py` |
| CC-10 | `settings.API_SUNSET_DATES` contains `v1` sunset date | Inspect `app/core/config.py` |
| CC-11 | `/health` route remains unversioned | grep `"/health"` in `app/main.py` |
| CC-12 | `DeprecationMiddleware` adds correct headers | Inspect middleware implementation |
| CC-13 | Header strategy falls back to current version | Test T-19 |
| CC-14 | Path strategy routes correctly | Test T-01, T-02 |
| CC-15 | OpenAPI per version contains only its routes | Curl `/api/v1/openapi.json` and `/api/v2/openapi.json` |
| CC-16 | Root `/openapi.json` defaults to current version | Curl `/openapi.json` |
| CC-17 | `Link` header points to successor version | Test T-08 |
| CC-18 | Sunset date is in the future | Inspect `settings.API_SUNSET_DATES` |
| CC-19 | Deprecation headers only appear on v1 routes | Test T-07 |
| CC-20 | Versioned schemas are isolated | Inspect imports in `app/schemas/v1/` and `app/schemas/v2/` |
| CC-21 | Middleware runs after auth | Inspect middleware registration order |
| CC-22 | Tool execution time < 6s | Time measurement |
| CC-23 | Files modified ≤ 6 | Count modified files |
| CC-24 | Files created ≥ 8 | Count created files |
| CC-25 | Routing overhead < 0.1ms | Benchmark T-28 |
| CC-26 | Header parsing overhead < 0.5ms | Benchmark T-29 |
| CC-27 | OpenAPI generation < 200ms per version | Benchmark T-30 |
| CC-28 | Memory overhead < 1MB per worker | Memory measurement |
| CC-29 | Response size increase < 5% | Benchmark T-30 |
| CC-30 | Idempotent: re-run leaves no extra files | Test T-26 |

## 7. Definition of Done

- [ ] All 30 Completeness Criteria verified
- [ ] All 30 tests pass in `tests/test_api_versioning.py`
- [ ] Tool execution time < 6s measured
- [ ] Files modified ≤ 6 confirmed
- [ ] Files created ≥ 8 confirmed
- [ ] Routing overhead < 0.1ms benchmarked
- [ ] Header parsing overhead < 0.5ms benchmarked
- [ ] OpenAPI generation < 200ms per version benchmarked
- [ ] Memory overhead < 1MB per worker measured
- [ ] Response size increase < 5% measured
- [ ] Idempotency verified by re-run
- [ ] Documentation updated in README.md
- [ ] All edge cases tested (EC-1..EC-15)

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-VER-01 | A v1 call NEVER routes to a v2 handler | Separate `APIRouter` instances | T-01, T-02 |
| INV-VER-02 | Deprecated routes ALWAYS emit `Deprecation: true` | `DeprecationMiddleware` | T-07, T-08 |
| INV-VER-03 | The `Link` header points to the successor version | URL construction in middleware | T-08, T-09 |
| INV-VER-04 | OpenAPI per version contains ONLY that version's routes | Separate OpenAPI routers | T-24, T-25 |
| INV-VER-05 | Header strategy defaults to `current_version` | `get_api_version()` dependency | T-19, T-20 |
| INV-VER-06 | Versioned schemas are isolated per directory | Strict directory separation | T-13, T-14 |
| INV-VER-07 | Adding a new version NEVER breaks existing v1 clients | Legacy route preservation | T-01, T-02 |

---

## 9. User Stories

### 9.1 Core functionality (US-01 .. US-05)

**US-01: Add v2 without breaking v1**
- **As a** backend developer
- **I want** to introduce v2 routes while keeping v1 unchanged
- **So that** existing clients continue working during migration
- **Given:** project with `/api/v1/items` route
- **When:** I call `add_api_versioning("/code/myapp")`
- **Then:**
  - `/api/v1/items` remains unchanged
  - `/api/v2/items` is created with identical initial implementation
  - `DeprecationMiddleware` is registered
  - `Sunset` header is set to 180 days from now

**US-02: Default to path-based versioning**
- **As a** API consumer
- **I want** to access different versions via URL paths
- **So that** I can cache responses at the CDN level
- **Given:** strategy="path" configured
- **When:** I call `GET /api/v1/items` and `GET /api/v2/items`
- **Then:**
  - v1 call routes to `app/api/v1/main.py`
  - v2 call routes to `app/api/v2/main.py`
  - Responses include correct version in OpenAPI docs

**US-03: Add deprecation headers to v1**
- **As a** API consumer
- **I want** to know when v1 will be removed
- **So that** I can plan my migration
- **Given:** v1 route `/api/v1/items`
- **When:** I call `GET /api/v1/items`
- **Then:**
  - Response includes `Deprecation: true`
  - `Sunset` header shows exact removal date
  - `Link` header points to `/api/v2/items`

**US-04: Isolate versioned schemas**
- **As a** backend developer
- **I want** v1 and v2 schemas in separate directories
- **So that** I can evolve them independently
- **Given:** Item schema in `app/schemas/item.py`
- **When:** I run the tool
- **Then:**
  - v1 schema moves to `app/schemas/v1/item.py`
  - v2 schema copies to `app/schemas/v2/item.py`
  - No shared imports between versions

**US-05: Generate separate OpenAPI per version**
- **As a** API consumer
- **I want** accurate docs for each version
- **So that** I know what's available in v1 vs v2
- **Given:** project with `/api/v1/items` and `/api/v2/items`
- **When:** I request `/api/v1/openapi.json` and `/api/v2/openapi.json`
- **Then:**
  - Each OpenAPI doc shows only its version's routes
  - Root `/openapi.json` defaults to v2
  - Docs include deprecation info for v1

### 9.2 Deprecation lifecycle (US-06 .. US-10)

**US-06: Compute sunset date once at migration time**
- **As a** backend developer
- **I want** a fixed sunset date for v1
- **So that** all clients see the same removal timeline
- **Given:** deprecation_period_days=180
- **When:** I run the tool
- **Then:**
  - `settings.API_SUNSET_DATES["v1"]` is set to `now() + timedelta(days=180)`
  - Date is stored in `app/core/api_version.py`
  - Middleware uses this exact date in headers

**US-07: Keep health check unversioned**
- **As a** DevOps engineer
- **I want** health checks to work without versioning
- **So that** monitoring tools don't break
- **Given:** `/health` route in `app/main.py`
- **When:** I run the tool
- **Then:**
  - `/health` remains accessible without `/api/v1/health`
  - Health check is excluded from versioned routers
  - Response includes no deprecation headers

**US-08: Handle missing successor route**
- **As a** backend developer
- **I want** graceful handling when v2 lacks a successor route
- **So that** clients aren't misled
- **Given:** `/api/v1/old` exists but `/api/v2/old` doesn't
- **When:** I call `GET /api/v1/old`
- **Then:**
  - Response includes `Deprecation: true`
  - No `Link` header is present
  - OpenAPI docs show v1 route as deprecated

**US-09: Preserve v1 route layout exactly**
- **As a** API consumer
- **I want** v1 routes to remain unchanged
- **So that** my existing clients don't break
- **Given:** `/api/v1/items/{id}` route
- **When:** I run the tool
- **Then:**
  - Route moves to `app/api/v1/main.py` unchanged
  - Path, method, and response schema match original
  - Only deprecation headers are added

**US-10: Warn on sunset date in the past**
- **As a** backend developer
- **I want** to catch invalid deprecation periods
- **So that** I don't misconfigure the API
- **Given:** deprecation_period_days=-30
- **When:** I run the tool
- **Then:**
  - Tool raises ValueError
  - Error message specifies valid range (>= 0)
  - No files are modified

### 9.3 Schema evolution (US-11 .. US-15)

**US-11: Rename field in v2 schema**
- **As a** backend developer
- **I want** to rename a field in v2
- **So that** I can improve the API design
- **Given:** v1 schema has `created_at` field
- **When:** I rename it to `timestamp` in `app/schemas/v2/item.py`
- **Then:**
  - v1 responses still use `created_at`
  - v2 responses use `timestamp`
  - OpenAPI docs reflect the change

**US-12: Add new field in v2**
- **As a** backend developer
- **I want** to extend the schema in v2
- **So that** I can add new features
- **Given:** v1 Item schema
- **When:** I add `tags: list[str]` to v2 schema
- **Then:**
  - v1 responses exclude the new field
  - v2 responses include `tags`
  - OpenAPI docs show the addition

**US-13: Remove deprecated field in v2**
- **As a** backend developer
- **I want** to clean up unused fields in v2
- **So that** the API stays lean
- **Given:** v1 schema has `legacy_id` field
- **When:** I remove it from v2 schema
- **Then:**
  - v1 responses still include `legacy_id`
  - v2 responses exclude it
  - OpenAPI docs reflect the removal

**US-14: Change field type in v2**
- **As a** backend developer
- **I want** to evolve field types in v2
- **So that** I can improve data modeling
- **Given:** v1 schema has `price: float`
- **When:** I change it to `price: Decimal` in v2
- **Then:**
  - v1 responses use `float`
  - v2 responses use `Decimal`
  - OpenAPI docs show the type change

**US-15: Handle circular references in versioned schemas**
- **As a** backend developer
- **I want** circular references to work in v2
- **So that** I can model complex relationships
- **Given:** User schema references Item schema
- **When:** I add circular ref in `app/schemas/v2/user.py`
- **Then:**
  - v2 schema resolves the circular ref
  - OpenAPI docs show the relationship
  - No impact on v1 schemas

### 9.4 Strategy: path vs header (US-16 .. US-20)

**US-16: Default to current version with header strategy**
- **As a** API consumer
- **I want** to fall back to current version
- **So that** I don't need to specify version explicitly
- **Given:** strategy="header" configured
- **When:** I call `GET /api/items` without Accept header
- **Then:**
  - Request routes to v2 handler
  - Response includes no deprecation headers
  - OpenAPI docs show default version

**US-17: Parse Accept header for version**
- **As a** API consumer
- **I want** to specify version via Accept header
- **So that** I can use a single endpoint
- **Given:** strategy="header" configured
- **When:** I call `GET /api/items` with `Accept: application/vnd.app.v1+json`
- **Then:**
  - Request routes to v1 handler
  - Response includes deprecation headers
  - OpenAPI docs reflect the version

**US-18: Reject malformed Accept header**
- **As a** API consumer
- **I want** clear errors for invalid Accept headers
- **So that** I can fix my client
- **Given:** strategy="header" configured
- **When:** I call `GET /api/items` with `Accept: application/json`
- **Then:**
  - Request routes to v2 handler
  - Response includes no deprecation headers
  - OpenAPI docs show default version

**US-19: Handle conflicting path and header versions**
- **As a** API consumer
- **I want** path to override header version
- **So that** I can use both strategies together
- **Given:** strategy="header" configured
- **When:** I call `GET /api/v1/items` with `Accept: application/vnd.app.v2+json`
- **Then:**
  - Request routes to v1 handler
  - Response includes deprecation headers
  - OpenAPI docs reflect the path version

**US-20: Support CORS preflight on versioned routes**
- **As a** frontend developer
- **I want** CORS preflight to work on versioned routes
- **So that** I can call the API from the browser
- **Given:** `/api/v1/items` route
- **When:** Browser sends OPTIONS request to `/api/v1/items`
- **Then:**
  - Preflight response includes CORS headers
  - Deprecation headers are omitted
  - OpenAPI docs show CORS support

### 9.5 Performance & observability (US-21 .. US-25)

**US-21: Measure routing overhead**
- **As a** DevOps engineer
- **I want** to track versioning overhead
- **So that** I can ensure performance SLOs
- **Given:** `/api/v1/items` and `/api/v2/items` routes
- **When:** I benchmark 1000 requests to each
- **Then:**
  - Routing overhead < 0.1ms per request
  - Memory overhead < 1MB per worker
  - Response size increase < 5%

**US-22: Track deprecated route usage**
- **As a** product owner
- **I want** to monitor v1 usage
- **So that** I can plan its removal
- **Given:** `/api/v1/items` route
- **When:** I call `GET /api/v1/items`
- **Then:**
  - Request is logged with `version=v1`
  - Metrics include deprecation tag
  - Dashboard shows v1 vs v2 traffic

**US-23: Generate OpenAPI quickly**
- **As a** API consumer
- **I want** fast OpenAPI generation
- **So that** I can get docs quickly
- **Given:** project with 100 routes
- **When:** I request `/api/v1/openapi.json`
- **Then:**
  - Response time < 200ms
  - Docs include only v1 routes
  - Root `/openapi.json` defaults to v2

**US-24: Handle high request volume**
- **As a** DevOps engineer
- **I want** versioning to scale
- **So that** I can handle production traffic
- **Given:** 1000 concurrent requests
- **When:** I call `/api/v1/items` and `/api/v2/items`
- **Then:**
  - Routing overhead < 0.1ms per request
  - Memory overhead < 1MB per worker
  - Response size increase < 5%

**US-25: Verify tool idempotency**
- **As a** backend developer
- **I want** safe tool re-runs
- **So that** I don't create duplicate files
- **Given:** project with existing v1 and v2
- **When:** I run `add_api_versioning` again
- **Then:**
  - No files are modified
  - Tool reports "already enabled"
  - Existing routes remain unchanged

---

## 10. Test Plan

### 10.1 Routing isolation tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | v1 call routes to v1 handler | Project with `/api/v1/items` | GET /api/v1/items | 200, routes to `app/api/v1/endpoints/items.py` |
| T-02 | v2 call routes to v2 handler | Project with `/api/v2/items` | GET /api/v2/items | 200, routes to `app/api/v2/endpoints/items.py` |
| T-03 | v1 call never hits v2 handler | Both versions have /items | GET /api/v1/items | 200, debug logs show v1 handler only |
| T-04 | v2 call never hits v1 handler | Both versions have /items | GET /api/v2/items | 200, debug logs show v2 handler only |
| T-05 | Missing version returns 404 | Only v1 exists | GET /api/v3/items | 404 |
| T-06 | Health check remains unversioned | /health route exists | GET /health | 200, no deprecation headers |

### 10.2 Deprecation header tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-07 | v1 routes include deprecation | Project with deprecation_period_days=180 | GET /api/v1/items | Headers: Deprecation=true, Sunset=<future date> |
| T-08 | Link header points to successor | v1 and v2 have /items | GET /api/v1/items | Link: </api/v2/items>; rel="successor-version" |
| T-09 | No successor route omits Link | v1 has /old, v2 doesn't | GET /api/v1/old | Deprecation header present, no Link header |
| T-10 | v2 routes lack deprecation | Project with v1+v2 | GET /api/v2/items | No Deprecation/Sunset headers |
| T-11 | Sunset date matches config | settings.API_SUNSET_DATES["v1"] | GET /api/v1/items | Sunset header equals config value |
| T-12 | Middleware runs after auth | Auth requires X-Token header | GET /api/v1/items with valid token | 200, both auth and deprecation headers |

### 10.3 Schema isolation tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-13 | v1 response matches v1 schema | v1 schema has fieldA, v2 renamed to fieldB | GET /api/v1/items | response contains fieldA |
| T-14 | v2 response matches v2 schema | v2 schema added fieldC | GET /api/v2/items | response contains fieldC |
| T-15 | Schema imports are isolated | v1/item.py imports from v1/ | Inspect imports in v2/item.py | No imports from v1/ |
| T-16 | Field rename in v2 only | v1: price:float, v2: price:Decimal | GET /api/v1/items vs /api/v2/items | Different field types per version |
| T-17 | Removed field in v2 only | v1 has legacy_id, v2 doesn't | GET /api/v1/items/{id} | legacy_id present in v1 only |
| T-18 | Circular refs work per version | User has Items in v2 only | GET /api/v2/users/{id} | Response includes nested items |

### 10.4 Header strategy tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-19 | No Accept header defaults to current | strategy="header" | GET /api/items | Routes to v2, no deprecation headers |
| T-20 | Valid Accept header routes correctly | strategy="header" | GET /api/items with Accept:application/vnd.app.v1+json | Routes to v1, deprecation headers |
| T-21 | Malformed Accept falls back | strategy="header" | GET /api/items with Accept:application/json | Routes to v2 |
| T-22 | Unsupported version falls back | strategy="header" | GET /api/items with Accept:application/vnd.app.v3+json | Routes to v2 |
| T-23 | Path overrides Accept header | strategy="header" | GET /api/v1/items with Accept:application/vnd.app.v2+json | Routes to v1 |
| T-24 | CORS preflight works | strategy="header", /api/items | OPTIONS /api/items | 200, CORS headers, no versioning headers |

### 10.5 OpenAPI tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-25 | v1 OpenAPI shows only v1 routes | Project with v1+v2 | GET /api/v1/openapi.json | paths only contain /api/v1/ routes |
| T-26 | v2 OpenAPI shows only v2 routes | Project with v1+v2 | GET /api/v2/openapi.json | paths only contain /api/v2/ routes |
| T-27 | Root OpenAPI defaults to current | Project with v2 current | GET /openapi.json | Matches /api/v2/openapi.json |
| T-28 | Deprecated routes marked in docs | v1 route /items | GET /api/v1/openapi.json | /items has deprecation flag |
| T-29 | Schema differences visible | v1 and v2 Item schemas differ | GET /api/v1/openapi.json vs /api/v2/openapi.json | Different schemas/components |
| T-30 | OpenAPI gen <200ms per version | Project with 50 routes | Time GET /api/v1/openapi.json | Response time <200ms |

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|----------------|-------------|-------|
| `add_multi_tenancy` | Yes | Versioning applies AFTER tenant resolution | Tenant middleware must run before versioning middleware |
| `add_soft_delete` | No | Versioned routes inherit soft delete behavior | Soft delete remains version-agnostic |
| `add_audit_log` | No | Audit logs capture version in metadata | Logs include `api_version` field |
| `add_rbac` | Yes | RBAC applies BEFORE versioning | Authorization checks run first |
| `add_api_key_auth` | No | API keys work across versions | Key validation is version-independent |
| `add_oauth2_provider` | Yes | OAuth2 runs BEFORE versioning | Token validation precedes version routing |
| `add_mfa` | No | MFA applies to all versions | Versioning doesn't affect MFA flow |
| `add_cache_layer` | Yes | Cache keys include version | `/api/v1/items` and `/api/v2/items` cache separately |
| `add_circuit_breaker` | No | Circuit breakers are version-specific | Each version has independent failure tracking |

**Conflicts:** None identified.

## 12. Rollback Procedure

### Code rollback (before deploy)
```bash
git checkout -- app/api/v1/ app/api/v2/ app/schemas/v1/ app/schemas/v2/
git checkout -- app/main.py app/api/main.py app/core/config.py
rm -rf app/api/middleware/deprecation.py app/api/deps_version.py
rm -rf tests/test_api_versioning.py
```

### Database rollback (after deploy)
No database changes to rollback.

### Data preservation rollback
No data changes to preserve.

### Failure mode: tool partially modified files
```bash
git clean -fd app/api/v1/ app/api/v2/ app/schemas/v1/ app/schemas/v2/
git checkout -- app/main.py app/api/main.py app/core/config.py
rm -rf app/api/middleware/deprecation.py app/api/deps_version.py
rm -rf tests/test_api_versioning.py
```

### Emergency: sunset date passed but v1 still active
```bash
sed -i '/DeprecationMiddleware/d' app/main.py
sed -i '/API_SUNSET_DATES/d' app/core/config.py
```

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-1 | Project has no existing routes | Tool errors: "No routes found. Add at least one route first." |
| EC-2 | New version label collides with existing | Tool errors: "Version v2 already exists. Choose a different new_version." |
| EC-3 | Strategy=header but client sends both Accept and v1 path | Path takes precedence; routes to v1 handler |
| EC-4 | Sunset date in the past | Tool errors: "deprecation_period_days must be >= 0. Received -30." |
| EC-5 | Two routes have same path in v1 but different in v2 | Tool copies both routes to v2; developer must resolve conflict |
| EC-6 | v2 route uses schema that doesn't exist in v1 | Tool creates empty schema file in v1 directory |
| EC-7 | Removing v1 route that v2 doesn't have successor for | Deprecation headers omit Link field |
| EC-8 | OpenAPI generation for empty version | Returns empty OpenAPI spec with version tag |
| EC-9 | Versioned middleware order | Deprecation middleware runs AFTER auth middleware |
| EC-10 | Reverse proxy strips /api/v1 prefix | Middleware reads X-Forwarded-Prefix header if available |
| EC-11 | CORS preflight on versioned route | Preflight response includes CORS headers, omits versioning headers |
| EC-12 | Client sends Accept: application/json | Falls back to current version |
| EC-13 | Health check route | Remains unversioned at /health |
| EC-14 | New version has different auth scheme | Tool warns: "Auth scheme differs between versions. Verify client compatibility." |
| EC-15 | Versioned schemas with circular references | Tool preserves circular references in both versions |

## 14. Acceptance Criteria (Final Sign-off)

✅ All 30 Completeness Criteria verified  
✅ All 30 tests pass in `tests/test_api_versioning.py`  
✅ Tool execution time < 6s measured  
✅ Files modified ≤ 6 confirmed  
✅ Files created ≥ 8 confirmed  
✅ Routing overhead < 0.1ms benchmarked  
✅ Header parsing overhead < 0.5ms benchmarked  
✅ OpenAPI generation < 200ms per version benchmarked  
✅ Memory overhead < 1MB per worker measured  
✅ Developer successfully migrates `/items` endpoint from v1 to v2 while maintaining v1 compatibility  

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks
- [ ] Validate `project_dir` exists
- [ ] Validate `app/api/` directory exists
- [ ] Validate at least one route exists
- [ ] Check for existing version directories
- [ ] Validate `deprecation_period_days` >= 0
- [ ] Parse existing routes with AST

### 15.2 Version constants
- [ ] Create `app/core/api_version.py`
- [ ] Add `API_CURRENT_VERSION` constant
- [ ] Add `API_DEPRECATED_VERSIONS` list
- [ ] Add `API_SUNSET_DATES` dict
- [ ] Compute sunset date
- [ ] Verify file parses

### 15.3 Middleware
- [ ] Create `app/api/middleware/deprecation.py`
- [ ] Implement `DeprecationMiddleware`
- [ ] Add deprecation header logic
- [ ] Add sunset header logic
- [ ] Add Link header logic
- [ ] Register middleware in `app/main.py`

### 15.4 Version routers
- [ ] Create `app/api/v1/main.py`
- [ ] Move existing routes to v1 router
- [ ] Create `app/api/v2/main.py`
- [ ] Copy routes to v2 router
- [ ] Mount routers in `app/main.py`
- [ ] Verify routers parse

### 15.5 Versioned schemas
- [ ] Create `app/schemas/v1/` directory
- [ ] Move existing schemas to v1 directory
- [ ] Create `app/schemas/v2/` directory
- [ ] Copy schemas to v2 directory
- [ ] Update imports in versioned routers
- [ ] Verify schemas parse

### 15.6 Header strategy
- [ ] Create `app/api/deps_version.py`
- [ ] Implement `get_api_version()` dependency
- [ ] Add Accept header parsing
- [ ] Add fallback to current version
- [ ] Add header strategy tests
- [ ] Verify file parses

### 15.7 OpenAPI
- [ ] Configure separate OpenAPI per version
- [ ] Set root OpenAPI to current version
- [ ] Add deprecation info to v1 OpenAPI
- [ ] Verify OpenAPI generation time < 200ms
- [ ] Add OpenAPI tests
- [ ] Verify docs accessibility

### 15.8 Test generation
- [ ] Create `tests/test_api_versioning.py`
- [ ] Generate routing isolation tests
- [ ] Generate deprecation header tests
- [ ] Generate schema isolation tests
- [ ] Generate header strategy tests
- [ ] Generate OpenAPI tests

### 15.9 Atomicity
- [ ] Use temp-file + rename pattern for all writes
- [ ] Track modified files for rollback
- [ ] Verify all files parse after modification
- [ ] Return error if any step fails
- [ ] Rollback all changes on failure
- [ ] Return success report with metrics

### 15.10 Documentation
- [ ] Update README.md API section
- [ ] Add versioning docs to `core/KNOWLEDGE.md`
- [ ] Add tool entry to `manifest.yaml`
- [ ] Add tool to `SKILL.md` tools table
- [ ] Update `mcp_server.py` with new MCP tool decorator
- [ ] Verify docs accessibility

### 15.11 Verification
- [ ] Run `ast.parse` on every modified file
- [ ] Run import audit on the project
- [ ] Run `pytest tests/` to verify no regressions
- [ ] Measure tool execution time
- [ ] Measure versioning overhead
- [ ] Return success report with metrics

### 15.12 Performance
- [ ] Benchmark routing overhead
- [ ] Benchmark header parsing overhead
- [ ] Benchmark OpenAPI generation time
- [ ] Measure memory overhead
- [ ] Measure response size increase
- [ ] Verify all benchmarks meet SLOs

## 16. Documentation Output

```json
{
  "status": "success",
  "files_created": [
    "app/core/api_version.py",
    "app/api/middleware/deprecation.py",
    "app/api/v1/main.py",
    "app/api/v2/main.py",
    "app/schemas/v1/item.py",
    "app/schemas/v2/item.py",
    "app/api/deps_version.py",
    "tests/test_api_versioning.py"
  ],
  "files_modified": [
    "app/main.py",
    "app/api/main.py",
    "app/core/config.py"
  ],
  "metrics": {
    "execution_time_ms": 5123,
    "files_changed": 11,
    "lines_added": 423,
    "lines_removed": 18,
    "current_version": "v2",
    "new_version": "v1",
    "strategy": "path",
    "deprecation_period_days": 180
  },
  "next_steps": [
    "Run: pytest tests/test_api_versioning.py -v",
    "Test: curl -I /api/v1/items to verify deprecation headers",
    "Test: curl /api/v2/items to verify new version routing",
    "Update: evolve v2 routes and schemas as needed",
    "Monitor: track v1 usage metrics to plan removal"
  ],
  "warnings": [
    "CORS preflight requests on versioned routes omit deprecation headers",
    "Sunset date is fixed at migration time; verify deprecation_period_days"
  ],
  "notes": [
    "API versioning enabled with strategy=path",
    "v1 routes preserved exactly in app/api/v1/main.py",
    "DeprecationMiddleware registered AFTER auth middleware",
    "Sunset date computed as 180 days from migration time",
    "Separate OpenAPI docs available at /api/v1/openapi.json and /api/v2/openapi.json",
    "Root /openapi.json defaults to v2"
  ]
}
