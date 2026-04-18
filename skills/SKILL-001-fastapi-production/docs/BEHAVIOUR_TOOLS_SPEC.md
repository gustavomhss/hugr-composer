# Behaviour Tools Specification

> 20 tools that add production-grade behavioral patterns to FastAPI.
> These are the patterns that Netflix, Stripe, AWS build internally
> but nobody ships as drop-in tools.

---

## Category 1: Resiliency (5 tools)

### TOOL-095: add_load_shedding

**Problem:** Under load, services crash instead of degrading gracefully. A 10x traffic spike shouldn't mean downtime — it should mean reduced functionality.

**What it generates:**
- `app/resilience/load_shedder.py` — LoadShedder: monitors p99 latency in real-time via sliding window, triggers degradation tiers
- `app/resilience/priority.py` — RequestPriority enum (CRITICAL/HIGH/NORMAL/LOW) + classifier based on path/method/user tier
- `app/resilience/degradation.py` — DegradationManager: disable non-critical features (analytics events, verbose logging, low-priority webhooks), reduce batch sizes, switch to cached responses
- `app/middleware/load_shedding.py` — LoadSheddingMiddleware: reject LOW priority with 429 + Retry-After, degrade NORMAL, always pass CRITICAL (health checks, payments)

**Config:** `LOAD_SHEDDING_ENABLED`, `LOAD_SHEDDING_P99_THRESHOLD_MS`, `LOAD_SHEDDING_RECOVERY_WINDOW_S`

**Why it's a banger:** The difference between a pager at 3 AM and a service that handles 10x traffic gracefully. AWS, Netflix, Google all have this internally. Nobody ships it open source.

---

### TOOL-096: add_adaptive_timeouts

**Problem:** Fixed timeouts are always wrong. Too low = false failures. Too high = cascade failures. Timeouts should LEARN from observed latency.

**What it generates:**
- `app/resilience/adaptive_timeout.py` — AdaptiveTimeout: tracks p50/p95/p99 per downstream dependency, auto-adjusts timeout to `p99 * 1.5` with configurable floor/ceiling
- `app/resilience/timeout_registry.py` — TimeoutRegistry: per-dependency tracking (DB, Redis, Stripe, etc.)
- Decorator: `@adaptive_timeout("stripe_api")` for any async function

**Config:** `ADAPTIVE_TIMEOUT_ENABLED`, `ADAPTIVE_TIMEOUT_FLOOR_MS`, `ADAPTIVE_TIMEOUT_CEILING_MS`, `ADAPTIVE_TIMEOUT_WINDOW_SIZE`

**Why it's a banger:** Google's "Tail at Scale" paper proved fixed timeouts cause cascading failures. This implements the solution. No Python framework has it.

---

### TOOL-097: add_bulkhead_isolation

**Problem:** One slow endpoint exhausts the thread/connection pool and takes down the entire service. Payments should NEVER be affected by a slow analytics query.

**What it generates:**
- `app/resilience/bulkhead.py` — Bulkhead: separate semaphore pools per endpoint group (payments, crud, analytics)
- `app/resilience/pool_config.py` — BulkheadConfig: max_concurrent per group, queue_size, timeout
- `app/middleware/bulkhead.py` — BulkheadMiddleware: route → group → acquire semaphore → 503 if pool full
- `app/api/routes/bulkhead_status.py` — GET /resilience/bulkheads (pool utilization per group)

**Config:** `BULKHEAD_ENABLED`, `BULKHEAD_PAYMENTS_MAX`, `BULKHEAD_CRUD_MAX`, `BULKHEAD_ANALYTICS_MAX`

**Why it's a banger:** Netflix's Hystrix made this pattern famous. In Python, nobody has it as a drop-in middleware. This tool generates it calibrated for your API's route structure.

---

### TOOL-098: add_retry_budget

**Problem:** When a downstream service has a blip, every client retries simultaneously. This "retry storm" turns a 1-second blip into a 10-minute outage.

**What it generates:**
- `app/resilience/retry_budget.py` — RetryBudget: tracks retry ratio globally, blocks retries when budget exceeds 10% of total traffic
- `app/resilience/retry_decorator.py` — `@with_retry_budget(budget="stripe")` decorator for any async call
- `app/api/routes/retry_status.py` — GET /resilience/retry-budget (current ratio per downstream)

**Config:** `RETRY_BUDGET_RATIO`, `RETRY_BUDGET_WINDOW_S`, `RETRY_BUDGET_MIN_REQUESTS`

**Why it's a banger:** Google SRE book, Chapter 22. The #1 cause of cascading outages that nobody talks about. This is production wisdom in a `pip install`.

---

### TOOL-099: add_chaos_testing

**Problem:** You don't know if your service handles failures until it fails in production. Chaos engineering lets you inject failures SAFELY in dev/staging.

**What it generates:**
- `app/chaos/__init__.py` — ChaosEngine: register failure injectors, probability-based activation
- `app/chaos/injectors.py` — LatencyInjector (add random delay), ErrorInjector (return 500), TimeoutInjector (hang), MemoryInjector (allocate N MB)
- `app/chaos/middleware.py` — ChaosMiddleware: only active when `CHAOS_ENABLED=true` (NEVER in production)
- `app/api/routes/chaos.py` — POST /chaos/enable, POST /chaos/disable, GET /chaos/status
- Guard: `ENVIRONMENT != "production"` hardcoded — physically cannot enable in prod

**Config:** `CHAOS_ENABLED` (default false), `CHAOS_LATENCY_MS`, `CHAOS_ERROR_RATE`, `CHAOS_TIMEOUT_RATE`

**Why it's a banger:** Netflix's Chaos Monkey, but for a single FastAPI service. Test your circuit breakers, retries, and bulkheads BEFORE production tells you they're broken.

---

## Category 2: Intelligence (5 tools)

### TOOL-100: add_api_replay_debugger

**Problem:** "Can't reproduce in local." Every developer's nightmare. Production bugs that only happen under specific state + timing + data combinations.

**What it generates:**
- `app/debug/recorder.py` — RequestRecorder: captures full request/response in Redis ring buffer (configurable TTL, max 10K entries)
- `app/debug/replayer.py` — RequestReplayer: re-execute any recorded request against current code, return diff of old vs new response
- `app/api/routes/debug.py` — GET /debug/requests (list recorded), POST /debug/replay/{id} (replay + diff), DELETE /debug/flush
- `app/middleware/request_recorder.py` — RecorderMiddleware: captures in background, zero impact on response time

**Config:** `DEBUG_RECORDER_ENABLED`, `DEBUG_RECORDER_TTL_S`, `DEBUG_RECORDER_MAX_ENTRIES`, `DEBUG_RECORDER_EXCLUDE_PATHS`

**Why it's a banger:** Time-travel debugging for APIs. Sentry captures errors. This captures EVERYTHING — even 200s that returned wrong data. Nobody has this.

---

### TOOL-101: add_anomaly_detector

**Problem:** By the time you get a PagerDuty alert, thousands of users are already affected. You need to detect anomalies in SECONDS, not minutes.

**What it generates:**
- `app/anomaly/__init__.py` — AnomalyDetector: statistical anomaly detection on request rate, error rate, latency, payload size
- `app/anomaly/detector.py` — Z-score + exponential moving average on sliding windows, configurable sensitivity
- `app/anomaly/alerter.py` — AlertDispatcher: webhook, log, Slack (lazy httpx), configurable channels
- `app/middleware/anomaly.py` — AnomalyMiddleware: updates metrics per request, triggers alert on anomaly
- `app/api/routes/anomaly.py` — GET /anomaly/status (current baselines + deviations)

**Config:** `ANOMALY_ENABLED`, `ANOMALY_SENSITIVITY`, `ANOMALY_WINDOW_SIZE`, `ANOMALY_ALERT_WEBHOOK_URL`

---

### TOOL-102: add_request_fingerprint

**Problem:** Client sends the same POST twice (network retry, double-click). Without idempotency keys, you process it twice. But requiring clients to send Idempotency-Key headers is friction.

**What it generates:**
- `app/fingerprint/hasher.py` — RequestFingerprinter: hash(user_id + method + path + sorted(body)) → SHA-256
- `app/fingerprint/store.py` — FingerprintStore: Redis SET with TTL, memory fallback
- `app/middleware/fingerprint.py` — FingerprintMiddleware: auto-dedup unsafe methods, return cached response on duplicate, Idempotent-Replayed: true header

**Config:** `FINGERPRINT_ENABLED`, `FINGERPRINT_TTL_S`, `FINGERPRINT_METHODS` (default: POST, PUT)

**Why it's a banger:** Stripe's Idempotency-Key but AUTOMATIC — no client cooperation needed. Nobody has server-side automatic request deduplication.

---

### TOOL-103: add_auto_ratelimit

**Problem:** Static rate limits are always wrong. 100/min for an API key that does 50/min is fine. 100/min for a key that suddenly does 10,000/min (compromised) is too late.

**What it generates:**
- `app/ratelimit/adaptive.py` — AdaptiveRateLimiter: learns each client's normal pattern (EMA), flags and throttles outliers (>3σ from baseline)
- `app/ratelimit/baseline.py` — BaselineTracker: per-client request rate baseline with Redis persistence
- `app/middleware/adaptive_ratelimit.py` — Middleware: soft-block (429) when client exceeds their OWN baseline by 3x

**Config:** `ADAPTIVE_RATELIMIT_ENABLED`, `ADAPTIVE_RATELIMIT_SENSITIVITY`, `ADAPTIVE_RATELIMIT_LEARNING_PERIOD_H`

---

### TOOL-104: add_api_fuzzer

**Problem:** Unit tests check expected behavior. Fuzzing checks UNEXPECTED behavior. What happens when someone sends `{"price": -99999999}` or `{"name": "a"*1000000}`?

**What it generates:**
- `app/fuzzer/__init__.py` — APIFuzzer: reads OpenAPI schema, generates adversarial inputs per field type
- `app/fuzzer/generators.py` — type-aware generators: boundary ints, unicode edge cases, SQL payloads, XSS vectors, empty/null/huge strings
- `app/fuzzer/runner.py` — FuzzRunner: hit each endpoint N times, report any non-JSON 5xx, timeout, or crash
- `scripts/run_fuzz.py` — CLI: `python scripts/run_fuzz.py --iterations 1000`

**Config:** `FUZZ_ITERATIONS`, `FUZZ_TIMEOUT_S`, `FUZZ_EXCLUDE_PATHS`

---

## Category 3: Lifecycle (5 tools)

### TOOL-105: add_schema_evolution_guard

**What it generates:**
- `app/schema_guard/comparator.py` — SchemaComparator: diff two OpenAPI JSON schemas, classify changes as BREAKING/COMPATIBLE/ADDITIVE
- `app/schema_guard/rules.py` — Breaking change rules: field removed, type changed, required added, enum shrunk, response shape changed
- `scripts/check_schema_compat.py` — CI script: compare current schema vs last release, exit 1 on breaking change
- `.github/workflows/schema_guard.yml` — GitHub Action template

**Config:** `SCHEMA_GUARD_BASELINE_PATH`, `SCHEMA_GUARD_FAIL_ON_BREAKING`

---

### TOOL-106: add_data_seeder

**What it generates:**
- `app/seeder/__init__.py` — DataSeeder: reads SQLAlchemy models, generates realistic test data respecting FKs + constraints
- `app/seeder/generators.py` — Smart generators: names (Faker), emails (domain-consistent), prices (sensible ranges), dates (realistic timelines)
- `app/seeder/graph.py` — DependencyGraph: topological sort of models by FK, seed in correct order
- `app/api/routes/seeder.py` — POST /dev/seed?count=100 (only in dev/staging)
- `scripts/seed.py` — CLI: `python scripts/seed.py --count 100`

**Config:** `SEEDER_ENABLED` (default false in production), `SEEDER_DEFAULT_COUNT`

---

### TOOL-107: add_api_deprecation

**What it generates:**
- `app/deprecation/__init__.py` — DeprecationRegistry: register endpoint with sunset date
- `app/deprecation/middleware.py` — DeprecationMiddleware: adds `Sunset` header (RFC 8594), `Deprecation` header, link to replacement
- `app/deprecation/reporter.py` — DeprecationReporter: tracks usage of deprecated endpoints, alerts when sunset date approaches
- `app/api/routes/deprecation.py` — GET /api/deprecations (list all deprecated + sunset dates)
- Decorator: `@deprecated(sunset="2026-06-01", replacement="/api/v2/items")`

**Config:** `DEPRECATION_WARN_DAYS_BEFORE_SUNSET`

---

### TOOL-108: add_tenant_onboarding

**What it generates:**
- `app/onboarding/__init__.py` — OnboardingOrchestrator: create tenant → admin user → seed data → configure billing → send welcome email
- `app/onboarding/steps.py` — OnboardingStep protocol: each step is atomic, compensatable, and reportable
- `app/schemas/onboarding.py` — OnboardingRequest, OnboardingStatus, OnboardingProgress
- `app/api/routes/onboarding.py` — POST /onboarding/start, GET /onboarding/{id}/status

**Config:** `ONBOARDING_STEPS` (configurable pipeline), `ONBOARDING_WELCOME_EMAIL_TEMPLATE`

---

### TOOL-109: add_graceful_shutdown

**What it generates:**
- `app/lifecycle/shutdown.py` — GracefulShutdown: signal handler (SIGTERM/SIGINT), drain phase (stop accepting new requests), complete phase (wait for in-flight to finish, max 30s), cleanup phase (close DB pools, flush queues, disconnect Redis)
- `app/lifecycle/health_gate.py` — ShutdownHealthGate: /healthz returns 503 during drain (load balancer stops sending traffic)
- `app/middleware/shutdown.py` — ShutdownMiddleware: reject new requests with 503 + Retry-After during drain

**Config:** `SHUTDOWN_DRAIN_SECONDS`, `SHUTDOWN_TIMEOUT_SECONDS`

---

## Category 4: Observability (3 tools)

### TOOL-110: add_request_tracing_ui

**What it generates:**
- `app/tracing_ui/__init__.py` — TracingBuffer: ring buffer of last 1000 requests with timing breakdown per middleware
- `app/tracing_ui/collector.py` — TimingCollector: measures time spent in each middleware layer, DB queries, external calls
- `app/api/routes/tracing.py` — GET /tracing/requests (list), GET /tracing/requests/{id} (full breakdown), GET /tracing/slow (p99 requests)
- `app/tracing_ui/templates/dashboard.html` — minimal self-contained HTML dashboard (no React, no build step, just HTML+CSS+vanilla JS)

---

### TOOL-111: add_dependency_health_map

**What it generates:**
- `app/health_map/__init__.py` — HealthMapBuilder: discovers all dependencies (DB, Redis, S3, Stripe, external APIs) from config
- `app/health_map/checker.py` — DependencyChecker: async health check per dependency with latency + status
- `app/api/routes/health_map.py` — GET /health/map (JSON dependency graph with status), GET /health/map/html (visual SVG map)

---

### TOOL-112: add_cost_tracker

**What it generates:**
- `app/costs/__init__.py` — CostTracker: estimates per-request cost based on resources consumed
- `app/costs/estimators.py` — DBQueryCostEstimator (queries × avg cost), S3CostEstimator (bytes transferred), APICostEstimator (external API calls)
- `app/middleware/cost_tracker.py` — CostMiddleware: annotates each response with `X-Request-Cost-Estimate` header
- `app/api/routes/costs.py` — GET /costs/summary (daily/weekly/monthly), GET /costs/by-endpoint (top N expensive endpoints)

---

## Category 5: Developer Experience (2 tools)

### TOOL-113: add_api_playground

**What it generates:**
- Enhanced Swagger UI with auth pre-configured, example payloads from models, WebSocket testing panel, GraphQL explorer, response diff tool
- `app/playground/templates/playground.html` — self-contained HTML

---

### TOOL-114: add_migration_rollback_guard

**What it generates:**
- `scripts/test_migration_rollback.py` — for each migration: upgrade → verify → downgrade → verify schema matches pre-upgrade
- Blocks CI if any migration has broken or missing downgrade
- `app/migrations/rollback_tester.py` — RollbackTester: automated upgrade/downgrade cycle
