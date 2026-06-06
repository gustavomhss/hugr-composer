<!--
{
  "tool_num": "017",
  "tool_name": "add_api_versioning",
  "model": "deepseek/deepseek-chat",
  "elapsed_seconds": 402.85093956510536,
  "prompt_tokens": 45772,
  "completion_tokens": 9605,
  "cost_usd": 0.04544375,
  "calls": 6
}
-->

# TOOL-017: add_api_versioning

> **Status**: SPEC v2 (rigorous)  
> **Last updated**: 2026-04-08  

---

## 1. Overview

| **Tool name**       | `fastapi_add_api_versioning` |  
| **Category**        | EXTEND > API Design          |  
| **Complexity**      | High                         |  
| **Dependencies**    | existing project with at least one resource (model + routes), Alembic optional |  
| **Signature**       | `add_api_versioning(project_dir: str, current_version: str = "v1", new_version: str = "v2", strategy: Literal["path", "header"] = "path", deprecation_period_days: int = 180) -> dict` |  
| **Parameters**      | `project_dir`: project root path<br>`current_version`: version label of the existing API surface (default `v1`)<br>`new_version`: label for the new version being introduced (default `v2`)<br>`strategy`: how clients select the version — `path` (`/api/v1/...` vs `/api/v2/...`) or `header` (`Accept: application/vnd.app.v2+json`)<br>`deprecation_period_days`: number of days from migration until v1 routes are removed; sets the `Sunset` header date |  

## 2. Purpose  

This tool adds API versioning to a FastAPI project, enabling multiple API versions to coexist in the same application. It solves the problem of evolving APIs without breaking existing clients by providing clean separation between versions. The tool integrates by creating version-specific routers, schemas, and CRUD wrappers, while maintaining backward compatibility through a shim layer that translates fields between versions. Deprecated versions emit headers (`Deprecation`, `Sunset`, `Link`) to guide clients toward the successor version.

## 3. Performance SLOs  

| **Metric**                     | **Target**                     | **Why**                                                                 |  
|--------------------------------|--------------------------------|-------------------------------------------------------------------------|  
| Tool execution time            | < 6s                          | Multiple files modified and created                                     |  
| Files modified                 | ≤ 6                           | Global files updated for versioning setup                               |  
| Files created                  | ≥ 8                           | Versioning module, routers, middleware, OpenAPI config, tests, etc.    |  
| Per-version routing overhead   | < 0.1 ms                      | FastAPI router resolution is highly optimized                          |  
| Header parsing overhead        | < 0.5 ms                      | Header strategy adds minimal latency                                   |  
| Migration runtime              | 0s                            | No database changes; pure code migration                               |  
| OpenAPI generation per version | < 200 ms                      | Each version's OpenAPI must generate quickly                           |  
| Memory overhead                | < 1 MB per worker             | Minimal additional memory for versioning logic                        |  
| No DB schema changes           | 0                             | Versioning is purely an API surface change                            |

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
from app.api.middleware.deprecation import DeprecationMiddleware
from app.core.config import settings

router = APIRouter()

# Path-based versioning
if settings.API_VERSION_STRATEGY == "path":
    router.include_router(v1_router, prefix=f"/api/{settings.API_CURRENT_VERSION}")
    router.include_router(v2_router, prefix=f"/api/{settings.API_NEW_VERSION}")
# Header-based versioning uses single prefix with version dependency
else:
    router.include_router(v1_router, prefix="/api")
    router.include_router(v2_router, prefix="/api")
```

### 4.3 Versioned router v1 (NEW)
```python
# app/api/v1/main.py
from fastapi import APIRouter
from app.api.v1.endpoints import items, users
from app.api.middleware.deprecation import add_deprecation_headers

router = APIRouter()

# Apply deprecation middleware to all v1 routes
router.middleware("http")(add_deprecation_headers)

router.include_router(items.router, prefix="/items", tags=["items"])
router.include_router(users.router, prefix="/users", tags=["users"])
```

### 4.4 Versioned router v2 (NEW)
```python
# app/api/v2/main.py
from fastapi import APIRouter
from app.api.v2.endpoints import items, users

router = APIRouter()

router.include_router(items.router, prefix="/items", tags=["items"])
router.include_router(users.router, prefix="/users", tags=["users"])

# v2-specific route that doesn't exist in v1
@router.get("/health/detailed", tags=["health"])
async def detailed_health():
    """v2-only health endpoint with more details"""
    return {
        "status": "healthy",
        "version": "v2",
        "timestamp": "2026-04-08T10:30:00Z",
        "components": ["database", "cache", "storage"]
    }
```

### 4.5 Deprecation middleware (NEW)
```python
# app/api/middleware/deprecation.py
from datetime import datetime
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from app.core.config import settings
from app.core.api_version import get_sunset_date, build_successor_url


class DeprecationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        
        # Check if this is a deprecated version route
        if request.url.path.startswith(f"/api/{settings.API_CURRENT_VERSION}"):
            response.headers["Deprecation"] = "true"
            response.headers["Sunset"] = get_sunset_date().isoformat()
            successor_url = build_successor_url(request.url, settings.API_CURRENT_VERSION, settings.API_NEW_VERSION)
            response.headers["Link"] = f'<{successor_url}>; rel="successor-version"'
        
        return response


def add_deprecation_headers(request: Request, call_next):
    """Function middleware for v1 router"""
    async def wrapper():
        response = await call_next(request)
        response.headers["Deprecation"] = "true"
        response.headers["Sunset"] = get_sunset_date().isoformat()
        return response
    return wrapper()
```

### 4.6 Header strategy dependency (NEW)
```python
# app/api/deps_version.py
from fastapi import Header, HTTPException, Request
from app.core.config import settings


async def get_api_version_header(
    accept: str = Header(default="application/json"),
    request: Request = None
) -> str:
    """Parse API version from Accept header"""
    if "application/vnd.app" in accept:
        # Extract version from Accept: application/vnd.app.v2+json
        parts = accept.split(".")
        if len(parts) >= 2:
            version = parts[-1].split("+")[0]
            if version in [settings.API_CURRENT_VERSION, settings.API_NEW_VERSION]:
                return version
            raise HTTPException(
                status_code=406,
                detail=f"Unsupported API version: {version}. Supported: {settings.API_CURRENT_VERSION}, {settings.API_NEW_VERSION}"
            )
    
    # Default to current version if no vendor header or parsing fails
    return settings.API_CURRENT_VERSION


async def get_api_version_path(request: Request) -> str:
    """Extract API version from URL path"""
    path_parts = request.url.path.split("/")
    if len(path_parts) >= 3 and path_parts[1] == "api":
        version = path_parts[2]
        if version in [settings.API_CURRENT_VERSION, settings.API_NEW_VERSION]:
            return version
    raise HTTPException(status_code=404, detail="Invalid API version in path")


def get_versioned_router(version: str):
    """Dependency to get the correct router based on version"""
    from app.api.v1.main import router as v1_router
    from app.api.v2.main import router as v2_router
    
    routers = {
        settings.API_CURRENT_VERSION: v1_router,
        settings.API_NEW_VERSION: v2_router
    }
    return routers.get(version, v1_router)
```

### 4.7 Versioned schema v1: BEFORE
```python
# app/schemas/item.py
from pydantic import BaseModel
from datetime import datetime
from uuid import UUID


class ItemBase(BaseModel):
    title: str
    description: str | None = None


class ItemCreate(ItemBase):
    pass


class Item(ItemBase):
    id: UUID
    owner_id: UUID
    created_at: datetime

    class Config:
        from_attributes = True
```

### 4.8 Versioned schema v2: AFTER
```python
# app/schemas/v2/item.py
from pydantic import BaseModel, Field
from datetime import datetime
from uuid import UUID


class ItemBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(None, max_length=1000)
    tags: list[str] = Field(default_factory=list, max_items=10)  # New in v2
    metadata: dict[str, str] = Field(default_factory=dict)  # New in v2


class ItemCreate(ItemBase):
    category_id: UUID | None = None  # New optional field in v2


class Item(ItemBase):
    id: UUID
    owner_id: UUID
    created_at: datetime
    updated_at: datetime | None = None  # New field in v2
    category_id: UUID | None = None

    class Config:
        from_attributes = True
```

### 4.9 Versioned schema v1 (moved)
```python
# app/schemas/v1/item.py
from pydantic import BaseModel
from datetime import datetime
from uuid import UUID


class ItemBase(BaseModel):
    title: str
    description: str | None = None


class ItemCreate(ItemBase):
    pass


class Item(ItemBase):
    id: UUID
    owner_id: UUID
    created_at: datetime

    class Config:
        from_attributes = True
```

### 4.10 Version translation layer (NEW)
```python
# app/core/version_translation.py
from datetime import datetime
from uuid import UUID
from app.schemas.v1.item import Item as ItemV1
from app.schemas.v2.item import Item as ItemV2


def v2_to_v1_item(item_v2: ItemV2) -> ItemV1:
    """Convert v2 Item schema to v1 for backward compatibility"""
    return ItemV1(
        id=item_v2.id,
        title=item_v2.title,
        description=item_v2.description,
        owner_id=item_v2.owner_id,
        created_at=item_v2.created_at
    )


def v1_to_v2_item(item_v1: ItemV1, **additional_fields) -> ItemV2:
    """Convert v1 Item schema to v2 with default values for new fields"""
    return ItemV2(
        id=item_v1.id,
        title=item_v1.title,
        description=item_v1.description,
        owner_id=item_v1.owner_id,
        created_at=item_v1.created_at,
        updated_at=datetime.utcnow(),
        tags=[],
        metadata={},
        category_id=None,
        **additional_fields
    )


def translate_create_v1_to_v2(create_v1) -> dict:
    """Translate v1 create schema to v2 create schema fields"""
    data = create_v1.model_dump()
    # Add default values for v2-only fields
    data.update({
        "tags": [],
        "metadata": {},
        "category_id": None
    })
    return data
```

### 4.11 Versioned CRUD wrapper (NEW)
```python
# app/crud/item_versioned.py
from typing import TypeVar, Generic
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from app.crud.item import create_item as create_item_base
from app.core.version_translation import translate_create_v1_to_v2

T = TypeVar("T", bound=BaseModel)


class VersionedCRUD(Generic[T]):
    def __init__(self, version: str):
        self.version = version
    
    async def create(
        self,
        session: AsyncSession,
        *,
        item_in: T,
        owner_id: UUID
    ):
        """Create item with version-specific handling"""
        if self.version == "v1":
            # Convert v1 schema to v2 for storage
            v2_data = translate_create_v1_to_v2(item_in)
            # Use v2 CRUD but return v1 schema
            from app.schemas.v2.item import ItemCreate as ItemCreateV2
            v2_in = ItemCreateV2(**v2_data)
            item = await create_item_base(session, item_in=v2_in, owner_id=owner_id)
            from app.core.version_translation import v2_to_v1_item
            return v2_to_v1_item(item)
        else:
            # v2 uses direct CRUD
            return await create_item_base(session, item_in=item_in, owner_id=owner_id)


# Factory function
def get_item_crud(version: str) -> VersionedCRUD:
    return VersionedCRUD(version)
```

### 4.12 Migration for API version tracking
```python
# alembic/versions/0010_add_api_version_tracking.py
"""add api version tracking

Revision ID: 0010
Revises: 0009
Create Date: 2026-04-08
"""
from alembic import op
import sqlalchemy as sa
from datetime import datetime, timedelta


revision = "0010"
down_revision = "0009"


def upgrade() -> None:
    # Create table for tracking API version usage (optional analytics)
    op.create_table(
        "api_version_usage",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("version", sa.String(16), nullable=False, index=True),
        sa.Column("endpoint", sa.String(255), nullable=False),
        sa.Column("method", sa.String(10), nullable=False),
        sa.Column("client_ip", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    
    # Create index for analytics queries
    op.create_index(
        "ix_api_version_usage_version_created",
        "api_version_usage",
        ["version", "created_at"]
    )
    
    # Insert initial version configuration
    op.create_table(
        "api_version_config",
        sa.Column("version", sa.String(16), primary_key=True),
        sa.Column("is_deprecated", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("deprecated_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sunset_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    
    # Insert v1 as deprecated with sunset date 180 days from now
    sunset_date = datetime.utcnow() + timedelta(days=180)
    op.execute(
        sa.text(
            "INSERT INTO api_version_config (version, is_deprecated, sunset_date) VALUES "
            "(:v1, :deprecated, :sunset), (:v2, :deprecated2, :sunset2)"
        ).bindparams(
            v1="v1",
            deprecated=True,
            sunset=sunset_date,
            v2="v2",
            deprecated2=False,
            sunset2=None,
        )
    )


def downgrade() -> None:
    op.drop_table("api_version_config")
    op.drop_index("ix_api_version_usage_version_created", table_name="api_version_usage")
    op.drop_table("api_version_usage")

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Version routing is strictly isolated** | Each version's router is mounted at `/api/<version>` with no shared handler paths. Path collisions raise `RuntimeError` during tool execution. |
| QS-2 | **Deprecation headers are always present on deprecated versions** | `DeprecationMiddleware` injects headers for any path starting with `/api/<deprecated_version>`. Verified by T-07..T-09. |
| QS-3 | **Header strategy falls back to current version** | `deps_version.get_api_version()` returns `settings.API_CURRENT_VERSION` when Accept header is missing or malformed. Verified by T-19..T-21. |
| QS-4 | **OpenAPI docs are version-specific** | Each `/api/<version>/openapi.json` contains only routes from that version. Root `/openapi.json` mirrors current version. Verified by T-24..T-26. |
| QS-5 | **No regression in v1 behavior** | All existing v1 routes are copied verbatim to `app/api/v1/` with identical schemas. Verified by T-28. |
| QS-6 | **Sunset date is computed correctly** | `core/api_version.py` computes `API_SUNSET_DATE` as `datetime.now() + timedelta(days=deprecation_period_days)`. Verified by T-10. |
| QS-7 | **Link header points to equivalent v2 resource** | Middleware constructs successor URL by replacing version segment in path. Verified by T-11. |
| QS-8 | **Health checks remain unversioned** | Tool explicitly excludes `/health` from versioning. Verified by grep `^/health` in routes. |
| QS-9 | **Middleware runs after auth** | `app.add_middleware(DeprecationMiddleware)` is called after auth middleware in `main.py`. Verified by T-29. |
| QS-10 | **No DB schema changes** | Tool validates zero Alembic revisions are created unless `--with-alembic` is passed. Verified by T-30. |
| QS-11 | **Idempotent execution** | Re-running the tool produces identical file structure. Modified files are detected via checksum. Verified by T-27. |

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | `api_version.py` exists at `app/core/api_version.py` | File exists, exports `API_SUNSET_DATE` |
| CC-02 | `DeprecationMiddleware` exists at `app/api/middleware/deprecation.py` | File exists, class inherits `BaseHTTPMiddleware` |
| CC-03 | Versioned routers exist at `app/api/v1/main.py` and `app/api/v2/main.py` | Both files exist, contain `APIRouter` instances |
| CC-04 | `deps_version.py` exists for header strategy | File exists, contains `get_api_version()` dependency |
| CC-05 | Config has `API_CURRENT_VERSION` and `API_NEW_VERSION` | grep `API_CURRENT_VERSION` in `core/config.py` |
| CC-06 | Main router mounts both versions under `/api/<version>` | Inspect `app/api/main.py` for versioned prefixes |
| CC-07 | Deprecation middleware registered in `main.py` | grep `app.add_middleware(DeprecationMiddleware` |
| CC-08 | All existing routes copied to `app/api/v1/` | Diff route counts between original and v1 |
| CC-09 | OpenAPI accessible at `/api/v1/openapi.json` and `/api/v2/openapi.json` | curl both endpoints |
| CC-10 | Root `/openapi.json` matches current version | curl `/openapi.json` and compare to v1 |
| CC-11 | Sunset date is ISO8601 format | Inspect `DeprecationMiddleware` header format |
| CC-12 | Link header has valid URL and `rel="successor-version"` | curl v1 route, inspect headers |
| CC-13 | Health check remains at `/health` | grep `^/health` in routes |
| CC-14 | Header strategy dependency parses `Accept` correctly | Test with `Accept: application/vnd.app.v2+json` |
| CC-15 | Missing Accept header defaults to current version | curl without Accept header |
| CC-16 | Malformed Accept header returns 406 | Test with `Accept: application/vnd.app.invalid` |
| CC-17 | Path strategy routes are prefix-matched | Test `/api/v1/items` vs `/api/v2/items` |
| CC-18 | Deprecation headers only on v1 routes | curl v1 and v2 routes, compare headers |
| CC-19 | Middleware runs after auth | Inspect middleware order in `main.py` |
| CC-20 | No DB migrations created by default | Check Alembic revision count |
| CC-21 | All v1 schemas copied to `app/schemas/v1/` | Diff schema counts between original and v1 |
| CC-22 | V2 schemas exist in `app/schemas/v2/` | Directory exists, contains at least one schema |
| CC-23 | Tool execution time < 6s | Time measurement |
| CC-24 | Files modified ≤ 6 | Count in tool output |
| CC-25 | Files created ≥ 8 | Count in tool output |
| CC-26 | Per-version routing overhead < 0.1ms | Benchmark T-28 |
| CC-27 | Header parsing overhead < 0.5ms | Benchmark T-29 |
| CC-28 | OpenAPI generation < 200ms per version | Time `/api/v1/openapi.json` load |
| CC-29 | Existing tests pass | pytest 0 failures |
| CC-30 | New test file `test_api_versioning.py` has 30 tests | File exists, test count |

## 7. Definition of Done

- [ ] All 30 Completeness Criteria verified
- [ ] Tool execution time measured and logged (<6s)
- [ ] No regression in existing test suite (pytest 0 failures)
- [ ] 30 new tests passing in `test_api_versioning.py`
- [ ] Versioned OpenAPI docs accessible at `/api/v1/openapi.json` and `/api/v2/openapi.json`
- [ ] Deprecation headers present on all v1 routes (T-07..T-09)
- [ ] Header strategy fallback works (T-19..T-21)
- [ ] Health check remains unversioned at `/health`
- [ ] Sunset date computed correctly (T-10)
- [ ] Link headers point to valid successor URLs (T-11)
- [ ] Middleware order correct (T-29)
- [ ] No DB migrations created by default (T-30)
- [ ] README.md updated with versioning documentation

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-VER-01 | A v1 call NEVER routes to v2 handler | Path prefixes are mutually exclusive | T-01, T-02 |
| INV-VER-02 | Deprecated routes ALWAYS emit `Deprecation: true` | Middleware checks path prefix | T-07, T-08 |
| INV-VER-03 | The `Link` header points to the same resource in v2 | URL path segment replacement | T-11, T-12 |
| INV-VER-04 | OpenAPI per version contains ONLY its routes | Separate router mounting | T-24, T-25 |
| INV-VER-05 | Header strategy defaults to current version | `get_api_version()` fallback | T-19, T-20 |
| INV-VER-06 | Health checks remain unversioned | Explicit route exclusion | T-17 |
| INV-VER-07 | Middleware runs AFTER auth | Registration order in `main.py` | T-29 |

---

## 9. User Stories

### 9.1 Core functionality (US-01 .. US-05)

**US-01: Add API versioning to an existing project**
- **As a** backend developer evolving an API
- **I want** to add versioning with one command
- **So that** I can introduce breaking changes safely
- **Given:** project with `/items` and `/users` routes
- **When:** I call `add_api_versioning(project_dir="/app", strategy="path")`
- **Then:**
  - Routes are mounted at `/api/v1/items` and `/api/v2/items`
  - `DeprecationMiddleware` is registered
  - `app/api/v1/` and `app/api/v2/` directories created
  - Tool returns `{files_created: 9, files_modified: 4}`

**US-02: Access both versions simultaneously**
- **Given:** `/items` route exists in both v1 and v2
- **When:** I call `GET /api/v1/items` and `GET /api/v2/items`
- **Then:**
  - Both routes respond with 200 OK
  - Response bodies match their respective schema versions
  - No routing collisions (INV-VER-01)

**US-03: Deprecate old version with headers**
- **Given:** v1 routes are deprecated
- **When:** I call `GET /api/v1/items`
- **Then:**
  - Response includes `Deprecation: true` header
  - `Sunset` header shows date 180 days from now
  - `Link` header points to `/api/v2/items` (INV-VER-02)

**US-04: Default to current version with header strategy**
- **Given:** strategy="header" configured
- **When:** I call `GET /api/items` with no Accept header
- **Then:**
  - Request routes to v1 handler
  - Response matches v1 schema
  - No deprecation headers included (INV-VER-05)

**US-05: Maintain unversioned health check**
- **Given:** `/health` route exists
- **When:** I call `GET /health`
- **Then:**
  - Response returns 200 OK
  - Route remains accessible without version prefix
  - No deprecation headers included (INV-VER-06)

### 9.2 Deprecation lifecycle (US-06 .. US-10)

**US-06: Compute sunset date correctly**
- **Given:** deprecation_period_days=90
- **When:** I call `add_api_versioning()`
- **Then:**
  - `API_SUNSET_DATE` is computed as `now() + timedelta(days=90)`
  - Date is stored in `app/core/api_version.py`
  - Middleware uses this value for Sunset header (INV-VER-03)

**US-07: Reject requests after sunset date**
- **Given:** sunset date is in the past
- **When:** I call `GET /api/v1/items`
- **Then:**
  - Response returns 410 Gone
  - Body includes message "v1 is no longer supported"
  - `Link` header points to v2 equivalent

**US-08: Migrate clients with Link header**
- **Given:** deprecated v1 route `/api/v1/items/{id}`
- **When:** I call `GET /api/v1/items/123`
- **Then:**
  - `Link` header includes `rel="successor-version"`
  - URL points to `/api/v2/items/123`
  - Response body matches v1 schema (INV-VER-03)

**US-09: Remove deprecated routes after sunset**
- **Given:** sunset date has passed
- **When:** I run `remove_deprecated_routes()`
- **Then:**
  - All v1 routes are deleted from `app/api/v1/`
  - `DeprecationMiddleware` no longer injects headers
  - OpenAPI docs no longer list v1 routes

**US-10: Warn clients approaching sunset**
- **Given:** sunset date is 30 days away
- **When:** I call `GET /api/v1/items`
- **Then:**
  - Response includes `Warning: 299 - "v1 will sunset in 30 days"`
  - `Sunset` header shows correct date
  - `Link` header points to v2 equivalent

### 9.3 Schema evolution (US-11 .. US-15)

**US-11: Rename field in v2 schema**
- **Given:** v1 schema has `description` field
- **When:** I rename it to `details` in `app/schemas/v2/item.py`
- **Then:**
  - `GET /api/v2/items` returns `details` field
  - `GET /api/v1/items` still returns `description`
  - No schema conflicts between versions (INV-VER-04)

**US-12: Add new field in v2 schema**
- **Given:** v1 schema has `title` field
- **When:** I add `subtitle` to `app/schemas/v2/item.py`
- **Then:**
  - `GET /api/v2/items` includes `subtitle`
  - `GET /api/v1/items` does NOT include `subtitle`
  - OpenAPI docs reflect field differences

**US-13: Remove field in v2 schema**
- **Given:** v1 schema has `tags` field
- **When:** I remove it from `app/schemas/v2/item.py`
- **Then:**
  - `GET /api/v2/items` omits `tags`
  - `GET /api/v1/items` still includes `tags`
  - No regression in v1 clients

**US-14: Change field type in v2 schema**
- **Given:** v1 `created_at` field is string
- **When:** I change it to datetime in `app/schemas/v2/item.py`
- **Then:**
  - `GET /api/v2/items` returns ISO8601 datetime
  - `GET /api/v1/items` still returns string
  - No type coercion errors

**US-15: Validate schema isolation**
- **Given:** v2 schema adds `rating` field
- **When:** I call `GET /api/v1/items`
- **Then:**
  - Response does NOT include `rating`
  - OpenAPI docs show only v1 fields
  - No schema leakage between versions (INV-VER-04)

### 9.4 Strategy: path vs header (US-16 .. US-20)

**US-16: Use path strategy by default**
- **Given:** no strategy specified
- **When:** I call `add_api_versioning()`
- **Then:**
  - Routes are mounted at `/api/v1/` and `/api/v2/`
  - No Accept header parsing occurs
  - Clients must specify version in path

**US-17: Parse Accept header correctly**
- **Given:** strategy="header" configured
- **When:** I call `GET /api/items` with `Accept: application/vnd.app.v2+json`
- **Then:**
  - Request routes to v2 handler
  - Response matches v2 schema
  - No path prefix required (INV-VER-05)

**US-18: Handle malformed Accept header**
- **Given:** strategy="header" configured
- **When:** I call `GET /api/items` with `Accept: application/vnd.app.invalid+json`
- **Then:**
  - Response returns 406 Not Acceptable
  - Body includes supported versions
  - Defaults to v1 if header missing

**US-19: Fallback to current version**
- **Given:** strategy="header" configured
- **When:** I call `GET /api/items` with `Accept: application/json`
- **Then:**
  - Request routes to v1 handler
  - Response matches v1 schema
  - No deprecation headers included (INV-VER-05)

**US-20: Reject conflicting version indicators**
- **Given:** strategy="header" configured
- **When:** I call `GET /api/v1/items` with `Accept: application/vnd.app.v2+json`
- **Then:**
  - Response returns 400 Bad Request
  - Body explains version conflict
  - Requires consistent version selection

### 9.5 OpenAPI & docs (US-21 .. US-25)

**US-21: Generate versioned OpenAPI docs**
- **Given:** `/items` route exists in both versions
- **When:** I call `GET /api/v1/openapi.json` and `GET /api/v2/openapi.json`
- **Then:**
  - Each file contains only its version's routes
  - Schemas match version-specific fields
  - No cross-version pollution (INV-VER-04)

**US-22: Default OpenAPI to current version**
- **Given:** `/openapi.json` endpoint exists
- **When:** I call `GET /openapi.json`
- **Then:**
  - Response matches `/api/v1/openapi.json`
  - No deprecation headers included
  - Clients can discover current version

**US-23: Document deprecation headers**
- **Given:** v1 routes are deprecated
- **When:** I inspect `/api/v1/openapi.json`
- **Then:**
  - Response headers include `Deprecation`, `Sunset`, `Link`
  - Example shows successor URL
  - Warning notes sunset date

**US-24: Regenerate client SDKs**
- **Given:** OpenAPI docs for v1 and v2
- **When:** I run `openapi-generator-cli generate -i /api/v2/openapi.json`
- **Then:**
  - SDK includes only v2 endpoints
  - Schemas match v2 fields
  - No v1 routes included

**US-25: Measure OpenAPI generation performance**
- **Given:** 50 routes in each version
- **When:** I call `GET /api/v1/openapi.json`
- **Then:**
  - Response returns in < 200 ms
  - Memory usage < 1 MB
  - No impact on request handling

---

## 10. Test Plan

### 10.1 Routing Isolation

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | v1 path routes to v1 handler | `/items` exists in v1 | GET /api/v1/items | 200, v1 schema response |
| T-02 | v2 path routes to v2 handler | `/items` exists in v2 | GET /api/v2/items | 200, v2 schema response |
| T-03 | v1 call never hits v2 handler | v1 and v2 have `/items` | GET /api/v1/items | Response matches v1 schema only (INV-VER-01) |
| T-04 | v2 call never hits v1 handler | v1 and v2 have `/items` | GET /api/v2/items | Response matches v2 schema only (INV-VER-01) |
| T-05 | Unversioned path returns 404 | No route at `/items` | GET /items | 404 |
| T-06 | Health check remains unversioned | `/health` exists | GET /health | 200, no version prefix (INV-VER-06) |

### 10.2 Deprecation Headers

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-07 | v1 routes include Deprecation header | v1 is deprecated | GET /api/v1/items | Deprecation: true present (INV-VER-02) |
| T-08 | v2 routes omit Deprecation header | v2 is current | GET /api/v2/items | No Deprecation header |
| T-09 | Sunset header shows correct date | deprecation_period_days=180 | GET /api/v1/items | Sunset: <now + 180 days> |
| T-10 | Sunset date computation correct | deprecation_period_days=90 | Inspect API_SUNSET_DATE | now + 90 days (INV-VER-03) |
| T-11 | Link header points to v2 equivalent | v1 /items exists | GET /api/v1/items | Link: </api/v2/items>; rel="successor-version" (INV-VER-03) |
| T-12 | No Link header on v2 routes | v2 is current | GET /api/v2/items | No Link header |

### 10.3 Schema Isolation

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-13 | v1 schema unchanged | v1 has description field | GET /api/v1/items | description field present |
| T-14 | v2 schema can add fields | v2 adds subtitle field | GET /api/v2/items | subtitle field present |
| T-15 | v2 schema can remove fields | v2 removes tags field | GET /api/v2/items | No tags field |
| T-16 | v2 schema can rename fields | v2 renames description→details | GET /api/v2/items | details field present |
| T-17 | v1 responses don't include v2 fields | v2 adds rating field | GET /api/v1/items | No rating field (INV-VER-04) |
| T-18 | OpenAPI per version matches schema | v1 and v2 schemas differ | GET /api/v1/openapi.json | Only v1 fields in schema |

### 10.4 Header Strategy

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-19 | Defaults to current version | No Accept header | GET /api/items | Routes to v1 (INV-VER-05) |
| T-20 | Parses v2 Accept header | Accept: application/vnd.app.v2+json | GET /api/items | Routes to v2 |
| T-21 | Malformed Accept returns 406 | Accept: application/vnd.app.invalid+json | GET /api/items | 406 error |
| T-22 | Basic Accept falls back to v1 | Accept: application/json | GET /api/items | Routes to v1 (INV-VER-05) |
| T-23 | Version conflict returns 400 | Path /api/v1/items + Accept: v2 | GET /api/v1/items | 400 error |

### 10.5 OpenAPI & Docs

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-24 | v1 OpenAPI contains only v1 routes | v1 has /items, v2 has /items | GET /api/v1/openapi.json | Only /api/v1/items listed (INV-VER-04) |
| T-25 | v2 OpenAPI contains only v2 routes | v1 has /items, v2 has /items | GET /api/v2/openapi.json | Only /api/v2/items listed |
| T-26 | Root OpenAPI matches current version | v1 is current | GET /openapi.json | Matches /api/v1/openapi.json |
| T-27 | OpenAPI generation < 200ms | 50 routes per version | Time GET /api/v1/openapi.json | < 200ms response |

### 10.6 Integration & Performance

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-28 | Middleware runs after auth | Auth middleware exists | Inspect middleware order | DeprecationMiddleware registered after auth (INV-VER-07) |
| T-29 | Routing overhead < 0.1ms | Benchmark path strategy | Measure GET /api/v1/items | < 0.1ms p99 |
| T-30 | No DB migrations by default | Fresh project | Run tool | No alembic revisions created |

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|----------------|-------------|-------|
| `add_multi_tenancy` | Yes | Versioning applies AFTER tenant resolution | Tenant middleware must run first to resolve tenant context before version routing |
| `add_soft_delete` | No | Soft delete works independently across versions | Each version's routes inherit soft delete behavior |
| `add_audit_log` | No | Audit logs capture versioned requests | Logs include version prefix or header for traceability |
| `add_rbac` | Yes | RBAC applies BEFORE versioning | Authorization checks must precede version routing |
| `add_api_key_auth` | Yes | API key validation precedes versioning | Versioning middleware runs after API key auth |
| `add_oauth2_provider` | Yes | OAuth2 token validation precedes versioning | Version routing occurs after token validation |
| `add_mfa` | No | MFA works independently across versions | Each version's routes inherit MFA requirements |
| `add_cache_layer` | No | Cache keys include version prefix | `/api/v1/items` and `/api/v2/items` cache independently |
| `add_circuit_breaker` | No | Circuit breakers apply per version | Each version's routes have independent failure thresholds |

**Conflicts:** None identified.

## 12. Rollback Procedure

### Code rollback (before deploy)
```bash
# Revert file changes
git checkout -- app/api/main.py app/main.py app/core/config.py

# Remove created files
rm -rf app/api/v1 app/api/v2 app/api/middleware/deprecation.py \
  app/api/deps_version.py app/core/api_version.py \
  app/schemas/v1 app/schemas/v2 tests/test_api_versioning.py
```

### Database rollback (after deploy)
```sql
-- Only needed if --with-alembic was used
ALTER TABLE api_versions DROP CONSTRAINT IF EXISTS api_versions_pkey;
DROP TABLE IF EXISTS api_versions;
```

### Data preservation rollback
```bash
# No data migration occurred
echo "No data migration to rollback"
```

### Failure mode: tool partially modified files
```bash
# Restore from backup
cp -r /backup/api_versioning/* .
```

### Emergency: sunset date passed but clients still use v1
```bash
# Temporarily extend sunset date
sed -i "s/Sunset: .*/Sunset: $(date -d '+30 days' -u +'%Y-%m-%dT%H:%M:%SZ')/" \
  app/api/middleware/deprecation.py
```

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-1 | Project has no existing routes | Tool errors: "No routes found. Add at least one resource first." |
| EC-2 | New version label collides with existing | Tool errors: "Version v2 already exists. Choose a different label." |
| EC-3 | Strategy=header but client sends both Accept and v1 path | Tool returns 400: "Conflicting version indicators. Use either path or header, not both." |
| EC-4 | Sunset date in the past | Tool errors: "deprecation_period_days must be ≥ 0. Received -90." |
| EC-5 | Two routes have the same path in v1 but different in v2 | Tool warns: "Route /items exists in both versions with different handlers. Verify intended behavior." |
| EC-6 | v2 route uses a schema that doesn't exist in v1 | Tool creates empty v1 schema stub with warning: "Schema app/schemas/v1/item.py created with minimal fields." |
| EC-7 | Removing a v1 route that v2 doesn't have a successor for | Tool warns: "Route /api/v1/items has no successor in v2. No Link header will be generated." |
| EC-8 | OpenAPI generation for empty version | Tool creates empty OpenAPI spec with warning: "Version v2 has no routes. Add endpoints to populate OpenAPI." |
| EC-9 | Reverse proxy strips the /api/v1 prefix | Middleware reads X-Forwarded-Prefix if available; otherwise returns 400 |
| EC-10 | CORS preflight on a versioned route | Middleware skips deprecation headers for OPTIONS requests |
| EC-11 | Client sends `Accept: application/json` | Defaults to current version with warning: "No version specified in Accept header. Defaulting to v1." |
| EC-12 | Health check route should be UN-versioned | Tool explicitly excludes /health from versioning with note: "Health check remains at /health" |
| EC-13 | New version has a different auth scheme | Tool warns: "Version v2 uses different auth scheme than v1. Verify compatibility." |
| EC-14 | Versioned schemas with circular references | Tool errors: "Circular reference detected in v2 schemas. Resolve manually." |
| EC-15 | Two instances of the tool run concurrently | First wins (atomic file write); second detects existing state and skips |

## 14. Acceptance Criteria (Final Sign-off)

✅ 1. All 30 Completeness Criteria verified  
✅ 2. Tool execution time < 6s measured  
✅ 3. No regression in existing test suite (pytest 0 failures)  
✅ 4. 30 new tests passing in `test_api_versioning.py`  
✅ 5. Versioned OpenAPI docs accessible at `/api/v1/openapi.json` and `/api/v2/openapi.json`  
✅ 6. Deprecation headers present on all v1 routes (T-07..T-09)  
✅ 7. Header strategy fallback works (T-19..T-21)  
✅ 8. Health check remains unversioned at `/health`  
✅ 9. Sunset date computed correctly (T-10)  
✅ 10. Developer successfully migrates client SDK to v2 using generated OpenAPI spec  

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks
- [ ] Validate `project_dir` exists and contains FastAPI project
- [ ] Verify at least one resource exists (model + routes)
- [ ] Check for existing versioning setup (idempotency)
- [ ] Validate `current_version` and `new_version` are distinct
- [ ] Verify `deprecation_period_days` ≥ 0
- [ ] Check for conflicting route paths between versions

### 15.2 Settings configuration
- [ ] Add `API_CURRENT_VERSION` to `app/core/config.py`
- [ ] Add `API_NEW_VERSION` to `app/core/config.py`
- [ ] Compute `API_SUNSET_DATE` in `app/core/api_version.py`
- [ ] Add `API_VERSION_STRATEGY` to `app/core/config.py`
- [ ] Add `API_DEPRECATED_VERSIONS` to `app/core/config.py`
- [ ] Verify all settings parse correctly

### 15.3 Versioned routers
- [ ] Create `app/api/v1/main.py` with existing routes
- [ ] Create `app/api/v2/main.py` with copied routes
- [ ] Modify `app/api/main.py` to mount versioned routers
- [ ] Verify router isolation (no path collisions)
- [ ] Add version prefix to all routes
- [ ] Ensure health check remains unversioned

### 15.4 Middleware
- [ ] Create `app/api/middleware/deprecation.py`
- [ ] Implement `DeprecationMiddleware` class
- [ ] Register middleware in `app/main.py` after auth
- [ ] Verify middleware order with `print` debugging
- [ ] Test header injection on v1 routes
- [ ] Skip middleware for OPTIONS requests

### 15.5 Header strategy
- [ ] Create `app/api/deps_version.py`
- [ ] Implement `get_api_version()` dependency
- [ ] Handle malformed Accept headers
- [ ] Default to current version when header missing
- [ ] Return 406 for unsupported versions
- [ ] Verify fallback behavior

### 15.6 Versioned schemas
- [ ] Create `app/schemas/v1/` with existing schemas
- [ ] Create `app/schemas/v2/` with copied schemas
- [ ] Verify schema isolation between versions
- [ ] Handle circular references
- [ ] Add type hints for schema evolution
- [ ] Ensure OpenAPI reflects versioned schemas

### 15.7 OpenAPI configuration
- [ ] Generate `/api/v1/openapi.json`
- [ ] Generate `/api/v2/openapi.json`
- [ ] Configure root `/openapi.json` to mirror current
- [ ] Include deprecation headers in OpenAPI docs
- [ ] Document versioning strategy
- [ ] Verify OpenAPI generation performance

### 15.8 Test generation
- [ ] Create `tests/test_api_versioning.py`
- [ ] Generate all 30 test cases
- [ ] Verify routing isolation
- [ ] Test deprecation headers
- [ ] Benchmark performance
- [ ] Verify idempotent execution

### 15.9 Documentation
- [ ] Update README.md with versioning docs
- [ ] Add tool entry to `manifest.yaml`
- [ ] Document migration path for clients
- [ ] Include OpenAPI examples
- [ ] Add deprecation header reference
- [ ] Document emergency procedures

### 15.10 Atomicity
- [ ] Use temp-file + rename pattern for all writes
- [ ] Track modified files for rollback
- [ ] Verify file writes with checksums
- [ ] Rollback on any failure
- [ ] Ensure idempotent execution
- [ ] Return success/failure report

### 15.11 Verification
- [ ] Run `ast.parse` on all modified files
- [ ] Verify imports resolve correctly
- [ ] Run existing test suite
- [ ] Execute new versioning tests
- [ ] Measure tool execution time
- [ ] Benchmark routing overhead

### 15.12 Output
- [ ] Generate success report JSON
- [ ] Include files created/modified
- [ ] Add performance metrics
- [ ] List next steps
- [ ] Include warnings
- [ ] Add installation notes

## 16. Documentation Output

```json
{
  "status": "success",
  "files_created": [
    "app/api/v1/main.py",
    "app/api/v2/main.py",
    "app/api/middleware/deprecation.py",
    "app/api/deps_version.py",
    "app/core/api_version.py",
    "app/schemas/v1/item.py",
    "app/schemas/v2/item.py",
    "tests/test_api_versioning.py"
  ],
  "files_modified": [
    "app/api/main.py",
    "app/main.py",
    "app/core/config.py"
  ],
  "metrics": {
    "execution_time_ms": 4218,
    "files_changed": 11,
    "lines_added": 387,
    "lines_removed": 12,
    "current_version": "v1",
    "new_version": "v2",
    "strategy": "path",
    "deprecation_period_days": 180
  },
  "next_steps": [
    "Run pytest tests/test_api_versioning.py -v",
    "Verify routes at /api/v1/items and /api/v2/items",
    "Check deprecation headers on v1 routes",
    "Test OpenAPI docs at /api/v1/openapi.json and /api/v2/openapi.json",
    "Migrate client SDK to v2 using generated OpenAPI spec"
  ],
  "warnings": [
    "Health check remains at /health and is NOT versioned",
    "CORS preflight requests skip deprecation headers",
    "Reverse proxies must preserve /api/v1 prefix for path strategy"
  ],
  "notes": [
    "Versioning enabled with strategy=path",
    "DeprecationMiddleware registered after auth",
    "Sunset date computed as 2026-10-08",
    "Existing tests still pass: 47/47",
    "Routing overhead measured at 0.08ms p99"
  ]
}
