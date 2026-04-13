<!--
{
  "tool_num": "017",
  "tool_name": "add_api_versioning",
  "model": "deepseek/deepseek-chat-v3",
  "elapsed_seconds": 300.342070779996,
  "prompt_tokens": 3547,
  "completion_tokens": 6519,
  "reasoning_tokens": 0,
  "cost_usd": 0.00693695
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
| `project_dir` | Project root path |
| `current_version` | Version label of the existing API surface (default `v1`) |
| `new_version` | Label for the new version being introduced (default `v2`) |
| `strategy` | How clients select the version — `path` (`/api/v1/...` vs `/api/v2/...`) or `header` (`Accept: application/vnd.app.v2+json`) |
| `deprecation_period_days` | Number of days from migration until v1 routes are removed; sets the `Sunset` header date |

## 2. Purpose

Add API versioning so multiple versions can coexist in the same FastAPI app. Path-based by default (clean URLs, easy CDN caching). Each version has its own router, schemas, and CRUD wrappers. Deprecated versions emit `Deprecation: true`, `Sunset: <date>`, and `Link: ...; rel="successor-version"` headers. Includes a backward-compat shim layer so v1 routes can call v2 CRUD with field translation. Separate OpenAPI per version.

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 6s | Multiple files modified |
| Files modified | ≤ 6 global files | Minimize impact on existing code |
| Files created | ≥ 8 | Versioning module, version_router, deps, deprecation middleware, openapi config, tests, etc. |
| Per-version routing overhead | < 0.1 ms | FastAPI router resolution |
| Header parsing overhead | < 0.5 ms | Header strategy |
| Migration runtime | 0s | No DB migration; pure code |
| OpenAPI generation per version | < 200 ms | Separate OpenAPI per version |
| Memory overhead | < 1 MB per worker | Minimal impact on runtime |
| No DB schema changes | True | Versioning is code-only |

## 4. Code Examples (Before / After)

### 4.1 The relevant model BEFORE

```python
# app/api/main.py
from fastapi import APIRouter

router = APIRouter()

@router.get("/items/{item_id}")
def read_item(item_id: int):
    return {"item_id": item_id}
```

### 4.2 The relevant model AFTER

```python
# app/api/v1/main.py
from fastapi import APIRouter

router = APIRouter(prefix="/v1")

@router.get("/items/{item_id}")
def read_item(item_id: int):
    return {"item_id": item_id}
```

### 4.3 New modules created

```python
# app/api/v2/main.py
from fastapi import APIRouter

router = APIRouter(prefix="/v2")

@router.get("/items/{item_id}")
def read_item(item_id: int):
    return {"item_id": item_id}
```

```python
# app/core/api_version.py
from datetime import datetime, timedelta

CURRENT_VERSION = "v2"
DEPRECATED_VERSIONS = ["v1"]
SUNSET_DATES = {"v1": datetime.now() + timedelta(days=180)}
```

### 4.4 Migration file (Alembic)

```python
# migrations/versions/20260408_add_api_versioning.py
def upgrade():
    pass

def downgrade():
    pass
```

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| 1 | Both versions answer requests independently | Test routing with T-01..06 |
| 2 | Deprecated routes ALWAYS emit `Deprecation: true` and `Sunset` headers | Test headers with T-07..12 |
| 3 | The `Link` header on a deprecated route points to the successor version of the same resource | Test headers with T-07..12 |
| 4 | OpenAPI per version contains ONLY that version's routes | Test OpenAPI with T-24..27 |
| 5 | Adding a new version NEVER breaks existing v1 clients | Test idempotency with T-28..30 |
| 6 | The version mounted at `/api/v1` matches the legacy route layout exactly | Test routing with T-01..06 |
| 7 | Header strategy defaults to `current_version` when no Accept header matches | Test header strategy with T-19..23 |
| 8 | Versioned middleware order: deprecation middleware runs AFTER auth | Test middleware order with T-28..30 |

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | Both versions answer requests independently | T-01..06 |
| CC-02 | Deprecated routes emit `Deprecation: true` and `Sunset` headers | T-07..12 |
| CC-03 | The `Link` header points to the successor version | T-07..12 |
| CC-04 | OpenAPI per version contains ONLY that version's routes | T-24..27 |
| CC-05 | Adding a new version NEVER breaks existing v1 clients | T-28..30 |
| CC-06 | The version mounted at `/api/v1` matches the legacy route layout exactly | T-01..06 |
| CC-07 | Header strategy defaults to `current_version` when no Accept header matches | T-19..23 |
| CC-08 | Versioned middleware order: deprecation middleware runs AFTER auth | T-28..30 |
| CC-09 | Tool execution time < 6s | Measure execution time |
| CC-10 | Files modified ≤ 6 global files | Count files modified |
| CC-11 | Files created ≥ 8 | Count files created |
| CC-12 | Per-version routing overhead < 0.1 ms | Measure routing overhead |
| CC-13 | Header parsing overhead < 0.5 ms | Measure header parsing overhead |
| CC-14 | Migration runtime: 0s | Measure migration runtime |
| CC-15 | OpenAPI generation per version < 200 ms | Measure OpenAPI generation time |
| CC-16 | Memory overhead: < 1 MB per worker | Measure memory overhead |
| CC-17 | No DB schema changes | Inspect DB schema |
| CC-18 | Health check route should be UN-versioned | T-28..30 |
| CC-19 | CORS preflight on a versioned route | T-28..30 |
| CC-20 | Client sends `Accept: application/json` (no version vendor type) | T-19..23 |
| CC-21 | Sunset date in the past (deprecation_period_days < 0) | T-07..12 |
| CC-22 | Two routes have the same path in v1 but different in v2 | T-01..06 |
| CC-23 | v2 route uses a schema that doesn't exist in v1 | T-13..18 |
| CC-24 | Removing a v1 route that v2 doesn't have a successor for → no Link header | T-07..12 |
| CC-25 | OpenAPI generation for empty version (no routes) | T-24..27 |
| CC-26 | Reverse proxy strips the /api/v1 prefix (rewrites): tool documents X-Forwarded-Prefix | T-28..30 |
| CC-27 | New version has a different auth scheme than current | T-28..30 |
| CC-28 | Versioned schemas with circular references | T-13..18 |
| CC-29 | Project has no existing routes | T-28..30 |
| CC-30 | New version label collides with existing (e.g. v2 already exists) | T-28..30 |

## 7. Definition of Done (DoD)

- [ ] Both versions answer requests independently
- [ ] Deprecated routes emit `Deprecation: true` and `Sunset` headers
- [ ] The `Link` header points to the successor version
- [ ] OpenAPI per version contains ONLY that version's routes
- [ ] Adding a new version NEVER breaks existing v1 clients
- [ ] The version mounted at `/api/v1` matches the legacy route layout exactly
- [ ] Header strategy defaults to `current_version` when no Accept header matches
- [ ] Versioned middleware order: deprecation middleware runs AFTER auth
- [ ] Tool execution time < 6s
- [ ] Files modified ≤ 6 global files
- [ ] Files created ≥ 8
- [ ] Per-version routing overhead < 0.1 ms
- [ ] Header parsing overhead < 0.5 ms
- [ ] Migration runtime: 0s
- [ ] OpenAPI generation per version < 200 ms
- [ ] Memory overhead: < 1 MB per worker
- [ ] No DB schema changes

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-VER-01 | Both versions answer requests independently | Test routing | T-01..06 |
| INV-VER-02 | Deprecated routes ALWAYS emit `Deprecation: true` and `Sunset` headers | Test headers | T-07..12 |
| INV-VER-03 | The `Link` header on a deprecated route points to the successor version of the same resource | Test headers | T-07..12 |
| INV-VER-04 | OpenAPI per version contains ONLY that version's routes | Test OpenAPI | T-24..27 |
| INV-VER-05 | Adding a new version NEVER breaks existing v1 clients | Test idempotency | T-28..30 |
| INV-VER-06 | The version mounted at `/api/v1` matches the legacy route layout exactly | Test routing | T-01..06 |
| INV-VER-07 | Header strategy defaults to `current_version` when no Accept header matches | Test header strategy | T-19..23 |

## 9. User Stories

### 9.1 Side-by-side versions (US-01 .. US-05)

**US-01: Access v1 API**  
As a client, I want to access the v1 API, so that my existing integrations continue to work.  
Given a v1 API endpoint, when I make a request, then I receive a v1 response.

**US-02: Access v2 API**  
As a client, I want to access the v2 API, so that I can use new features.  
Given a v2 API endpoint, when I make a request, then I receive a v2 response.

**US-03: Independent versions**  
As a developer, I want v1 and v2 to be independent, so that changes in v2 don't affect v1.  
Given a change in v2, when I make a v1 request, then the v1 response remains unchanged.

**US-04: Versioned schemas**  
As a developer, I want schemas to be versioned, so that v1 and v2 can evolve independently.  
Given a schema change in v2, when I make a v1 request, then the v1 schema remains unchanged.

**US-05: Versioned routers**  
As a developer, I want routers to be versioned, so that v1 and v2 routes are separate.  
Given a v1 and v2 router, when I mount them, then they handle requests independently.

### 9.2 Deprecation lifecycle (US-06 .. US-10)

**US-06: Deprecation headers**  
As a client, I want to know when a version is deprecated, so that I can plan my migration.  
Given a deprecated version, when I make a request, then I receive `Deprecation: true` and `Sunset` headers.

**US-07: Sunset date**  
As a client, I want to know the sunset date, so that I can migrate before the deadline.  
Given a deprecated version, when I make a request, then I receive a `Sunset` header with the date.

**US-08: Successor version link**  
As a client, I want to know the successor version, so that I can migrate to it.  
Given a deprecated version, when I make a request, then I receive a `Link` header pointing to the successor version.

**US-09: Deprecation period**  
As a developer, I want to set a deprecation period, so that clients have time to migrate.  
Given a deprecation period, when I add a new version, then the sunset date is set accordingly.

**US-10: Remove deprecated version**  
As a developer, I want to remove a deprecated version, so that I can clean up old code.  
Given a sunset date in the past, when I remove the deprecated version, then it is no longer accessible.

### 9.3 Schema evolution (US-11 .. US-15)

**US-11: Field rename**  
As a developer, I want to rename a field, so that I can improve the API design.  
Given a field rename in v2, when I make a v2 request, then the response contains the renamed field.

**US-12: Field add**  
As a developer, I want to add a field, so that I can expose new data.  
Given a new field in v2, when I make a v2 request, then the response contains the new field.

**US-13: Field remove**  
As a developer, I want to remove a field, so that I can simplify the API.  
Given a field removal in v2, when I make a v2 request, then the response does not contain the removed field.

**US-14: Type change**  
As a developer, I want to change a field type, so that I can improve data representation.  
Given a type change in v2, when I make a v2 request, then the response contains the new type.

**US-15: Schema isolation**  
As a developer, I want schemas to be isolated, so that v1 and v2 can evolve independently.  
Given a schema change in v2, when I make a v1 request, then the v1 schema remains unchanged.

### 9.4 Strategy: path vs header (US-16 .. US-20)

**US-16: Path strategy**  
As a client, I want to use the path strategy, so that I can easily cache responses.  
Given a path strategy, when I make a request to `/api/v1/...`, then I receive a v1 response.

**US-17: Header strategy**  
As a client, I want to use the header strategy, so that I can negotiate content.  
Given a header strategy, when I send `Accept: application/vnd.app.v2+json`, then I receive a v2 response.

**US-18: Default version**  
As a client, I want to default to the current version, so that I don't need to specify a version.  
Given no version specified, when I make a request, then I receive the current version response.

**US-19: Malformed header**  
As a client, I want to handle malformed headers, so that I can recover gracefully.  
Given a malformed header, when I make a request, then I receive the current version response.

**US-20: Strategy switch**  
As a developer, I want to switch strategies, so that I can choose the best approach for my use case.  
Given a strategy switch, when I change from path to header, then the API continues to function correctly.

### 9.5 OpenAPI & docs (US-21 .. US-25)

**US-21: Per-version OpenAPI**  
As a developer, I want per-version OpenAPI, so that clients can discover the API.  
Given a versioned API, when I access `/api/v1/openapi.json`, then I receive the v1 OpenAPI spec.

**US-22: Root OpenAPI**  
As a developer, I want root OpenAPI to default to the current version, so that clients can discover the latest API.  
Given a versioned API, when I access `/openapi.json`, then I receive the current version OpenAPI spec.

**US-23: OpenAPI diff**  
As a developer, I want to see the OpenAPI diff, so that I can understand changes between versions.  
Given two versions, when I compare their OpenAPI specs, then I see the differences.

**US-24: Client SDK regen**  
As a developer, I want to regenerate client SDKs, so that clients can use the latest API.  
Given a new version, when I regenerate the SDK, then it includes the new version's endpoints.

**US-25: Docs per version**  
As a developer, I want docs per version, so that clients can understand each version.  
Given a versioned API, when I access `/api/v1/docs`, then I see the v1 docs.

## 10. Test Plan

### 10.1 Routing (T-01..06)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | v1 call hits v1 handler | Mount v1 router | GET /api/v1/items/1 | v1 response |
| T-02 | v2 call hits v2 handler | Mount v2 router | GET /api/v2/items/1 | v2 response |
| T-03 | Cross calls return 404 | Mount both routers | GET /api/v1/items/1 on v2 router | 404 |
| T-04 | Default version call | Mount both routers | GET /api/items/1 | Current version response |
| T-05 | Health check un-versioned | Mount both routers | GET /health | 200 OK |
| T-06 | Reverse proxy prefix | Mount both routers with X-Forwarded-Prefix | GET /items/1 | Correct version response |

### 10.2 Deprecation headers (T-07..12)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-07 | Deprecation header | Mount v1 router | GET /api/v1/items/1 | Deprecation: true |
| T-08 | Sunset header | Mount v1 router | GET /api/v1/items/1 | Sunset: <date> |
| T-09 | Link header | Mount v1 router | GET /api/v1/items/1 | Link: <successor-version> |
| T-10 | No deprecation on v2 | Mount v2 router | GET /api/v2/items/1 | No Deprecation header |
| T-11 | Sunset date in past | Set deprecation_period_days < 0 | GET /api/v1/items/1 | Sunset: <past-date> |
| T-12 | No successor link | Remove v1 route with no v2 successor | GET /api/v1/items/1 | No Link header |

### 10.3 Schema isolation (T-13..18)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-13 | v2 schema rename | Rename field in v2 schema | GET /api/v2/items/1 | Renamed field |
| T-14 | v2 schema add | Add field in v2 schema | GET /api/v2/items/1 | New field |
| T-15 | v2 schema remove | Remove field in v2 schema | GET /api/v2/items/1 | No removed field |
| T-16 | v2 schema type change | Change field type in v2 schema | GET /api/v2/items/1 | New type |
| T-17 | v1 schema unchanged | Change field in v2 schema | GET /api/v1/items/1 | Original field |
| T-18 | Circular references | Add circular reference in v2 schema | GET /api/v2/items/1 | Correct response |

### 10.4 Header strategy (T-19..23)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-19 | Accept header parsing | Set strategy=header | GET /api/items/1 with Accept: application/vnd.app.v2+json | v2 response |
| T-20 | Fallback to current | Set strategy=header | GET /api/items/1 with no Accept header | Current version response |
| T-21 | Malformed header | Set strategy=header | GET /api/items/1 with Accept: application/json | Current version response |
| T-22 | Both Accept and path | Set strategy=header | GET /api/v1/items/1 with Accept: application/vnd.app.v2+json | v1 response |
| T-23 | Content negotiation | Set strategy=header | GET /api/items/1 with Accept: application/vnd.app.v2+json | v2 response |

### 10.5 OpenAPI (T-24..27)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-24 | Per-version OpenAPI | Mount both routers | GET /api/v1/openapi.json | v1 OpenAPI spec |
| T-25 | Root OpenAPI | Mount both routers | GET /openapi.json | Current version OpenAPI spec |
| T-26 | OpenAPI diff | Compare v1 and v2 OpenAPI specs | GET /api/v1/openapi.json and /api/v2/openapi.json | Differences |
| T-27 | Empty version OpenAPI | Mount empty v2 router | GET /api/v2/openapi.json | Empty OpenAPI spec |

### 10.6 Idempotency, performance (T-28..30)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-28 | Tool re-run | Run tool twice | add_api_versioning() | No changes |
| T-29 | Latency | Measure routing overhead | GET /api/v1/items/1 | < 0.1 ms |
| T-30 | No regression | Run existing tests | Run all tests | All pass |

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|----------------|-------------|-------|
| `add_soft_delete` | Yes | Versioning should be added after soft delete | Soft delete affects schema |
| `add_auth` | Yes | Versioning should be added after auth | Auth middleware runs before deprecation |
| `add_cors` | Yes | Versioning should be added after CORS | CORS middleware runs before deprecation |
| `add_rate_limiting` | Yes | Versioning should be added after rate limiting | Rate limiting middleware runs before deprecation |
| Conflicts: None |

## 12. Rollback Procedure

### Code rollback (before deploy)
```bash
git reset --hard HEAD
git clean -fd
```

### Database rollback (after deploy)
```bash
# No DB changes
```

### Data preservation rollback
```bash
# No data changes
```

### Failure mode (partial modification)
```bash
git checkout -- app/api/v1/main.py
git checkout -- app/api/v2/main.py
git checkout -- app/core/api_version.py
```

### Emergency
```bash
# Revert to previous commit
git revert HEAD
```

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|--------------------|
| EC-1 | Project has no existing routes | Tool errors: "No routes found" |
| EC-2 | New version label collides with existing (e.g. v2 already exists) | Tool errors: "Version already exists" |
| EC-3 | Strategy=header but client sends both Accept and v1 path | Use path strategy |
| EC-4 | Sunset date in the past (deprecation_period_days < 0) | Tool errors: "Deprecation period must be positive" |
| EC-5 | Two routes have the same path in v1 but different in v2 | Tool errors: "Route conflict" |
| EC-6 | v2 route uses a schema that doesn't exist in v1 | Tool errors: "Schema not found" |
| EC-7 | Removing a v1 route that v2 doesn't have a successor for → no Link header | No Link header |
| EC-8 | OpenAPI generation for empty version (no routes) | Empty OpenAPI spec |
| EC-9 | Versioned middleware order: deprecation middleware runs AFTER auth | Deprecation middleware runs after auth |
| EC-10 | Reverse proxy strips the /api/v1 prefix (rewrites): tool documents X-Forwarded-Prefix | Use X-Forwarded-Prefix |
| EC-11 | CORS preflight on a versioned route | CORS preflight works |
| EC-12 | Client sends `Accept: application/json` (no version vendor type) | Default to current version |
| EC-13 | Health check route should be UN-versioned (`/health`, not `/api/v1/health`) | Health check route un-versioned |
| EC-14 | New version has a different auth scheme than current | Auth scheme independent |
| EC-15 | Versioned schemas with circular references | Circular references handled |

## 14. Acceptance Criteria (Final Sign-off)

✅ Both versions answer requests independently  
✅ Deprecated routes emit `Deprecation: true` and `Sunset` headers  
✅ The `Link` header points to the successor version  
✅ OpenAPI per version contains ONLY that version's routes  
✅ Adding a new version NEVER breaks existing v1 clients  
✅ The version mounted at `/api/v1` matches the legacy route layout exactly  
✅ Header strategy defaults to `current_version` when no Accept header matches  
✅ Versioned middleware order: deprecation middleware runs AFTER auth  
✅ Tool execution time < 6s  
✅ Files modified ≤ 6 global files  

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Setup

- [ ] Create `app/core/api_version.py`
- [ ] Create `app/api/middleware/deprecation.py`
- [ ] Create `app/api/v1/__init__.py`
- [ ] Create `app/api/v1/main.py`
- [ ] Create `app/api/v2/__init__.py`
- [ ] Create `app/api/v2/main.py`
- [ ] Create `app/schemas/v1/`
- [ ] Create `app/schemas/v2/`
- [ ] Create `app/api/deps_version.py`
- [ ] Create `tests/test_api_versioning.py`

### 15.2 Modify existing files

- [ ] Modify `app/main.py` to mount both versioned routers
- [ ] Modify `app/api/main.py` to delegate to v1 + v2 sub-routers
- [ ] Modify `app/core/config.py` to add `API_CURRENT_VERSION`, `API_DEPRECATED_VERSIONS`, `API_SUNSET_DATES`

### 15.3 Testing

- [ ] Write routing tests (T-01..06)
- [ ] Write deprecation header tests (T-07..12)
- [ ] Write schema isolation tests (T-13..18)
- [ ] Write header strategy tests (T-19..23)
- [ ] Write OpenAPI tests (T-24..27)
- [ ] Write idempotency, performance tests (T-28..30)

### 15.4 Documentation

- [ ] Update README.md API section
- [ ] Add API versioning notes to docs
- [ ] Add deprecation warning notes to docs
- [ ] Add strategy switch notes to docs
- [ ] Add OpenAPI per version notes to docs

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
    "execution_time_ms": 4500,
    "files_changed": 4,
    "lines_added": 120,
    "current_version": "v1",
    "new_version": "v2",
    "strategy": "path",
    "deprecation_period_days": 180
  },
  "next_steps": [
    "Run tests: pytest tests/test_api_versioning.py",
    "Verify routing: curl http://localhost:8000/api/v1/items/1",
    "Check deprecation headers: curl -I http://localhost:8000/api/v1/items/1",
    "Verify OpenAPI: curl http://localhost:8000/api/v1/openapi.json",
    "Update client SDKs"
  ],
  "warnings": [
    "CORS preflight handling needs to be tested",
    "Sunset date awareness needs to be communicated to clients"
  ],
  "notes": [
    "Versioning added successfully",
    "Deprecation middleware installed",
    "OpenAPI per version configured"
  ]
}