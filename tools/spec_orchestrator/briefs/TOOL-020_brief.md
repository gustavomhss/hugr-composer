## Tool: `add_long_running_task`

### Overview parameters
- Tool name: `fastapi_add_long_running_task`
- Category: EXTEND > API Design
- Complexity: High
- Dependencies: existing FastAPI project with auth, Redis (task queue), ARQ (background worker)
- Signature: `add_long_running_task(project_dir: str, max_task_duration_seconds: int = 3600, polling_interval_hint_seconds: int = 5, result_ttl_seconds: int = 86400) -> dict`
- Parameters:
  - `project_dir`: project root path
  - `max_task_duration_seconds`: hard timeout for any background task (default 1h)
  - `polling_interval_hint_seconds`: suggested polling interval returned to client in response headers
  - `result_ttl_seconds`: how long completed task results are kept in Redis (default 24h)

### Purpose
Add infrastructure for long-running operations that don't fit in a normal HTTP request-response cycle (reports, exports, bulk migrations, AI inference). The client POSTs a task, receives an immediate 202 Accepted with a `task_id` and a `Location` header pointing to a status endpoint. The client polls `GET /tasks/{task_id}` to check progress. When the task completes, the response includes the result (inline for small payloads, or a presigned URL for large files). Tasks are processed by ARQ workers, tracked in Redis with TTL, and report progress via structured status updates. This tool generates the task model, the submission/status/cancel endpoints, the ARQ worker harness, and progress-reporting utilities.

### Performance SLOs
- Tool execution time < 5s
- Files modified ≤ 5
- Files created ≥ 9 (task model, task schemas, task CRUD, task routes, worker harness, progress tracker, Redis keys, config settings, tests)
- Submission endpoint latency < 50 ms (just enqueue to Redis)
- Status poll latency < 10 ms (Redis GET)
- Progress update latency < 5 ms (Redis SET)
- Worker picks up task within 1s of submission
- Task timeout enforced via asyncio.wait_for
- Completed results available for result_ttl_seconds (default 24h)
- No new DB tables required (Redis-only state); optional PostgreSQL persistence for audit

### Key technical decisions
1. **State in Redis, not PostgreSQL.** Task metadata (status, progress, result, error) stored as Redis hashes with TTL. Avoids DB writes on every progress update. Optional: persist completed tasks to PostgreSQL for long-term audit.
2. **ARQ as the worker.** Tasks are Python async functions decorated with `@task_handler("task_type")`. ARQ handles retries, timeouts, and concurrency.
3. **Task lifecycle:** `pending` → `running` → `completed` | `failed` | `cancelled`. Each transition updates Redis hash.
4. **Progress reporting:** Worker calls `await report_progress(task_id, pct=45, message="Processing row 450/1000")`. Client sees this on next poll.
5. **Result delivery:** Small results (< 1 MB) inline in the status response. Large results: worker uploads to storage, sets `result_url` (presigned URL with TTL).
6. **Cancellation:** `DELETE /tasks/{task_id}` sets a cancellation flag in Redis. Worker checks `is_cancelled(task_id)` periodically and aborts gracefully.
7. **Task registry:** Dictionary mapping `task_type` string to handler function. Submission endpoint validates task_type against registry.
8. **Idempotency:** Client can submit with `Idempotency-Key` header. If key exists in Redis, returns existing task_id instead of creating new one.
9. **Auth:** Task is owned by the submitting user. Status/cancel endpoints verify ownership. Admin can see all tasks.
10. **SSE integration:** If `add_sse` is installed, completion/progress can also push SSE events to the user's channel (optional, not default).

### Key invariants
1. Submission ALWAYS returns 202 with task_id and Location header — NEVER blocks on task execution.
2. A task in `completed` or `failed` state NEVER transitions to another state.
3. A cancelled task ALWAYS transitions to `cancelled` within max_task_duration_seconds.
4. Task results ALWAYS expire after result_ttl_seconds — NEVER persist indefinitely in Redis.
5. A non-owner NEVER sees or cancels another user's task (except admin).
6. The task registry ALWAYS rejects unknown task_type at submission (not at worker pickup).
7. Progress updates are ALWAYS monotonically increasing (pct cannot decrease).
8. The worker timeout ALWAYS fires for tasks exceeding max_task_duration_seconds.

### User story themes
- 9.1 Submission & polling (US-01..05): submit task, get 202, poll status, see progress, get result
- 9.2 Lifecycle & cancellation (US-06..10): cancel running task, timeout, retry failed, idempotency key
- 9.3 Results & cleanup (US-11..15): inline result, presigned URL for large, TTL expiry, admin list
- 9.4 Auth & access (US-16..20): owner check, admin override, cross-user isolation, API key task submission
- 9.5 Integration & observability (US-21..25): SSE progress push, audit log, multi-tenant scoping, tool idempotency

### Test plan categories
- 10.1 Submission (T-01..06): 202 response, Location header, task_id format, unknown task_type → 422, duplicate idempotency key
- 10.2 Polling & progress (T-07..12): pending→running→completed flow, progress reporting, poll latency
- 10.3 Cancellation & timeout (T-13..18): cancel running task, cancel pending, cancel completed (no-op), timeout enforcement
- 10.4 Results (T-19..24): inline result, presigned URL, TTL expiry, result not found after TTL
- 10.5 Auth & integration (T-25..30): owner check, admin list, cross-user isolation, SSE integration, audit entry

### Edge cases (15)
1. Task type not in registry → 422 with available types list
2. Worker crashes mid-task → task stays `running` until timeout, then marked `failed`
3. Redis goes down during progress update → update lost, task continues (fire-and-forget progress)
4. Client polls immediately after submission → `pending` status (worker hasn't picked up yet)
5. Two submissions with same idempotency key → second returns existing task_id
6. Task completes but result > 1 MB → worker stores to S3, returns presigned URL
7. Cancel request after task already completed → 200 with `already_completed` status
8. Worker timeout fires but task caught in DB lock → asyncio cancellation + forced cleanup
9. Admin lists tasks across all users → returns all with pagination
10. Task submitted by API key (no user_id) → task owned by key identity
11. Progress reported at 100% but task not yet completed → status stays `running` until handler returns
12. Redis TTL expires while client is polling → 404 with `task_expired` message
13. Concurrent cancel + complete race → first writer wins (Redis atomic SET)
14. Tool re-run is idempotent → routes not duplicated
15. Large number of pending tasks (10K) → ARQ handles queue, no memory issue in API server

### Files created
- `app/core/tasks.py` — TaskStatus enum, TaskMeta schema, Redis key helpers, progress reporter
- `app/core/task_registry.py` — task handler registry + decorator
- `app/schemas/task.py` — TaskSubmit, TaskStatusResponse, TaskListResponse
- `app/crud/task.py` — Redis-backed CRUD (create, get, update_status, cancel, list_for_user)
- `app/api/routes/tasks.py` — POST /tasks, GET /tasks/{id}, DELETE /tasks/{id}, GET /tasks (admin)
- `app/workers/task_worker.py` — ARQ worker with task handler dispatch
- `tests/test_long_running_task.py` — 30 tests

### Files modified
- `app/api/main.py` — register task routes
- `app/core/config.py` — add TASK_* settings
- `.env.example` — add TASK_MAX_DURATION, TASK_RESULT_TTL

### Anti-patterns
- DO NOT block the submission endpoint waiting for the task to complete
- DO NOT store task state in PostgreSQL for every progress update (Redis only, optional PG persist on completion)
- DO NOT allow task_type to be an arbitrary string — validate against registry
- DO NOT let progress percentage decrease
- DO NOT return 200 from submission — ALWAYS 202
- DO NOT skip the Location header in the 202 response
- DO NOT process tasks in the API worker process — always delegate to ARQ
