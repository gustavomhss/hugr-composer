# Query-allow-list REST facade (GraphQL-style persisted queries)

## Background

A public API front-end wants to mitigate arbitrary-query DoS by only
accepting **persisted queries**: queries are registered up-front by
their SHA-256 hash; clients then send only the hash + variables, not
the full query text.

To keep things tractable, queries are simple named data lookups over
an in-memory catalog. There is no GraphQL parser — the facade just
uses names + variable bindings.

## Requirements

1. `POST /queries/register` — body `{"name": "<string>",
   "depth_limit": <int>}`. Returns `{"query_id": "<64-char hex>"}`.
   The `query_id` is the SHA-256 hex of the canonical JSON of
   `{"name": "...", "depth_limit": <int>}` (sort keys, no
   whitespace). This id is the ONLY handle that will execute the
   query later.
2. `POST /q` — body `{"query_id": "<string>", "variables": {...}}`.
   - Unknown `query_id` → 400 with `{"error": "unknown query"}`.
   - Known query: returns `{"data": {...}}` as defined below.
3. Exactly three query names are supported:
   - `list_users` — returns `{"users": [{"id": "u1", "name": "..."}]}`
     with `depth_limit` controlling how many users to include (max 3
     hard-coded). Variables: none.
   - `deep_nested` — returns a nested dict of depth `depth_limit`
     (e.g. `{"n": {"n": {"n": {}}}}` with depth=3). The server MUST
     reject `depth_limit > 6` at registration time with HTTP 400
     (depth bomb protection).
   - `echo_vars` — returns `{"vars": <variables as-received>}`.
4. The raw query text ("list_users", "deep_nested", etc.) MUST NEVER
   be accepted at `/q` — only registered hashes work. Sending
   `{"name": "list_users"}` directly → 400.
5. `GET /queries` — returns `{"queries": [{"query_id": "...", "name":
   "..."}]}` — all registered queries.
6. `GET /health` → 200.

## Acceptance criteria

- Register list_users with depth_limit=2 → /q returns 2 users.
- Same registration twice → same `query_id` (deterministic hash).
- /q with raw name (not hash) → 400.
- Register deep_nested with depth_limit=10 → 400 at registration.
- /q with unknown query_id → 400 {"error": "unknown query"}.
- 500 distinct register+execute calls complete in <30s, no 500s.

## Non-requirements

- No real GraphQL schema or parser.
- No authentication.
- No persistence.
