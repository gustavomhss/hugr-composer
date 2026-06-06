## Tool: `add_saga`

### Overview parameters
- Tool name: `fastapi_add_saga`
- Category: EXTEND > Infrastructure
- Complexity: High
- Dependencies: existing FastAPI project with SQLAlchemy, Alembic, Redis or DB-backed state
- Signature: `add_saga(project_dir: str, state_backend: Literal["postgres", "redis"] = "postgres", step_timeout_seconds: int = 30, max_compensations: int = 10) -> dict`
- Parameters:
  - `project_dir`: project root path
  - `state_backend`: where saga state is persisted — `postgres` (durable) or `redis` (faster but volatile)
  - `step_timeout_seconds`: timeout per saga step
  - `max_compensations`: safety cap on compensation attempts

### Purpose
Implement the Saga pattern for distributed transactions across multiple services or aggregates. A saga is a sequence of steps, each with a forward action and a compensation action. If any step fails, previously-completed steps are compensated (rolled back) in reverse order. This is the standard pattern for workflows that cross service boundaries and can't use a single DB transaction (e.g. book flight → reserve hotel → charge credit card — if card charge fails, compensate hotel then flight). The tool generates a `Saga` base class, a `SagaStep` decorator, a state machine persisting to PostgreSQL (default) or Redis, a coordinator that drives execution, and admin endpoints to inspect running sagas.

### Performance SLOs
- Tool execution time < 5s
- Files modified ≤ 5
- Files created ≥ 9 (base class, step decorator, coordinator, state model, migration, admin routes, config, tests, example saga)
- Step execution overhead < 2 ms (excluding the actual step work)
- State persistence per step < 5 ms (single INSERT/UPDATE)
- Compensation invocation within 1s of step failure
- Timeout enforcement via asyncio.wait_for per step

### Key technical decisions
1. **Base class:** `class BookingSaga(Saga):` with methods `@SagaStep(compensate=cancel_flight) async def book_flight(...)`. Each step is a coroutine.
2. **State machine:** saga has states `pending` → `running` → `compensating` → `completed` | `failed` | `compensated`. Steps have states `pending` → `completed` | `failed` | `compensated`.
3. **State persistence:** `saga_instances` table with `id, saga_type, state, current_step, created_at, completed_at` and `saga_step_executions` table with `id, saga_id, step_name, state, input, output, error`.
4. **Coordinator:** kicks off saga, calls each step in order, persists state after each, on failure triggers compensation loop in reverse.
5. **Compensation:** a step's compensation is ONLY called if the forward action completed successfully. Pending/failed steps are not compensated.
6. **Idempotency:** each step takes a `saga_id` so it can dedupe (store checkpoint after each success). On coordinator restart, resume from last completed step.
7. **Timeout per step:** `asyncio.wait_for(step(), timeout=step_timeout_seconds)`. Timeout counts as failure → triggers compensation.
8. **Admin endpoints:** `GET /sagas/{id}` (current state + step history), `POST /sagas/{id}/resume` (manual resume after fix), `POST /sagas/{id}/abort` (force compensation).
9. **Durable mode (PostgreSQL):** all state in DB, survives restarts.
10. **Volatile mode (Redis):** faster, state lost on Redis restart (suitable for sagas < 1 min).

### Key invariants
1. A step's compensation is ONLY called after the step's forward action completed successfully.
2. Compensations ALWAYS execute in REVERSE order of forward steps.
3. A saga NEVER executes the same step twice without explicit retry.
4. State updates are PERSISTED BEFORE the next step runs (crash-safe).
5. A step timeout ALWAYS triggers compensation (no silent retry).
6. A compensation failure after max_compensations attempts escalates to manual intervention (saga marked `requires_human`).
7. The coordinator NEVER holds a DB transaction across multiple steps (each step is its own transaction).
8. Admin force-abort ALWAYS triggers compensation from the current step backward.

### User story themes
- 9.1 Happy path (US-01..05): define saga, 3 steps all succeed, state transitions, final state=completed
- 9.2 Compensation (US-06..10): step 3 fails, compensate 2 then 1, saga=compensated
- 9.3 Resilience (US-11..15): coordinator restart, resume from last step, timeout triggers compensate
- 9.4 Admin (US-16..20): inspect running saga, force abort, resume stuck saga, list all
- 9.5 Edge cases & integration (US-21..25): compensation failure, multi-worker, tool idempotency

### Test plan categories
- 10.1 Happy path (T-01..06): 3-step saga completes, state persisted
- 10.2 Compensation (T-07..12): step 3 fails→compensate 2→1, compensation order, step 1 failure no compensation
- 10.3 Resilience (T-13..18): restart, resume, timeout, max_compensations
- 10.4 Admin (T-19..24): get state, abort, resume, list
- 10.5 Integration (T-25..30): multi-worker, Redis vs PG, tool idempotency

### Edge cases (15)
1. Compensation for step N fails permanently → saga marked `requires_human`, admin notified
2. Coordinator crashes between step success and state update → next run re-executes step (idempotency key required)
3. Multiple coordinators race on same saga → database lock on `saga_instances.id`
4. Saga with 0 steps → completes immediately
5. Saga step that doesn't define a compensation → compensation is a no-op for that step
6. Timeout during compensation → retry compensation up to max_compensations
7. Compensation mutates data that other sagas depend on → documented as caller responsibility
8. Resume a saga whose last step was `running` (coordinator died mid-step) → re-execute the step
9. Compensation in wrong order → tool validates order at registration, refuses bad definitions
10. State backend (Redis) down during saga execution → saga pauses, resumes when backend is back
11. Step input too large (> 1 MB) → saga errors at registration
12. Step returns None but compensation expects value → runtime TypeError, caught as step failure
13. Saga takes longer than step_timeout × steps → not a tool concern (per-step timeout)
14. Two sagas with same type run concurrently → each has unique saga_id, no interference
15. Tool re-run idempotent

### Anti-patterns
- DO NOT use a single DB transaction across saga steps (defeats the purpose)
- DO NOT skip state persistence between steps (crash = lost work)
- DO NOT allow compensations out of order (data corruption risk)
- DO NOT retry compensations indefinitely (escalate to human after max)
- DO NOT store raw SQL state (use model with typed columns)
- DO NOT allow arbitrary Python code in step definitions without registration
