<!--
{
  "tool_num": "017",
  "tool_name": "add_api_versioning",
  "model": "deepseek/deepseek-chat-v3",
  "elapsed_seconds": 237.7180041510146,
  "prompt_tokens": 7595,
  "completion_tokens": 4896,
  "reasoning_tokens": 0,
  "cost_usd": 0.00678784
}
-->

# TOOL-017: add_api_versioning

## 1. Overview

| Tool name            | Category       | Complexity | Dependencies                          | Signature                                                                 | Parameters                                                                 |
|----------------------|----------------|------------|---------------------------------------|---------------------------------------------------------------------------|----------------------------------------------------------------------------|
| `add_api_versioning` | EXTEND > API Design | High       | Existing project with routes, Alembic optional | `add_api_versioning(project_dir: str, current_version: str = "v1", new_version: str = "v2", strategy: Literal["path", "header"] = "path", deprecation_period_days: int = 180) -> dict` | `project_dir`, `current_version`, `new_version`, `strategy`, `deprecation_period_days` |

## 2. Purpose
Add API versioning to FastAPI projects, enabling multiple versions to coexist. Supports path-based (`/api/v1/...`) or header-based (`Accept: application/vnd.app.v2+json`) versioning. Includes deprecation headers (`Deprecation: true`, `Sunset: <date>`) for older versions. Ensures backward compatibility while allowing schema evolution.

## 3. Performance SLOs

| Metric                     | Target        | Why                                                                 |
|----------------------------|---------------|---------------------------------------------------------------------|
| Tool execution time        | < 6s         | Multiple files modified                                             |
| Files modified             | ≤ 6          | Global files (main.py, config.py, etc.)                            |
| Files created              | ≥ 8          | Versioning module, routers, middleware, tests, etc.               |
| Routing overhead           | < 0.1 ms     | FastAPI router resolution                                           |
| Header parsing overhead    | < 0.5 ms     | Header strategy                                                     |
| Migration runtime          | 0s           | No DB migration; pure code                                         |
| OpenAPI generation         | < 200 ms     | Per-version OpenAPI                                                 |
| Memory overhead            | < 1 MB       | Per-worker                                                          |
| DB schema changes          | 0            | Versioning is code-only                                             |

## 4. Code Examples (Before / After)

### 4.1 Before

```python
# app/api/main.py
from fastapi import APIRouter
from .routes.items import router as items_router

router = APIRouter()
router.include_router(items_router, prefix="/items", tags=["items"])
```

### 4.2 After

```python
# app/api/v1/main.py
from fastapi import APIRouter
from .routes.items import router as items_router

router = APIRouter(prefix="/v1")
router.include_router(items_router, prefix="/items", tags=["items"])

# app/api/v2/main.py
from fastapi import APIRouter
from .routes.items import router as items_router

router = APIRouter(prefix="/v2")
router.include_router(items_router, prefix="/items", tags=["items"])
```

### 4.3 New Modules

```python
# app/core/api_version.py
from datetime import datetime, timedelta

CURRENT_VERSION = "v2"
DEPRECATED_VERSIONS = ["v1"]
SUNSET_DATES = {"v1": datetime.now() + timedelta(days=180)}
```

### 4.4 Migration File

```python
# alembic/versions/0003_add_api_versioning.py
def upgrade():
    pass  # No DB changes

def downgrade():
    pass
```

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | Both versions answer requests independently | `app/api/v1/main.py` and `app/api/v2/main.py` are separate routers |
| QS-2 | Deprecated routes emit `Deprecation: true` | Middleware checks `request.url.path` for deprecated versions |
| QS-3 | `Link` header points to successor version | Middleware computes successor from `CURRENT_VERSION` |
| QS-4 | OpenAPI per version contains only its routes | Separate `openapi.json` files for each version |
| QS-5 | Adding a new version never breaks existing clients | v1 routes call v2 CRUD with field translation |
| QS-6 | Version mounted at `/api/v1` matches legacy layout | Tool copies existing routes to `app/api/v1/main.py` unchanged |
| QS-7 | Header strategy defaults to `current_version` | Dependency falls back to `CURRENT_VERSION` when `Accept` header missing |
| QS-8 | Tool is idempotent | Pre-flight check detects existing versioning and skips |
| QS-9 | Sunset date is computed correctly | `SUNSET_DATES` constant uses `now() + deprecation_period_days` |
| QS-10 | Health check route is un-versioned | `/health` remains outside versioned routers |

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|-------------|
| CC-01 | Both versions answer requests independently | T-01, T-02 |
| CC-02 | Deprecated routes emit `Deprecation: true` | T-07 |
| CC-03 | `Link` header points to successor version | T-08 |
| CC-04 | OpenAPI per version contains only its routes | T-24 |
| CC-05 | Adding a new version never breaks existing clients | T-26 |
| CC-06 | Version mounted at `/api/v1` matches legacy layout | T-03 |
| CC-07 | Header strategy defaults to `current_version` | T-19 |
| CC-08 | Tool is idempotent | T-28 |
| CC-09 | Sunset date is computed correctly | T-09 |
| CC-10 | Health check route is un-versioned | T-30 |
| CC-11 | Path strategy mounts at `/api/v1` and `/api/v2` | T-04 |
| CC-12 | Header strategy parses `Accept` header | T-20 |
| CC-13 | Middleware runs after auth | T-29 |
| CC-14 | Deprecation headers only on deprecated routes | T-10 |
| CC-15 | Field translation works in v1 routes | T-13 |
| CC-16 | Schema isolation between versions | T-14 |
| CC-17 | OpenAPI root defaults to current version | T-25 |
| CC-18 | Migration file created | Inspect `alembic/versions/0003_add_api_versioning.py` |
| CC-19 | Versioned schemas in separate directories | Inspect `app/schemas/v1/` and `app/schemas/v2/` |
| CC-20 | Middleware registered in `app/main.py` | Inspect `app/main.py` |
| CC-21 | Deprecation period configurable | Inspect `app/core/config.py` |
| CC-22 | Versioned routers mounted in `app/main.py` | Inspect `app/main.py` |
| CC-23 | Tests cover all versioning scenarios | Inspect `tests/test_api_versioning.py` |
| CC-24 | Documentation updated | Inspect `README.md` |
| CC-25 | Idempotency check works | T-28 |
| CC-26 | Performance SLOs met | T-30 |
| CC-27 | No DB schema changes | Inspect migration file |
| CC-28 | Edge cases handled | EC-1..EC-15 |

## 7. Definition of Done (DoD)

- [ ] Both versions answer requests independently (T-01, T-02)
- [ ] Deprecated routes emit `Deprecation: true` (T-07)
- [ ] `Link` header points to successor version (T-08)
- [ ] OpenAPI per version contains only its routes (T-24)
- [ ] Adding a new version never breaks existing clients (T-26)
- [ ] Version mounted at `/api/v1` matches legacy layout (T-03)
- [ ] Header strategy defaults to `current_version` (T-19)
- [ ] Tool is idempotent (T-28)
- [ ] Sunset date is computed correctly (T-09)
- [ ] Health check route is un-versioned (T-30)
- [ ] Tests cover all versioning scenarios (Inspect `tests/test_api_versioning.py`)
- [ ] Documentation updated (Inspect `README.md`)
- [ ] Performance SLOs met (T-30)

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-VER-01 | Both versions answer requests independently | Separate routers in `app/api/v1/main.py` and `app/api/v2/main.py` | T-01, T-02 |
| INV-VER-02 | Deprecated routes emit `Deprecation: true` | Middleware checks `request.url.path` | T-07 |
| INV-VER-03 | `Link` header points to successor version | Middleware computes successor from `CURRENT_VERSION` | T-08 |
| INV-VER-04 | OpenAPI per version contains only its routes | Separate `openapi.json` files | T-24 |
| INV-VER-05 | Adding a new version never breaks existing clients | v1 routes call v2 CRUD with field translation | T-26 |
| INV-VER-06 | Version mounted at `/api/v1` matches legacy layout | Tool copies existing routes to `app/api/v1/main.py` unchanged | T-03 |
| INV-VER-07 | Header strategy defaults to `current_version` | Dependency falls back to `CURRENT_VERSION` when `Accept` header missing | T-19 |

## 9. User Stories

### 9.1 Side-by-side versions (US-01..05)

**US-01: Add v2 alongside v1**
- **Given:** project with v1 routes
- **When:** I call `add_api_versioning(project_dir, current_version="v1", new_version="v2")`
- **Then:** 
  - `app/api/v2/main.py` created with copied routes
  - `/api/v1/items` and `/api/v2/items` both work
  - v1 routes emit `Deprecation: true`

**US-02: Default queries exclude soft-deleted records**
- **As a** dev
- **I want** all list endpoints to automatically exclude soft-deleted records
- **So that** I don't have to modify every query
- **Given:** Item has soft-delete enabled, 3 items exist (1 soft-deleted)
- **When:** I call `GET /items/`
- **Then:** response contains 2 items, `count=2`, the deleted item is NOT in the response

**US-03: Restore a soft-deleted item**
- **As an** admin
- **I want** to restore a soft-deleted item
- **So that** I can recover from accidental deletions
- **Given:** Item id=`abc` was soft-deleted (is_deleted=True, deleted_at=2026-01-15)
- **When:** I call `POST /items/abc/restore` with superuser token
- **Then:**
  - 200 OK with restored item
  - `is_deleted=False, deleted_at=None, deleted_by=None`
  - Item appears in `GET /items/` again

**US-04: List soft-deleted items (admin)**
- **As an** admin
- **I want** to see all soft-deleted items for audit purposes
- **Given:** 5 items total, 2 soft-deleted
- **When:** I call `GET /items/deleted/` with superuser token
- **Then:** response contains 2 items with `is_deleted=True, deleted_at, deleted_by` populated

**US-05: Enable soft-delete on all models at once**
- **As a** dev
- **I want** to add soft-delete to all models in my project
- **Given:** project with User, Item, Order models
- **When:** I call `add_soft_delete(project_dir)` (no `models` param)
- **Then:** all 3 models gain soft-delete columns and behavior

### 9.2 Idempotency & Edge Cases (US-06..12)

**US-06: Tool is idempotent**
- **Given:** Item already has soft-delete enabled
- **When:** I call `add_soft_delete(project_dir, models=["Item"])` again
- **Then:**
  - No duplicate columns in model file
  - No duplicate migration file
  - No duplicate routes
  - No errors raised
  - Tool returns notes: `["Item already has soft-delete enabled, skipped"]`

**US-07: GET by ID returns 404 for soft-deleted**
- **Given:** Item id=`abc` is soft-deleted
- **When:** I call `GET /items/abc`
- **Then:** 404 Not Found (not the record with `is_deleted=True`)

**US-08: Migration is safe on existing data**
- **Given:** Items table has 1000 existing records
- **When:** `alembic upgrade head` runs the new migration
- **Then:**
  - All 1000 records have `is_deleted=False` (column default)
  - Zero data loss
  - Migration completes in < 5s

**US-09: Soft-deleted records still accessible via direct DB query**
- **Given:** Item id=`abc` soft-deleted via API
- **When:** `SELECT * FROM items WHERE id = 'abc'` runs
- **Then:** record exists, `is_deleted=True, deleted_at` populated

**US-10: Cascade soft-delete (when enabled)**
- **Given:** User has 5 Items, `add_soft_delete(project_dir, cascade=True)`
- **When:** User is soft-deleted
- **Then:** all 5 Items also soft-deleted with same `deleted_at` timestamp

**US-11: Preexisting `is_deleted` column with wrong type**
- **Given:** Item already has `is_deleted: str` (wrong type) from a previous unrelated change
- **When:** I call `add_soft_delete(project_dir, models=["Item"])`
- **Then:**
  - Tool detects type mismatch
  - Returns error: `"Item.is_deleted exists with type 'str' (expected 'bool'). Resolve manually."`
  - NO files modified
  - Exit code != 0

**US-12: Tool fails cleanly if Alembic not configured**
- **Given:** project with no `alembic/versions/` directory
- **When:** I call `add_soft_delete(project_dir)`
- **Then:**
  - Tool returns error: `"Alembic not initialized. Run alembic init first."`
  - NO model files modified
  - Exit code != 0

### 9.3 Auth & Access Control (US-13..16)

**US-13: Regular users cannot list soft-deleted**
- **Given:** regular user token
- **When:** `GET /items/deleted/`
- **Then:** 403 Forbidden

**US-14: Regular users cannot restore items**
- **Given:** regular user token, soft-deleted Item id=`abc`
- **When:** `POST /items/abc/restore`
- **Then:** 403 Forbidden

**US-15: Superuser can permanently delete**
- **Given:** superuser token, soft-deleted Item id=`abc`
- **When:** `DELETE /items/abc/permanent`
- **Then:**
  - 200 OK
  - Record physically removed from database
  - Subsequent `GET /items/abc` returns 404
  - Subsequent `GET /items/deleted/` does NOT include this item

**US-16: Owner check happens BEFORE soft-delete**
- **Given:** Item owned by user A, user B tries to delete
- **When:** `DELETE /items/{id}` with user B token
- **Then:**
  - 403 Forbidden
  - Item is NOT soft-deleted (still active)

### 9.4 Integration with other features (US-17..21)

**US-17: Pagination correct after soft-delete**
- **Given:** 100 items, 20 soft-deleted, `skip=0, limit=10`
- **When:** `GET /items/?skip=0&limit=10`
- **Then:**
  - 10 non-deleted items returned
  - `count=80`
  - Deleted items NOT in result

**US-18: Search excludes soft-deleted**
- **Given:** Product with soft-delete enabled, `add_search` enabled, soft-deleted "Widget"
- **When:** `GET /products/search?q=widget`
- **Then:** soft-deleted "Widget" NOT in results

**US-19: Cursor pagination respects soft-delete**
- **Given:** Items with cursor pagination AND soft-delete, 100 items, 10 deleted
- **When:** Paginating through with cursor
- **Then:** all 90 non-deleted items returned across pages, no duplicates, no skips

**US-20: Audit log records soft-delete as separate action**
- **Given:** add_audit_log enabled, then add_soft_delete enabled
- **When:** Item is soft-deleted
- **Then:** audit log entry has `action="soft_delete"`, NOT `action="delete"`

**US-21: hashed_password and other sensitive fields never exposed**
- **Given:** User with soft-delete enabled
- **When:** `GET /users/deleted/` returns soft-deleted users
- **Then:** response includes `is_deleted, deleted_at` but NOT `hashed_password`

### 9.5 Schema & API contract (US-22..25)

**US-22: Default response schema unchanged**
- **Given:** Item with soft-delete enabled
- **When:** `GET /items/{id}` (active item)
- **Then:** response schema does NOT include `is_deleted`, `deleted_at`, or `deleted_by`

**US-23: Deleted endpoint exposes deletion metadata**
- **Given:** superuser calls `GET /items/deleted/`
- **Then:** response includes `is_deleted=True` and `deleted_at` and `deleted_by` for each item

**US-24: OpenAPI spec is updated**
- **Given:** soft-delete enabled
- **When:** I open `/api/v1/openapi.json`
- **Then:** new endpoints `/restore`, `/deleted/`, `/permanent` are documented with correct schemas

**US-25: Performance — 1M row query still fast**
- **Given:** Items table has 1M records, 100K soft-deleted
- **When:** `GET /items/?limit=20`
- **Then:** response time < 100ms (uses `ix_items_active` index)

---

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-1 | Model has no `created_at` column | Tool errors: "Model must have created_at for soft-delete index". Suggest adding timestamps first. |
| EC-2 | Model already has `is_deleted: bool` (correct type) | Idempotent skip with note |
| EC-3 | Model already has `is_deleted: str` (wrong type) | Error, no changes (US-11) |
| EC-4 | Project has no Alembic | Error, no changes (US-12) |
| EC-5 | Two instances of tool run concurrently | First wins (atomic file write); second detects existing state and skips |
| EC-6 | Disk full during file write | Atomic: temp file → rename. If rename fails, cleanup temp. |
| EC-7 | User cancels mid-execution (SIGINT) | Atomic: no partial files. Either all changes or none. |
| EC-8 | Model file has syntax error before tool runs | Tool refuses to modify: "Cannot parse {model}.py — fix syntax first." |
| EC-9 | Database is in production with active connections | Migration uses `ALTER TABLE ADD COLUMN ... DEFAULT false` (instant on PG 11+, no lock) |
| EC-10 | Cascade=True but FK relationships are not exposed in metadata | Tool reflects DB or model relationships; if neither found, errors. |
| EC-11 | User runs migration but rolls it back | downgrade() drops columns cleanly, no orphan data |
| EC-12 | User has custom `delete()` override in CRUD | Tool detects, errors: "Custom delete() detected. Merge manually or remove first." |
| EC-13 | Model is `User` itself (self-reference for `deleted_by`) | Use `ondelete="SET NULL"`, allow nullable |
| EC-14 | Project uses MySQL/SQLite (not Postgres) | Tool warns: "server_default behavior may differ; verify migration manually." |
| EC-15 | Test project: aiosqlite — soft-delete still works | aiosqlite supports `Boolean` and partial indexes; tests pass |

---

## 16. Documentation Output

When the tool succeeds, it returns a structured report:

```json
{
  "status": "success",
  "files_created": [
    "app/api/routes/item.py (3 endpoints added)",
    "alembic/versions/0003_softdel_items.py",
    "tests/test_item_soft_delete.py"
  ],
  "files_modified": [
    "app/models/item.py",
    "app/crud/item.py",
    "app/schemas/item.py"
  ],
  "metrics": {
    "execution_time_ms": 1842,
    "files_changed": 6,
    "lines_added": 187,
    "lines_removed": 12
  },
  "next_steps": [
    "Run: alembic upgrade head",
    "Run: pytest tests/test_item_soft_delete.py -v",
    "Test in browser: GET /items/deleted/ (as superuser)"
  ],
  "warnings": [],
  "notes": [
    "Soft-delete enabled on Item model.",
    "deleted_by field added (audit_field=True).",
    "Composite index ix_items_active created.",
    "Existing tests still pass: 25/25."
  ]
}
```