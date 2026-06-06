## Tool: `add_graphql`

### Overview parameters
- Tool name: `fastapi_add_graphql`
- Category: EXTEND > API Design
- Complexity: High
- Dependencies: existing FastAPI project with at least 1 SQLAlchemy model + auth (User), Strawberry GraphQL, dataloader (`aiodataloader`)
- Signature: `add_graphql(project_dir: str, models: list[str] | None = None, mount_path: str = "/graphql", expose_mutations: bool = True, enable_subscriptions: bool = False, max_query_depth: int = 8, max_query_complexity: int = 1000) -> dict`
- Parameters:
  - `project_dir`: project root path
  - `models`: list of model names to expose via GraphQL (None = all SQLAlchemy models)
  - `mount_path`: where to mount the GraphQL endpoint (default `/graphql`)
  - `expose_mutations`: if True, generates Mutation type with create/update/delete (default True)
  - `enable_subscriptions`: if True, mounts WebSocket route for `subscription` (default False)
  - `max_query_depth`: hard cap on query nesting depth (defense against malicious queries)
  - `max_query_complexity`: complexity score cap (each field has weight 1, lists multiply by max items)

### Purpose
Add a GraphQL layer on top of an existing REST FastAPI app using **Strawberry GraphQL** as the schema-first library. Generates GraphQL types from SQLAlchemy models, query/mutation resolvers that delegate to existing CRUD, an `aiodataloader`-based N+1 prevention layer, and depth/complexity guards. The endpoint coexists with REST — both share the same auth, the same models, and the same database. GraphQL is opt-in: clients can use REST or GraphQL interchangeably for the same domain. Subscriptions (optional) use Starlette WebSocket route.

### Performance SLOs (target / why columns)
- Tool execution time < 6s
- Files modified ≤ 5
- Files created ≥ 10 (schema dir, types per model, resolvers, dataloaders, deps, depth/complexity validators, mount, tests, migration if needed)
- Single-field query latency p99 < 30 ms (similar to REST GET)
- N+1 query prevention: nested list of 100 parents with child fields → exactly 2 SQL queries (parent batch + child batch via dataloader)
- Depth limit enforced server-side, exceeding returns 400 with explicit error
- Complexity limit enforced server-side, exceeding returns 400
- Migration runtime: 0s (no DB schema change)
- Memory overhead per request < 2 MB (dataloader cache flushed at request end)
- Schema introspection bounded: introspection query < 200 ms

### Key technical decisions

1. **Library**: Strawberry GraphQL (typed, code-first, fastapi-friendly). Not Graphene (legacy). Not Ariadne (schema-first).
2. **Mount**: `strawberry.fastapi.GraphQLRouter` mounted at `/graphql`. Same FastAPI app, shared lifespan.
3. **Auth**: same `CurrentUser` dependency from REST. Strawberry context loads `request.state.user`.
4. **Type generation**: per SQLAlchemy model, generate a `@strawberry.type` class via inspection of `__mapper__.attrs`. Fields are auto-typed (Column types → strawberry types).
5. **Resolvers**: each query/mutation calls into existing `app/crud/<model>.py` functions — NO duplication of business logic.
6. **N+1 prevention**: `aiodataloader` per request. Each FK relationship gets a dataloader instance attached to the request context. Resolvers use `await loader.load(parent.id)`.
7. **Mutations**: when `expose_mutations=True`, generates `create_<Model>`, `update_<Model>`, `delete_<Model>` mutations. Each takes a `<Model>Input` strawberry type.
8. **Depth limit**: custom Strawberry extension that walks the query AST counting nesting; rejects > `max_query_depth`.
9. **Complexity limit**: custom Strawberry extension scoring each field (1 per scalar, N per list field with `first` arg), rejects > `max_query_complexity`.
10. **Subscriptions**: optional. If enabled, WebSocket route at `mount_path` (Starlette WebSocketRoute). Subscriptions use AsyncIterators from a Redis pub/sub channel.
11. **Pagination**: GraphQL connections (cursor-based, Relay-style). `edges`, `pageInfo`, `cursor`, `hasNextPage`.
12. **Errors**: graceful — auth fails → `Unauthorized` extension; not-found → `NotFound`. Never leak stack traces in production.

### Key invariants (you must invent test IDs INV-GQL-01..08 and reference T-XX)
1. Every GraphQL query/mutation runs through the SAME `CurrentUser` dependency as REST (auth never bypassed).
2. N+1 queries are NEVER issued — nested fetches always go through dataloader batch loading.
3. Query depth > `max_query_depth` is ALWAYS rejected with 400 BEFORE any resolver runs.
4. Query complexity > `max_query_complexity` is ALWAYS rejected with 400 before resolvers run.
5. Mutations CANNOT be invoked when `expose_mutations=False` (mutation type not generated).
6. The same business logic in CRUD is invoked from REST and GraphQL — no duplication.
7. Schema introspection is restricted to authenticated users in production (configurable via `INTROSPECTION_AUTH_REQUIRED` setting).
8. Errors NEVER leak stack traces; only typed error extensions reach the client.

### User story themes (5 sub-sections)
- 9.1 Schema generation (US-01..05): types from models, queries, mutations, scalar custom types, enums
- 9.2 Auth & access (US-06..10): JWT auth on /graphql, owner check via dataloader, anonymous query rejection
- 9.3 N+1 prevention (US-11..15): nested lists with dataloader batching, missing dataloader detection, dataloader cache lifetime
- 9.4 Limits & DoS protection (US-16..20): depth limit, complexity limit, introspection bounded, query timeout
- 9.5 Mutation flows + integration (US-21..25): create/update/delete mutations, idempotency, transactional, REST/GQL coexistence

### Test plan categories (5-6 sub-sections, 30 tests total)
- 10.1 Schema generation (T-01..06): query type exists, mutation type exists, fields match model, scalar types
- 10.2 Resolution & N+1 (T-07..12): single field, nested list batched in 2 queries, dataloader cache hit
- 10.3 Auth (T-13..18): authenticated query 200, anonymous query 401, cross-user data 404, introspection auth
- 10.4 Limits (T-19..24): depth = max → 200, depth+1 → 400, complexity 999 → 200, 1001 → 400
- 10.5 Mutations (T-25..27): create_X mutation works, update propagates, delete soft-deletes
- 10.6 REST/GQL coexistence + perf (T-28..30): same data via REST and GraphQL, p99 latency, idempotency

### Edge cases (15 EC-1..EC-15)
1. Project has no SQLAlchemy models
2. Strawberry not installed
3. Model has a circular FK relationship
4. Two models share the same name (different module)
5. A model field is a JSON column with no schema → typed as `JSON` scalar
6. A model has a private/underscore field (`_internal_id`) — should be excluded from GraphQL
7. Mutation input uses an enum that doesn't exist in DB enum
8. Query depth = `max_query_depth` exactly (boundary case)
9. Complexity = `max_query_complexity` exactly (boundary case)
10. Subscription enabled but no Redis configured → tool errors at install
11. Two clients open WebSocket subscription for same channel → both receive events
12. Introspection query disabled in production → 400 / 401
13. Query has invalid syntax → 400 with parse error
14. Mutation runs but DB constraint fails → typed error extension, not 500
15. GraphQL endpoint behind reverse proxy that strips WebSocket Upgrade header → tool documents

### Files created (suggested)
- `app/graphql/__init__.py`
- `app/graphql/schema.py` — main schema entry point
- `app/graphql/types.py` — strawberry types per model
- `app/graphql/queries.py` — Query type with all queries
- `app/graphql/mutations.py` — Mutation type (when enabled)
- `app/graphql/dataloaders.py` — per-relationship dataloaders
- `app/graphql/extensions.py` — depth + complexity validators
- `app/graphql/context.py` — request context builder (user + dataloaders)
- `app/api/main.py` (modified) — mount GraphQLRouter
- `tests/test_graphql.py` — 30 tests
- `app/core/config.py` (modified) — add GRAPHQL_* settings
- `pyproject.toml` (modified) — add strawberry-graphql and aiodataloader deps

### Anti-patterns to AVOID in this spec
- DO NOT duplicate business logic between REST and GraphQL — both must call the same CRUD functions
- DO NOT skip N+1 prevention; every relationship MUST have a dataloader
- DO NOT introduce new auth path; reuse `CurrentUser`
- DO NOT use Graphene (legacy); use Strawberry
- DO NOT expose admin/superuser-only endpoints by default; mutations are gated by user roles
- DO NOT enable introspection in production without auth
- DO NOT use the @strawberry.field decorator for scalar fields that map directly to Column types — use auto-generation
- DO NOT split the schema into too many files; aim for 5-7 files in `app/graphql/`

### Documentation Output JSON shape
- files_created: 10+ paths
- files_modified: 3-4 paths
- metrics: execution_time_ms, files_changed, lines_added, models_exposed (count), max_query_depth, max_query_complexity
- next_steps: at least 5 (run tests, query browser at /graphql, sample query, mutation example, check N+1 detection)
- warnings: at least 2 (introspection auth in prod, depth limit choice, mutation auth)
- notes: at least 4 (which models exposed, mutation status, subscription status, integration with REST)
