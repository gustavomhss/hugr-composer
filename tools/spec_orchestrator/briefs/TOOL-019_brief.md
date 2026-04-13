## Tool: `add_batch_endpoint`

### Overview parameters
- Tool name: `fastapi_add_batch_endpoint`
- Category: EXTEND > API Design
- Complexity: Medium
- Dependencies: existing FastAPI project with at least 1 resource (model + CRUD + routes), Alembic optional
- Signature: `add_batch_endpoint(project_dir: str, models: list[str] | None = None, max_batch_size: int = 50, strategy: Literal["sequential", "parallel"] = "sequential", timeout_per_item_ms: int = 5000) -> dict`
- Parameters:
  - `project_dir`: project root path
  - `models`: list of model names to add batch endpoints for (None = all models with existing routes)
  - `max_batch_size`: hard cap on items per batch request (default 50)
  - `strategy`: how to process items — `sequential` (one-by-one, order guaranteed) or `parallel` (asyncio.gather, faster, order not guaranteed)
  - `timeout_per_item_ms`: per-item timeout; total request timeout = N × timeout

### Purpose
Add a batch processing endpoint for each resource so clients can send multiple operations in a single HTTP request. Instead of N individual calls to `POST /items/`, the client sends one call to `POST /items/batch` with a list of operations. Each operation is processed independently, and the response uses HTTP 207 Multi-Status to report per-item results. This eliminates N round-trips, enables atomicity via `all_or_nothing` mode, and provides a clean API for bulk imports, migrations, and admin tools. The tool generates a generic batch router factory that works with any existing CRUD, plus Pydantic schemas for the request/response contract.

### Performance SLOs
- Tool execution time < 4s
- Files modified ≤ 4
- Files created ≥ 6 (batch router factory, schemas, per-model batch routes, tests)
- Batch of 50 items response time < 5s (sequential) / < 2s (parallel)
- Individual item failure must NOT block other items in `best_effort` mode
- Memory overhead per batch request < 10 MB
- Max batch size enforced server-side (reject > max with 422)
- Per-item timeout enforced (asyncio.wait_for)
- No new DB tables required (code-only tool)

### Key technical decisions
1. **Response: HTTP 207 Multi-Status.** Each item in the response has its own `status_code` (201, 200, 404, 422, 500) and optional `error`.
2. **Two modes:** `all_or_nothing` (single transaction, rollback on any failure) and `best_effort` (SAVEPOINT per item, partial success allowed).
3. **Generic batch router factory:** `create_batch_router(model_class, crud_module, schema_in, schema_out)` returns an APIRouter with `/batch` POST endpoint. Per-model routers use this factory — NO code duplication.
4. **Schema:** `BatchRequest` with `items: list[SchemaIn]` and `mode: Literal["all_or_nothing", "best_effort"]`. `BatchResponse` with `results: list[BatchItemResult]` where each has `index`, `status_code`, `data` (on success), `error` (on failure).
5. **Sequential processing:** simple for loop over items, each committed individually (best_effort) or all in one TX (all_or_nothing).
6. **Parallel processing:** `asyncio.gather(*[process_one(item) for item in items])` with per-item timeout via `asyncio.wait_for`. Only available in `best_effort` mode (parallel + all_or_nothing is contradictory).
7. **Validation:** Pydantic validates the full batch before processing starts. If any item fails Pydantic validation, the entire request is 422.
8. **Max batch size:** `Field(..., max_length=max_batch_size)` on the items list. Enforced at schema level.
9. **Progress tracking:** For very large batches, return immediately with a job ID and process async (future enhancement, not in MVP).
10. **Integration with soft-delete:** batch delete routes use soft-delete if available.
11. **Integration with audit_log:** each item in the batch produces its own audit entry.
12. **Integration with multi-tenancy:** batch items are auto-stamped with current tenant.

### Key invariants
1. The batch endpoint NEVER returns 200 — it ALWAYS returns 207 Multi-Status (even if all items succeed).
2. In `all_or_nothing` mode, a failure in ANY item rolls back ALL items in the same transaction.
3. In `best_effort` mode, each item is isolated via SAVEPOINT; failure in item N does NOT affect items N-1 or N+1.
4. A request with > `max_batch_size` items is ALWAYS rejected with 422 before processing.
5. The generic factory produces IDENTICAL behavior regardless of which model it wraps.
6. Individual item timeout is ALWAYS enforced via `asyncio.wait_for`.
7. Auth (CurrentUser) is checked ONCE at the batch level, not per-item.

### User story themes
- 9.1 Core batch create (US-01..05): batch create 5 items, all succeed; batch with 1 invalid → 207 mixed
- 9.2 Modes (US-06..10): all_or_nothing rollback, best_effort partial success, parallel mode, mixed status codes
- 9.3 Limits & validation (US-11..15): max batch size rejection, per-item timeout, Pydantic pre-validation
- 9.4 Integration (US-16..20): batch + soft-delete, batch + audit log, batch + multi-tenancy, batch + RBAC
- 9.5 Error handling & idempotency (US-21..25): duplicate detection, foreign key failure, DB constraint, tool idempotency

### Test plan categories
- 10.1 Batch create (T-01..06): all succeed, 1 fail, empty batch, single item
- 10.2 All-or-nothing (T-07..12): rollback on failure, no partial state, transaction isolation
- 10.3 Best-effort (T-13..18): partial success, SAVEPOINT isolation, item N failure doesn't affect N+1
- 10.4 Limits & auth (T-19..24): max size rejection, per-item timeout, auth checked once, owner check
- 10.5 Integration & perf (T-25..30): soft-delete, audit per item, multi-tenant stamp, p99 latency

### Edge cases (15)
1. Empty batch (items=[]) → 422
2. Batch with exactly max_batch_size items → 207 (boundary)
3. Batch with max_batch_size+1 → 422
4. all_or_nothing + parallel strategy requested → 422 (contradictory)
5. All items fail in best_effort → 207 with all errors (not 500)
6. One item timeout in parallel mode → that item 408, others succeed
7. DB connection pool exhausted during large batch → graceful 503
8. Batch of items that violate unique constraint → per-item 409
9. Batch of items referencing non-existent FK → per-item 404
10. Batch create + soft-delete model → created items have is_deleted=False
11. Batch endpoint behind rate limiter → counted as 1 request, not N
12. Client sends batch with duplicate items (same payload twice) → both processed
13. CRUD raises unexpected exception → per-item 500 with sanitized error
14. Request body > 10 MB → 413 before parsing
15. Tool re-run is idempotent → routes not duplicated

### Files created
- `app/core/batch.py` — BatchRequest, BatchResponse, BatchItemResult schemas + factory
- `app/api/routes/{model}_batch.py` — per-model batch route (or appended to existing route file)
- `tests/test_batch_endpoint.py` — 30 tests

### Files modified
- `app/api/main.py` — register batch routes
- `app/core/config.py` — add BATCH_MAX_SIZE, BATCH_TIMEOUT_PER_ITEM_MS settings

### Anti-patterns
- DO NOT duplicate CRUD logic; the batch factory calls existing `crud.create()` per item
- DO NOT return 200 or 201 for batch operations; ALWAYS use 207
- DO NOT use 500 for individual item failures; use the appropriate 4xx per item
- DO NOT allow parallel + all_or_nothing (logically contradictory)
- DO NOT process items before Pydantic validates the full list
- DO NOT count batch as N requests for rate limiting
