<!--
{
  "tool_num": "017",
  "tool_name": "add_api_versioning",
  "model": "deepseek/deepseek-chat-v3",
  "elapsed_seconds": 336.61609854502603,
  "prompt_tokens": 3821,
  "completion_tokens": 6703,
  "reasoning_tokens": 0,
  "cost_usd": 0.00718839
}
-->

# TOOL-017: add_api_versioning

## 1. Overview

| Field | Value |
|-------|-------|
| Tool name | `fastapi_add_api_versioning` |
| Category | EXTEND > API Design |
| Complexity | High |
| Dependencies | Existing project with at least one resource (model + routes), Alembic optional |
| Signature | `add_api_versioning(project_dir: str, current_version: str = "v1", new_version: str = "v2", strategy: Literal["path", "header"] = "path", deprecation_period_days: int = 180) -> dict` |
| Parameters | 
  - `project_dir`: project root path
  - `current_version`: version label of the existing API surface (default `v1`)
  - `new_version`: label for the new version being introduced (default `v2`)
  - `strategy`: how clients select the version — `path` (`/api/v1/...` vs `/api/v2/...`) or `header` (`Accept: application/vnd.app.v2+json`)
  - `deprecation_period_days`: number of days from migration until v1 routes are removed; sets the `Sunset` header date |

## 2. Purpose
Add API versioning so multiple versions can coexist in the same FastAPI app. Path-based by default (clean URLs, easy CDN caching). Each version has its own router, schemas, and CRUD wrappers. Deprecated versions emit `Deprecation: true`, `Sunset: <date>`, and `Link: ...; rel="successor-version"` headers. Includes a backward-compat shim layer so v1 routes can call v2 CRUD with field translation. Separate OpenAPI per version.

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 6s | Multiple files modified |
| Files modified | ≤ 6 global files | Minimize global impact |
| Files created | ≥ 8 | Versioning module, version_router, deps, deprecation middleware, openapi config, tests, etc. |
| Per-version routing overhead | < 0.1 ms | FastAPI router resolution |
| Header parsing overhead | < 0.5 ms | Header strategy |
| Migration runtime | 0s | No DB migration; pure code |
| OpenAPI generation per version | < 200 ms | Separate OpenAPI per version |
| Memory overhead | < 1 MB per worker | Minimal runtime impact |
| No DB schema changes | 0 | Versioning is code-only |

## 4. Code Examples (Before / After)

### 4.1 Before

```python
# app/api/main.py
from fastapi import APIRouter

router = APIRouter()

@router.get("/items/{item_id}")
def read_item(item_id: int):
    return {"item_id": item_id}
```

### 4.2 After

```python
# app/api/v1/main.py
from fastapi import APIRouter

router = APIRouter(prefix="/v1")

@router.get("/items/{item_id}")
def read_item(item_id: int):
    return {"item_id": item_id}
```

### 4.3 New Modules

```python
# app/api/v2/main.py
from fastapi import APIRouter

router = APIRouter(prefix="/v2")

@router.get("/items/{item_id}")
def read_item(item_id: int):
    return {"item_id": item_id}
```

### 4.4 Migration File

```python
# migrations/versions/20260408_add_api_versioning.py
from alembic import op
import sqlalchemy as sa

def upgrade():
    pass

def downgrade():
    pass
```

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| 1 | Both versions answer requests independently | Test routing with T-01..T-06 |
| 2 | Deprecated routes ALWAYS emit `Deprecation: true` and `Sunset` headers | Test headers with T-07..T-12 |
| 3 | The `Link` header on a deprecated route points to the successor version of the same resource | Test headers with T-07..T-12 |
| 4 | OpenAPI per version contains ONLY that version's routes | Test OpenAPI with T-24..T-27 |
| 5 | Adding a new version NEVER breaks existing v1 clients | Test idempotency with T-28..T-30 |
| 6 | The version mounted at `/api/v1` matches the legacy route layout exactly | Test routing with T-01..T-06 |
| 7 | Header strategy defaults to `current_version` when no Accept header matches | Test header strategy with T-19..T-23 |
| 8 | Schemas are versioned per directory | Inspect `app/schemas/v1/` and `app/schemas/v2/` |
| 9 | CRUD layer is shared but adapted | Inspect `app/crud/` |
| 10 | Deprecation middleware runs AFTER auth | Test middleware order with T-28..T-30 |

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | Both versions answer requests independently | Test routing with T-01..T-06 |
| CC-02 | Deprecated routes ALWAYS emit `Deprecation: true` and `Sunset` headers | Test headers with T-07..T-12 |
| CC-03 | The `Link` header on a deprecated route points to the successor version of the same resource | Test headers with T-07..T-12 |
| CC-04 | OpenAPI per version contains ONLY that version's routes | Test OpenAPI with T-24..T-27 |
| CC-05 | Adding a new version NEVER breaks existing v1 clients | Test idempotency with T-28..T-30 |
| CC-06 | The version mounted at `/api/v1` matches the legacy route layout exactly | Test routing with T-01..T-06 |
| CC-07 | Header strategy defaults to `current_version` when no Accept header matches | Test header strategy with T-19..T-23 |
| CC-08 | Schemas are versioned per directory | Inspect `app/schemas/v1/` and `app/schemas/v2/` |
| CC-09 | CRUD layer is shared but adapted | Inspect `app/crud/` |
| CC-10 | Deprecation middleware runs AFTER auth | Test middleware order with T-28..T-30 |
| CC-11 | Versioned middleware order: deprecation middleware runs AFTER auth | Test middleware order with T-28..T-30 |
| CC-12 | Reverse proxy strips the /api/v1 prefix (rewrites): tool documents X-Forwarded-Prefix | Inspect documentation |
| CC-13 | CORS preflight on a versioned route | Test CORS with T-28..T-30 |
| CC-14 | Client sends `Accept: application/json` (no version vendor type) | Test header strategy with T-19..T-23 |
| CC-15 | Health check route should be UN-versioned (`/health`, not `/api/v1/health`) | Inspect `app/main.py` |
| CC-16 | New version has a different auth scheme than current | Inspect `app/api/v2/main.py` |
| CC-17 | Versioned schemas with circular references | Inspect `app/schemas/v1/` and `app/schemas/v2/` |
| CC-18 | Tool execution time < 6s | Measure execution time |
| CC-19 | Files modified ≤ 6 global files | Inspect `app/main.py`, `app/api/main.py`, `app/core/config.py` |
| CC-20 | Files created ≥ 8 | Inspect `app/core/api_version.py`, `app/api/middleware/deprecation.py`, `app/api/v1/__init__.py`, `app/api/v1/main.py`, `app/api/v2/__init__.py`, `app/api/v2/main.py`, `app/schemas/v1/`, `app/schemas/v2/`, `app/api/deps_version.py`, `tests/test_api_versioning.py` |
| CC-21 | Per-version routing overhead < 0.1 ms | Measure routing overhead |
| CC-22 | Header parsing overhead < 0.5 ms | Measure header parsing overhead |
| CC-23 | Migration runtime: 0s | Measure migration runtime |
| CC-24 | OpenAPI generation per version < 200 ms | Measure OpenAPI generation time |
| CC-25 | Memory overhead: < 1 MB per worker | Measure memory overhead |
| CC-26 | No DB schema changes | Inspect `migrations/versions/20260408_add_api_versioning.py` |
| CC-27 | Sunset date in the past (deprecation_period_days < 0) | Inspect `app/core/api_version.py` |
| CC-28 | Two routes have the same path in v1 but different in v2 | Inspect `app/api/v1/main.py` and `app/api/v2/main.py` |

## 7. Definition of Done (DoD)

- [ ] Both versions answer requests independently
- [ ] Deprecated routes ALWAYS emit `Deprecation: true` and `Sunset` headers
- [ ] The `Link` header on a deprecated route points to the successor version of the same resource
- [ ] OpenAPI per version contains ONLY that version's routes
- [ ] Adding a new version NEVER breaks existing v1 clients
- [ ] The version mounted at `/api/v1` matches the legacy route layout exactly
- [ ] Header strategy defaults to `current_version` when no Accept header matches
- [ ] Schemas are versioned per directory
- [ ] CRUD layer is shared but adapted
- [ ] Deprecation middleware runs AFTER auth
- [ ] Versioned middleware order: deprecation middleware runs AFTER auth
- [ ] Reverse proxy strips the /api/v1 prefix (rewrites): tool documents X-Forwarded-Prefix
- [ ] CORS preflight on a versioned route

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-VER-01 | Both versions answer requests independently | `get()` adds `where(is_deleted == False)` unconditionally | T-03 |
| INV-VER-02 | Deprecated routes ALWAYS emit `Deprecation: true` and `Sunset` headers | `get()` adds `where(is_deleted == False)` unconditionally | T-03 |
| INV-VER-03 | The `Link` header on a deprecated route points to the successor version of the same resource | `get()` adds `where(is_deleted == False)` unconditionally | T-03 |
| INV-VER-04 | OpenAPI per version contains ONLY that version's routes | `get()` adds `where(is_deleted == False)` unconditionally | T-03 |
| INV-VER-05 | Adding a new version NEVER breaks existing v1 clients | `get()` adds `where(is_deleted == False)` unconditionally | T-03 |
| INV-VER-06 | The version mounted at `/api/v1` matches the legacy route layout exactly | `get()` adds `where(is_deleted == False)` unconditionally | T-03 |
| INV-VER-07 | Header strategy defaults to `current_version` when no Accept header matches | `get()` adds `where(is_deleted == False)` unconditionally | T-03 |

## 9. User Stories

### 9.1 Side-by-side versions (US-01 .. US-05)

**US-01: Basic v1+v2 coexistence**
Given an existing API with v1 routes
When I add v2 routes
Then both versions should answer requests independently

**US-02: Clean separation**
Given an existing API with v1 routes
When I add v2 routes
Then v1 and v2 routes should be in separate directories

**US-03: Versioned schemas**
Given an existing API with v1 schemas
When I add v2 schemas
Then v1 and v2 schemas should be in separate directories

**US-04: Versioned routers**
Given an existing API with v1 routes
When I add v2 routes
Then v1 and v2 routes should be in separate routers

**US-05: Versioned OpenAPI**
Given an existing API with v1 routes
When I add v2 routes
Then v1 and v2 routes should have separate OpenAPI docs

### 9.2 Deprecation lifecycle (US-06 .. US-10)

**US-06: Deprecation header**
Given an existing API with v1 routes
When I add v2 routes
Then v1 routes should emit `Deprecation: true` header

**US-07: Sunset date**
Given an existing API with v1 routes
When I add v2 routes
Then v1 routes should emit `Sunset: <date>` header

**US-08: Link header**
Given an existing API with v1 routes
When I add v2 routes
Then v1 routes should emit `Link: ...; rel="successor-version"` header

**US-09: Migration window**
Given an existing API with v1 routes
When I add v2 routes
Then v1 routes should be removed after `deprecation_period_days`

**US-10: Removal**
Given an existing API with v1 routes
When I add v2 routes
Then v1 routes should be removed after `deprecation_period_days`

### 9.3 Schema evolution (US-11 .. US-15)

**US-11: Field rename**
Given an existing API with v1 schemas
When I add v2 schemas
Then v2 schemas can rename v1 fields

**US-12: Field add**
Given an existing API with v1 schemas
When I add v2 schemas
Then v2 schemas can add new fields

**US-13: Field remove**
Given an existing API with v1 schemas
When I add v2 schemas
Then v2 schemas can remove v1 fields

**US-14: Type change**
Given an existing API with v1 schemas
When I add v2 schemas
Then v2 schemas can change v1 field types

**US-15: Schema isolation**
Given an existing API with v1 schemas
When I add v2 schemas
Then v2 schemas don't leak into v1 responses

### 9.4 Strategy: path vs header (US-16 .. US-20)

**US-16: Path strategy**
Given an existing API with v1 routes
When I add v2 routes
Then v1 and v2 routes should be mounted at `/api/v1/...` and `/api/v2/...`

**US-17: Header strategy**
Given an existing API with v1 routes
When I add v2 routes
Then v1 and v2 routes should be mounted at `/api/...` and use `Accept: application/vnd.app.v2+json`

**US-18: Default behavior**
Given an existing API with v1 routes
When I add v2 routes
Then the default strategy should be path-based

**US-19: Content negotiation**
Given an existing API with v1 routes
When I add v2 routes
Then the header strategy should use `Accept: application/vnd.app.v2+json`

**US-20: Fallback**
Given an existing API with v1 routes
When I add v2 routes
Then the header strategy should default to `current_version` when no Accept header matches

### 9.5 OpenAPI & docs (US-21 .. US-25)

**US-21: Per-version docs**
Given an existing API with v1 routes
When I add v2 routes
Then v1 and v2 routes should have separate OpenAPI docs

**US-22: OpenAPI diff**
Given an existing API with v1 routes
When I add v2 routes
Then v1 and v2 routes should have separate OpenAPI docs

**US-23: Client SDK regen**
Given an existing API with v1 routes
When I add v2 routes
Then v1 and v2 routes should have separate OpenAPI docs

**US-24: Root OpenAPI**
Given an existing API with v1 routes
When I add v2 routes
Then the root `/openapi.json` should default to current version

**US-25: Versioned OpenAPI**
Given an existing API with v1 routes
When I add v2 routes
Then v1 and v2 routes should have separate OpenAPI docs

## 10. Test Plan

### 10.1 Routing (T-01..06)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | v1 calls hit v1 handler | Existing API with v1 routes | Call `/api/v1/items/1` | Response from v1 handler |
| T-02 | v2 calls hit v2 handler | Existing API with v1 routes | Call `/api/v2/items/1` | Response from v2 handler |
| T-03 | Cross calls return 404 | Existing API with v1 routes | Call `/api/v1/items/1` with v2 Accept header | 404 |
| T-04 | Cross calls return 404 | Existing API with v1 routes | Call `/api/v2/items/1` with v1 Accept header | 404 |
| T-05 | Default strategy is path | Existing API with v1 routes | Call `/api/v1/items/1` | Response from v1 handler |
| T-06 | Header strategy defaults to current | Existing API with v1 routes | Call `/api/items/1` with no Accept header | Response from v1 handler |

### 10.2 Deprecation headers (T-07..12)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-07 | Deprecation header | Existing API with v1 routes | Call `/api/v1/items/1` | `Deprecation: true` header |
| T-08 | Sunset date | Existing API with v1 routes | Call `/api/v1/items/1` | `Sunset: <date>` header |
| T-09 | Link header | Existing API with v1 routes | Call `/api/v1/items/1` | `Link: ...; rel="successor-version"` header |
| T-10 | Deprecation header only on v1 | Existing API with v1 routes | Call `/api/v2/items/1` | No `Deprecation` header |
| T-11 | Sunset date only on v1 | Existing API with v1 routes | Call `/api/v2/items/1` | No `Sunset` header |
| T-12 | Link header only on v1 | Existing API with v1 routes | Call `/api/v2/items/1` | No `Link` header |

### 10.3 Schema isolation (T-13..18)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-13 | v2 schemas don't leak into v1 responses | Existing API with v1 routes | Call `/api/v1/items/1` | Response matches v1 schema |
| T-14 | Field renames work | Existing API with v1 routes | Call `/api/v2/items/1` | Response matches v2 schema |
| T-15 | Field adds work | Existing API with v1 routes | Call `/api/v2/items/1` | Response matches v2 schema |
| T-16 | Field removes work | Existing API with v1 routes | Call `/api/v2/items/1` | Response matches v2 schema |
| T-17 | Type changes work | Existing API with v1 routes | Call `/api/v2/items/1` | Response matches v2 schema |
| T-18 | Schema isolation | Existing API with v1 routes | Call `/api/v1/items/1` | Response matches v1 schema |

### 10.4 Header strategy (T-19..23)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-19 | Accept header parsing | Existing API with v1 routes | Call `/api/items/1` with `Accept: application/vnd.app.v2+json` | Response from v2 handler |
| T-20 | Fallback to current | Existing API with v1 routes | Call `/api/items/1` with no Accept header | Response from v1 handler |
| T-21 | Malformed header | Existing API with v1 routes | Call `/api/items/1` with `Accept: application/json` | Response from v1 handler |
| T-22 | Default strategy is path | Existing API with v1 routes | Call `/api/v1/items/1` | Response from v1 handler |
| T-23 | Header strategy defaults to current | Existing API with v1 routes | Call `/api/items/1` with no Accept header | Response from v1 handler |

### 10.5 OpenAPI (T-24..27)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-24 | Per-version openapi.json works | Existing API with v1 routes | Call `/api/v1/openapi.json` | OpenAPI doc for v1 |
| T-25 | Per-version openapi.json works | Existing API with v1 routes | Call `/api/v2/openapi.json` | OpenAPI doc for v2 |
| T-26 | Root defaults to current | Existing API with v1 routes | Call `/openapi.json` | OpenAPI doc for v1 |
| T-27 | OpenAPI diff | Existing API with v1 routes | Call `/api/v1/openapi.json` and `/api/v2/openapi.json` | Different OpenAPI docs |

### 10.6 Idempotency, performance (T-28..30)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-28 | Tool re-run | Existing API with v1 routes | Run `add_api_versioning` twice | No changes |
| T-29 | Latency | Existing API with v1 routes | Call `/api/v1/items/1` | Response time < 0.1 ms |
| T-30 | No regression | Existing API with v1 routes | Call `/api/v1/items/1` | Response matches v1 schema |

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|-----------------|-------------|-------|
| `fastapi_add_soft_delete` | Yes | Versioning must run after soft delete | Soft delete modifies routes |
| `fastapi_add_auth` | Yes | Versioning must run after auth | Auth modifies routes |
| `fastapi_add_cors` | Yes | Versioning must run after CORS | CORS modifies routes |
| `fastapi_add_rate_limit` | Yes | Versioning must run after rate limit | Rate limit modifies routes |
| `fastapi_add_logging` | Yes | Versioning must run after logging | Logging modifies routes |
| `fastapi_add_metrics` | Yes | Versioning must run after metrics | Metrics modifies routes |
| `fastapi_add_cache` | Yes | Versioning must run after cache | Cache modifies routes |
| `fastapi_add_validation` | Yes | Versioning must run after validation | Validation modifies routes |

Conflicts: None

## 12. Rollback Procedure

### Code rollback (before deploy)
```bash
git reset --hard HEAD
```

### Database rollback (after deploy)
```bash
alembic downgrade -1
```

### Data preservation rollback
```bash
# No data migration; pure code
```

### Failure mode (partial modification)
```bash
git checkout -- app/api/main.py
git checkout -- app/main.py
git checkout -- app/core/config.py
```

### Emergency
```bash
# Contact Stripe support
```

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-1 | Project has no existing routes | Tool errors: "Project must have at least one route" |
| EC-2 | New version label collides with existing (e.g. v2 already exists) | Tool errors: "Version label already exists" |
| EC-3 | Strategy=header but client sends both Accept and v1 path | Tool defaults to path strategy |
| EC-4 | Sunset date in the past (deprecation_period_days < 0) | Tool errors: "Sunset date must be in the future" |
| EC-5 | Two routes have the same path in v1 but different in v2 | Tool errors: "Route path collision" |
| EC-6 | v2 route uses a schema that doesn't exist in v1 | Tool errors: "Schema not found" |
| EC-7 | Removing a v1 route that v2 doesn't have a successor for → no Link header | Tool emits no Link header |
| EC-8 | OpenAPI generation for empty version (no routes) | Tool generates empty OpenAPI doc |
| EC-9 | Versioned middleware order: deprecation middleware runs AFTER auth | Tool ensures middleware order |
| EC-10 | Reverse proxy strips the /api/v1 prefix (rewrites): tool documents X-Forwarded-Prefix | Tool documents X-Forwarded-Prefix |
| EC-11 | CORS preflight on a versioned route | Tool handles CORS preflight |
| EC-12 | Client sends `Accept: application/json` (no version vendor type) | Tool defaults to current version |
| EC-13 | Health check route should be UN-versioned (`/health`, not `/api/v1/health`) | Tool ensures health check route is un-versioned |
| EC-14 | New version has a different auth scheme than current | Tool ensures auth scheme is versioned |
| EC-15 | Versioned schemas with circular references | Tool handles circular references |

## 14. Acceptance Criteria (Final Sign-off)

✅ Both versions answer requests independently  
✅ Deprecated routes ALWAYS emit `Deprecation: true` and `Sunset` headers  
✅ The `Link` header on a deprecated route points to the successor version of the same resource  
✅ OpenAPI per version contains ONLY that version's routes  
✅ Adding a new version NEVER breaks existing v1 clients  
✅ The version mounted at `/api/v1` matches the legacy route layout exactly  
✅ Header strategy defaults to `current_version` when no Accept header matches  
✅ Schemas are versioned per directory  
✅ CRUD layer is shared but adapted  
✅ Deprecation middleware runs AFTER auth  

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Setup

- [ ] Clone the repository
- [ ] Install dependencies
- [ ] Run existing tests
- [ ] Backup existing routes
- [ ] Backup existing schemas

### 15.2 Versioned Routers

- [ ] Create `app/api/v1/main.py`
- [ ] Create `app/api/v2/main.py`
- [ ] Move existing routes to `app/api/v1/main.py`
- [ ] Copy existing routes to `app/api/v2/main.py`
- [ ] Mount both routers in `app/main.py`

### 15.3 Versioned Schemas

- [ ] Create `app/schemas/v1/`
- [ ] Create `app/schemas/v2/`
- [ ] Move existing schemas to `app/schemas/v1/`
- [ ] Copy existing schemas to `app/schemas/v2/`
- [ ] Update imports in `app/api/v1/main.py`

### 15.4 Deprecation Middleware

- [ ] Create `app/api/middleware/deprecation.py`
- [ ] Implement middleware logic
- [ ] Register middleware in `app/main.py`
- [ ] Test middleware order
- [ ] Test middleware headers

### 15.5 Header Strategy

- [ ] Create `app/api/deps_version.py`
- [ ] Implement header parsing logic
- [ ] Test header parsing
- [ ] Test fallback behavior
- [ ] Test malformed header

### 15.6 OpenAPI

- [ ] Create `app/api/v1/openapi.json`
- [ ] Create `app/api/v2/openapi.json`
- [ ] Test per-version OpenAPI
- [ ] Test root OpenAPI
- [ ] Test OpenAPI diff

### 15.7 Testing

- [ ] Create `tests/test_api_versioning.py`
- [ ] Implement routing tests
- [ ] Implement deprecation header tests
- [ ] Implement schema isolation tests
- [ ] Implement header strategy tests

### 15.8 Documentation

- [ ] Update README.md
- [ ] Document versioning strategy
- [ ] Document deprecation headers
- [ ] Document header strategy
- [ ] Document OpenAPI per version

### 15.9 Final Checks

- [ ] Run all tests
- [ ] Check code coverage
- [ ] Review code quality
- [ ] Review documentation
- [ ] Deploy to staging

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
    "app/schemas/v1/",
    "app/schemas/v2/",
    "app/api/deps_version.py",
    "tests/test_api_versioning.py"
  ],
  "files_modified": [
    "app/main.py",
    "app/api/main.py",
    "app/core/config.py",
    "README.md"
  ],
  "metrics": {
    "execution_time_ms": 5500,
    "files_changed": 4,
    "lines_added": 1200,
    "current_version": "v1",
    "new_version": "v2",
    "strategy": "path",
    "deprecation_period_days": 180
  },
  "next_steps": [
    "Run all tests",
    "Check code coverage",
    "Review code quality",
    "Review documentation",
    "Deploy to staging"
  ],
  "warnings": [
    "CORS preflight handling",
    "Sunset date awareness"
  ],
  "notes": [
    "Versioning installed successfully",
    "Deprecation headers added",
    "OpenAPI per version works"
  ]
}
```