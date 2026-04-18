# Banger Tools Specification

> 10 tools that don't exist anywhere in the Python ecosystem.
> 5 from internal brainstorm + 5 from deep web research.

---

## BRAINSTORM PICKS (5 tools)

### TOOL-B01: add_api_replay_debugger

**One-line:** Time-travel debugging for APIs in production.

**Problem:** "Can't reproduce in local." Every developer's nightmare. Production bugs that only happen under specific state + timing + data combinations.

**What it generates:**
- `app/debug/recorder.py` — RequestRecorder: captures full request/response in Redis ring buffer (configurable TTL, max 10K entries)
- `app/debug/replayer.py` — RequestReplayer: re-execute any recorded request against current code, return diff of old vs new response
- `app/api/routes/debug.py` — GET /debug/requests (list recorded), POST /debug/replay/{id} (replay + diff), DELETE /debug/flush
- `app/middleware/request_recorder.py` — RecorderMiddleware: captures in background, zero impact on response time

**Config:** `DEBUG_RECORDER_ENABLED`, `DEBUG_RECORDER_TTL_S`, `DEBUG_RECORDER_MAX_ENTRIES`, `DEBUG_RECORDER_EXCLUDE_PATHS`

**Why nobody has it:** Sentry captures errors. This captures EVERYTHING — even 200s that returned wrong data. Combines recording + replay + diff in a single tool.

---

### TOOL-B02: add_schema_evolution_guard

**One-line:** Prevents breaking API changes automatically in CI.

**Problem:** Stripe, Twilio, GitHub spend millions not to break APIs. This gives the same protection to anyone.

**What it generates:**
- `app/schema_guard/comparator.py` — SchemaComparator: diff two OpenAPI JSON schemas, classify changes as BREAKING/COMPATIBLE/ADDITIVE
- `app/schema_guard/rules.py` — Breaking change rules: field removed, type changed, required added, enum shrunk, response shape changed
- `scripts/check_schema_compat.py` — CI script: compare current schema vs last release, exit 1 on breaking change

**Config:** `SCHEMA_GUARD_BASELINE_PATH`, `SCHEMA_GUARD_FAIL_ON_BREAKING`

---

### TOOL-B03: add_load_shedding

**One-line:** Graceful degradation under load — not crash, not 503, degrade intelligently.

**Problem:** A 10x traffic spike shouldn't mean downtime — it should mean reduced functionality.

**What it generates:**
- `app/resilience/load_shedder.py` — LoadShedder: monitors p99 latency via sliding window, triggers degradation tiers
- `app/resilience/priority.py` — RequestPriority enum (CRITICAL/HIGH/NORMAL/LOW) + classifier
- `app/resilience/degradation.py` — DegradationManager: disable non-critical features, reduce batch sizes, switch to cached responses
- `app/middleware/load_shedding.py` — LoadSheddingMiddleware: reject LOW priority with 429 + Retry-After, always pass CRITICAL

**Config:** `LOAD_SHEDDING_ENABLED`, `LOAD_SHEDDING_P99_THRESHOLD_MS`, `LOAD_SHEDDING_RECOVERY_WINDOW_S`

**Why nobody has it:** AWS, Netflix, Google all have this internally. Nobody ships it open source.

---

### TOOL-B04: add_api_fuzzer

**One-line:** Schema-aware fuzzing that finds bugs unit tests miss.

**Problem:** Unit tests check expected behavior. Fuzzing checks UNEXPECTED behavior. What happens when someone sends `{"price": -99999999}`?

**What it generates:**
- `app/fuzzer/generators.py` — type-aware generators: boundary ints, unicode edge cases, SQL payloads, XSS vectors, empty/null/huge strings
- `app/fuzzer/runner.py` — FuzzRunner: hit each endpoint N times, report any non-JSON 5xx, timeout, or crash
- `scripts/run_fuzz.py` — CLI: `python scripts/run_fuzz.py --iterations 1000`

**Config:** `FUZZ_ITERATIONS`, `FUZZ_TIMEOUT_S`, `FUZZ_EXCLUDE_PATHS`

**Why nobody has it:** Schemathesis exists but requires manual setup. This generates a fuzzer CALIBRATED for the specific API schema.

---

### TOOL-B05: add_data_seeder

**One-line:** Intelligent seed with realistic data that respects FK relationships.

**Problem:** Faker is generic and doesn't understand relationships. This reads SQLAlchemy models, understands FKs, and generates realistic interconnected data.

**What it generates:**
- `app/seeder/generators.py` — Smart generators: names, emails, prices that make sense per field type
- `app/seeder/graph.py` — DependencyGraph: topological sort of models by FK, seed in correct order
- `app/api/routes/seeder.py` — POST /dev/seed?count=100 (only in dev/staging)
- `scripts/seed.py` — CLI: `python scripts/seed.py --count 100`

**Config:** `SEEDER_ENABLED` (default false in production), `SEEDER_DEFAULT_COUNT`

---

## RESEARCH PICKS (5 tools — from deep web research)

### TOOL-R01: add_zero_downtime_migration

**One-line:** Decomposes breaking schema changes into safe expand/migrate/contract migration triplets automatically.

**Problem:** Renaming a column, adding NOT NULL, changing a type — each requires 3 separate Alembic revisions with dual-write triggers, and testing rollback per phase. Currently takes senior engineers 1-3 days PER risky migration. Nobody has automated the *decomposition* itself — Squawk only lints after you've written it.

**What it generates:**
- 3 Alembic revision files per change (expand → migrate data → contract) with proper dependency chain
- Temporary dual-write event handler (`after_insert`/`after_update`) to keep old+new columns in sync during transition
- Rollback script for each phase
- Pre-flight safety check: validates expand migration against currently running app code
- CI hook: blocks contract phase until monitoring confirms zero queries hit old columns

**Sources:** Defacto's 37-migration case study, Google's "Expand and Contract" pattern, Squawk linter limitations.

**Why devs would tweet about it:** Every engineer who has done a zero-downtime migration has written this infrastructure by hand, every single time. Automating the DECOMPOSITION — not just the linting — is the part nobody has cracked.

---

### TOOL-R02: add_request_replay (enhanced)

**One-line:** Records production requests with all dependency interactions into portable cassettes for deterministic local replay.

**Problem:** VCR.py records HTTP but ignores database state. Timetracer (GitHub, ~200 stars) is pre-alpha. Nobody has a production-grade recording system that integrates with FastAPI middleware, handles async context, redacts PII, samples intelligently, and generates self-contained replay files.

**What it generates:**
- `RecorderMiddleware`: captures request/response + all httpx/aiohttp calls + SQLAlchemy queries + Redis commands
- PII redaction pipeline: configurable field patterns (email, phone, SSN, credit card) applied before storage
- Sampling: percentage-based + 100% capture on 5xx + header-triggered manual capture (`X-Record-Request: true`)
- `replay` CLI command: loads cassette, patches all external boundaries, replays exact request with mocked deps
- Diff reporter: compares replay response vs recorded response

**Sources:** Timetracer project, VCR.py limitations, Optibus Playback library.

---

### TOOL-R03: add_chaos_layer (enhanced)

**One-line:** Application-level chaos engineering without Kubernetes/Istio — integrates with existing circuit breakers and feature flags.

**Problem:** Chaos Toolkit runs from OUTSIDE. This runs INSIDE the app and integrates with the circuit breakers (TOOL-022), rate limiters (TOOL-057), and feature flags (TOOL-009) already in the skill. It doesn't just inject faults — it VALIDATES that your defenses work.

**What it generates:**
- `ChaosMiddleware`: latency injection, error injection, connection drops, partial response corruption
- Fault targeting: per-endpoint, per-tenant, per-header, per-time-window
- Integration with circuit_breaker: validates breaker trips at configured threshold
- Integration with feature_flags: chaos profiles controlled via flags for safe canary testing
- Pytest fixtures: `@chaos_scenario(latency_p99=2000, error_rate=0.3)` for resilience test suites
- CI mode: runs chaos scenarios, fails build if defenses don't behave as expected
- Guard: `ENVIRONMENT != "production"` hardcoded — physically cannot enable in prod

**Sources:** Netflix Chaos Monkey, pyresilience (defense only), chaos-toolkit (external only).

---

### TOOL-R04: add_compliance_engine

**One-line:** Declarative data governance at the ORM level — GDPR/CCPA/SOC2 enforcement in code, not dashboards.

**Problem:** Compliance engineering takes 4-8 weeks. Vanta/Drata ($50K+/year) automate the AUDIT but not the CODE. This tool looks at SQLAlchemy models, detects PII fields, and generates the enforcement infrastructure.

**What it generates:**
- Model annotations: `pii=True`, `retention_days=90`, `erasure_cascade=True` as column metadata
- Automatic PII field detection from column names/types (email, phone, ssn, ip_address)
- Data retention enforcer: background job that soft/hard-deletes past retention, with audit log
- Right-to-erasure: `DELETE /compliance/erasure/{user_id}` — cascades across all related tables, anonymizes where FK integrity requires, produces erasure certificate
- Field-level encryption: transparent encrypt/decrypt for PII columns (Fernet/AES-GCM), key rotation
- Access logging: logs every query touching PII-annotated fields
- SOC2 evidence exporter: generates exact artifacts auditors ask for
- GDPR Article 30 "Record of Processing Activities" auto-generated from model annotations
- Integration with audit_log (TOOL-005) and multi_tenancy (TOOL-008)

**Sources:** Multi-Tenant Leakage study (70% of SaaS breaches = implementation gaps), GDPR Article 30 requirements.

**Why devs would tweet about it:** The difference between a 3-month compliance sprint and a one-command generation. ORM-level approach = compliance rules live next to the code they govern.

---

### TOOL-R05: add_api_monetization

**One-line:** Usage-metered billing with Stripe Billing Meters v2 — the complete "API-as-a-Product" stack.

**Problem:** Charging per API call/feature with real-time usage tracking, overage handling, and self-serve dashboards is what companies like Moesif ($50K+/year) exist to solve. Since Stripe's Billing Meters v2 (March 2025), the infrastructure exists natively — but the integration work is still a 2-3 week build.

**What it generates:**
- `MeteringMiddleware`: tracks every API call with endpoint, tenant, timestamp, compute duration, response size
- Metering rules DSL: `meter("gpt-inference", cost_unit="token", per=1000)`
- Stripe Billing Meter sync: batches meter events → Stripe Meter Event API with retry + dead-letter
- Usage dashboard: `GET /billing/usage` (current), `/usage/history`, `/limits` (remaining quota)
- Tier enforcement: 429 when quota exhausted, configurable grace period + overage pricing
- Self-serve: `POST /billing/upgrade`, `GET /billing/plans`
- Usage alerts: webhook/email at 80/90/100% quota
- Revenue analytics (admin): MRR, usage trends, top consumers, churn risk
- Integration with rate_limiting (TOOL-057) for quota-aware limits and multi_tenancy (TOOL-008)

**Sources:** Stripe Meter Events v2 API (2025), Moesif/Amberflo pricing, Stripe's $200B API economy estimate.

**Why devs would tweet about it:** Collapses a $50K/year vendor or 3-week build into a single tool invocation. Stripe Meter v2 integration is especially timely — API launched 2025, docs sparse, most teams haven't figured batching patterns.
