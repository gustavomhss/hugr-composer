## Tool: `extract_service`

### Overview parameters
- Tool name: `fastapi_extract_service`
- Category: EVOLVE
- Complexity: Very High
- Dependencies: existing FastAPI project, git, AST, Docker
- Signature: `extract_service(project_dir: str, module_paths: list[str], new_service_name: str, new_service_port: int = 8001, communication: str = "http", generate_client: bool = True) -> dict`
- Parameters:
  - `project_dir`: source monolith path
  - `module_paths`: list of modules/directories to extract into the new service
  - `new_service_name`: directory name for the extracted service
  - `new_service_port`: port for the new service
  - `communication`: `http` (REST), `grpc`, or `events`
  - `generate_client`: create a typed client for the monolith to call the new service

### Purpose
Carve out a subset of the monolith into a standalone FastAPI service. Moves the specified modules (routes, models, schemas, tests), computes the shared dependencies, generates the boundary contract (REST/gRPC/events), scaffolds a new project skeleton with Docker + CI, and replaces the in-monolith calls with client calls to the new service. Essential for strangler-fig migrations when a monolith needs to split. Generates a transition plan with "split" (monolith stops serving these routes) and "proxy" (monolith proxies to the new service) modes so teams can roll out incrementally.

### Performance SLOs
- Tool execution time < 10s for a 20-module extraction
- Files modified ≤ 40 (monolith: imports + calls replaced)
- Files created ≥ 25 (new service: routes, models, schemas, tests, Dockerfile, CI, client, docs + proxy layer)
- AST walk < 3s
- Dependency graph build < 2s
- Zero impact on unmodified modules

### Key technical decisions
1. **Dependency graph:** reuse blast_radius engine to find cross-cutting deps
2. **Boundary contract:** REST with OpenAPI schema + generated Python client
3. **Shared models:** moved to a shared library (`common/`) both services depend on
4. **Database split:** same DB (initially) OR separate DB with explicit FK removal
5. **Transition modes:**
   - `split`: monolith stops serving the routes, new service serves them
   - `proxy`: monolith proxies HTTP calls to the new service (zero-downtime rollout)
6. **Client generation:** Pydantic-typed client with retries, timeout, circuit breaker
7. **CI pipeline:** new service gets its own GitHub Actions workflow
8. **Docker/compose:** new service added to `docker-compose.yml` with dedicated service
9. **Tests:** both services' test suites run in CI; contract tests ensure boundary stability
10. **Rollback plan:** generated doc explains how to re-merge into monolith if needed

### Key invariants
1. The monolith's tests ALWAYS still pass after extraction (verified post-apply).
2. Shared code is ALWAYS moved to a single `common/` package, never duplicated.
3. The new service is ALWAYS self-contained (can build + run in isolation).
4. Proxy mode NEVER introduces more than 50 ms latency.
5. Contract tests are ALWAYS generated from the original monolith behavior.
6. Database split is OPTIONAL and explicit (default: shared).
7. Client is ALWAYS typed — no untyped dicts crossing the boundary.

### User story themes
- 9.1 Basic extraction (US-01..05): 1 module, 5 modules, with deps, contract, tests
- 9.2 Communication modes (US-06..10): REST, gRPC, events, proxy, split
- 9.3 Shared code (US-11..15): common lib, duplication rejected, dep graph, circular
- 9.4 DB strategies (US-16..20): shared DB, split DB, FK removal, transitional
- 9.5 Edge cases (US-21..25): monolith rollback, tool idempotency, circular refs, scale

### Test plan categories
- 10.1 Dependency discovery (T-01..06): direct, transitive, shared, common lib
- 10.2 Extraction (T-07..12): route, model, schema, tests, Docker, CI
- 10.3 Communication (T-13..18): REST, gRPC, events, client
- 10.4 Transition modes (T-19..24): split, proxy, rollback
- 10.5 Edge cases (T-25..30): circular, tool idempotency, DB split

### Edge cases (15)
1. Module has circular dep with monolith → extraction blocked with clear message
2. Module uses raw SQL referencing monolith tables → flagged for manual resolution
3. Module has private imports across boundaries → moved to common lib
4. 1 module extraction → minimal scaffold
5. 50 module extraction → all generated
6. Proxy mode → latency verified < 50 ms
7. Monolith tests fail post-extraction → rollback plan triggered automatically
8. Database split chosen → FK constraints removed with warning
9. Tool re-run idempotent
10. Client generation fails (OpenAPI incomplete) → error with hint
11. Port already in use → warning, uses next available
12. Contract tests generated → pass on both monolith and new service
13. Dockerfile layer caching → preserved
14. CI pipeline validated locally before commit → green
15. Rollback plan documentation included → maintainer verified

### Anti-patterns
- DO NOT duplicate shared code (creates drift)
- DO NOT extract without running the monolith's tests first
- DO NOT split the DB in the same step (too much change)
- DO NOT skip contract tests (boundary rots silently)
- DO NOT generate untyped clients (defeats the boundary)
