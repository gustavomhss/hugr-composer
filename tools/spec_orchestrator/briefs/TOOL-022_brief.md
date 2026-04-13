## Tool: `add_circuit_breaker`

### Overview parameters
- Tool name: `fastapi_add_circuit_breaker`
- Category: EXTEND > Infrastructure
- Complexity: Medium
- Dependencies: existing FastAPI project, Redis (shared state across workers), httpx
- Signature: `add_circuit_breaker(project_dir: str, failure_threshold: int = 5, recovery_timeout_seconds: int = 30, half_open_max_calls: int = 3, failure_window_seconds: int = 60) -> dict`
- Parameters:
  - `project_dir`: project root path
  - `failure_threshold`: consecutive failures to open circuit (default 5)
  - `recovery_timeout_seconds`: wait before half-open attempt (default 30s)
  - `half_open_max_calls`: max probe calls in half-open state (default 3)
  - `failure_window_seconds`: sliding window for counting failures (default 60s)

### Purpose
Add a circuit breaker pattern for outbound HTTP calls to external services. When an external service fails repeatedly (e.g. 5 failures in 60s), the breaker opens and subsequent calls fail fast with 503 instead of hanging for the full timeout. After `recovery_timeout_seconds`, the breaker enters half-open state and allows a few probe calls; if they succeed, it closes; if they fail, it opens again. State is shared across workers via Redis. The tool generates a decorator `@circuit_breaker("service_name")` for service calls, a state machine, and admin endpoints to force-open/close circuits for manual interventions.

### Performance SLOs
- Tool execution time < 3s
- Files modified ≤ 4
- Files created ≥ 7 (breaker module, decorator, state machine, admin routes, config, tests, middleware)
- State lookup (Redis GET) < 1 ms
- Decorator overhead when closed < 0.5 ms
- Open state fast-fail response < 0.5 ms
- Failure count update (Redis INCR) < 1 ms
- State propagation across workers < 100 ms (Redis pubsub)
- No new DB tables

### Key technical decisions
1. **State machine:** `CLOSED` → `OPEN` (after failure_threshold) → `HALF_OPEN` (after recovery_timeout) → `CLOSED` (after N successful probes) or back to `OPEN` (on any failure).
2. **Shared state:** Redis hash `circuit:{service_name}` with fields `state`, `failure_count`, `last_failure_at`, `half_open_probe_count`.
3. **Sliding window failure counting:** Use Redis sorted set with timestamps; count entries in last `failure_window_seconds`.
4. **Decorator:** `@circuit_breaker("stripe")` wraps async functions. On call: check state, execute or fast-fail, update counters.
5. **Fast-fail exception:** `CircuitBreakerOpenError` raised when circuit is open. Caller catches and returns 503 to user.
6. **Half-open probing:** Allows exactly `half_open_max_calls` concurrent calls. Others fast-fail until probe results are in.
7. **Admin endpoints:** `GET /circuit/{service}` returns state; `POST /circuit/{service}/open` and `POST /circuit/{service}/close` for manual override.
8. **Metrics:** Emit state transitions to logs/metrics (open_count, close_count, half_open_duration).
9. **Fallback function:** Optional `fallback=fn` param on decorator — if provided, called when circuit is open instead of raising.
10. **Integration with httpx:** provide ready-made `CircuitBreakerHTTPClient` wrapper that applies the breaker to every request.

### Key invariants
1. State transitions are ATOMIC via Redis Lua script (no race between check-and-update).
2. An open circuit ALWAYS fast-fails within 1 ms (no external call attempted).
3. A circuit NEVER re-opens without at least 1 failure after half-open probes.
4. Failure count is BOUNDED by failure_window (old failures drop out).
5. Admin force-open/close ALWAYS overrides automatic state machine.
6. State changes ALWAYS published via Redis pubsub so all workers see the transition within 100 ms.
7. The decorator NEVER swallows exceptions — only translates them to `CircuitBreakerOpenError` when fast-failing.

### User story themes
- 9.1 Basic breaker (US-01..05): call closed circuit, threshold reached, circuit opens, fast-fail
- 9.2 Recovery flow (US-06..10): half-open after timeout, probe success closes, probe failure re-opens
- 9.3 Admin override (US-11..15): force open, force close, view state, bypass auto-recovery
- 9.4 Integration & fallback (US-16..20): httpx wrapper, fallback function, integration with retry logic
- 9.5 Observability & edge cases (US-21..25): metrics, concurrent workers, tool idempotency

### Test plan categories
- 10.1 State machine (T-01..06): closed→open, open→half_open, half_open→closed, half_open→open
- 10.2 Failure counting (T-07..12): sliding window expiry, threshold boundary, concurrent failures
- 10.3 Admin (T-13..18): force open, force close, state endpoint
- 10.4 Integration (T-19..24): httpx wrapper, fallback, decorator on async fn
- 10.5 Edge & perf (T-25..30): Redis down, concurrent workers, transition latency, tool idempotency

### Edge cases (15)
1. Redis down → circuit stays in last known state; fall-open by default (allow calls with warning)
2. Two workers race to transition CLOSED → OPEN → Lua script atomicity ensures single transition
3. half_open_max_calls in flight when one fails → remaining in-flight succeed but next call sees OPEN
4. Service recovers during half_open but one probe times out → circuit re-opens (one failure is enough)
5. Admin force-opens then auto-recovery tries to close → force override persists until admin closes
6. Decorator on sync function → tool errors (only async supported)
7. Fallback function raises → caller sees fallback exception, not CircuitBreakerOpenError
8. Multiple services sharing a client → each service has independent breaker state
9. Circuit name contains special chars → sanitized to alphanumeric+underscore
10. Redis pubsub message lost → TTL on state record is safety net
11. Failure window = 0 → treats every failure as immediate threshold hit
12. Recovery timeout = 0 → immediate half-open (effectively no breaker)
13. Tool re-run idempotent
14. Breaker on endpoint that uses websockets → not applicable, tool documents
15. Metrics emission fails → does NOT block the request

### Anti-patterns
- DO NOT use in-memory state (must be shared across workers)
- DO NOT skip atomic state transitions (race conditions will corrupt state)
- DO NOT swallow the original exception in the decorator
- DO NOT open the circuit on 4xx responses (client errors, not service failures)
- DO NOT block on pubsub for state changes (fire-and-forget)
