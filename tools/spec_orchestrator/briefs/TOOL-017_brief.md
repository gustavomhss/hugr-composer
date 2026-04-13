## Tool: `add_api_versioning`

### Overview parameters
- Tool name: `fastapi_add_api_versioning`
- Category: EXTEND > API Design
- Complexity: High
- Dependencies: existing project with at least one resource (model + routes), Alembic optional
- Signature: `add_api_versioning(project_dir: str, current_version: str = "v1", new_version: str = "v2", strategy: Literal["path", "header"] = "path", deprecation_period_days: int = 180) -> dict`
- Parameters:
  - `project_dir`: project root path
  - `current_version`: version label of the existing API surface (default `v1`)
  - `new_version`: label for the new version being introduced (default `v2`)
  - `strategy`: how clients select the version — `path` (`/api/v1/...` vs `/api/v2/...`) or `header` (`Accept: application/vnd.app.v2+json`)
  - `deprecation_period_days`: number of days from migration until v1 routes are removed; sets the `Sunset` header date

### Purpose
Add API versioning so multiple versions can coexist in the same FastAPI app. Path-based by default (clean URLs, easy CDN caching). Each version has its own router, schemas, and CRUD wrappers. Deprecated versions emit `Deprecation: true`, `Sunset: <date>`, and `Link: ...; rel="successor-version"` headers. Includes a backward-compat shim layer so v1 routes can call v2 CRUD with field translation. Separate OpenAPI per version.

### Performance SLOs (target / why columns)
- Tool execution time < 6s (multiple files modified)
- Files modified ≤ 6 global files
- Files created ≥ 8 (versioning module, version_router, deps, deprecation middleware, openapi config, tests, etc.)
- Per-version routing overhead < 0.1 ms (FastAPI router resolution)
- Header parsing overhead < 0.5 ms (header strategy)
- Migration runtime: 0s (no DB migration; pure code)
- OpenAPI generation per version < 200 ms
- Memory overhead: < 1 MB per worker
- No DB schema changes

### Key technical decisions

1. **Path strategy is default**: routes mounted at `/api/v1/...` and `/api/v2/...`. Each version gets its own `APIRouter` instance with its own prefix.
2. **Header strategy alternative**: single mount at `/api/...`, custom dependency parses `Accept: application/vnd.app.v2+json`. If header missing → defaults to current version.
3. **Schemas are versioned per directory**: `app/schemas/v1/`, `app/schemas/v2/`. Schemas are NOT shared across versions.
4. **CRUD layer is shared but adapted**: `app/crud/` stays version-agnostic; v1 routes use a `to_v1_schema()` translator on output.
5. **Field renames**: `add_api_versioning` provides a `rename_map` parameter (out of scope of THIS spec — handled in EVOLVE/refactor_model). v2 schemas can rename v1 fields.
6. **Deprecation middleware**: a Starlette middleware that detects routes under the deprecated version path and adds headers.
7. **Sunset date computation**: `now() + deprecation_period_days`. Stored in a constant in `app/core/api_version.py`.
8. **OpenAPI**: each version exposes its own at `/api/v1/openapi.json` and `/api/v2/openapi.json`. Root `/openapi.json` defaults to current.
9. **Auto-generation of v2 from v1**: tool scans existing routes, copies them to a new `app/api/v2_routes/` directory unchanged (the dev manually edits to evolve them).
10. **No automatic data migration**: data stays the same; only the API surface changes.

### Key invariants (you must invent test IDs INV-VER-01..07 and reference T-XX)
1. Both versions answer requests independently (a v1 call NEVER routes to v2 handler and vice versa).
2. Deprecated routes ALWAYS emit `Deprecation: true` and `Sunset` headers.
3. The `Link` header on a deprecated route points to the successor version of the same resource.
4. OpenAPI per version contains ONLY that version's routes (no cross-pollution).
5. Adding a new version NEVER breaks existing v1 clients (zero regression).
6. The version mounted at `/api/v1` matches the legacy route layout exactly.
7. Header strategy defaults to `current_version` when no Accept header matches.

### User story themes (5 sub-sections)
- 9.1 Side-by-side versions (US-01..05): basic v1+v2 coexistence, clean separation
- 9.2 Deprecation lifecycle (US-06..10): deprecation header, sunset date, migration window, removal
- 9.3 Schema evolution (US-11..15): field rename, field add, field remove, type change
- 9.4 Strategy: path vs header (US-16..20): default behavior, content negotiation, fallback
- 9.5 OpenAPI & docs (US-21..25): per-version docs, openapi diff, client SDK regen

### Test plan categories (5-6 sub-sections, 30 tests total)
- 10.1 Routing (T-01..06): v1 calls hit v1 handler, v2 calls hit v2 handler, cross calls return 404
- 10.2 Deprecation headers (T-07..12): Deprecation: true, Sunset date, Link header, only on v1
- 10.3 Schema isolation (T-13..18): v2 schemas don't leak into v1 responses, field renames work
- 10.4 Header strategy (T-19..23): Accept header parsing, fallback to current, malformed header
- 10.5 OpenAPI (T-24..27): per-version openapi.json works, root defaults to current
- 10.6 Idempotency, performance (T-28..30): tool re-run, latency, no regression

### Edge cases (15 EC-1..EC-15)
1. Project has no existing routes
2. New version label collides with existing (e.g. v2 already exists)
3. Strategy=header but client sends both Accept and v1 path
4. Sunset date in the past (deprecation_period_days < 0)
5. Two routes have the same path in v1 but different in v2
6. v2 route uses a schema that doesn't exist in v1
7. Removing a v1 route that v2 doesn't have a successor for → no Link header
8. OpenAPI generation for empty version (no routes)
9. Versioned middleware order: deprecation middleware runs AFTER auth
10. Reverse proxy strips the /api/v1 prefix (rewrites): tool documents X-Forwarded-Prefix
11. CORS preflight on a versioned route
12. Client sends `Accept: application/json` (no version vendor type)
13. Health check route should be UN-versioned (`/health`, not `/api/v1/health`)
14. New version has a different auth scheme than current
15. Versioned schemas with circular references

### Files created (suggested)
- `app/core/api_version.py` — constants, sunset date computation
- `app/api/middleware/deprecation.py` — Starlette middleware
- `app/api/v1/__init__.py`, `app/api/v1/main.py` — v1 router (existing routes moved here)
- `app/api/v2/__init__.py`, `app/api/v2/main.py` — v2 router (copied from v1, manually edited later)
- `app/schemas/v1/`, `app/schemas/v2/` — versioned schemas
- `app/api/deps_version.py` — header strategy dependency
- `tests/test_api_versioning.py` — 30 tests
- Documentation update note: README.md API section

### Files modified (suggested)
- `app/main.py` — mount both versioned routers, register middleware
- `app/api/main.py` — refactor to delegate to v1 + v2 sub-routers
- `app/core/config.py` — add `API_CURRENT_VERSION`, `API_DEPRECATED_VERSIONS`, `API_SUNSET_DATES`

### Anti-patterns to AVOID in this spec
- DO NOT use vague language ("modify routes appropriately" → instead say exactly which lines)
- DO NOT skip the migration of EXISTING routes; v1 must contain all routes that exist today
- DO NOT propose runtime version detection beyond path/header (no query string versioning, no body field)
- DO NOT propose semantic versioning at the resource level (this is whole-API versioning only)
- DO NOT introduce new DB tables (versioning is code-only)
- DO NOT mention "Stripe" or other vendors except for inspiration in section 12 emergency

### Documentation Output JSON shape
Include an example response with:
- files_created: 9 paths
- files_modified: 4 paths
- metrics: execution_time_ms, files_changed, lines_added, current_version, new_version, strategy, deprecation_period_days
- next_steps: at least 5 concrete commands or tests
- warnings: at least 2 specific gotchas (CORS preflight handling, sunset date awareness)
- notes: at least 3 facts about what was installed
