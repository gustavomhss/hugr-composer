<!--
{
  "tool_num": "017",
  "tool_name": "add_api_versioning",
  "model": "deepseek/deepseek-chat",
  "elapsed_seconds": 547.8067860838491,
  "prompt_tokens": 47251,
  "completion_tokens": 10168,
  "cost_usd": 0.05397121,
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
| Dependencies | FastAPI 0.95+, Starlette, Alembic (optional), Python 3.8+ |
| Signature | `add_api_versioning(project_dir: str, current_version: str = "v1", new_version: str = "v2", strategy: Literal["path", "header"] = "path", deprecation_period_days: int = 180, rename_map: Optional[Dict[str, Dict[str, str]]] = None) -> dict` |
| Parameters | `project_dir`: Absolute path containing `app/` and `tests/` (e.g. `/code/project`)<br>`current_version`: Label for existing API routes (default `"v1"`, must match existing route prefixes)<br>`new_version`: Label for new API version (default `"v2"`, must be unique)<br>`strategy`: Version selection method - `"path"` for `/api/v1/resource` or `"header"` for `Accept: application/vnd.company.v2+json`<br>`deprecation_period_days`: Days until v1 routes are removed (default 180, minimum 30)<br>`rename_map`: Field renames between versions (e.g. `{"User": {"old_name": "new_name"}}`) |

## 2. Purpose

This tool implements production-grade API versioning for FastAPI applications, enabling safe evolution of APIs without breaking existing clients. It solves critical versioning challenges by creating isolated route handlers (`/api/v1/users` vs `/api/v2/users`), version-specific Pydantic schemas, and automatic deprecation headers for old versions. The implementation maintains backward compatibility through a translation layer that converts v2 responses to v1 format, while allowing gradual migration to new schemas. Versioning works through either URL paths (default) or content negotiation headers, with complete OpenAPI documentation generated per version and clear sunset timelines communicated via HTTP headers.

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 8s | Complex file operations and validations |
| Files modified | 4-6 files | Main app router, config, middleware registration |
| Files created | 9-12 files | Version routers, schemas, tests, middleware |
| Path routing overhead | < 0.2 ms | FastAPI router prefix matching |
| Header parsing latency | < 1.0 ms | Accept header parsing and validation |
| Migration runtime | 0s | Pure code changes, no DB operations |
| OpenAPI generation time | < 300 ms per version | Separate spec generation |
| Memory overhead | < 2 MB per worker | Versioned router and schema storage |
| Response latency penalty | < 0.5 ms | Deprecation middleware processing |
| Concurrent version support | ≥ 3 active versions | Router isolation design |

---

## 4. Code Examples (Before / After)

### 4.1 Main router: BEFORE
```python
# app/main.py
from fastapi import FastAPI
from app.api.main import router as api_router
from app.core.config import settings

app = FastAPI(title=settings.PROJECT_NAME)
app.include_router(api_router, prefix="/api")
```

### 4.2 Main router: AFTER
```python
# app/main.py
from fastapi import FastAPI
from app.api.v1.main import router as v1_router
from app.api.v2.main import router as v2_router
from app.api.middleware.deprecation import DeprecationMiddleware
from app.core.config import settings

app = FastAPI(title=settings.PROJECT_NAME)
app.add_middleware(DeprecationMiddleware)
app.include_router(v1_router, prefix=f"/api/{settings.API_CURRENT_VERSION}")
app.include_router(v2_router, prefix=f"/api/{settings.API_NEW_VERSION}")
```

### 4.3 Versioned router (NEW)
```python
# app/api/v2/main.py
from fastapi import APIRouter
from app.api.v2.endpoints import items, users

router = APIRouter()
router.include_router(items.router, prefix="/items", tags=["v2 items"])
router.include_router(users.router, prefix="/users", tags=["v2 users"])
```

### 4.4 Header strategy dependency (NEW)
```python
# app/api/deps_version.py
from fastapi import Header, HTTPException
from typing import Annotated
from app.core.config import settings

def get_api_version(
    accept: Annotated[str, Header()] = "application/json"
) -> str:
    """Parse Accept header for versioned media types"""
    if "vnd.company.v2+json" in accept:
        return "v2"
    if "vnd.company.v1+json" in accept:
        return "v1"
    if accept == "application/json":
        return settings.API_CURRENT_VERSION
    raise HTTPException(
        status_code=406,
        detail=f"Unsupported Accept header. Valid types: application/json, application/vnd.company.v1+json, application/vnd.company.v2+json"
    )
```

### 4.5 Versioned schema with field changes (NEW)
```python
# app/schemas/v2/item.py
from pydantic import BaseModel, Field
from datetime import datetime
from uuid import UUID
from typing import Optional


class ItemBase(BaseModel):
    name: str = Field(..., max_length=255, alias="title")  # renamed field
    description: Optional[str] = Field(None, max_length=2048)  # longer length
    tags: list[str] = Field(default_factory=list)  # new field


class ItemCreate(ItemBase):
    pass


class Item(ItemBase):
    id: UUID
    owner_id: UUID 
    created_at: datetime
    updated_at: datetime  # new field

    class Config:
        from_attributes = True
        populate_by_name = True
```

### 4.6 Deprecation middleware (NEW)
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
        path = request.url.path
        if any(path.startswith(f"/api/{v}") for v in settings.API_DEPRECATED_VERSIONS):
            response.headers.update({
                "Deprecation": "true",
                "Sunset": settings.API_SUNSET_DATES["v1"].strftime("%a, %d %b %Y %H:%M:%S GMT"),
                "Link": f'<{path.replace("v1", "v2")}>; rel="successor-version"',
                "Warning": '299 - "Deprecated API version"'
            })
        return response
```

### 4.7 Versioned endpoint: BEFORE
```python
# app/api/endpoints/items.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.item import Item as DBItem
from app.schemas.item import Item, ItemCreate
from app.core.deps import get_db

router = APIRouter()

@router.post("/", response_model=Item)
async def create_item(
    *, db: AsyncSession = Depends(get_db), item_in: ItemCreate
):
    db_item = DBItem(**item_in.dict())
    db.add(db_item)
    await db.commit()
    await db.refresh(db_item)
    return db_item
```

### 4.8 Versioned endpoint: AFTER
```python
# app/api/v2/endpoints/items.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.item import Item as DBItem
from app.schemas.v2.item import Item, ItemCreate
from app.core.deps import get_db
from datetime import datetime

router = APIRouter()

@router.post("/", response_model=Item)
async def create_item_v2(
    *, db: AsyncSession = Depends(get_db), item_in: ItemCreate
):
    db_item = DBItem(
        title=item_in.name,  # field rename handled
        description=item_in.description,
        tags=",".join(item_in.tags),  # new field
        updated_at=datetime.utcnow()  # new field
    )
    db.add(db_item)
    await db.commit()
    await db.refresh(db_item)
    return db_item
```

### 4.9 Versioned config (NEW)
```python
# app/core/config.py
from datetime import datetime, timedelta
from typing import Dict
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    API_CURRENT_VERSION: str = "v2"
    API_DEPRECATED_VERSIONS: list[str] = ["v1"]
    API_SUNSET_DATES: Dict[str, datetime] = {
        "v1": datetime.utcnow() + timedelta(days=180)
    }
    API_VERSION_STRATEGY: str = "path"  # or "header"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
```

### 4.10 Schema translation layer (NEW)
```python
# app/core/schema_translation.py
from typing import Type, Any
from pydantic import BaseModel
from app.schemas.v1.item import Item as V1Item
from app.schemas.v2.item import Item as V2Item


def translate_schema(
    source: BaseModel, target_model: Type[BaseModel]
) -> BaseModel:
    """Convert between versioned schemas using field mappings"""
    if isinstance(source, V2Item) and target_model is V1Item:
        return V1Item(
            title=source.name,
            description=source.description,
            id=source.id,
            owner_id=source.owner_id,
            created_at=source.created_at
        )
    elif isinstance(source, V1Item) and target_model is V2Item:
        return V2Item(
            name=source.title,
            description=source.description,
            id=source.id,
            owner_id=source.owner_id,
            created_at=source.created_at,
            updated_at=source.created_at,
            tags=[]
        )
    raise ValueError(f"No translation path from {type(source)} to {target_model}")

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | Versioned routes NEVER leak between versions | Separate `APIRouter` instances with isolated route tables and prefix validation. Verified by T-01, T-02 |
| QS-2 | Deprecated routes ALWAYS emit `Deprecation`, `Sunset`, and `Link` headers | `DeprecationMiddleware` adds headers unconditionally for paths matching `settings.API_DEPRECATED_VERSIONS`. Verified by T-07 |
| QS-3 | OpenAPI per version contains ONLY that version's routes | Separate OpenAPI routers with isolated route collections and version-specific tags. Verified by T-24 |
| QS-4 | Adding a new version NEVER breaks existing v1 clients | v1 routes copied verbatim to `app/api/v1/` with identical path signatures. Verified by T-03 |
| QS-5 | Header strategy defaults to `current_version` when no Accept header matches | `VersionHeaderDependency` falls back to `settings.API_CURRENT_VERSION` for `application/json`. Verified by T-19 |
| QS-6 | Versioned schemas are NEVER shared across versions | Separate schema directories (`app/schemas/v1/`, `app/schemas/v2/`) with import isolation. Verified by T-13 |
| QS-7 | Deprecation middleware runs AFTER auth middleware | Middleware registration order in `app/main.py` ensures auth runs first. Verified by T-09 |
| QS-8 | Health check route is NEVER versioned | `/health` route mounted at root router with explicit exclusion from versioning. Verified by T-13 |
| QS-9 | Version labels MUST match `^v\d+$` regex | `add_api_versioning()` validates version labels against regex at runtime. Verified by T-28 |
| QS-10 | Sunset date MUST be in the future | `settings.API_SUNSET_DATE` validated against current time with minimum 30-day window. Verified by T-08 |
| QS-11 | Versioned routes MUST maintain same auth scheme as original | Auth dependencies copied verbatim to versioned routes with identical scopes. Verified by T-14 |
| QS-12 | Field renames MUST preserve backward compatibility | Schema translation layer converts v2 responses to v1 format using `rename_map`. Verified by T-16 |

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | `app/api/v1/` directory exists with all existing routes | Directory exists, routes copied verbatim |
| CC-02 | `app/api/v2/` directory exists with copied routes | Directory exists, routes match v1 layout |
| CC-03 | `app/schemas/v1/` directory exists with copied schemas | Directory exists, schemas match original |
| CC-04 | `app/schemas/v2/` directory exists with copied schemas | Directory exists, schemas match v1 layout |
| CC-05 | `DeprecationMiddleware` registered in `app/main.py` | grep `app.add_middleware(DeprecationMiddleware` |
| CC-06 | `VersionHeaderDependency` exists in `app/api/deps_version.py` | File exists, exports verified |
| CC-07 | `settings.API_CURRENT_VERSION` exists in `app/core/config.py` | grep `API_CURRENT_VERSION` |
| CC-08 | `settings.API_NEW_VERSION` exists in `app/core/config.py` | grep `API_NEW_VERSION` |
| CC-09 | `settings.API_SUNSET_DATE` exists in `app/core/config.py` | grep `API_SUNSET_DATE` |
| CC-10 | `/health` route mounted at root router | grep `router.include_router(health.router, prefix="/health"` |
| CC-11 | `app/api/v1/main.py` mounts all v1 routes | Inspect `router.include_router()` calls |
| CC-12 | `app/api/v2/main.py` mounts all v2 routes | Inspect `router.include_router()` calls |
| CC-13 | `DeprecationMiddleware` adds headers for deprecated paths | Inspect middleware implementation |
| CC-14 | `VersionHeaderDependency` falls back to current version | Inspect dependency implementation |
| CC-15 | `tests/test_api_versioning.py` exists with 30 tests | File exists, tests verified |
| CC-16 | Existing test suite passes | pytest 0 failures |
| CC-17 | `app/api/v1/` routes match original layout | Diff routes against original |
| CC-18 | `app/api/v2/` routes match v1 layout | Diff routes against v1 |
| CC-19 | `app/schemas/v1/` schemas match original | Diff schemas against original |
| CC-20 | `app/schemas/v2/` schemas match v1 layout | Diff schemas against v1 |
| CC-21 | `DeprecationMiddleware` runs after auth middleware | Inspect middleware registration order |
| CC-22 | OpenAPI per version contains only that version's routes | Curl `/api/v1/openapi.json`, `/api/v2/openapi.json` |
| CC-23 | Root OpenAPI defaults to current version | Curl `/openapi.json` |
| CC-24 | Version labels match `^v\d+$` regex | Inspect version label validation |
| CC-25 | Sunset date is in the future | Inspect `settings.API_SUNSET_DATE` validation |
| CC-26 | Versioned routes maintain same auth scheme as original | Inspect auth dependencies |
| CC-27 | `DeprecationMiddleware` adds `Link` header to successor version | Inspect middleware implementation |
| CC-28 | `DeprecationMiddleware` adds `Sunset` header with correct date | Inspect middleware implementation |
| CC-29 | `DeprecationMiddleware` adds `Deprecation` header | Inspect middleware implementation |
| CC-30 | Tool execution time < 6s | Time measurement |
| CC-31 | Schema translation layer exists in `app/core/schema_translation.py` | File exists, exports verified |
| CC-32 | `rename_map` parameter is validated against existing schemas | Inspect schema field validation |
| CC-33 | Versioned routes support CORS preflight requests | Inspect CORS middleware registration |

## 7. Definition of Done (DoD)

- [ ] All 33 Completeness Criteria verified
- [ ] Existing test suite passes with 0 failures
- [ ] New `tests/test_api_versioning.py` created with 30 tests
- [ ] `app/api/v1/` directory exists with all existing routes
- [ ] `app/api/v2/` directory exists with copied routes
- [ ] `app/schemas/v1/` directory exists with copied schemas
- [ ] `app/schemas/v2/` directory exists with copied schemas
- [ ] `DeprecationMiddleware` registered in `app/main.py`
- [ ] `VersionHeaderDependency` exists in `app/api/deps_version.py`
- [ ] `settings.API_CURRENT_VERSION` exists in `app/core/config.py`
- [ ] `settings.API_NEW_VERSION` exists in `app/core/config.py`
- [ ] `settings.API_SUNSET_DATE` exists in `app/core/config.py`
- [ ] `/health` route mounted at root router
- [ ] Schema translation layer exists in `app/core/schema_translation.py`

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-VER-01 | A v1 call NEVER routes to v2 handler and vice versa | Separate `APIRouter` instances with isolated route tables | T-01, T-02 |
| INV-VER-02 | Deprecated routes ALWAYS emit `Deprecation`, `Sunset`, and `Link` headers | `DeprecationMiddleware` adds headers unconditionally for deprecated paths | T-07, T-08 |
| INV-VER-03 | OpenAPI per version contains ONLY that version's routes | Separate OpenAPI routers with version-specific tags | T-24, T-25 |
| INV-VER-04 | Adding a new version NEVER breaks existing v1 clients | v1 routes copied verbatim with identical path signatures | T-03, T-04 |
| INV-VER-05 | Header strategy defaults to `current_version` when no Accept header matches | `VersionHeaderDependency` falls back to `settings.API_CURRENT_VERSION` | T-19, T-20 |
| INV-VER-06 | Versioned schemas are NEVER shared across versions | Separate schema directories with import isolation | T-13, T-14 |
| INV-VER-07 | Deprecation middleware runs AFTER auth middleware | Middleware registration order in `app/main.py` | T-09, T-10 |
| INV-VER-08 | Field renames MUST preserve backward compatibility | Schema translation layer converts v2 responses to v1 format | T-16, T-17 |

---

## 9. User Stories

### 9.1 Core Versioning Functionality (US-01 .. US-05)

**US-01: Create isolated version routers**
- **As a** API developer
- **I want** separate routers for each version
- **So that** v1 and v2 routes never interfere
- **Given:** project with `/api/items` route
- **When:** I call `add_api_versioning(project_dir="/code/myapp")`
- **Then:**
  - `app/api/v1/main.py` created with original routes (INV-VER-01)
  - `app/api/v2/main.py` created with copied routes (CC-02)
  - Routers mounted at `/api/v1` and `/api/v2` respectively (INV-VER-06)

**US-02: Generate versioned schemas**
- **As a** schema maintainer
- **I want** separate schema directories
- **So that** v1 and v2 models evolve independently
- **Given:** `app/schemas/item.py` exists
- **When:** I run `add_api_versioning()`
- **Then:**
  - `app/schemas/v1/item.py` created with original schema (CC-03)
  - `app/schemas/v2/item.py` created with copied schema (CC-04)
  - Schemas imported only from their version directory (INV-VER-06)

**US-03: Maintain backward compatibility**
- **As a** API consumer
- **I want** v1 endpoints to work unchanged
- **So that** my application doesn't break
- **Given:** `/api/v1/items` route exists
- **When:** I call `GET /api/v1/items`
- **Then:**
  - Response matches original `/api/items` behavior (INV-VER-04)
  - `Deprecation: true` header present (INV-VER-02)
  - `Sunset` header shows date 180 days from now (CC-09)

**US-04: Add new version endpoints**
- **As a** API developer
- **I want** to introduce v2 endpoints
- **So that** I can evolve the API safely
- **Given:** `/api/v1/items` route exists
- **When:** I call `GET /api/v2/items`
- **Then:**
  - Response uses v2 schema (CC-04)
  - No deprecation headers present (INV-VER-02)
  - Route prefix is `/api/v2` (CC-12)

**US-05: Generate per-version OpenAPI docs**
- **As a** API documenter
- **I want** separate OpenAPI specs
- **So that** clients see version-specific endpoints
- **Given:** `/api/v1/items` and `/api/v2/items` routes exist
- **When:** I request `/api/v1/openapi.json`
- **Then:**
  - Only v1 routes appear in docs (INV-VER-03)
  - No v2 routes visible (CC-22)
  - Root `/openapi.json` defaults to v1 (CC-23)

### 9.2 Deprecation Lifecycle (US-06 .. US-10)

**US-06: Add deprecation headers**
- **As a** API consumer
- **I want** to know when endpoints will be removed
- **So that** I can plan my migration
- **Given:** `/api/v1/items` route exists
- **When:** I call `GET /api/v1/items`
- **Then:**
  - `Deprecation: true` header present (INV-VER-02)
  - `Sunset` header shows date 180 days from now (CC-09)
  - `Link` header points to `/api/v2/items` (CC-27)

**US-07: Remove deprecated version**
- **As a** API maintainer
- **I want** to remove old versions
- **So that** I can reduce maintenance overhead
- **Given:** Sunset date has passed
- **When:** I deploy after sunset date
- **Then:**
  - `/api/v1/items` returns 410 Gone (CC-13)
  - All v1 routes removed from router (CC-01)
  - `app/api/v1/` directory deleted (CC-17)

**US-08: Extend deprecation period**
- **As a** API owner
- **I want** to extend the deprecation period
- **So that** clients have more time to migrate
- **Given:** initial deprecation period of 180 days
- **When:** I call `add_api_versioning(deprecation_period_days=365)`
- **Then:**
  - `Sunset` header updated to 365 days from now (CC-09)
  - Middleware uses new sunset date (CC-13)
  - Config updated in `app/core/config.py` (CC-07)

**US-09: Handle sunset date in past**
- **As a** API developer
- **I want** to prevent invalid sunset dates
- **So that** clients aren't confused
- **Given:** deprecation_period_days=-1
- **When:** I call `add_api_versioning()`
- **Then:**
  - Tool raises ValueError (CC-25)
  - No files modified (CC-30)
  - Error message explains valid range (CC-24)

**US-10: Link to successor version**
- **As a** API consumer
- **I want** to know the new version of an endpoint
- **So that** I can migrate smoothly
- **Given:** `/api/v1/items` is deprecated
- **When:** I call `GET /api/v1/items`
- **Then:**
  - `Link` header present (INV-VER-02)
  - Header value is `<http://example.com/api/v2/items>; rel="successor-version"` (CC-27)
  - Link matches actual v2 endpoint (CC-12)

### 9.3 Schema Evolution (US-11 .. US-15)

**US-11: Rename field in v2 schema**
- **As a** API designer
- **I want** to rename a field in v2
- **So that** I can improve API clarity
- **Given:** v1 schema has `description` field
- **When:** I rename `description` to `summary` in v2 schema
- **Then:**
  - `/api/v2/items` accepts `summary` field (CC-04)
  - `/api/v1/items` continues using `description` (CC-03)
  - No impact on v1 clients (INV-VER-04)

**US-12: Add new field in v2**
- **As a** product owner
- **I want** to add a new field in v2
- **So that** I can expose more data
- **Given:** v1 schema has `title` field
- **When:** I add `subtitle` field to v2 schema
- **Then:**
  - `/api/v2/items` accepts `subtitle` (CC-04)
  - `/api/v1/items` ignores `subtitle` (CC-03)
  - No database migration needed (CC-30)

**US-13: Remove field in v2**
- **As a** API maintainer
- **I want** to remove unused fields
- **So that** I can simplify the API
- **Given:** v1 schema has `legacy_field`
- **When:** I remove `legacy_field` from v2 schema
- **Then:**
  - `/api/v2/items` rejects `legacy_field` (CC-04)
  - `/api/v1/items` continues using `legacy_field` (CC-03)
  - No impact on v1 clients (INV-VER-04)

**US-14: Change field type in v2**
- **As a** API developer
- **I want** to change a field's type
- **So that** I can improve data integrity
- **Given:** v1 `rating` field is integer
- **When:** I change `rating` to float in v2 schema
- **Then:**
  - `/api/v2/items` accepts float `rating` (CC-04)
  - `/api/v1/items` continues using integer `rating` (CC-03)
  - No database migration needed (CC-30)

**US-15: Handle missing v2 schema**
- **As a** API consumer
- **I want** to know when a schema doesn't exist
- **So that** I can report issues
- **Given:** v1 schema exists but v2 schema missing
- **When:** I call `GET /api/v2/items`
- **Then:**
  - 500 Internal Server Error returned (CC-04)
  - Error message indicates missing schema (CC-31)
  - Log shows `ImportError` for v2 schema (CC-15)

### 9.4 Versioning Strategy (US-16 .. US-20)

**US-16: Use path strategy by default**
- **As a** API consumer
- **I want** clean URLs
- **So that** I can easily cache responses
- **Given:** strategy="path"
- **When:** I call `GET /api/v1/items`
- **Then:**
  - Response comes from v1 handler (INV-VER-01)
  - No Accept header required (CC-14)
  - URL clearly shows version (CC-12)

**US-17: Use header strategy for single endpoint**
- **As a** API consumer
- **I want** version negotiation
- **So that** I can use a single endpoint
- **Given:** strategy="header"
- **When:** I call `GET /api/items` with `Accept: application/vnd.app.v2+json`
- **Then:**
  - Response comes from v2 handler (INV-VER-01)
  - No path prefix required (CC-06)
  - Content negotiation works (INV-VER-05)

**US-18: Fallback to current version**
- **As a** API consumer
- **I want** sensible defaults
- **So that** I don't need to specify version
- **Given:** strategy="header"
- **When:** I call `GET /api/items` with no Accept header
- **Then:**
  - Response comes from v1 handler (INV-VER-05)
  - No error returned (CC-14)
  - Defaults to current_version="v1" (CC-07)

**US-19: Handle malformed Accept header**
- **As a** API consumer
- **I want** graceful error handling
- **So that** I can fix my requests
- **Given:** strategy="header"
- **When:** I call `GET /api/items` with `Accept: invalid`
- **Then:**
  - 400 Bad Request returned (CC-06)
  - Error message explains valid formats (CC-14)
  - Log shows parsing error (CC-15)

**US-20: Support both path and header**
- **As a** API consumer
- **I want** flexibility
- **So that** I can use either strategy
- **Given:** strategy="header"
- **When:** I call `GET /api/v1/items` with `Accept: application/vnd.app.v2+json`
- **Then:**
  - Path strategy takes precedence (INV-VER-01)
  - Response comes from v1 handler (CC-12)
  - Header ignored when path specifies version (CC-06)

### 9.5 Performance & Observability (US-21 .. US-25)

**US-21: Measure routing overhead**
- **As a** performance engineer
- **I want** to measure versioning impact
- **So that** I can ensure low latency
- **Given:** `/api/v1/items` and `/api/v2/items` routes
- **When:** I call both endpoints 1000 times
- **Then:**
  - Average latency < 0.1 ms (CC-30)
  - No significant difference between versions (CC-30)
  - Routing overhead < 1% of total request time (CC-30)

**US-22: Monitor deprecation headers**
- **As a** SRE
- **I want** to track deprecated usage
- **So that** I can plan version removal
- **Given:** `/api/v1/items` is deprecated
- **When:** I call `GET /api/v1/items`
- **Then:**
  - Deprecation usage logged (CC-13)
  - Metrics include `api_deprecated_requests_total` (CC-15)
  - Alert triggers if usage spikes (CC-15)

**US-23: Ensure middleware order**
- **As a** security engineer
- **I want** proper middleware ordering
- **So that** auth works correctly
- **Given:** auth middleware exists
- **When:** I call any endpoint
- **Then:**
  - Auth middleware runs before deprecation middleware (INV-VER-07)
  - Middleware order verified in `app/main.py` (CC-05)
  - No security vulnerabilities introduced (CC-21)

**US-24: Handle high request volume**
- **As a** API operator
- **I want** to handle many requests
- **So that** I can scale efficiently
- **Given:** 1000 concurrent requests
- **When:** I call both v1 and v2 endpoints
- **Then:**
  - All requests handled successfully (CC-30)
  - Memory overhead < 1 MB per worker (CC-30)
  - No version leaks between requests (INV-VER-01)

**US-25: Measure tool execution time**
- **As a** developer
- **I want** fast tool execution
- **So that** I can iterate quickly
- **Given:** project with 50 routes
- **When:** I run `add_api_versioning()`
- **Then:**
  - Execution time < 6 seconds (CC-30)
  - Progress logged for each step (CC-15)
  - Metrics include `files_created` and `files_modified` (CC-30)

---

## 10. Test Plan

### 10.1 Routing Isolation

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | v1 call routes to v1 handler | `/api/v1/items` exists | GET `/api/v1/items` | Response from v1 handler |
| T-02 | v2 call routes to v2 handler | `/api/v2/items` exists | GET `/api/v2/items` | Response from v2 handler |
| T-03 | v1 call never routes to v2 | Both versions exist | GET `/api/v1/items` | No v2 handler invoked |
| T-04 | v2 call never routes to v1 | Both versions exist | GET `/api/v2/items` | No v1 handler invoked |
| T-05 | Missing version returns 404 | Only v1 exists | GET `/api/v3/items` | 404 Not Found |
| T-06 | Health check unversioned | `/health` exists | GET `/health` | 200 OK, no version prefix |

### 10.2 Deprecation Headers

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-07 | Deprecation header on v1 | `/api/v1/items` deprecated | GET `/api/v1/items` | `Deprecation: true` header |
| T-08 | Sunset header on v1 | Sunset date set | GET `/api/v1/items` | `Sunset` header matches config |
| T-09 | Link header points to successor | `/api/v2/items` exists | GET `/api/v1/items` | `Link` header points to `/api/v2/items` |
| T-10 | No deprecation headers on v2 | `/api/v2/items` active | GET `/api/v2/items` | No deprecation headers |
| T-11 | Deprecation middleware order | Auth middleware exists | Inspect middleware registration | Deprecation runs after auth |
| T-12 | Sunset date in future | deprecation_period_days=180 | Inspect `settings.API_SUNSET_DATE` | Date is 180 days from now |

### 10.3 Schema Isolation

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-13 | v1 schema unchanged | Original schema exists | Inspect `app/schemas/v1/item.py` | Matches original schema |
| T-14 | v2 schema separate | v1 schema exists | Inspect `app/schemas/v2/item.py` | Separate file, no shared imports |
| T-15 | Field rename in v2 | v2 renamed `description` to `summary` | POST `/api/v2/items` with `summary` | 200 OK, field accepted |
| T-16 | Field removal in v2 | v2 removed `legacy_field` | POST `/api/v2/items` with `legacy_field` | 422 Unprocessable Entity |
| T-17 | Field type change in v2 | v2 changed `rating` to float | POST `/api/v2/items` with float `rating` | 200 OK, float accepted |
| T-18 | Missing v2 schema | v2 schema missing | GET `/api/v2/items` | 500 Internal Server Error |

### 10.4 Header Strategy

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-19 | Header strategy defaults to current | No Accept header | GET `/api/items` | Routes to v1 handler |
| T-20 | Header strategy parses v2 | Accept: application/vnd.app.v2+json | GET `/api/items` | Routes to v2 handler |
| T-21 | Malformed Accept header | Accept: invalid | GET `/api/items` | 400 Bad Request |
| T-22 | Path takes precedence over header | Accept: application/vnd.app.v2+json | GET `/api/v1/items` | Routes to v1 handler |
| T-23 | No version in Accept header | Accept: application/json | GET `/api/items` | Routes to v1 handler |
| T-24 | OpenAPI per version | Both versions exist | GET `/api/v1/openapi.json` | Only v1 routes in docs |

### 10.5 OpenAPI & Documentation

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-25 | Root OpenAPI defaults to current | Both versions exist | GET `/openapi.json` | Matches v1 OpenAPI |
| T-26 | v2 OpenAPI contains only v2 | Both versions exist | GET `/api/v2/openapi.json` | Only v2 routes in docs |
| T-27 | Empty version OpenAPI | No v3 routes | GET `/api/v3/openapi.json` | Empty OpenAPI spec |
| T-28 | Version label validation | Invalid version label | Call `add_api_versioning(new_version="invalid")` | ValueError raised |
| T-29 | Tool execution time | Project with 50 routes | Time `add_api_versioning()` | < 6 seconds |
| T-30 | Idempotent tool execution | Versioning already enabled | Run `add_api_versioning()` again | No file changes, "skipped" note |

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|----------------|-------------|-------|
| `add_soft_delete` | Yes | Soft delete must run first | Versioned schemas must include soft delete fields |
| `add_multi_tenancy` | Yes | Multi-tenancy must run first | Versioned routes must respect tenant isolation |
| `add_audit_log` | No | Independent | Audit logs capture versioned endpoints |
| `add_rbac` | Yes | RBAC must run first | Versioned routes inherit RBAC permissions |
| `add_api_key_auth` | Yes | Auth must run first | Versioned routes inherit auth scheme |
| `add_oauth2_provider` | Yes | OAuth2 must run first | Versioned routes inherit OAuth2 scopes |
| `add_mfa` | Yes | MFA must run first | Versioned routes inherit MFA requirements |
| `add_cache_layer` | No | Independent | Cache keys include version prefix |
| `add_circuit_breaker` | No | Independent | Circuit breakers monitor versioned endpoints |
| `add_feature_flags` | No | Independent | Feature flags can control version availability |
| `add_bulk_operations` | Yes | Bulk ops must run first | Versioned bulk endpoints need version prefix |
| `add_data_export` | No | Independent | Export formats may differ per version |
| `add_search` | Yes | Search must run first | Versioned search endpoints need separate indices |

**Conflicts:** None identified.

## 12. Rollback Procedure

### Code rollback (before deploy)
```bash
# Revert all file changes
git checkout app/api/main.py
git checkout app/main.py
git checkout app/core/config.py

# Remove created files
rm -rf app/api/v1/
rm -rf app/api/v2/
rm -rf app/schemas/v1/
rm -rf app/schemas/v2/
rm app/api/middleware/deprecation.py
rm app/api/deps_version.py
rm tests/test_api_versioning.py
```

### Database rollback (after deploy)
```sql
-- N/A — API versioning is code-only with no database changes
```

### Data preservation rollback
```bash
# N/A — No data migration was performed
```

### Failure mode: tool partially modified files
```bash
# Restore original state from backup
cp backup/app/api/main.py app/api/main.py
cp backup/app/main.py app/main.py
cp backup/app/core/config.py app/core/config.py
rm -rf app/api/v1/
rm -rf app/api/v2/
rm -rf app/schemas/v1/
rm -rf app/schemas/v2/
rm -f app/api/middleware/deprecation.py
rm -f app/api/deps_version.py
rm -f tests/test_api_versioning.py
```

### Emergency: Client stuck on deprecated version
```bash
# Extend sunset date by 30 days
sed -i 's/API_SUNSET_DATE=.*/API_SUNSET_DATE=$(date -d "+30 days" +%Y-%m-%d)/' .env
```

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-1 | Project has no existing routes | Tool errors: "No routes found in app/api/endpoints/. Add routes first." |
| EC-2 | New version label collides with existing | Tool errors: "Version v2 already exists. Choose a different new_version." |
| EC-3 | Strategy=header but client sends both Accept and v1 path | Path strategy takes precedence, routes to v1 handler |
| EC-4 | Sunset date in the past | Tool errors: "deprecation_period_days must be ≥30. Got -1." |
| EC-5 | Two routes have same path in v1 but different in v2 | Both routes preserved, v2 route takes precedence in OpenAPI |
| EC-6 | v2 route uses schema that doesn't exist in v1 | Tool errors: "Schema app/schemas/v2/item.py missing. Create it first." |
| EC-7 | Removing v1 route that v2 doesn't have successor for | No Link header added for deprecated route |
| EC-8 | OpenAPI generation for empty version | Returns empty OpenAPI spec with no routes |
| EC-9 | Versioned middleware order incorrect | Tool warns: "DeprecationMiddleware must run AFTER auth middleware. Fixing automatically." |
| EC-10 | Reverse proxy strips /api/v1 prefix | Middleware reads X-Forwarded-Prefix if available |
| EC-11 | CORS preflight on versioned route | Preflight response includes Access-Control-Allow-Methods for both versions |
| EC-12 | Client sends Accept: application/json | Falls back to current_version="v1" |
| EC-13 | Health check route versioned | Tool warns: "/health should be unversioned. Moving to root router." |
| EC-14 | New version has different auth scheme | Tool warns: "v2 auth scheme differs from v1. Verify compatibility." |
| EC-15 | Versioned schemas with circular references | Tool errors: "Circular schema references detected. Resolve manually." |

## 14. Acceptance Criteria (Final Sign-off)

✅ 1. All 33 Completeness Criteria verified  
✅ 2. Existing test suite passes with 0 failures  
✅ 3. New `tests/test_api_versioning.py` created with 30 tests  
✅ 4. `app/api/v1/` directory exists with all existing routes  
✅ 5. `app/api/v2/` directory exists with copied routes  
✅ 6. `app/schemas/v1/` directory exists with copied schemas  
✅ 7. `app/schemas/v2/` directory exists with copied schemas  
✅ 8. `DeprecationMiddleware` registered in `app/main.py`  
✅ 9. `VersionHeaderDependency` exists in `app/api/deps_version.py`  
✅ 10. Developer successfully migrates client from `/api/v1/items` to `/api/v2/items` using Link header  

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Project Validation
- [ ] Verify `project_dir` exists and contains `app/` directory
- [ ] Confirm `app/api/endpoints/` directory exists with route files
- [ ] Validate `app/schemas/` directory exists with model schemas
- [ ] Check for existing version directories (v1, v2)
- [ ] Verify Python version ≥3.8
- [ ] Confirm FastAPI version ≥0.95

### 15.2 Version Directory Setup
- [ ] Create `app/api/v1/` directory structure
- [ ] Copy existing routes to `app/api/v1/endpoints/`
- [ ] Create `app/api/v2/` directory structure
- [ ] Copy routes to `app/api/v2/endpoints/` as starting point
- [ ] Create `app/schemas/v1/` directory
- [ ] Create `app/schemas/v2/` directory

### 15.3 Middleware Implementation
- [ ] Create `app/api/middleware/deprecation.py`
- [ ] Implement `DeprecationMiddleware` class
- [ ] Add header injection for deprecated routes
- [ ] Register middleware in `app/main.py`
- [ ] Verify middleware order (after auth)
- [ ] Test middleware with versioned requests

### 15.4 Header Strategy
- [ ] Create `app/api/deps_version.py`
- [ ] Implement `get_api_version()` dependency
- [ ] Handle Accept header parsing
- [ ] Implement fallback to current_version
- [ ] Add error handling for malformed headers
- [ ] Test with various Accept header formats

### 15.5 Router Configuration
- [ ] Modify `app/api/main.py` to use versioned routers
- [ ] Mount v1 router at `/api/v1`
- [ ] Mount v2 router at `/api/v2`
- [ ] Ensure health route remains unversioned
- [ ] Verify route isolation
- [ ] Test routing precedence

### 15.6 Schema Versioning
- [ ] Copy original schemas to `app/schemas/v1/`
- [ ] Create initial v2 schemas in `app/schemas/v2/`
- [ ] Implement schema translation layer
- [ ] Add field rename support
- [ ] Verify schema isolation
- [ ] Test backward compatibility

### 15.7 Configuration Updates
- [ ] Add `API_CURRENT_VERSION` to config
- [ ] Add `API_NEW_VERSION` to config
- [ ] Compute sunset date from deprecation_period_days
- [ ] Add `API_DEPRECATED_VERSIONS` list
- [ ] Add `API_VERSION_STRATEGY` setting
- [ ] Validate config values

### 15.8 OpenAPI Generation
- [ ] Configure per-version OpenAPI docs
- [ ] Test `/api/v1/openapi.json`
- [ ] Test `/api/v2/openapi.json`
- [ ] Verify root OpenAPI defaults to current
- [ ] Check route isolation in docs
- [ ] Measure generation performance

### 15.9 Test Generation
- [ ] Create `tests/test_api_versioning.py`
- [ ] Add routing isolation tests
- [ ] Add deprecation header tests
- [ ] Add schema versioning tests
- [ ] Add header strategy tests
- [ ] Add OpenAPI tests

### 15.10 Documentation
- [ ] Update `core/KNOWLEDGE.md` with versioning
- [ ] Add tool to `manifest.yaml`
- [ ] Update `SKILL.md` tools table
- [ ] Document versioning strategy
- [ ] Note CORS requirements
- [ ] Add reverse proxy guidance

### 15.11 Atomic Operations
- [ ] Use temp files for all writes
- [ ] Track modified files for rollback
- [ ] Verify file parses before commit
- [ ] Implement full rollback on failure
- [ ] Preserve original file permissions
- [ ] Log all changes

### 15.12 Verification
- [ ] Run `ast.parse` on all modified files
- [ ] Execute existing test suite
- [ ] Run new versioning tests
- [ ] Measure routing overhead
- [ ] Check memory usage
- [ ] Verify response sizes

### 15.13 Performance
- [ ] Time tool execution
- [ ] Measure routing latency
- [ ] Test header parsing speed
- [ ] Check OpenAPI generation time
- [ ] Verify middleware overhead
- [ ] Benchmark schema translation

## 16. Documentation Output

```json
{
  "status": "success",
  "files_created": [
    "app/api/v1/main.py",
    "app/api/v2/main.py",
    "app/schemas/v1/item.py",
    "app/schemas/v2/item.py",
    "app/api/middleware/deprecation.py",
    "app/api/deps_version.py",
    "tests/test_api_versioning.py",
    "app/core/api_version.py",
    "app/core/schema_translation.py"
  ],
  "files_modified": [
    "app/api/main.py",
    "app/main.py",
    "app/core/config.py"
  ],
  "metrics": {
    "execution_time_ms": 4872,
    "files_changed": 12,
    "lines_added": 523,
    "lines_removed": 18,
    "current_version": "v1",
    "new_version": "v2",
    "strategy": "path",
    "deprecation_period_days": 180
  },
  "next_steps": [
    "Run: pytest tests/test_api_versioning.py -v",
    "Test: curl -I http://localhost:8000/api/v1/items",
    "Test: curl -H 'Accept: application/vnd.app.v2+json' http://localhost:8000/api/items",
    "Update client SDKs with new OpenAPI specs",
    "Monitor deprecated endpoint usage metrics"
  ],
  "warnings": [
    "CORS preflight requests must handle versioned routes",
    "Reverse proxies may strip version prefixes - configure X-Forwarded-Prefix"
  ],
  "notes": [
    "API versioning enabled with strategy=path",
    "DeprecationMiddleware registered after auth",
    "Sunset date set to 2026-10-05",
    "Schema translation layer implemented",
    "30 tests added for versioning",
    "Existing tests pass: 47/47"
  ]
}
