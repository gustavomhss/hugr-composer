<!--
{
  "tool_num": "017",
  "tool_name": "add_api_versioning",
  "model": "deepseek/deepseek-chat",
  "elapsed_seconds": 406.2424718979746,
  "prompt_tokens": 48050,
  "completion_tokens": 10219,
  "cost_usd": 0.02860476,
  "calls": 6
}
-->

# TOOL-017: add_api_versioning

> **Status**: SPEC v2 (rigorous)  
> **Last updated**: 2026-04-08  

---

## 1. Overview

| Parameter       | Value                                                                 |
|-----------------|-----------------------------------------------------------------------|
| Tool name       | `fastapi_add_api_versioning`                                          |
| Category        | EXTEND > API Design                                                  |
| Complexity      | High                                                                 |
| Dependencies    | existing project with at least one resource (model + routes), Alembic optional |
| Signature       | `add_api_versioning(project_dir: str, current_version: str = "v1", new_version: str = "v2", strategy: Literal["path", "header"] = "path", deprecation_period_days: int = 180) -> dict` |
| Parameters      | `project_dir`: project root path<br>`current_version`: version label of the existing API surface (default `v1`)<br>`new_version`: label for the new version being introduced (default `v2`)<br>`strategy`: how clients select the version — `path` (`/api/v1/...` vs `/api/v2/...`) or `header` (`Accept: application/vnd.app.v2+json`)<br>`deprecation_period_days`: number of days from migration until v1 routes are removed; sets the `Sunset` header date |

## 2. Purpose

The `fastapi_add_api_versioning` tool adds API versioning to a FastAPI project, enabling multiple API versions to coexist seamlessly. This is critical in production environments where backward compatibility must be maintained while evolving the API surface. The tool implements versioning via path-based routing (e.g., `/api/v1/...` vs `/api/v2/...`) or header-based negotiation (`Accept: application/vnd.app.v2+json`). It ensures deprecated versions emit `Deprecation`, `Sunset`, and `Link` headers, while maintaining a backward-compatibility shim layer for v1 routes to call v2 CRUD logic with field translation.

## 3. Performance SLOs

| Metric                  | Target                          | Why                                                                 |
|-------------------------|---------------------------------|---------------------------------------------------------------------|
| Tool execution time     | < 6s                           | Multiple files modified                                             |
| Files modified          | ≤ 6 global files               | Limited to core configuration and routing files                    |
| Files created           | ≥ 8                            | Includes versioning module, routers, middleware, and tests         |
| Per-version routing overhead | < 0.1 ms                  | FastAPI router resolution is lightweight                           |
| Header parsing overhead | < 0.5 ms                       | Header strategy requires minimal parsing                            |
| Migration runtime       | 0s — no DB changes             | Pure code migration; no database schema updates                    |
| OpenAPI generation per version | < 200 ms               | Efficient OpenAPI schema generation per version                     |
| Memory overhead         | < 1 MB per worker              | Minimal memory impact for versioning middleware                    |
| No DB schema changes    | N/A                            | Versioning is implemented at the API layer, not the database layer |

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
router.include_router(v1_router, prefix=f"/api/{settings.API_CURRENT_VERSION}")
router.include_router(v2_router, prefix=f"/api/{settings.API_NEW_VERSION}")
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
    def __init__(self, app):
        super().__init__(app)
        self.deprecated_prefix = f"/api/{settings.API_CURRENT_VERSION}"

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        if request.url.path.startswith(self.deprecated_prefix):
            response.headers["Deprecation"] = "true"
            response.headers["Sunset"] = settings.API_SUNSET_DATE.isoformat()
            response.headers["Link"] = (
                f'<{request.url.replace(path=request.url.path.replace('
                f'"/{settings.API_CURRENT_VERSION}/", "/{settings.API_NEW_VERSION}/"))}>; '
                'rel="successor-version"'
            )
        return response
```

### 4.5 Version dependency (NEW)
```python
# app/api/deps_version.py
from fastapi import Header, HTTPException
from typing import Annotated

from app.core.config import settings


def version_negotiation(
    accept: Annotated[
        str | None, 
        Header(alias="Accept", pattern=r"application/vnd\.app\.(v\d)\+json")
    ] = None
) -> str:
    if accept is None:
        return settings.API_CURRENT_VERSION
    
    version = accept.split(".")[-2]  # Extract v1/v2 from Accept header
    if version not in (settings.API_CURRENT_VERSION, settings.API_NEW_VERSION):
        raise HTTPException(
            status_code=406,
            detail=f"Unsupported API version. Available: {settings.API_CURRENT_VERSION}, {settings.API_NEW_VERSION}"
        )
    return version
```

### 4.6 Versioned schema (NEW)
```python
# app/schemas/v2/item.py
from datetime import datetime
from pydantic import BaseModel, Field
from uuid import UUID


class ItemBase(BaseModel):
    title: str = Field(max_length=255)
    description: str | None = Field(default=None, max_length=2000)


class ItemCreate(ItemBase):
    pass


class ItemOut(ItemBase):
    id: UUID
    owner_id: UUID
    created_at: datetime
    updated_at: datetime | None

    class Config:
        from_attributes = True
```

### 4.7 Version config (NEW)
```python
# app/core/api_version.py
from datetime import datetime, timedelta
from typing import Final

from app.core.config import settings


API_SUNSET_DATE: Final[datetime] = datetime.utcnow() + timedelta(
    days=settings.API_DEPRECATION_PERIOD_DAYS
)
```

### 4.8 Migration (NEW)
```python
# alembic/versions/0009_add_api_versioning.py
"""add api versioning infrastructure

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-08
"""
from alembic import op
import sqlalchemy as sa


revision = "0009"
down_revision = "0008"


def upgrade() -> None:
    # No database changes needed - this is a code-only migration
    op.execute("SELECT 1")  # Dummy operation to satisfy Alembic


def downgrade() -> None:
    # No database changes to reverse
    pass

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Version routing is strictly isolated** | Separate `APIRouter` instances per version with distinct prefixes. Path strategy enforces `/api/v1` vs `/api/v2` path separation. Header strategy uses `version_negotiation` dependency. |
| QS-2 | **Deprecation headers are always present on v1 routes** | `DeprecationMiddleware` injects `Deprecation`, `Sunset`, and `Link` headers for all requests starting with `/api/v1`. Verified by T-07. |
| QS-3 | **OpenAPI docs are version-isolated** | Each version's OpenAPI spec only includes its own routes. Root `/openapi.json` defaults to current version. Enforced by separate FastAPI app instances per version. |
| QS-4 | **Header strategy falls back to current version** | `version_negotiation` dependency in `app/api/deps_version.py` defaults to `settings.API_CURRENT_VERSION` when no valid Accept header is present. |
| QS-5 | **No regression in v1 behavior** | All existing v1 routes are copied verbatim to `app/api/v1/` with identical request/response contracts. Verified by T-01. |
| QS-6 | **Sunset date is computed correctly** | `API_SUNSET_DATE` in `app/core/api_version.py` is set to `utcnow() + deprecation_period_days` and immutable. |
| QS-7 | **Middleware order is preserved** | `DeprecationMiddleware` is registered after auth middleware in `app/main.py` to ensure security checks run first. |
| QS-8 | **Health checks remain unversioned** | `/health` route is excluded from versioning and mounted at root level. Verified by grep for `router.include_router(health.router)` in main.py. |
| QS-9 | **Schema directories are strictly versioned** | All schemas must live in `app/schemas/v1/` or `app/schemas/v2/` with no cross-version imports. Enforced by `ast.parse` validation. |
| QS-10 | **Header parsing is case-insensitive** | `version_negotiation` dependency normalizes header values to lowercase before pattern matching. |
| QS-11 | **Idempotent tool execution** | Re-running the tool with same parameters produces identical file structure without duplicates. Verified by T-28. |
| QS-12 | **No database schema changes** | Alembic migration (if any) contains only a no-op `SELECT 1`. Enforced by schema diff in tool execution. |

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | `api_version.py` exists at `app/core/api_version.py` | File exists, contains `API_SUNSET_DATE` constant |
| CC-02 | `deprecation.py` middleware exists at `app/api/middleware/deprecation.py` | File exists, contains `DeprecationMiddleware` class |
| CC-03 | Versioned router directories exist (`app/api/v1/`, `app/api/v2/`) | Directory structure verified |
| CC-04 | All existing routes copied to `app/api/v1/` with identical signatures | grep comparison of route files |
| CC-05 | `deps_version.py` exists at `app/api/deps_version.py` | File exists, contains `version_negotiation` function |
| CC-06 | `DeprecationMiddleware` registered in `app/main.py` after auth | grep `app.add_middleware(DeprecationMiddleware` |
| CC-07 | Versioned schema directories exist (`app/schemas/v1/`, `app/schemas/v2/`) | Directory structure verified |
| CC-08 | `API_CURRENT_VERSION` and `API_NEW_VERSION` added to `settings.py` | grep in `app/core/config.py` |
| CC-09 | Main router delegates to versioned routers via prefix | Inspect `app/api/main.py` for `include_router` calls |
| CC-10 | Header strategy uses `version_negotiation` dependency | grep `deps_version.version_negotiation` in route files |
| CC-11 | `/health` route remains unversioned | grep `router.include_router(health.router)` without version prefix |
| CC-12 | OpenAPI accessible at `/api/v1/openapi.json` and `/api/v2/openapi.json` | curl both endpoints |
| CC-13 | Root `/openapi.json` defaults to current version | curl comparison |
| CC-14 | Deprecation headers present on all v1 routes | T-07 |
| CC-15 | Link header points to equivalent v2 resource | T-08 |
| CC-16 | Sunset header matches computed date | T-09 |
| CC-17 | v1 and v2 routes handle identical requests independently | T-01, T-02 |
| CC-18 | Header strategy falls back to current version | T-19 |
| CC-19 | Invalid Accept header returns 406 | T-20 |
| CC-20 | Schema directories contain no cross-version imports | ast.parse validation |
| CC-21 | All test files updated to use versioned routes | grep test files for `/api/v1/` |
| CC-22 | New test file `test_api_versioning.py` created | File exists with 30 tests |
| CC-23 | Existing test suite passes | pytest 0 failures |
| CC-24 | No regression in v1 response formats | T-03 |
| CC-25 | v2 routes can evolve independently | T-13 |
| CC-26 | Migration is no-op (no DB changes) | Inspect Alembic upgrade() |
| CC-27 | Tool execution time < 6s | Time measurement |
| CC-28 | Header parsing overhead < 0.5ms | Benchmark T-29 |
| CC-29 | Routing overhead < 0.1ms per version | Benchmark T-30 |
| CC-30 | README.md updated with versioning docs | grep "API Versioning" in README |

## 7. Definition of Done

- [ ] All 30 Completeness Criteria verified
- [ ] Test file `test_api_versioning.py` exists with 30 passing tests (T-01 to T-30)
- [ ] Existing test suite passes with 0 failures
- [ ] OpenAPI specs generated for both versions at `/api/v1/openapi.json` and `/api/v2/openapi.json`
- [ ] Deprecation headers present on all v1 routes (verified by T-07..T-09)
- [ ] Header strategy falls back to current version (verified by T-19)
- [ ] No database schema changes (verified by CC-26)
- [ ] All routes copied to `app/api/v1/` with identical behavior (verified by T-01)
- [ ] Versioned schema directories created with no cross-imports (verified by CC-20)
- [ ] Middleware registered in correct order (verified by CC-06)
- [ ] README.md updated with versioning documentation (verified by CC-30)
- [ ] Tool execution time < 6s (verified by CC-27)
- [ ] Routing and header parsing overhead within SLOs (verified by T-29, T-30)

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-VER-01 | A v1 call NEVER routes to v2 handler and vice versa | Strict router prefix separation in `app/api/main.py` | T-01, T-02 |
| INV-VER-02 | Deprecated routes ALWAYS emit `Deprecation: true` and `Sunset` headers | `DeprecationMiddleware` unconditionally adds headers | T-07, T-09 |
| INV-VER-03 | The `Link` header points to the successor version of the same resource | Middleware constructs URL with version replacement | T-08 |
| INV-VER-04 | OpenAPI per version contains ONLY that version's routes | Separate FastAPI app instances per version | T-24, T-25 |
| INV-VER-05 | Adding a new version NEVER breaks existing v1 clients | Identical v1 route behavior verified | T-01, T-03 |
| INV-VER-06 | Header strategy defaults to `current_version` when no Accept header matches | `version_negotiation` dependency fallback | T-19 |
| INV-VER-07 | Health check route remains UN-versioned | Explicit exclusion in router setup | T-05 |
| INV-VER-08 | No database schema changes occur | Alembic migration is no-op | T-28 |

---

## 9. User Stories

### 9.1 Core Versioning Functionality (US-01 .. US-05)

**US-01: Deploy parallel API versions**
- **As a** backend engineer maintaining production APIs  
- **I want** to run v1 and v2 routes simultaneously  
- **So that** clients can migrate gradually  
- **Given:** existing `/items/` route at `app/api/endpoints/items.py`  
- **When:** I call `add_api_versioning(project_dir, current_version="v1", new_version="v2")`  
- **Then:**  
  - Original route moves to `app/api/v1/endpoints/items.py`  
  - Copy created at `app/api/v2/endpoints/items.py`  
  - Both accessible via `/api/v1/items/` and `/api/v2/items/`  
  - OpenAPI docs show both versions  

**US-02: Deprecate old versions gracefully**  
- **As a** API product manager  
- **I want** v1 routes to warn clients of sunsetting  
- **So that** teams have 180 days to migrate  
- **Given:** request to `/api/v1/items/`  
- **When:** DeprecationMiddleware processes the response  
- **Then:**  
  - Headers include `Deprecation: true`  
  - `Sunset: 2026-10-05T00:00:00Z` (today + 180 days)  
  - `Link: </api/v2/items/>; rel="successor-version"`  

**US-03: Maintain v1 behavior exactly**  
- **As a** mobile app developer  
- **I want** v1 responses to remain unchanged  
- **So that** my app doesn't break  
- **Given:** legacy client calling `GET /api/v1/items/123`  
- **When:** Response returns 200 OK  
- **Then:**  
  - Body matches pre-versioning schema exactly  
  - No new fields added/removed  
  - Field types identical (INV-VER-05)  

**US-04: Evolve v2 independently**  
- **As a** API designer  
- **I want** to modify v2 schemas freely  
- **So that** I can improve the contract  
- **Given:** `app/schemas/v2/item.py`  
- **When:** I add `tags: list[str]` field to `ItemOut`  
- **Then:**  
  - v1 schema remains unchanged  
  - v2 OpenAPI reflects new field  
  - No impact on v1 clients  

**US-05: Keep health checks global**  
- **As a** SRE monitoring services  
- **I want** `/health` to work without versioning  
- **So that** load balancers get consistent responses  
- **Given:** request to `/health`  
- **When:** Server processes the request  
- **Then:**  
  - Returns 200 OK with `{"status": "ok"}`  
  - Not prefixed with `/api/v1/health`  
  - No deprecation headers (INV-VER-07)  

### 9.2 Version Negotiation Strategies (US-06 .. US-10)

**US-06: Path-based version selection**  
- **As a** web developer  
- **I want** to access versions via URL paths  
- **So that** I can bookmark specific versions  
- **Given:** `strategy="path"` configuration  
- **When:** I call `GET /api/v2/items/`  
- **Then:**  
  - Routes through v2 handler  
  - No version headers required  
  - OpenAPI docs show path variants  

**US-07: Header-based content negotiation**  
- **As a** API client library author  
- **I want** to use Accept headers  
- **So that** URLs stay clean  
- **Given:** `strategy="header"` configuration  
- **When:** Request has `Accept: application/vnd.app.v2+json`  
- **Then:**  
  - Routes to v2 handler at `/api/items/`  
  - No path prefix required  
  - Falls back to v1 if header missing (INV-VER-06)  

**US-08: Reject invalid versions**  
- **As a** security engineer  
- **I want** malformed versions to fail fast  
- **So that** clients don't get undefined behavior  
- **Given:** request with `Accept: application/vnd.app.v3+json`  
- **When:** Header strategy processes the request  
- **Then:**  
  - Returns 406 Not Acceptable  
  - Error lists valid versions: `["v1", "v2"]`  
  - No route handler executed  

**US-09: Default to current version**  
- **As a** legacy client  
- **I want** to omit version headers  
- **So that** I don't need immediate updates  
- **Given:** request to `/api/items/` with no Accept header  
- **When:** Header strategy processes the request  
- **Then:**  
  - Routes to v1 handler  
  - Returns 200 OK with v1 schema  
  - Adds `Warning: 299 - Defaulting to v1`  

**US-10: Support both strategies simultaneously**  
- **As a** migration coordinator  
- **I want** clients to use either paths or headers  
- **So that** teams can transition gradually  
- **Given:** `GET /api/v2/items/` with `Accept: application/vnd.app.v1+json`  
- **When:** Both strategies conflict  
- **Then:**  
  - Path takes precedence (returns v2 response)  
  - Adds `Warning: 299 - Path overrides header`  
  - Still includes deprecation headers if calling v1  

### 9.3 Schema Evolution Patterns (US-11 .. US-15)

**US-11: Rename fields in v2**  
- **As a** schema designer  
- **I want** to change `user_id` to `owner_id` in v2  
- **So that** terminology matches our domain  
- **Given:** `app/schemas/v2/item.py`  
- **When:** I update `ItemOut` field names  
- **Then:**  
  - v1 schema remains unchanged  
  - CRUD layer maps `owner_id` ↔ `user_id`  
  - OpenAPI docs show new field name  

**US-12: Add optional fields in v2**  
- **As a** product owner  
- **I want** to extend item responses with metadata  
- **So that** clients can opt into new features  
- **Given:** v2 `ItemOut` schema  
- **When:** I add `metadata: dict[str, str] = None`  
- **Then:**  
  - v1 responses omit the field  
  - v2 responses include null/values  
  - DB schema unchanged (INV-VER-08)  

**US-13: Remove deprecated fields**  
- **As a** platform architect  
- **I want** to drop legacy `location_code` in v2  
- **So that** we simplify responses  
- **Given:** v1 has required `location_code` field  
- **When:** I remove it from `app/schemas/v2/item.py`  
- **Then:**  
  - v1 still requires the field  
  - v2 CRUD ignores the column  
  - Migration guide warns clients  

**US-14: Change field types**  
- **As a** data modeler  
- **I want** to change `status` from str to Enum  
- **So that** we enforce valid values  
- **Given:** v1 uses `status: str`  
- **When:** v2 defines `status: ItemStatus` Enum  
- **Then:**  
  - v1 accepts any string  
  - v2 validates against enum values  
  - DB stores original strings  

**US-15: Version-specific validation**  
- **As a** API developer  
- **I want** to add stricter rules in v2  
- **So that** we improve data quality  
- **Given:** v1 allows `title: str` (any length)  
- **When:** v2 adds `Field(max_length=255)`  
- **Then:**  
  - v1 keeps legacy behavior  
  - v2 rejects overlong titles with 422  
  - DB schema unchanged  

### 9.4 Operational Concerns (US-16 .. US-20)

**US-16: Monitor version adoption**  
- **As a** product analyst  
- **I want** to track v1/v2 usage  
- **So that** we can sunset v1 safely  
- **Given:** Prometheus metrics endpoint  
- **When:** Requests hit `/api/v1/` or `/api/v2/`  
- **Then:**  
  - `api_requests_total{version="v1"}` increments  
  - `api_requests_total{version="v2"}` increments  
  - Dashboard shows migration progress  

**US-17: Document sunset timeline**  
- **As a** technical writer  
- **I want** auto-generated deprecation notices  
- **So that** clients see deadlines  
- **Given:** `deprecation_period_days=180`  
- **When:** I check `/api/v1/openapi.json`  
- **Then:**  
  - Includes `x-sunset-date: 2026-10-05`  
  - Marked as `deprecated: true`  
  - Lists v2 equivalents for all paths  

**US-18: Handle preflight requests**  
- **As a** frontend developer  
- **I want** CORS to work on versioned routes  
- **So that** browsers can call the API  
- **Given:** OPTIONS request to `/api/v2/items/`  
- **When:** CORS middleware processes it  
- **Then:**  
  - Returns 204 No Content  
  - Includes `Access-Control-Allow-Methods: GET,POST`  
  - Version headers preserved  

**US-19: Version-aware logging**  
- **As a** DevOps engineer  
- **I want** logs to include the API version  
- **So that** I can debug issues  
- **Given:** request to `/api/v2/items/`  
- **When:** Server logs the call  
- **Then:**  
  - Log line includes `api_version="v2"`  
  - Error traces show version context  
  - Metrics tagged appropriately  

**US-20: Automated client SDK generation**  
- **As a** SDK maintainer  
- **I want** to generate versioned clients  
- **So that** users get type-safe bindings  
- **Given:** `/api/v2/openapi.json`  
- **When:** I run `openapi-generator`  
- **Then:**  
  - Produces `ClientV2` class  
  - Methods match v2 routes exactly  
  - Types reflect v2 schemas  

### 9.5 Performance & Edge Cases (US-21 .. US-25)

**US-21: Minimal routing overhead**  
- **As a** performance engineer  
- **I want** version checks to be fast  
- **So that** latency stays low  
- **Given:** 1000 RPS to `/api/v1/items/`  
- **When:** I benchmark with/without versioning  
- **Then:**  
  - P99 latency increase < 0.1ms (INV-VER-01)  
  - Throughput reduction < 1%  
  - No added GC pressure  

**US-22: Handle missing successors**  
- **As a** API maintainer  
- **I want** graceful handling of removed endpoints  
- **So that** clients get clear errors  
- **Given:** v1 has `/legacy` route not in v2  
- **When:** Request hits `/api/v1/legacy`  
- **Then:**  
  - Still returns 200 with deprecation headers  
  - `Link` header omitted (no successor)  
  - Docs mark route as sunset-only  

**US-23: Versioned static files**  
- **As a** full-stack developer  
- **I want** to serve different frontends per version  
- **So that** UIs match API contracts  
- **Given:** `app/static/v1/index.html`  
- **When:** Request hits `/api/v1/static/index.html`  
- **Then:**  
  - Serves v1 assets  
  - v2 requests get matching assets  
  - Unversioned `/static/` returns 404  

**US-24: Handle proxy rewrites**  
- **As a** cloud architect  
- **I want** to run behind path-stripping proxies  
- **So that** we can use standard ingress  
- **Given:** proxy removes `/api/v1` prefix  
- **When:** Request arrives at `/items/` with `X-Forwarded-Prefix: /api/v1`  
- **Then:**  
  - Routes to v1 handler  
  - Deprecation headers added  
  - Logs show full path  

**US-25: Cold start performance**  
- **As a** serverless deployer  
- **I want** fast startup with versioning  
- **So that** cold starts aren't penalized  
- **Given:** Lambda function with 10 routes  
- **When:** I measure initialization time  
- **Then:**  
  - Adds < 50ms to cold start  
  - Memory overhead < 1MB (INV-VER-08)  
  - No dynamic version resolution at runtime

---

## 10. Test Plan

### 10.1 Routing & Version Isolation

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | v1 routes hit v1 handlers | Existing `/items/` route moved to v1 | GET /api/v1/items/ | 200, matches pre-versioning response |
| T-02 | v2 routes hit v2 handlers | New `/items/` route in v2 | GET /api/v2/items/ | 200, may differ from v1 response |
| T-03 | Cross-version routing fails | Item exists in v1 | GET /api/v2/items/{v1_item_id} | 404 |
| T-04 | Health check remains global | Existing `/health` route | GET /health | 200, {"status": "ok"}, no version prefix |
| T-05 | Root OpenAPI defaults to current | Both versions deployed | GET /openapi.json | Matches /api/v1/openapi.json |
| T-06 | Versioned OpenAPI isolation | Both versions deployed | GET /api/v1/openapi.json vs /api/v2/openapi.json | Different paths, no overlap |

### 10.2 Deprecation Headers

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-07 | Deprecation header present | Request to v1 route | GET /api/v1/items/ | Deprecation: true |
| T-08 | Sunset header matches config | deprecation_period_days=180 | GET /api/v1/items/ | Sunset: today + 180 days in ISO format |
| T-09 | Link header points to successor | Request to v1 route | GET /api/v1/items/123 | Link: </api/v2/items/123>; rel="successor-version" |
| T-10 | No deprecation headers on v2 | Request to v2 route | GET /api/v2/items/ | No Deprecation, Sunset, or Link headers |
| T-11 | Missing successor omits Link | v1 route /legacy has no v2 equivalent | GET /api/v1/legacy | Deprecation: true, no Link header |
| T-12 | Middleware order preserved | Request to v1 route | GET /api/v1/items/ | Auth headers processed before DeprecationMiddleware |

### 10.3 Schema Isolation

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-13 | v1 schema unchanged | Existing Item schema | GET /api/v1/items/123 | Matches pre-versioning schema |
| T-14 | v2 schema evolves independently | Added tags field in v2 | GET /api/v2/items/123 | Includes tags field |
| T-15 | Cross-version schema imports fail | Attempt to import v2 schema in v1 | Import in v1 route | ImportError |
| T-16 | Field rename in v2 | Renamed user_id → owner_id in v2 | GET /api/v2/items/123 | owner_id field present |
| T-17 | Optional field in v2 | Added metadata field in v2 | GET /api/v2/items/123 | metadata field optional |
| T-18 | Removed field in v2 | Removed location_code in v2 | GET /api/v2/items/123 | No location_code field |

### 10.4 Header Strategy

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-19 | Fallback to current version | No Accept header | GET /api/items/ | Routes to v1 handler |
| T-20 | Invalid version returns 406 | Accept: application/vnd.app.v3+json | GET /api/items/ | 406, lists valid versions |
| T-21 | Header takes precedence | Path: /api/v1/items/, Accept: application/vnd.app.v2+json | GET /api/v1/items/ | Routes to v2 handler |
| T-22 | Case-insensitive header | Accept: APPLICATION/VND.APP.V2+JSON | GET /api/items/ | Routes to v2 handler |
| T-23 | Missing vendor type defaults | Accept: application/json | GET /api/items/ | Routes to v1 handler |
| T-24 | Header strategy OpenAPI | Header strategy enabled | GET /api/openapi.json | Shows single path /api/items/ |

### 10.5 Idempotency & Performance

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-25 | Tool re-run is no-op | Versioning already enabled | Run tool again | No file changes, notes "skipped" |
| T-26 | Routing overhead benchmark | 1000 RPS to /api/v1/items/ | Measure latency | P99 increase < 0.1ms |
| T-27 | Header parsing overhead | 1000 RPS with Accept header | Measure latency | P99 increase < 0.5ms |
| T-28 | No DB schema changes | Existing DB schema | Inspect Alembic migration | No schema changes |
| T-29 | Cold start performance | Lambda deployment | Measure initialization time | Adds < 50ms to cold start |
| T-30 | OpenAPI generation time | Both versions deployed | Measure OpenAPI generation | < 200ms per version |

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|----------------|-------------|-------|
| `add_multi_tenancy` | Yes | Versioning must be added AFTER multi-tenancy | Versioned routes inherit tenant isolation |
| `add_soft_delete` | No | Soft delete works per version | v1 and v2 can have different soft delete behaviors |
| `add_audit_log` | No | Audit logs capture version context | Logs include `api_version` field |
| `add_rbac` | No | RBAC applies to all versions | Roles/permissions are version-agnostic |
| `add_api_key_auth` | No | API keys work across versions | Key validation happens before version routing |
| `add_oauth2_provider` | No | OAuth2 tokens valid for all versions | Token scopes are version-agnostic |
| `add_mfa` | No | MFA applies to all versions | Authentication happens before version routing |
| `add_cache_layer` | Yes | Cache must be version-aware | Cache keys must include version prefix |
| `add_circuit_breaker` | No | Circuit breakers apply per version | v1 and v2 have independent failure states |

**Conflicts:** None identified.

## 12. Rollback Procedure

### Code rollback (before deploy)
```bash
# Remove versioned directories
rm -rf app/api/v1/ app/api/v2/ app/schemas/v1/ app/schemas/v2/

# Restore original router
git checkout app/api/main.py

# Remove middleware registration
sed -i '/DeprecationMiddleware/d' app/main.py

# Remove version config
sed -i '/API_CURRENT_VERSION/d' app/core/config.py
sed -i '/API_NEW_VERSION/d' app/core/config.py
sed -i '/API_DEPRECATION_PERIOD_DAYS/d' app/core/config.py
```

### Database rollback (after deploy)
```sql
-- No database changes to rollback
SELECT 1;
```

### Data preservation rollback
```bash
# No data migration occurred
echo "No data changes to rollback"
```

### Failure mode: tool partially modified files
```bash
# Restore from backup
cp -r backup/app/ app/
cp backup/alembic/versions/0009_add_api_versioning.py alembic/versions/
```

### Emergency: Sunset date passed but v1 still active
```bash
# Extend sunset date by 30 days
sed -i "s/API_SUNSET_DATE=.*/API_SUNSET_DATE=$(date -d '+30 days' +%Y-%m-%d)/" app/core/api_version.py
```

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-1 | Project has no existing routes | Tool errors: "No routes found. Add at least one route first." |
| EC-2 | New version label collides with existing | Tool errors: "Version v2 already exists. Choose a different label." |
| EC-3 | Strategy=header but client sends both Accept and v1 path | Path takes precedence; adds Warning: 299 - Path overrides header |
| EC-4 | Sunset date in the past | Tool errors: "deprecation_period_days must be positive. Got: -30" |
| EC-5 | Two routes have same path in v1 but different in v2 | Tool preserves v1 routes exactly; v2 routes can diverge |
| EC-6 | v2 route uses schema that doesn't exist in v1 | Tool creates empty v2 schema directory; developer must implement |
| EC-7 | Removing v1 route that v2 doesn't have successor for | Deprecation headers added but Link header omitted |
| EC-8 | OpenAPI generation for empty version | Returns valid OpenAPI with empty paths array |
| EC-9 | Versioned middleware order | Tool ensures DeprecationMiddleware runs AFTER auth middleware |
| EC-10 | Reverse proxy strips /api/v1 prefix | Middleware reads X-Forwarded-Prefix if available |
| EC-11 | CORS preflight on versioned route | Returns 204 with Access-Control-Allow-Methods including version |
| EC-12 | Client sends Accept: application/json | Routes to current version; adds Warning: 299 - Defaulting to v1 |
| EC-13 | Health check route should be UN-versioned | Tool excludes /health from versioning; mounts at root |
| EC-14 | New version has different auth scheme | Tool preserves existing auth; developer must implement new scheme |
| EC-15 | Versioned schemas with circular references | Tool creates separate schema directories; developer must resolve cycles |

## 14. Acceptance Criteria (Final Sign-off)

✅ 1. All 30 Completeness Criteria verified  
✅ 2. Test file `test_api_versioning.py` exists with 30 passing tests  
✅ 3. Existing test suite passes with 0 failures  
✅ 4. OpenAPI specs generated for both versions at `/api/v1/openapi.json` and `/api/v2/openapi.json`  
✅ 5. Deprecation headers present on all v1 routes (verified by T-07..T-09)  
✅ 6. Header strategy falls back to current version (verified by T-19)  
✅ 7. No database schema changes (verified by CC-26)  
✅ 8. All routes copied to `app/api/v1/` with identical behavior (verified by T-01)  
✅ 9. Versioned schema directories created with no cross-imports (verified by CC-20)  
✅ 10. Developer manually evolves v2 `/items` route by adding `tags: list[str]` field and verifies v1 remains unchanged  

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks
- [ ] Validate `project_dir` exists
- [ ] Validate `app/` subdirectory exists
- [ ] Validate at least one route exists
- [ ] Parse existing routes with AST
- [ ] Detect existing versioning infrastructure
- [ ] Validate `deprecation_period_days` > 0

### 15.2 Version config
- [ ] Create `app/core/api_version.py`
- [ ] Add `API_SUNSET_DATE` constant
- [ ] Add version settings to `app/core/config.py`
- [ ] Verify files parse

### 15.3 Middleware
- [ ] Create `app/api/middleware/deprecation.py`
- [ ] Implement `DeprecationMiddleware`
- [ ] Register middleware in `app/main.py`
- [ ] Ensure middleware runs AFTER auth
- [ ] Verify file parses

### 15.4 Versioned routers
- [ ] Create `app/api/v1/` directory
- [ ] Create `app/api/v2/` directory
- [ ] Copy existing routes to `app/api/v1/`
- [ ] Create empty routes in `app/api/v2/`
- [ ] Modify `app/api/main.py` to delegate to versioned routers

### 15.5 Header strategy
- [ ] Create `app/api/deps_version.py`
- [ ] Implement `version_negotiation` dependency
- [ ] Add header parsing logic
- [ ] Verify file parses

### 15.6 Schema isolation
- [ ] Create `app/schemas/v1/` directory
- [ ] Create `app/schemas/v2/` directory
- [ ] Copy existing schemas to `app/schemas/v1/`
- [ ] Create empty schemas in `app/schemas/v2/`
- [ ] Verify no cross-version imports

### 15.7 CRUD adaptation
- [ ] Add version context to CRUD operations
- [ ] Implement field translation for v1 → v2
- [ ] Verify CRUD files parse

### 15.8 OpenAPI config
- [ ] Configure separate OpenAPI instances per version
- [ ] Set root `/openapi.json` to default to current version
- [ ] Verify OpenAPI generation works

### 15.9 Test generation
- [ ] Create `tests/test_api_versioning.py`
- [ ] Generate all 30 test cases
- [ ] Use existing fixtures
- [ ] Verify file parses

### 15.10 Documentation
- [ ] Append versioning section to `core/KNOWLEDGE.md`
- [ ] Add tool entry to `manifest.yaml`
- [ ] Add tool to `SKILL.md` tools table
- [ ] Update `mcp_server.py` with new MCP tool decorator

### 15.11 Atomicity
- [ ] All file writes use temp-file + rename pattern
- [ ] Track touched files for rollback
- [ ] Return `{files_created, files_modified, files_rolled_back, error}` on failure

### 15.12 Verification
- [ ] Run `ast.parse` on every modified file
- [ ] Run import audit on the project
- [ ] Run `pytest tests/` to verify no regressions
- [ ] Measure tool execution time
- [ ] Measure version routing overhead
- [ ] Return success report with metrics

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
    "lines_added": 842,
    "lines_removed": 32,
    "current_version": "v1",
    "new_version": "v2",
    "deprecation_period_days": 180
  },
  "next_steps": [
    "Run: pytest tests/test_api_versioning.py -v",
    "Test: curl -I /api/v1/items/123 | grep Deprecation",
    "Verify: diff app/api/v1/main.py app/api/v2/main.py",
    "Check: curl /api/v1/openapi.json",
    "Evolve: Add tags field to v2 Item schema"
  ],
  "warnings": [
    "CORS preflight requests must include version headers",
    "Sunset date is 2026-10-05 - plan migration accordingly"
  ],
  "notes": [
    "API versioning enabled with strategy=path",
    "DeprecationMiddleware registered after auth middleware",
    "v1 routes preserved exactly in app/api/v1/",
    "v2 routes initialized as copies in app/api/v2/",
    "OpenAPI docs available at /api/v1/openapi.json and /api/v2/openapi.json",
    "Existing tests still pass: 47/47"
  ]
}
