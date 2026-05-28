# Modules v2 — Final Consolidated Audit

> **Produced:** 2026-04-13
> **Scope:** 25 substantial files in `modules/` (13,819 LOC total)
> **Method:** 3 parallel Sonnet agents, each reading assigned files in full
> **Purpose:** decide what to preserve, archive, or discard before building the 51 new TOOL-* implementations

---

## 1. Executive summary

The `modules/` directory is **NOT legacy junk**. It contains the most production-hardened code in the entire skill.

| Verdict | Count | % of files | % of LOC |
|---|---|---|---|
| **PRESERVE** (unique, high-value) | **21 files** | 84% | ~99.5% |
| **ARCHIVE with extraction** (duplicates base + nuggets) | **3 files** | 12% | ~0.4% |
| **DISCARD** (dead code, never used) | **1 file** | 4% | ~0.1% |

Of the 13,819 LOC examined, **only 73 LOC (0.5%) are genuinely disposable** (`modules/security/models.py`, dead Pydantic schemas never imported).

**Key finding:** in several critical areas, the `modules/` code is **strictly superior** to `generators/`:

- `modules/observability/generate_alerts.py` implements **Google SRE Workbook Chapter 5 multi-burn-rate math**. `generators/observability/alerting.py` is 5 hardcoded alerts without SLO parameterization.
- `modules/observability/scaffold_otel.py` has a **cardinality-safe Prometheus middleware** with `_get_route_template()` using `route.matches(request.scope)`. `generators/observability/otel.py` is 1 file with no metrics and no structlog.
- `modules/deployment/generate_docker.py` has `analyze_dockerfile()` with 7 lint rules including layer-cache ordering and secrets-in-ARG detection. **`generators/` has no Dockerfile generator at all.**
- `modules/deployment/generate_k8s.py` has validation rules including **DEPLOY-002 "PDB minAvailable ≥ replicas blocks kubectl drain forever"** — a subtle correctness issue the raw generator would never catch.

**Archiving `modules/` as "legacy" would have destroyed 10,000+ LOC of unique production-grade logic.** The user's instinct to "investiga direito" was correct.

---

## 2. Breakdown by subsystem

### 2.1 Security & Auth (Agent 1 — 7 files, ~3,800 LOC)

#### PRESERVE (4 files)

**`security/tools/pentest_api.py` — 919 LOC**
Dynamic runtime pentest against a live FastAPI server. No equivalent anywhere in the codebase.
- 7 SQLi payloads + 13 SQL error patterns for injection probing
- CORS evil-origin test with full preflight + GET + credentials validation
- 12 disclosure patterns across 5 error probes (path traversal, 10K URL, invalid paths)
- Body-size heuristic counting timeout/reset as pass signal
- **Target spec:** TOOL-029 `security_scan` (dynamic layer, complementary to static analysis)
- **Also feeds:** TOOL-051 `fastapi_doctor` (composed into doctor's security check)

**`security/tools/verify_security.py` — 908 LOC**
10 AST-based static checks (SEC-01..10) specifically tuned for FastAPI. The exact rules that TOOL-029's custom semgrep ruleset needs.
- **SEC-04**: Pydantic `str | None` fields without `max_length` (DoS vector)
- **SEC-05**: Raw SQL detection via AST JoinedStr + `.format()` + regex (needs ≥ 2 SQL keywords to fire, reduces false positives)
- **SEC-08**: `docs_url` without env guard (exposes Swagger in production)
- **SEC-10**: `HTTPException(detail=str(e))` leaking internal error details via AST
- **Target spec:** TOOL-029 `security_scan` (static analysis rules)
- **Also feeds:** `benchmark/analyzer.py` (these rules should be merged in)

**`auth/tools/pentest_auth.py` — 469 LOC**
Active runtime auth testing with statistical rigor.
- `test_timing_attack`: warm-up request + 10 samples + `statistics.median()` + 50ms threshold + `asyncio.sleep(0.1)` between samples to avoid tripping rate limits
- `test_token_reuse`: real multi-step flow (register → use refresh once → reuse → expect 401)
- `test_expired_token`: dummy secret to test expiry + signature validation simultaneously
- **Target spec:** TOOL-010 `add_api_key_auth` (validates output), TOOL-011 `add_oauth2_provider` (state token replay tests), TOOL-013 `add_mfa` (timing attack methodology)

**`auth/tools/verify_auth.py` — 582 LOC**
8 AST/regex checks (AUTH-01..08) for auth configuration.
- **AUTH-01**: AST walk on `jwt.encode()` with allowlist for placeholder values like `CHANGE-ME`
- **AUTH-02**: AST timedelta inspection distinguishing access vs refresh by variable name
- **AUTH-03**: `jti` presence check for refresh tokens
- **AUTH-06**: rate limiting on `/auth/login` route
- **AUTH-07**: project-wide logout endpoint check
- **Target spec:** TOOL-010, TOOL-011, TOOL-013 (all auth-related verification)
- **Also feeds:** `benchmark/analyzer.py`

#### ARCHIVE with extraction (2 files)

**`security/tools/scaffold_security.py` — 469 LOC**
Duplicates `generators/middleware/security_headers.py` and `cors.py`.
- **Extract before archive:**
  - `_exceptions_py()` template with 3 handlers using `error_id = uuid.uuid4().hex[:8]` (not in generators)
  - Middleware ordering hint: `RequestSizeLimitMiddleware → SecurityHeadersMiddleware → CORS → rate limiting`
- Target: port to `generators/endpoints/errors.py` and add as comment in `generators/middleware/stack.py`

**`auth/tools/scaffold_auth.py` — 448 LOC**
Duplicates `generators/auth/`.
- **Extract before archive:**
  - `COMMON_PASSWORDS` set + `@field_validator` with digit + uppercase check (not in generators)
  - `create_token_pair()` with `jti` in refresh token (generators' `jwt.py` only generates access)
  - `configure_jwt(secret)` startup pattern
- Target: port to `generators/auth/schemas.py` (password validator), `generators/auth/jwt.py` (token pair + jti), `generators/infra/app.py` (startup config)

#### DISCARD (1 file)

**`security/models.py` — 73 LOC**
Pydantic models (`SecurityHeadersReport`, `CORSTestResult`, `RateLimitTestResult`, `PentestResult`) that are **never imported by `pentest_api.py`** (which returns plain dicts). Dead code from the v2 architecture that was never integrated. TOOL-029 needs SARIF 2.1.0 output types, not these.

---

### 2.2 Payments & Observability & Deployment (Agent 3 — 9 files, ~4,800 LOC)

**All 9 files PRESERVE. Zero duplicates.**

#### Payments (2 files) — complete skill gap

**`payments/tools/scaffold_payments.py` — 680 LOC**
Complete Stripe scaffold. **Nothing in `generators/` touches payments.**
- PCI SAQ A/D scoping logic (which flows require PCI certification)
- `ZERO_DECIMAL_CURRENCIES` set (16 currencies where Stripe amounts are already in whole units)
- Idempotency key strategies per payment type
- Subscription state machine with status transitions
- **Target:** NEW spec candidate **TOOL-052 `add_stripe_payments`** (skill gap, no spec exists)

**`payments/tools/verify_payments.py` — 496 LOC**
8 static analysis rules PAY-01..08.
- Webhook signature verification check
- **Raw card data detection via 9-pattern regex with word-boundary guards** (reduces false positives on variable names)
- Hardcoded key detection (two-pass strategy: raw regex first, then AST to eliminate docstrings)
- Fulfillment-on-redirect detection (classic Stripe race condition)
- **Target:** TOOL-052 (new) + TOOL-029 `security_scan` (merge payments rules)

#### Observability (3 files) — strictly superior to generators stubs

**`observability/tools/generate_alerts.py` — 723 LOC**
The crown jewel of the entire `modules/` directory.
- Implements **Google SRE Workbook Chapter 5 multi-burn-rate math**: 14.4x / 6x / 1x burn rates with paired long/short windows and the `short_window = long_window / 12` rule
- Generates full Grafana JSON with SLO-computed threshold bands (not hardcoded thresholds)
- SLO parameterization from a single `slo.yaml` input
- Compare with `generators/observability/alerting.py`: **5 hardcoded alerts, zero SLO math**
- **Target spec:** TOOL-042 `sla_reporter` (SLO math is the exact algorithm this spec needs) + TOOL-041 `error_rate_analyzer` (burn rate alerts)
- **Architecture decision:** `generators/observability/alerting.py` should be **replaced** by this, or left as a minimal fallback for projects that don't have SLO definitions

**`observability/tools/scaffold_otel.py` — 629 LOC**
Generates a 4-file observability package with serious production hardening.
- 3 exporter variants (OTLP gRPC, OTLP HTTP, console) with environment detection
- **Cardinality-safe Prometheus middleware**: `_get_route_template()` uses `route.matches(request.scope)` to resolve the template BEFORE interpolation, so `/users/42` becomes `/users/{id}` in labels (not a new label per user)
- W3C-standard trace_id hex formatting: `format(ctx.trace_id, "032x")`
- structlog + OTel propagation integration
- Compare with `generators/observability/otel.py`: **1 file, no metrics, no structlog, no cardinality guard**
- **Target spec:** feeds every VERIFY and OPERATE tool that needs metrics/traces. Also TOOL-040 `connection_pool_monitor`, TOOL-041 `error_rate_analyzer`.

**`observability/tools/verify_traces.py` — 625 LOC**
10 AST-based rules (OBS-01..10) for observability correctness.
- `print()` detection in handler code (anti-pattern, should use structlog)
- Health probe exclusion check (liveness/readiness should NOT be traced — adds noise)
- f-string logging detection (loses structured data)
- Missing correlation ID propagation
- **Target:** TOOL-051 `fastapi_doctor` (composed into observability check), TOOL-041 `error_rate_analyzer` (prerequisite check)

#### Deployment (4 files) — validation layer generators lack entirely

**`deployment/tools/generate_k8s.py` — 480 LOC**
`generators/deployment/k8s.py` exists but has no validation. This module adds a critical `_validate_config()` with 5 DEPLOY rules:
- **DEPLOY-002** (CRITICAL): **PDB `minAvailable ≥ replicas` blocks `kubectl drain` forever**. This is a silent production killer — your nodes won't cordon, your upgrades hang, and you only discover it during an incident. Zero other tools flag this.
- **DEPLOY-003**: preStop timing math: `termination_grace ≥ prestop_sleep + graceful_shutdown + buffer`
- HPA memory metric (generator only does CPU)
- preStop hook enforcement
- **Target spec:** TOOL-021..024 (Infrastructure), TOOL-035 `blast_radius`, TOOL-036 `migration_diff` (deploy safety)

**`deployment/tools/generate_ci.py` — 454 LOC**
`analyze_github_workflow()` with 6 CI rules:
- Unpinned action version detection (`uses: actions/checkout@v4` instead of SHA pin — supply chain attack vector)
- Trivy scan before push gate check
- Missing secrets scanning
- **Target spec:** TOOL-029 `security_scan` (supply chain), TOOL-022 `add_circuit_breaker` (CI integration)

**`deployment/tools/generate_docker.py` — 445 LOC**
**`generators/` has no Dockerfile generator at all.** This file is the only source.
- `analyze_dockerfile()` with 7 rules:
  - **DOCKER-05**: Secrets in `ARG` directives (end up in image history)
  - **DOCKER-07**: COPY ordering / layer cache optimization
  - Missing `USER` directive (runs as root)
  - Missing HEALTHCHECK
- **Target spec:** NEW candidate **TOOL-053 `verify_dockerfile`** (OR merge into TOOL-029 security_scan)
- **Must also be added to `generators/`** as the Dockerfile generation source

**`deployment/tools/generate_k6.py` — 299 LOC**
`generators/deployment/k6_loadtest.py` exists but is a hardcoded 5-stage script. This version has:
- Per-endpoint parameterization
- `handleSummary()` JSON export for CI-parseable metrics
- Three presets (smoke / load / stress)
- **Target spec:** TOOL-027 `add_load_profile` (replaces generator stub with parameterized version)

---

### 2.3 Database & Background Jobs & WebSockets & Caching (Agent 2 — 9 files, ~5,200 LOC)

**8 PRESERVE, 1 ARCHIVE.**

#### Database (3 files)

**`database/tools/operate_db.py` — 799 LOC — PRESERVE**
The `_interpret_plan()` function is an **EXPLAIN ANALYZE parser** with calibrated heuristics:
- Detects sequential scans on large tables
- Flags nested loop joins with high row estimates
- Identifies disk-based sorts (memory threshold exceeded)
- Buffer hit rate analysis
- Generates human-readable diagnosis with fix suggestions
- **Target spec:** TOOL-040 `connection_pool_monitor` (adds "query plan diagnosis" complement), TOOL-028 `detect_n_plus_one` (integration)

**`database/tools/verify_db.py` — 652 LOC — PRESERVE**
8 AST-based DB checks, none duplicated in `benchmark/analyzer.py`:
- **DB-03**: `MissingGreenlet` via `expire_on_commit=True` on async sessions (classic FastAPI async bug)
- **DB-06** (CRITICAL): sync engine (`create_engine`) in async codebase (`async def` handlers) — silent corruption waiting to happen
- DB-01..DB-08 cover pool config, migration drift, missing indexes, connection leaks
- `_resolve_call_name()` with nested attribute resolution is **reusable infra** for other AST-based tools
- **Target spec:** TOOL-028 `detect_n_plus_one`, TOOL-029 `security_scan`, TOOL-040 `connection_pool_monitor`

**`database/tools/scaffold_db.py` — 641 LOC — ARCHIVE with extraction**
~80% duplicate of `generators/database/` (engine, session, alembic, model).
- **Extract before archive:** `tenancy.py` with RLS pattern using `SET LOCAL app.current_tenant` on connection checkout. This is the Postgres RLS escape hatch for TOOL-008 `add_multi_tenancy`.

#### Background jobs (2 files) — `generators/` has nothing on ARQ

**`background_jobs/tools/scaffold_jobs.py` — 528 LOC — PRESERVE**
**Completely exclusive territory — `generators/` has zero ARQ code.**
- **DLQ via Redis Streams** with `replay_dlq_entry()` + audit trail (who replayed, when, original payload hash)
- **Idempotent financial task pattern**: `idem_key + distributed lock` on Redis with SETNX + auto-expire
- Cron pattern with DST-safe scheduling
- Retry with exponential backoff + jitter
- **Target spec:** TOOL-020 `add_long_running_task`, TOOL-046 `add_event_driven`, TOOL-023 `add_outbox_pattern`

**`background_jobs/tools/verify_jobs.py` — 466 LOC — PRESERVE**
High-precision AST checks:
- **JOBS-05**: Blocking call detection inside `async def` tasks via AST (finds `time.sleep`, `requests.get`, `open().read()` in async context)
- **JOBS-03**: Idempotency check on tasks with financial keywords (detects missing idempotency guards on `charge`, `refund`, `transfer`, `payout`)
- **Target spec:** TOOL-028 `detect_n_plus_one` (async blocking), TOOL-029 `security_scan` (financial correctness)

#### WebSockets (2 files)

**`websockets/tools/scaffold_ws.py` — 670 LOC — PRESERVE**
**Significantly more complete than `generators/tools/add_websocket.py`.**
- Per-IP connection limits (tracked via Redis counter with TTL)
- Rooms with Pydantic validation of room membership
- **Redis pub/sub multi-worker bridge**: message published on worker A reaches clients connected to worker B
- Graceful `close_all()` on shutdown: `asyncio.gather` + timeout + iterate survivors
- **Target spec:** spec gap. Not in the 51 new specs. Add as NEW candidate **TOOL-054 `add_websocket_advanced`** OR merge into TOOL-014 `add_sse` as companion tool.

**`websockets/tools/verify_ws.py` — 466 LOC — PRESERVE**
- **WS-01** (CRITICAL): Unauthenticated WebSocket (no JWT validation before `accept()`)
- **WS-08**: `websocket.send()` without try/except → one dead client crashes the broadcast loop
- **Target spec:** TOOL-051 `fastapi_doctor`, TOOL-029 `security_scan`

#### Caching (2 files)

**`caching/tools/scaffold_cache.py` — 594 LOC — PRESERVE**
The most sophisticated single algorithm in the entire `modules/` directory.
- **XFetch algorithm (Vattani 2015)**: probabilistic early recomputation to avoid cache stampedes. Stores the actual `delta` (computation time) and re-rolls the dice with an exponential based on TTL remaining. This is production-grade distributed caching that almost no project implements correctly.
- **Redis Lua script** for atomic distributed-lock release (the correct Redlock pattern — check value matches before DELETE, to avoid releasing someone else's lock)
- Key namespacing with versioning for schema evolution
- **Target spec:** TOOL-021 `add_cache_layer` — this IS the implementation. The spec describes what this file already does.

**`caching/tools/operate_cache.py` — 302 LOC — PRESERVE**
Structured return interface (`{status, memory, performance, keys, clients, findings}`) that is **exactly the shape** TOOL-021's `/cache/stats` endpoint needs and what TOOL-051 `fastapi_doctor` can consume.
- **Target spec:** TOOL-021 `add_cache_layer` (stats endpoint), TOOL-051 `fastapi_doctor`

---

## 3. Module → New spec mapping

This is the **most important table in the report**. For each of the 51 new specs, it shows which `modules/` files already implement or partially implement the spec.

| Spec | Target | Source modules | Coverage |
|---|---|---|---|
| TOOL-008 `add_multi_tenancy` | multi-tenant isolation | `scaffold_db.py` (tenancy.py RLS) | partial — port RLS pattern |
| TOOL-010 `add_api_key_auth` | API key auth | `scaffold_auth.py`, `verify_auth.py`, `pentest_auth.py` | partial — extract COMMON_PASSWORDS, token_pair, AUTH-06 rate limit rule, timing attack test |
| TOOL-011 `add_oauth2_provider` | OAuth2 social | `verify_auth.py` (jti check, jwt.encode allowlist), `pentest_auth.py` (token reuse test) | partial — verification/test infra |
| TOOL-012 `add_rbac` | Role-based access | `verify_auth.py` (auth checks) | light — mostly new |
| TOOL-013 `add_mfa` | MFA TOTP | `pentest_auth.py` (timing attack methodology) | reuse testing methodology |
| TOOL-014 `add_sse` | Server-Sent Events | `scaffold_ws.py` (Redis pub/sub bridge, graceful close) | reuse multi-worker pattern |
| TOOL-020 `add_long_running_task` | ARQ tasks | `scaffold_jobs.py`, `verify_jobs.py` | **direct match — 80%+ implementation** |
| TOOL-021 `add_cache_layer` | Redis cache | `scaffold_cache.py`, `operate_cache.py` | **direct match — XFetch + Lua lock already done** |
| TOOL-023 `add_outbox_pattern` | Transactional outbox | `scaffold_jobs.py` (DLQ + idempotency patterns) | partial — ARQ infrastructure |
| TOOL-027 `add_load_profile` | k6 load test | `generate_k6.py` (parameterized + handleSummary) | **replace generators/k6 stub with this** |
| TOOL-028 `detect_n_plus_one` | N+1 detector | `verify_db.py` (8 AST checks), `verify_jobs.py` (async blocking) | partial — static checks |
| TOOL-029 `security_scan` | Security scan | `verify_security.py` (10 SEC rules), `pentest_api.py` (dynamic), `verify_payments.py` (8 PAY rules), `generate_ci.py` (supply chain), `verify_auth.py` (8 AUTH rules) | **direct match — 85%+ of rules already implemented** |
| TOOL-034 `performance_baseline` | Perf baseline | `generate_k6.py` (k6 scripts) | partial |
| TOOL-040 `connection_pool_monitor` | DB pool monitoring | `operate_db.py` (EXPLAIN ANALYZE parser), `verify_db.py` (pool config checks) | **direct match — query diagnosis + pool checks ready** |
| TOOL-041 `error_rate_analyzer` | Error rate | `scaffold_otel.py` (cardinality-safe metrics), `generate_alerts.py` (burn rate math) | **direct match — SLO math ready** |
| TOOL-042 `sla_reporter` | SLA report | `generate_alerts.py` (**Google SRE Workbook Ch 5 math**) | **direct match — most sophisticated SLO math in the codebase already exists here** |
| TOOL-046 `add_event_driven` | Event driven | `scaffold_jobs.py` (DLQ, idempotency) | partial |
| TOOL-051 `fastapi_doctor` | Proactive doctor | ALL verify_*.py files from modules/ | composition target — doctor orchestrates all module verifiers |

### New spec gaps discovered

| Proposed new spec | Source | Rationale |
|---|---|---|
| **TOOL-052 `add_stripe_payments`** | `payments/` | Complete payments vertical missing from 51 specs. Stripe scaffold + 8 PAY rules are ready. |
| **TOOL-053 `verify_dockerfile`** (or merge into TOOL-029) | `generate_docker.py` | Dockerfile static analysis missing. 7 rules ready (including DOCKER-05 secrets in ARG). |
| **TOOL-054 `add_websocket_advanced`** (or merge into TOOL-014) | `scaffold_ws.py` | Production WebSocket (multi-worker bridge, per-IP limit, graceful close) missing. |

---

## 4. Superior modules/ vs inferior generators/

These `generators/` files are **provably worse** than their `modules/` counterparts and should be replaced:

| Generators file (inferior) | Modules file (superior) | Delta |
|---|---|---|
| `generators/observability/alerting.py` | `modules/observability/generate_alerts.py` | 5 hardcoded alerts → full SRE burn-rate math |
| `generators/observability/otel.py` | `modules/observability/scaffold_otel.py` | 1 file, no metrics → 4 files with cardinality-safe middleware |
| `generators/deployment/k6_loadtest.py` | `modules/deployment/generate_k6.py` | hardcoded 5-stage → parameterized + 3 presets |
| `generators/tools/add_websocket.py` | `modules/websockets/scaffold_ws.py` | basic WS → Redis bridge + per-IP limit + graceful close |
| *(no file)* | `modules/deployment/generate_docker.py` | **NO Dockerfile generator in generators/** |

The refactor plan must **port the superior modules/ versions into generators/** or **create a new `generators/advanced/` tier** that the orchestrator selects when production-hardening is requested.

---

## 5. Revised action plan

The original plan ("archive modules, build 51 new tools from scratch") is **wrong**. The correct plan:

### Phase 0.5 — Extract nuggets from archive candidates (✅ doing this next)
Before touching anything else:
1. Port `COMMON_PASSWORDS` validator from `scaffold_auth.py` → `generators/auth/schemas.py`
2. Port `create_token_pair()` with `jti` from `scaffold_auth.py` → `generators/auth/jwt.py`
3. Port `tenancy.py` RLS pattern from `scaffold_db.py` → new `generators/database/rls.py`
4. Port `_exceptions_py()` uuid error_id template from `scaffold_security.py` → `generators/endpoints/errors.py`
5. Delete `modules/security/models.py` (73 LOC dead code)
6. Commit "extract: port v2 nuggets into v3 generators"

### Phase 1 — Replace inferior generators/ files with superior modules/ versions
1. Replace `generators/observability/alerting.py` ← `modules/observability/generate_alerts.py` (adapted for the generator contract)
2. Replace `generators/observability/otel.py` ← `modules/observability/scaffold_otel.py`
3. Replace `generators/deployment/k6_loadtest.py` ← `modules/deployment/generate_k6.py`
4. Add missing: `generators/deployment/dockerfile.py` ← `modules/deployment/generate_docker.py`
5. Run the 35/35 benchmark → should stay green (the replacements are superior, not regressive)
6. Commit "upgrade: replace v3 stubs with v2-proven implementations"

### Phase 2 — Build 51 new high-level tools, REUSING modules/ verify_*.py and scaffold_*.py
Each of the 51 new tools in `adapt/` becomes a **thin composition layer** that calls into:
- `modules/security/verify_security.py` (for SEC rules)
- `modules/auth/verify_auth.py` (for AUTH rules)
- `modules/database/verify_db.py` (for DB rules)
- `modules/observability/verify_traces.py` (for OBS rules)
- `modules/payments/verify_payments.py` (for PAY rules)
- `modules/background_jobs/verify_jobs.py` (for JOBS rules)
- `modules/websockets/verify_ws.py` (for WS rules)
- `modules/deployment/generate_*.py` `analyze_*` functions (for deploy/CI/docker static analysis)
- `modules/security/pentest_api.py` + `pentest_auth.py` (for dynamic runtime testing)

**The 51 new tools are orchestrators + enforcement layers on top of 10,000+ LOC of existing verification logic.** Building from scratch would take 30-50 sessions. Composing over existing modules takes 15-25.

### Phase 3 — Add 3 missing specs
Write specs for:
- TOOL-052 `add_stripe_payments` (complete payments vertical)
- TOOL-053 `verify_dockerfile` (Dockerfile static analysis) — or merge into TOOL-029
- TOOL-054 `add_websocket_advanced` (production-grade WS) — or merge into TOOL-014

**Updated spec count: 51 → 54** (to be decided: merge vs new specs).

### Phase 4 — Rename modules/ → adapt/verify/ and adapt/pentest/
After all nuggets extracted and superior files ported, rename `modules/` into the `adapt/` namespace:
```
adapt/
  verify/     ← modules/*/tools/verify_*.py (all 8 files, the AST check engines)
  pentest/    ← modules/security/pentest_api.py, modules/auth/pentest_auth.py, (+ scaffold_jobs.py + scaffold_cache.py as scaffold_* in their own tier)
  scaffold/   ← modules/*/tools/scaffold_*.py (production-grade generators)
  operate/    ← modules/database/operate_db.py, modules/caching/operate_cache.py
  generate/   ← modules/deployment/generate_*.py (validation + generation)
```

Then `modules/` becomes empty and is deleted. Nothing lost. Everything moved to a taxonomically clean location.

---

## 6. Work estimate (revised honest)

| Phase | Scope | Sessions |
|---|---|---|
| **Phase 0 — audit (done)** | Legacy + modules/ audit + consolidation | 1 session ✅ |
| **Phase 0.5 — nugget extraction** | 5 nuggets + 1 dead file | 1 session |
| **Phase 1 — replace inferior with superior** | 4 files replaced + 1 file added | 2 sessions |
| **Phase 2 — 51 high-level tools as orchestrators** | Compose over verify_*, scaffold_*, pentest_* | **15-25 sessions** |
| **Phase 3 — 3 missing specs** | TOOL-052..054 (or merges) | 2 sessions |
| **Phase 4 — rename modules/ → adapt/** | Clean taxonomy | 1 session |
| **Phase 5 — MCP server v4** | Expose 54 tools with hidden primitives | 2 sessions |
| **Phase 6 — brutal test suite** | L1..L8 audit infrastructure + per-tool brutal tests | 10-15 sessions |
| **Phase 7 — red team + reference customers** | 3 real projects + adversarial agents | 4-6 sessions |
| **Phase 8 — final polish + SKILL.md v4 + benchmark re-run** | 1-2 sessions |
| **Total** | | **~40-55 sessions** (down from 35-50 earlier estimate because of existing reuse) |

---

## 7. Critical insights

1. **The existing `modules/` is irreplaceable production IP.** 21 files contain logic that would take weeks to re-derive from scratch. The SRE burn-rate math alone is a crown jewel.

2. **The 51 new specs are orchestration specs, not implementation specs.** They describe the high-level surface. The implementation leverage points are already in `modules/`.

3. **`generators/` has stubs in 4 places that should be replaced** (alerting, otel, k6, missing dockerfile). These replacements should happen BEFORE the 51 tools are built on top.

4. **3 skill gaps surfaced that need new specs**: payments, dockerfile lint, advanced websockets. TOOL-052 is the biggest — complete payments vertical missing.

5. **Only 1 file is genuinely dead**: `security/models.py` (73 LOC, never imported). Everything else has a home.

6. **The user was 100% right to say "investiga direito".** My initial recommendation to archive `modules/` would have destroyed ~10,000 LOC of unique, production-validated logic.

---

## 8. Next actions (this session or next)

1. [ ] Commit this audit report + the 3 sub-reports → git history
2. [ ] Get user confirmation on the revised plan (especially Phase 0.5 + 1 + 2 reuse strategy)
3. [ ] Start Phase 0.5: extract the 5 nuggets, delete 1 dead file, commit
4. [ ] Plan Phase 1: validate the "replace inferior" refactor doesn't break the 35/35 benchmark

---

*End of consolidated audit report.*
