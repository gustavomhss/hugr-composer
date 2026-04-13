<!--
{
  "tool_num": "017",
  "tool_name": "add_api_versioning",
  "model": "deepseek/deepseek-chat",
  "elapsed_seconds": 439.3632449150318,
  "prompt_tokens": 46592,
  "completion_tokens": 9802,
  "cost_usd": 0.049914520000000004,
  "calls": 6
}
-->

# TOOL-017: add_api_versioning

> **Status**: SPEC v2 (rigorous)  
> **Last updated**: 2026-04-08  

---

## 1. Overview

| Field          | Value                                                                 |
|----------------|-----------------------------------------------------------------------|
| Tool name      | `fastapi_add_api_versioning`                                          |
| Category       | EXTEND > API Design                                                  |
| Complexity     | High                                                                 |
| Dependencies   | FastAPI, Pydantic, Starlette, Alembic (optional)                     |
| Signature      | `add_api_versioning(project_dir: str, current_version: str = "v1", new_version: str = "v2", strategy: Literal["path", "header"] = "path", deprecation_period_days: int = 180) -> dict` |
| Parameters     | `project_dir`: Absolute path to the project root directory<br>`current_version`: Label for the existing API version (default `v1`)<br>`new_version`: Label for the new API version (default `v2`)<br>`strategy`: Version selection method (`path` or `header`, default `path`)<br>`deprecation_period_days`: Days until v1 routes are removed (default `180`) |

## 2. Purpose

This tool adds API versioning to FastAPI applications, enabling multiple API versions to coexist in the same codebase. It solves the problem of evolving APIs without breaking existing clients by isolating versions into separate routers and schemas. The tool integrates by generating version-specific directories, routers, and OpenAPI documentation while maintaining backward compatibility through a deprecation middleware and field translation layer.

## 3. Performance SLOs

| Metric                  | Target                          | Why                                                                 |
|-------------------------|---------------------------------|---------------------------------------------------------------------|
| Tool execution time     | < 6s                           | Multiple files are modified and created                             |
| Files modified          | ≤ 6                            | Global files like `main.py` and `config.py` are updated            |
| Files created           | ≥ 8                            | Versioned routers, schemas, middleware, and tests are generated    |
| Routing overhead        | < 0.1 ms                       | FastAPI router resolution is optimized                             |
| Header parsing overhead | < 0.5 ms                       | Header strategy uses efficient parsing                             |
| Migration runtime       | 0s                             | No database changes are required                                   |
| OpenAPI generation      | < 200 ms per version           | OpenAPI generation is optimized for large schemas                  |
| Memory overhead         | < 1 MB per worker              | Minimal additional memory for versioning middleware                |
| No DB schema changes    | 0                              | Versioning is implemented purely in code                           |

---

## 4. Code Examples (Before / After)

### 4.1 Main application router: BEFORE
```python
# app/api/main.py
from fastapi import APIRouter

from app.api.endpoints import items, users, orders

router = APIRouter()

router.include_router(items.router, prefix="/items", tags=["items"])
router.include_router(users.router, prefix="/users", tags=["users"])
router.include_router(orders.router, prefix="/orders", tags=["orders"])
```

### 4.2 Main application router: AFTER
```python
# app/api/main.py
from fastapi import APIRouter

from app.api.v1.main import router as v1_router
from app.api.v2.main import router as v2_router

router = APIRouter()

router.include_router(v1_router, prefix="/api/v1")
router.include_router(v2_router, prefix="/api/v2")
```

### 4.3 Item endpoint: BEFORE
```python
# app/api/endpoints/items.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.api.deps import get_current_user, get_db
from app.crud.item import get_item, create_item, update_item, delete_item
from app.schemas.item import Item, ItemCreate, ItemUpdate
from app.models.user import User

router = APIRouter()

@router.get("/{item_id}", response_model=Item)
async def read_item(
    item_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Item:
    item = await get_item(db, item_id=item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if item.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    return item

@router.post("/", response_model=Item, status_code=status.HTTP_201_CREATED)
async def create_new_item(
    item_in: ItemCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Item:
    return await create_item(db, item_in=item_in, owner_id=current_user.id)
```

### 4.4 Item endpoint: AFTER (v1 version)
```python
# app/api/v1/endpoints/items.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.api.deps import get_current_user, get_db
from app.crud.item import get_item, create_item, update_item, delete_item
from app.schemas.v1.item import Item, ItemCreate, ItemUpdate
from app.models.user import User

router = APIRouter()

@router.get("/items/{item_id}", response_model=Item)
async def read_item_v1(
    item_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Item:
    item = await get_item(db, item_id=item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if item.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    return item

@router.post("/items/", response_model=Item, status_code=status.HTTP_201_CREATED)
async def create_item_v1(
    item_in: ItemCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Item:
    return await create_item(db, item_in=item_in, owner_id=current_user.id)
```

### 4.5 Versioned schema directory (NEW)
```python
# app/schemas/v2/item.py
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict
from uuid import UUID


class ItemBase(BaseModel):
    title: str = Field(max_length=255, description="Display name of the item")
    description: str | None = Field(
        default=None, max_length=1024, description="Extended description"
    )
    tags: list[str] = Field(
        default_factory=list, max_items=10, description="Categorical tags"
    )


class ItemCreate(ItemBase):
    pass


class ItemUpdate(BaseModel):
    title: str | None = Field(None, max_length=255)
    description: str | None = Field(None, max_length=1024)
    tags: list[str] | None = Field(None, max_items=10)


class Item(ItemBase):
    id: UUID
    owner_id: UUID
    created_at: datetime
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)
```

### 4.6 API version constants module (NEW)
```python
# app/core/api_version.py
from datetime import datetime, timedelta
from typing import Final

# Configuration
API_CURRENT_VERSION: Final[str] = "v2"
API_DEPRECATED_VERSIONS: Final[list[str]] = ["v1"]
API_VERSION_STRATEGY: Final[str] = "path"  # "path" or "header"

# Sunset dates (computed at tool execution time)
API_SUNSET_DATES: Final[dict[str, datetime]] = {
    "v1": datetime(2026, 10, 5, 0, 0, 0)  # now + 180 days
}

# Vendor media type for header strategy
API_VENDOR_TYPE: Final[str] = "application/vnd.company"


def get_version_from_accept_header(accept: str | None) -> str:
    """Parse Accept header to extract API version."""
    if not accept:
        return API_CURRENT_VERSION
    
    # Example: application/vnd.company.v2+json
    for part in accept.split(","):
        part = part.strip()
        if API_VENDOR_TYPE in part:
            try:
                version_part = part.split(".")[1]  # vnd.company.v2+json -> v2+json
                version = version_part.split("+")[0]  # v2+json -> v2
                if version in [API_CURRENT_VERSION] + API_DEPRECATED_VERSIONS:
                    return version
            except (IndexError, AttributeError):
                continue
    
    return API_CURRENT_VERSION


def compute_sunset_date(deprecation_days: int) -> datetime:
    """Calculate sunset date from today."""
    return datetime.utcnow() + timedelta(days=deprecation_days)
```

### 4.7 Deprecation middleware (NEW)
```python
# app/api/middleware/deprecation.py
from datetime import datetime
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from urllib.parse import urljoin

from app.core.api_version import API_DEPRECATED_VERSIONS, API_SUNSET_DATES


class DeprecationMiddleware(BaseHTTPMiddleware):
    """Adds RFC 8594 deprecation headers for deprecated API versions."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        
        # Check if request path is under a deprecated version
        for deprecated_version in API_DEPRECATED_VERSIONS:
            deprecated_prefix = f"/api/{deprecated_version}/"
            if request.url.path.startswith(deprecated_prefix):
                # Add deprecation headers
                response.headers["Deprecation"] = "true"
                
                # Format Sunset date per RFC 7231
                sunset_date = API_SUNSET_DATES.get(deprecated_version)
                if sunset_date:
                    response.headers["Sunset"] = sunset_date.strftime(
                        "%a, %d %b %Y %H:%M:%S GMT"
                    )
                
                # Build successor link
                current_prefix = f"/api/{deprecated_version}"
                successor_prefix = "/api/v2"
                if request.url.path.startswith(current_prefix):
                    successor_path = request.url.path.replace(
                        current_prefix, successor_prefix, 1
                    )
                    base_url = str(request.base_url)
                    successor_url = urljoin(base_url, successor_path)
                    response.headers["Link"] = (
                        f'<{successor_url}>; rel="successor-version"'
                    )
        
        return response
```

### 4.8 Header strategy dependency (NEW)
```python
# app/api/deps_version.py
from fastapi import Header, HTTPException, Request
from typing import Annotated

from app.core.api_version import (
    API_CURRENT_VERSION,
    API_DEPRECATED_VERSIONS,
    get_version_from_accept_header,
)


def get_api_version_header(
    accept: Annotated[str | None, Header(alias="Accept")] = None,
) -> str:
    """
    Dependency for header-based versioning.
    Extracts version from Accept header or defaults to current.
    """
    version = get_version_from_accept_header(accept)
    
    # Validate version exists
    valid_versions = [API_CURRENT_VERSION] + API_DEPRECATED_VERSIONS
    if version not in valid_versions:
        raise HTTPException(
            status_code=406,
            detail=f"Unsupported API version in Accept header. "
                   f"Supported: {', '.join(valid_versions)}",
        )
    
    return version


def get_api_version_path(request: Request) -> str:
    """
    Dependency for path-based versioning.
    Extracts version from URL path segment.
    """
    path_parts = request.url.path.split("/")
    if len(path_parts) > 2 and path_parts[1] == "api":
        version = path_parts[2]
        valid_versions = [API_CURRENT_VERSION] + API_DEPRECATED_VERSIONS
        if version in valid_versions:
            return version
    
    # Default to current if path doesn't match pattern
    return API_CURRENT_VERSION
```

### 4.9 Migration for version configuration table
```python
# alembic/versions/0010_add_api_version_config.py
"""Add API version configuration table

Revision ID: 0010
Revises: 0009
Create Date: 2026-04-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0010"
down_revision = "0009"


def upgrade() -> None:
    # Create table for version configuration (optional, for audit)
    op.create_table(
        "api_version_config",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("version_label", sa.String(16), nullable=False, unique=True),
        sa.Column("is_current", sa.Boolean(), nullable=False, default=False),
        sa.Column("is_deprecated", sa.Boolean(), nullable=False, default=False),
        sa.Column("sunset_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.CheckConstraint(
            "NOT (is_current AND is_deprecated)",
            name="ck_version_current_not_deprecated"
        ),
    )
    
    # Insert initial configuration
    op.execute("""
        INSERT INTO api_version_config 
        (version_label, is_current, is_deprecated, sunset_date)
        VALUES 
        ('v1', false, true, '2026-10-05 00:00:00+00'),
        ('v2', true, false, NULL)
    """)
    
    # Create index for quick lookups
    op.create_index(
        "ix_api_version_config_current",
        "api_version_config",
        ["is_current"],
        unique=True,
        postgresql_where=sa.text("is_current = true")
    )
    op.create_index(
        "ix_api_version_config_label",
        "api_version_config",
        ["version_label"],
        unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_api_version_config_label", table_name="api_version_config")
    op.drop_index("ix_api_version_config_current", table_name="api_version_config")
    op.drop_table("api_version_config")

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Version routing is strictly isolated** | Each version's routes are mounted under `/api/<version>` with separate `APIRouter` instances. No cross-version handler leakage. |
| QS-2 | **Deprecation headers are always present for deprecated versions** | `DeprecationMiddleware` injects headers for any path starting with `/api/<deprecated_version>`. |
| QS-3 | **Schema versions are directory-isolated** | `app/schemas/v1/` and `app/schemas/v2/` contain independent schema definitions. No shared imports between versions. |
| QS-4 | **Header strategy defaults to current version** | `get_api_version()` dependency falls back to `API_CURRENT_VERSION` when Accept header is missing/malformed. |
| QS-5 | **OpenAPI docs are version-specific** | Each version's router generates its own OpenAPI at `/api/<version>/openapi.json` with no cross-pollution. |
| QS-6 | **No regression in v1 behavior** | Existing v1 routes are copied verbatim to `app/api/v1/` with identical path structures and response shapes. |
| QS-7 | **Sunset dates are computed exactly** | `API_SUNSET_DATES` in `core/api_version.py` uses `datetime.now() + timedelta(days=deprecation_period_days)`. |
| QS-8 | **Link headers point to valid successors** | Middleware validates the target path exists in the successor version before adding the `Link` header. |
| QS-9 | **Deprecation middleware runs after auth** | Middleware registration order in `main.py` ensures auth completes before version checks. |
| QS-10 | **CRUD remains version-agnostic** | `app/crud/` contains no version-specific logic; translation happens in route handlers via `to_v1_schema()`. |
| QS-11 | **Health checks remain unversioned** | `/health` route is explicitly excluded from versioning and remains at the root path. |

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | `core/api_version.py` exists with version constants | File exists, exports `API_CURRENT_VERSION`, `API_DEPRECATED_VERSIONS`, `API_SUNSET_DATES` |
| CC-02 | `middleware/deprecation.py` implements `DeprecationMiddleware` | File exists, class inherits `BaseHTTPMiddleware`, adds headers |
| CC-03 | Versioned router directories exist (`app/api/v1/`, `app/api/v2/`) | Directory structure matches |
| CC-04 | Versioned schema directories exist (`app/schemas/v1/`, `app/schemas/v2/`) | Directory structure matches |
| CC-05 | `deps_version.py` implements header parsing | File exists, contains `get_api_version()` dependency |
| CC-06 | Main router includes both versioned routers with prefixes | grep `router.include_router(v1_router, prefix="/api/v1")` in `main.py` |
| CC-07 | Deprecation middleware registered in FastAPI app | grep `app.add_middleware(DeprecationMiddleware)` after auth middleware |
| CC-08 | All existing routes copied to v1 directory unchanged | diff `app/api/endpoints/` vs `app/api/v1/` shows identical handlers |
| CC-09 | v2 routes initially match v1 routes | diff `app/api/v1/` vs `app/api/v2/` shows identical initial state |
| CC-10 | OpenAPI available at `/api/v1/openapi.json` and `/api/v2/openapi.json` | curl both endpoints, validate 200 OK |
| CC-11 | Root `/openapi.json` redirects to current version | curl `/openapi.json`, validate Location header |
| CC-12 | Sunset date is 180 days in future by default | Inspect `API_SUNSET_DATES` calculation |
| CC-13 | Health check remains at `/health` | grep `@app.get("/health")` in `main.py` |
| CC-14 | Header strategy dependency skips versioned paths | Inspect `get_api_version()` bypass logic for `/api/v1/...` paths |
| CC-15 | All v1 schemas copied to `app/schemas/v1/` | diff original schemas vs v1 directory |
| CC-16 | v2 schemas initially match v1 schemas | diff `app/schemas/v1/` vs `app/schemas/v2/` |
| CC-17 | Deprecation headers only on v1 routes | curl v1 and v2 routes, check headers |
| CC-18 | Link header points to valid v2 path | Inspect middleware path translation logic |
| CC-19 | Tool execution time < 6s | Time measurement during run |
| CC-20 | Files modified count ≤ 6 | Count in tool output |
| CC-21 | Files created count ≥ 8 | Count in tool output |
| CC-22 | Routing overhead < 0.1ms | Benchmark T-28 |
| CC-23 | Header parsing overhead < 0.5ms | Benchmark T-29 |
| CC-24 | OpenAPI generation < 200ms per version | Benchmark T-30 |
| CC-25 | No DB schema changes | Inspect Alembic history |
| CC-26 | Existing tests pass | pytest 0 failures |
| CC-27 | New test file `test_api_versioning.py` exists | File exists with 30 tests |
| CC-28 | CRUD remains unchanged | diff `app/crud/` before/after |
| CC-29 | Config updated with version constants | grep `API_CURRENT_VERSION` in `config.py` |
| CC-30 | README.md updated with versioning docs | grep "API Versioning" in README |

## 7. Definition of Done

- [ ] All 30 Completeness Criteria verified
- [ ] Tool execution time < 6s (CC-19)
- [ ] Routing overhead < 0.1ms (CC-22)
- [ ] Header parsing overhead < 0.5ms (CC-23)
- [ ] OpenAPI generation < 200ms per version (CC-24)
- [ ] Existing test suite passes (CC-26)
- [ ] New test file with 30 tests exists (CC-27)
- [ ] All versioned directories created (CC-03, CC-04)
- [ ] Deprecation middleware registered (CC-07)
- [ ] Sunset date computed correctly (CC-12)
- [ ] Health check remains unversioned (CC-13)
- [ ] README updated with versioning docs (CC-30)
- [ ] No DB schema changes (CC-25)

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-VER-01 | A v1 call NEVER routes to a v2 handler | Path-based router isolation | T-01, T-02 |
| INV-VER-02 | Deprecated routes ALWAYS emit Deprecation headers | Middleware path prefix check | T-07, T-08 |
| INV-VER-03 | Link header points to a valid v2 equivalent route | Middleware path translation | T-09, T-10 |
| INV-VER-04 | OpenAPI contains ONLY its version's routes | Separate OpenAPI generation per router | T-24, T-25 |
| INV-VER-05 | Header strategy defaults to current version | `get_api_version()` fallback logic | T-19, T-20 |
| INV-VER-06 | Health check remains at root path | Explicit exclusion from versioning | T-11 |
| INV-VER-07 | v1 behavior matches pre-versioning exactly | Route and schema copy verification | T-03, T-04 |

---

## 9. User Stories

### 9.1 Core Versioning Functionality (US-01 .. US-05)

**US-01: Deploy v2 alongside v1**
- **As a** backend engineer evolving our API
- **I want** to run `add_api_versioning(project_dir="/app", current_version="v1", new_version="v2")`
- **So that** both versions run simultaneously without breaking existing clients
- **Given:** FastAPI app with `/items` and `/users` routes
- **When:** Tool executes successfully
- **Then:**
  - Existing routes move to `app/api/v1/main.py`
  - Identical routes copied to `app/api/v2/main.py`
  - Both versions available at `/api/v1/items` and `/api/v2/items`
  - OpenAPI docs at `/api/v1/openapi.json` and `/api/v2/openapi.json`

**US-02: Access v1 routes during deprecation**
- **As a** mobile app maintaining backward compatibility
- **I want** to keep calling v1 endpoints
- **Given:** Deprecation period set to 180 days
- **When:** Calling `GET /api/v1/items/123`
- **Then:**
  - Response includes `Deprecation: true` header
  - `Sunset` header shows exact removal date (current date + 180 days)
  - Response body matches pre-versioning format exactly (INV-VER-06)

**US-03: Migrate to v2 endpoints**
- **As a** web client developer
- **I want** to transition to v2 endpoints
- **Given:** New `ItemV2` schema with added `tags` field
- **When:** Calling `POST /api/v2/items` with new schema
- **Then:**
  - Request succeeds with 201 Created
  - Response includes v2-specific fields
  - No impact on v1 endpoints (INV-VER-01)

**US-04: Verify v1 behavior unchanged**
- **As a** QA engineer
- **I want** to validate v1 functionality
- **Given:** Existing test suite for v1 API
- **When:** Running all v1 tests against `/api/v1/` endpoints
- **Then:**
  - All tests pass with identical responses
  - No regressions in status codes or body shapes
  - Performance remains within 0.1ms overhead (CC-22)

**US-05: Access versioned OpenAPI docs**
- **As a** API consumer
- **I want** to discover version-specific endpoints
- **Given:** Running FastAPI app with versioning enabled
- **When:** Requesting `/api/v2/openapi.json`
- **Then:**
  - Documentation shows only v2 routes
  - Schema definitions match v2 models
  - No v1 routes appear (INV-VER-04)

### 9.2 Deprecation Lifecycle (US-06 .. US-10)

**US-06: Receive deprecation warnings for v1**
- **As a** client application
- **I want** to know when v1 will sunset
- **Given:** Request to deprecated v1 endpoint
- **When:** Calling `GET /api/v1/users/me`
- **Then:**
  - Response includes `Deprecation: true` header
  - `Sunset` header shows RFC-1123 formatted date
  - `Link` header points to `/api/v2/users/me` (INV-VER-02)

**US-07: Follow Link header to successor**
- **As a** developer migrating from v1 to v2
- **I want** to discover equivalent v2 endpoints
- **Given:** Deprecated v1 endpoint `/api/v1/orders`
- **When:** Following the `Link` header value
- **Then:**
  - Redirects to `/api/v2/orders`
  - New endpoint exists and returns 200 OK
  - Response schema matches v2 standards (CC-10)

**US-08: Maintain v1 during deprecation**
- **As a** product owner
- **I want** v1 to remain fully functional
- **Given:** 90 days remaining in deprecation period
- **When:** Calling all v1 endpoints
- **Then:**
  - All responses include correct deprecation headers
  - No functionality is degraded
  - Performance remains within SLOs (CC-19)

**US-09: Validate sunset date calculation**
- **As a** release engineer
- **I want** accurate deprecation timelines
- **Given:** Tool run on 2026-04-08 with 180-day period
- **When:** Checking `API_SUNSET_DATES` in `core/api_version.py`
- **Then:**
  - v1 sunset date is 2026-10-05
  - Date is computed as `datetime.now() + timedelta(days=180)`
  - Timezone is UTC (CC-12)

**US-10: Exclude health checks from versioning**
- **As a** monitoring system
- **I want** consistent health check endpoint
- **Given:** Versioned FastAPI application
- **When:** Calling `GET /health`
- **Then:**
  - Returns 200 OK with unversioned response
  - No deprecation headers present
  - Route remains at root path (INV-VER-06)

### 9.3 Schema Evolution (US-11 .. US-15)

**US-11: Add new field in v2 schema**
- **As a** API designer
- **I want** to extend models in v2
- **Given:** `ItemV1` schema with `title` and `description`
- **When:** Creating `ItemV2` with added `tags: list[str]`
- **Then:**
  - v1 schema remains unchanged in `app/schemas/v1/`
  - v2 schema exists in `app/schemas/v2/`
  - CRUD operations accept both versions (CC-10)

**US-12: Rename field across versions**
- **As a** API developer
- **I want** to improve field naming
- **Given:** v1 uses `created_at` timestamp field
- **When:** v2 renames it to `created_date`
- **Then:**
  - v1 routes continue using `created_at`
  - v2 routes expose `created_date`
  - Translation layer handles both names (CC-15)

**US-13: Remove deprecated field**
- **As a** API maintainer
- **I want** to clean up unused fields
- **Given:** v1 `User` schema with `legacy_id` field
- **When:** Removing `legacy_id` from v2 schema
- **Then:**
  - v1 responses still include `legacy_id`
  - v2 responses omit the field
  - No database schema changes required (CC-25)

**US-14: Change field type in v2**
- **As a** data architect
- **I want** to strengthen type safety
- **Given:** v1 `price` field as `float`
- **When:** v2 changes to `Decimal` type
- **Then:**
  - v1 continues accepting floats
  - v2 requires precise decimal values
  - OpenAPI docs reflect both types (CC-10)

**US-15: Maintain schema isolation**
- **As a** security engineer
- **I want** to prevent version leaks
- **Given:** v2-only `metadata` field
- **When:** Calling v1 endpoint
- **Then:**
  - Response never includes `metadata`
  - v1 schema has no knowledge of v2 additions
  - Pydantic models are strictly separated (INV-VER-04)

### 9.4 Version Selection Strategies (US-16 .. US-20)

**US-16: Default to path-based versioning**
- **As a** API consumer
- **I want** explicit version in URL
- **Given:** Newly versioned API
- **When:** Calling `/api/v2/items`
- **Then:**
  - Request routes to v2 handler
  - No version headers required
  - CDN-friendly caching (CC-14)

**US-17: Use header-based versioning**
- **As a** API client
- **I want** clean URLs with version negotiation
- **Given:** Strategy set to `header`
- **When:** Sending `Accept: application/vnd.app.v2+json`
- **Then:**
  - Routes to v2 handler at `/api/items`
  - Defaults to current version if header missing
  - Parses vendor type correctly (INV-VER-05)

**US-18: Handle malformed version header**
- **As a** robust client
- **I want** graceful fallback
- **Given:** Header strategy enabled
- **When:** Sending `Accept: application/json` (no version)
- **Then:**
  - Uses `API_CURRENT_VERSION`
  - Returns 200 OK with current version
  - Logs warning about missing version (CC-14)

**US-19: Prefer explicit path over header**
- **As a** API gateway
- **I want** unambiguous version selection
- **Given:** Request to `/api/v1/items` with `Accept: v2`
- **When:** Path and header conflict
- **Then:**
  - Path wins (routes to v1)
  - Response includes v1 schema
  - Deprecation headers if applicable (INV-VER-02)

**US-20: Support mixed strategy rollout**
- **As a** devops engineer
- **I want** to test header strategy
- **Given:** Production using path strategy
- **When:** Deploying with `strategy="header"`
- **Then:**
  - Both `/api/v1/` and header negotiation work
  - No downtime during transition
  - Metrics show strategy usage (CC-29)

### 9.5 Performance & Observability (US-21 .. US-25)

**US-21: Measure version routing overhead**
- **As a** performance engineer
- **I want** to validate SLOs
- **Given:** Versioned endpoints
- **When:** Benchmarking `GET /api/v2/items`
- **Then:**
  - Routing adds < 0.1ms latency
  - Throughput remains > 1000 RPS
  - No memory leaks detected (CC-22)

**US-22: Monitor deprecation header impact**
- **As a** SRE
- **I want** to track v1 usage
- **Given:** Deprecation headers enabled
- **When:** Analyzing access logs
- **Then:**
  - Can filter by `Deprecation: true` responses
  - Sunset timeline visible in dashboards
  - Alert when v1 traffic spikes (CC-30)

**US-23: Validate OpenAPI generation speed**
- **As a** documentation portal
- **I want** fast schema loading
- **Given:** 50+ endpoint API
- **When:** Requesting `/api/v2/openapi.json`
- **Then:**
  - Response in < 200ms
  - Schema validates against OpenAPI 3.1
  - No missing endpoints (CC-24)

**US-24: Audit version isolation**
- **As a** security auditor
- **I want** to confirm strict separation
- **Given:** v1 and v2 running concurrently
- **When:** Inspecting handler assignments
- **Then:**
  - No v1 calls reach v2 handlers (INV-VER-01)
  - No shared schema imports between versions
  - Middleware order correct (CC-07)

**US-25: Track version adoption**
- **As a** product manager
- **I want** migration metrics
- **Given:** Versioned API endpoints
- **When:** Analyzing traffic patterns
- **Then:**
  - Can compare `/api/v1` vs `/api/v2` requests
  - Monitor Link header click-throughs
  - Sunset compliance visible (CC-12)

---

## 10. Test Plan

### 10.1 Routing Isolation

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | v1 call routes to v1 handler | Existing `/items` route moved to v1 | GET /api/v1/items | 200 OK, response matches pre-versioning |
| T-02 | v2 call routes to v2 handler | Identical `/items` route copied to v2 | GET /api/v2/items | 200 OK, response matches v2 schema |
| T-03 | v1 call never hits v2 handler | Both versions have `/items` route | GET /api/v1/items | Response lacks v2-specific fields |
| T-04 | v2 call never hits v1 handler | Both versions have `/items` route | GET /api/v2/items | Response includes v2-specific fields |
| T-05 | Invalid version returns 404 | Only v1 and v2 exist | GET /api/v3/items | 404 Not Found |
| T-06 | Health check remains unversioned | Versioning enabled | GET /health | 200 OK, no deprecation headers |

### 10.2 Deprecation Headers

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-07 | Deprecation header on v1 | Deprecation period set to 180 days | GET /api/v1/items | Deprecation: true header present |
| T-08 | Sunset header on v1 | Current date 2026-04-08 | GET /api/v1/items | Sunset: Mon, 05 Oct 2026 00:00:00 GMT |
| T-09 | Link header points to valid v2 route | `/items` exists in both versions | GET /api/v1/items | Link: </api/v2/items>; rel="successor-version" |
| T-10 | No deprecation headers on v2 | v2 is current version | GET /api/v2/items | No Deprecation or Sunset headers |
| T-11 | Deprecation headers only on v1 | Both versions have `/users` route | GET /api/v1/users | Deprecation headers present |
| T-12 | No Link header if no successor | v1 route `/legacy` has no v2 equivalent | GET /api/v1/legacy | No Link header |

### 10.3 Schema Isolation

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-13 | v1 schema matches pre-versioning | Existing Item schema moved to v1 | GET /api/v1/items/123 | Response matches original schema |
| T-14 | v2 schema can add new fields | ItemV2 adds `tags` field | GET /api/v2/items/123 | Response includes tags field |
| T-15 | Field rename across versions | v1 uses `created_at`, v2 uses `created_date` | GET /api/v2/items/123 | Response uses created_date |
| T-16 | Field removal in v2 | v1 has `legacy_id`, v2 removes it | GET /api/v2/items/123 | Response lacks legacy_id |
| T-17 | Type change across versions | v1 `price` is float, v2 is Decimal | POST /api/v2/items | Accepts Decimal, rejects float |
| T-18 | Circular references isolated | v1 and v2 schemas have circular refs | GET /api/v1/items/123 | Response validates against v1 schema |

### 10.4 Header Strategy

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-19 | Header strategy defaults to current | Accept header missing | GET /api/items | Routes to v2 handler |
| T-20 | Valid Accept header routes correctly | Accept: application/vnd.app.v2+json | GET /api/items | Routes to v2 handler |
| T-21 | Malformed Accept header defaults | Accept: application/json | GET /api/items | Routes to v2 handler |
| T-22 | Path wins over header | Path /api/v1/items, Accept: v2 | GET /api/v1/items | Routes to v1 handler |
| T-23 | Unknown version in header defaults | Accept: application/vnd.app.v3+json | GET /api/items | Routes to v2 handler |
| T-24 | Header strategy with invalid vendor | Accept: application/vnd.other.v2+json | GET /api/items | Routes to v2 handler |

### 10.5 OpenAPI Documentation

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-25 | v1 OpenAPI contains only v1 routes | Both versions have `/items` route | GET /api/v1/openapi.json | Only /api/v1/items in paths |
| T-26 | v2 OpenAPI contains only v2 routes | Both versions have `/items` route | GET /api/v2/openapi.json | Only /api/v2/items in paths |
| T-27 | Root OpenAPI defaults to current | v2 is current version | GET /openapi.json | Redirects to /api/v2/openapi.json |
| T-28 | OpenAPI generation time < 200ms | 50+ endpoints per version | GET /api/v2/openapi.json | Response in < 200ms |
| T-29 | OpenAPI schema validation | Versioned OpenAPI docs | Validate against OpenAPI 3.1 spec | All schemas valid |
| T-30 | OpenAPI includes deprecation info | v1 routes are deprecated | GET /api/v1/openapi.json | Deprecation info in v1 paths |

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|----------------|-------------|-------|
| `add_soft_delete` | Yes | Soft delete must run before versioning | Versioned schemas inherit soft delete fields |
| `add_cursor_pagination` | No | Pagination works independently | Versioned routes can use cursor pagination |
| `add_search` | No | Search works independently | Versioned routes can use search |
| `add_audit_log` | Yes | Audit logs must run before versioning | Versioned routes inherit audit logging |
| `add_data_export` | No | Data export works independently | Versioned routes can use data export |
| `add_bulk_operations` | No | Bulk operations work independently | Versioned routes can use bulk operations |
| `add_multi_tenancy` | Yes | Versioning must run after multi-tenancy | Versioned routes inherit tenant context |
| `add_feature_flags` | No | Feature flags work independently | Versioned routes can use feature flags |
| `add_api_key_auth` | Yes | API key auth must run before versioning | Versioned routes inherit API key validation |
| `add_oauth2_provider` | Yes | OAuth2 must run before versioning | Versioned routes inherit OAuth2 scopes |
| `add_rbac` | Yes | RBAC must run before versioning | Versioned routes inherit RBAC checks |
| `add_mfa` | Yes | MFA must run before versioning | Versioned routes inherit MFA requirements |
| `add_cache_layer` | No | Cache layer works independently | Versioned routes can use caching |
| `add_circuit_breaker` | No | Circuit breaker works independently | Versioned routes can use circuit breaking |
| `add_outbox_pattern` | No | Outbox pattern works independently | Versioned routes can use outbox pattern |
| `add_long_running_task` | No | Long running tasks work independently | Versioned routes can use long running tasks |
| `add_sse` | No | SSE works independently | Versioned routes can use SSE |
| `add_webhook_sender` | No | Webhook sender works independently | Versioned routes can use webhook sender |
| `add_webhook_receiver` | No | Webhook receiver works independently | Versioned routes can use webhook receiver |

**Conflicts:** None identified.

## 12. Rollback Procedure

### Code rollback (before deploy)
```bash
# Revert modified files
git checkout app/main.py app/api/main.py app/core/config.py

# Remove created files
rm -rf app/core/api_version.py app/api/middleware/deprecation.py \
       app/api/v1/ app/api/v2/ app/schemas/v1/ app/schemas/v2/ \
       app/api/deps_version.py tests/test_api_versioning.py
```

### Database rollback (after deploy)
```sql
-- No database changes to rollback
SELECT 'No database changes were made during API versioning';
```

### Data preservation rollback
```bash
# No data migration occurred
echo "No data migration was performed during API versioning"
```

### Failure mode: tool partially modified files
```bash
# Find and revert any partially modified files
find app/ tests/ -name '*.py' -exec git checkout {} \;

# Remove any partially created directories
rm -rf app/api/v1/ app/api/v2/ app/schemas/v1/ app/schemas/v2/
```

### Emergency: Versioning breaks production
```bash
# Temporarily disable versioning middleware
sed -i '/DeprecationMiddleware/d' app/main.py

# Redirect all traffic to v1
sed -i 's/\/api\/v2/\/api\/v1/g' app/main.py
```

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-1 | Project has no existing routes | Tool errors: "No routes found in project. Add routes first." |
| EC-2 | New version label collides with existing | Tool errors: "Version v2 already exists. Choose a different label." |
| EC-3 | Strategy=header but client sends both Accept and v1 path | Path wins: routes to v1 handler |
| EC-4 | Sunset date in the past | Tool errors: "Deprecation period must be positive. Got -30 days." |
| EC-5 | Two routes have the same path in v1 but different in v2 | Tool warns: "Route conflict detected. Manual resolution required." |
| EC-6 | v2 route uses a schema that doesn't exist in v1 | Tool errors: "Schema mismatch. Add schema to v1 first." |
| EC-7 | Removing a v1 route that v2 doesn't have a successor for | No Link header added for that route |
| EC-8 | OpenAPI generation for empty version | Returns empty OpenAPI spec with 200 OK |
| EC-9 | Versioned middleware order: deprecation middleware runs AFTER auth | Tool reorders middleware automatically |
| EC-10 | Reverse proxy strips the /api/v1 prefix | Tool documents X-Forwarded-Prefix handling |
| EC-11 | CORS preflight on a versioned route | Versioning middleware skips preflight requests |
| EC-12 | Client sends `Accept: application/json` (no version vendor type) | Defaults to current version |
| EC-13 | Health check route should be UN-versioned | Explicitly excluded from versioning |
| EC-14 | New version has a different auth scheme than current | Tool warns: "Auth scheme mismatch detected." |
| EC-15 | Versioned schemas with circular references | Each version maintains independent circular references |

## 14. Acceptance Criteria (Final Sign-off)

✅ All 30 Completeness Criteria verified  
✅ Tool execution time < 6s  
✅ Routing overhead < 0.1ms  
✅ Header parsing overhead < 0.5ms  
✅ OpenAPI generation < 200ms per version  
✅ Existing test suite passes  
✅ New test file with 30 tests exists  
✅ All versioned directories created  
✅ Deprecation middleware registered  
✅ Run end-to-end test: `curl -X GET http://localhost:8000/api/v1/items` → 200 OK with deprecation headers  

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks
- [ ] Validate `project_dir` exists
- [ ] Validate `app/` subdirectory exists
- [ ] Validate existing routes in `app/api/`
- [ ] Parse target route files with AST
- [ ] Detect existing versioning setup
- [ ] Validate deprecation period is positive

### 15.2 Version constants
- [ ] Create `app/core/api_version.py`
- [ ] Define `API_CURRENT_VERSION`, `API_DEPRECATED_VERSIONS`, `API_SUNSET_DATES`
- [ ] Compute sunset date as `now() + deprecation_period_days`
- [ ] Export version constants
- [ ] Verify file parses
- [ ] Write atomically

### 15.3 Deprecation middleware
- [ ] Create `app/api/middleware/deprecation.py`
- [ ] Implement `DeprecationMiddleware` class
- [ ] Add deprecation headers for v1 routes
- [ ] Add Link header pointing to v2 equivalent
- [ ] Verify file parses
- [ ] Write atomically

### 15.4 Versioned routers
- [ ] Create `app/api/v1/` directory
- [ ] Move existing routes to `app/api/v1/main.py`
- [ ] Create `app/api/v2/` directory
- [ ] Copy v1 routes to `app/api/v2/main.py`
- [ ] Verify both files parse
- [ ] Write atomically

### 15.5 Versioned schemas
- [ ] Create `app/schemas/v1/` directory
- [ ] Move existing schemas to `app/schemas/v1/`
- [ ] Create `app/schemas/v2/` directory
- [ ] Copy v1 schemas to `app/schemas/v2/`
- [ ] Verify all schema files parse
- [ ] Write atomically

### 15.6 Header strategy dependency
- [ ] Create `app/api/deps_version.py`
- [ ] Implement `get_api_version()` dependency
- [ ] Parse `Accept` header for version
- [ ] Default to `API_CURRENT_VERSION` if header missing/malformed
- [ ] Verify file parses
- [ ] Write atomically

### 15.7 Main router modification
- [ ] Modify `app/main.py` to mount versioned routers
- [ ] Register deprecation middleware after auth
- [ ] Exclude `/health` from versioning
- [ ] Verify file parses
- [ ] Write atomically

### 15.8 Config update
- [ ] Modify `app/core/config.py`
- [ ] Add versioning-related settings
- [ ] Export version constants
- [ ] Verify file parses
- [ ] Write atomically

### 15.9 Test generation
- [ ] Create `tests/test_api_versioning.py`
- [ ] Generate all 30 test cases
- [ ] Cover routing, headers, schemas, strategy
- [ ] Verify file parses
- [ ] Write atomically

### 15.10 Documentation updates
- [ ] Append versioning section to `README.md`
- [ ] Add tool entry to `manifest.yaml`
- [ ] Add tool to `SKILL.md` tools table
- [ ] Update `mcp_server.py` with new MCP tool decorator
- [ ] Verify all files parse
- [ ] Write atomically

### 15.11 Atomicity
- [ ] All file writes use temp-file + rename pattern
- [ ] Track touched files for rollback
- [ ] If ANY step fails, rollback ALL previous writes
- [ ] Return `{files_created, files_modified, files_rolled_back, error}` on failure
- [ ] Verify no partial files remain
- [ ] Measure tool execution time

### 15.12 Verification
- [ ] Run `ast.parse` on every modified file
- [ ] Run import audit on the project
- [ ] Run `pytest tests/` to verify no regressions
- [ ] Measure routing overhead
- [ ] Measure header parsing overhead
- [ ] Return success report with metrics

### 15.13 Performance benchmarks
- [ ] Measure routing overhead for v1 and v2 routes
- [ ] Measure header parsing overhead for header strategy
- [ ] Measure OpenAPI generation time for both versions
- [ ] Measure memory overhead per worker
- [ ] Measure tool execution time
- [ ] Verify all benchmarks meet SLOs

## 16. Documentation Output

```json
{
  "status": "success",
  "files_created": [
    "app/core/api_version.py",
    "app/api/middleware/deprecation.py",
    "app/api/v1/__init__.py",
    "app/api/v1/main.py",
    "app/api/v2/__init__.py",
    "app/api/v2/main.py",
    "app/schemas/v1/__init__.py",
    "app/schemas/v2/__init__.py",
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
    "files_changed": 13,
    "lines_added": 847,
    "lines_removed": 32,
    "current_version": "v1",
    "new_version": "v2",
    "strategy": "path",
    "deprecation_period_days": 180
  },
  "next_steps": [
    "Run: pytest tests/test_api_versioning.py -v",
    "Test: curl -X GET http://localhost:8000/api/v1/items",
    "Test: curl -X GET http://localhost:8000/api/v2/items",
    "Verify: curl -X GET http://localhost:8000/api/v1/openapi.json",
    "Verify: curl -X GET http://localhost:8000/api/v2/openapi.json"
  ],
  "warnings": [
    "CORS preflight requests must be handled outside versioning middleware",
    "Reverse proxies may strip version prefixes; configure X-Forwarded-Prefix handling"
  ],
  "notes": [
    "API versioning enabled with strategy=path",
    "Deprecation middleware registered after auth middleware",
    "Sunset date computed as 2026-10-05",
    "Health check route remains unversioned at /health"
  ]
}
