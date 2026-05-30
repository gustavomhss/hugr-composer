# Round-5 + Round-6 — Canonical Triage

**Date:** 2026-05-30
**Inputs:** Round-5 (16 jurors, post-#77 main `636ab57`) + Round-6 (16 jurors, same base)
**Total findings emitted by jurors:** ~160 across 32 audits
**Purpose:** dedupe, classify, group into anti-patterns; produce the inputs for fix-waves (B) and contract rules (D).

This document supersedes individual juror reports for fix-prioritization. It does NOT replace them as evidence — each finding here cites its source juror (e.g. `R5-O4-C5`, `R6-S11-F2`).

---

## 1. Classification taxonomy

Every finding lands in exactly one bucket:

| Bucket | Definition | Action |
|---|---|---|
| **B (BLOCKER)** | Exploitable in shipped code OR product-claim contradicted by emitted code. Cannot ship. | Fix-PR before any external eval. |
| **R (REAL — fix soon)** | Real defect, real impact, not 1-step exploit. | Fix-PR in current sprint. |
| **L (LOW — defer)** | Real but cosmetic / docs-only / non-default path. | Backlog. |
| **D (DUP)** | Same root cause as another finding already counted. | Roll-up reference only. |
| **F (FALSE-POSITIVE)** | Juror misread code; behavior is correct as-is. | Note + drop. |

A finding can additionally be tagged **P{n}** — belongs to anti-pattern cluster n (see §3).

---

## 2. Findings by tool/surface (the B output)

### 2.1 Compose layer — auth_access (CRITICAL surface)

| Finding | Bucket | Pattern | Note |
|---|---|---|---|
| R5-O4-C1 (social_login OAuth state CSRF) | **B** | P1 | TODO not closed; state generated then discarded |
| R5-O4-C2 (Apple id_token sig not verified) | **B** | P1 | ATO direct path — **CLOSED** in `fix/r5-o4-c2-apple-id-token-verify` (RS256 + JWKS + iss/aud/exp enforced) |
| R5-O4-C3 (GitHub `email_verified=bool(email)`) | **B** | — | Cross-provider takeover |
| R5-O4-C4 (Apple empty provider_user_id squat) | **B** | — | First-attacker-wins |
| R5-O4-C5 (Passkey client-supplied `user_id`) | **B** | P2 | No auth dep on `/register/begin`+`/complete` |
| R5-O4-C6 (SMS OTP no verify-rate-limit) | **B** | — | 10^6 brute in minutes |
| R5-O4-C7 (DPoP proof not bound to access token) | **B** | — | RFC 9449 §4.2 + cnf/jkt absent |
| R5-O4-C8 (DPoP+signing in-process nonce stores) | **B** | P3 | Multi-worker replay |
| R5-O4-H1..H7 (DPoP typ, api_key timing oracle, passkey challenge dict, OTP toll fraud, plaintext OTP, sig canonicalization) | **R** | P3 mostly | Wave-2 |
| R5-O1-F1 (BOLA fail-open default) | **B** | — | Flip `STRICT_MODE=True` |
| R5-O1-F2 (Tenant INSERT cross-tenant via explicit tenant_id) | **B** | — | Listener doesn't cover insert |
| R5-O1-F3 (Tenant router unmounted on api/routes/__init__.py) | **R** | — | Copy discovery from add_model |
| R5-O1-F6 (Slug-knowledge signup) | **R** | — | At minimum loud warning |
| R5-O1-F4/F5/F7..F13 | **L** | — | Dead-code, doc drift, mostly cosmetic |
| R5-S2 — Cedar/OPA/feature_flags F1..F22 | mixed | P2,P5 | F1/F15/F18 = **B**; F7/F13/F14 = **R**; rest L |
| R6-S1-F1 (password-reset NOT single-use) | **B** | — | JWT stateless, no consume table |
| R6-S1-F2 (recovery timing oracle) | **R** | — | Symmetric dummy-send needed |
| R6-S1-F3 (reset-password no rate-limit) | **R** | — | Add limiter |
| R6-S1-F4 (email-change no re-auth, no old-addr notify) | **R** | — | Wave-2 |
| R6-S2-F1+F2+F3+F9 (jti blocklist TODO, family-invalid TODO, refresh race, logout-not-fence) | **B** | P1 | One PR closes 4 |
| R6-S2-F5 (RS256 generator accepts symmetric key) | **R** | — | Allowlist on `generate_jwt` |
| R6-S2-F11 (refresh tokens not hashed) | **B** | — | Model + migration needed |
| R6-S2-F12 (CSRF `!=` not constant-time + not wired on refresh) | **R** | — | Compose-side wiring missing |

### 2.2 Compose layer — crud_data

| Finding | Bucket | Pattern | Note |
|---|---|---|---|
| R5-O2-D1 (versioning router wired to wrong path) | **B** | — | api/routes/__init__.py variant |
| R5-O2-D2 (versioning endpoints no auth, no tenant) | **B** | P2 | 5 routes; body-supplied author_id |
| R5-O2-D3 (content_type ignored in versioning lookup) | **B** | — | Cross-type collisions |
| R5-O2-D4 (TOCTOU on version_number + published) | **B** | — | No SELECT FOR UPDATE |
| R5-O2-D5 (`append-only` claim false) | **B** | P4 | Lifecycle mutates rows |
| R5-O2-D6 (event store is in-memory dict) | **B** | P3,P4 | Per-worker, vanishes on restart |
| R5-O2-D7 (event store endpoints no auth) | **B** | P2 | Append/read any aggregate |
| R5-O2-D8 (bulk PATCH mass-assignment) | **B** | P5 | tenant_id/owner_id escape |
| R5-O2-D9 (idempotency-key global namespace) | **B** | — | Cross-tenant cache replay |
| R5-O2-D10 (search GIN index unused) | **R** | — | Perf claim false |
| R5-O2-D11 (bulk_delete rolls back outer tx) | **B** | — | Session corruption |
| R5-O2-D12 (idempotency init at module import) | **R** | P6 | Lifespan path needed |
| R5-O2-D13..D21 | mostly **L** | — | Doc gaps, encoding, edge cases |
| R5-S1-F1 (audit endpoints no auth) | **B** | P2 | — |
| R5-S1-F2 (audit actor caller-controlled) | **B** | P2 | — |
| R5-S1-F3 (audit export 500 on default since_seq=0) | **R** | — | One-line guard |
| R5-S1-F4 (audit weak default HMAC secret in signature) | **R** | — | Remove default |
| R5-S1-F5 (audit purely in-memory) | **B** | P3,P4 | Adapter ships InMemory |
| R5-S1-F6 (S3 presign confirm path no magic-byte) | **B** | P4 | "Never trusts content-type" claim false |
| R5-S1-F7 (virus 451 dead code) | **B** | P4 | Test passes as grep only |
| R5-S1-F8 (PresignedUploadResponse `stored_key` leak) | **R** | — | Round-5 + Round-6 dup |
| R5-S1-F9..F11 (soft_delete bypasses via update/create) | **R** | — | Patch CRUDBase.update too |
| R5-S4-F1 (bulk_delete tx corruption) | **D** of R5-O2-D11 | — | — |
| R5-S4-F6 (CSV formula injection on export) | **B** | — | Prefix `=+-@\t\r` |
| R5-S4-F10 (tenant_id fail-open via `except: pass`) | **B** | P7 | Silent NULL inserts |
| R5-S4-F7 (CSV formula injection on import) | **R** | — | Stored injection chain |
| R5-S4-F2,F3,F4,F5,F8,F9 | **L/R** | — | Quality / config |
| R5-S8 search-deep F1..F4 | **R** | — | NUL → 500, LIKE wildcard bleed, rank cursor drops ties, dead sort param |

### 2.3 Compose layer — infrastructure (financial + external)

| Finding | Bucket | Pattern | Note |
|---|---|---|---|
| R5-O3-F1 (notifications no auth, IDOR via query param) | **B** | P2 | — |
| R5-O3-F2 (notifications `NotImplementedError` get_session) | **B** | — | Crash on first call |
| R5-O3-F3 (refund flow never calls Stripe) | **B** | — | Confirmed by R5-S7-S03 also |
| R5-O3-F4 (refund no ownership of payment_id) | **R** | — | Latent until F3 fixed |
| R5-O3-F5 (Stripe webhook no event-id dedup) | **R** | — | 3/3 handlers |
| R5-O3-F6 (refund flow secretly depends on checkout config) | **R** | — | Cross-tool prereq |
| R5-O3-F7 (ML registry race on first-load) | **R** | P3 | Lock or pre-load |
| R5-O3-F8 (ML loader SSRF + no size cap) | **B** | — | urllib.request.urlretrieve any URL |
| R5-O3-F9 (notifications NOTIFICATION_CHANNELS dead config) | **R** | P4 | Channel-order claim false |
| R5-O3-F10 (ML health logic OR bug) | **R** | — | Lies under load |
| R5-O3-F11..F13 | **L** | — | Idempotency key shape, dead imports, monotonicity |
| R5-S7 (stripe deep) duplicates of R5-O3-F3 + new R5-S7-01 (webhook secret default `""`) | **B** | — | One PR closes both |
| R5-S7-02 (subscription endpoints 500 on empty secret) | **B** | — | Move `get_stripe_billing()` inside try |
| R5-S7-09 (`REFUND_MAX_AMOUNT_CENTS = 100_000_00` typo) | **R** | — | One char |
| R5-S5 (observability) F1 cardinality, F4 redactor blind, F9 sampler dead, F10 no traceparent, F6 correlation_id never wired | **B/R** | P4 mostly | Marketing claims dead |
| R5-S6 (health/diag) F1 DSN leak, F2 bucket leak, F3 SVG XSS, F4 replay reuses Auth, F5 mem buffer, F6 dead config, F7 webhook unsigned | mixed **B/R** | P2,P4 | — |
| R5-S9 (security middleware) Sentinel SSRF hostname blind (R5-S01), CMD FP storm (R5-S03), DLP `@sensitive` dead (R5-S09), IBAN overfire (R5-S10), CSRF `secure=False` (R5-S19), CSRF default secret (R5-S20), honeypot tag in /docs (R5-S14) | mixed **B/R** | P4 | — |
| R5-S10 (req hardening) CORS wildcard+creds crash (F1), `/cors/config` unauth leak (F3), secret rotation race (F5), Vault re-instantiated (F7), sanitize_html fallback only escapes (F10), JSON-bomb (F11), fingerprint anonymous collision (F15), fingerprint response cache no TTL align (F16) | mostly **B** | P2,P3 | — |
| R6-O1 (rate limit) F1..F25 — adaptive_throttle is marketing only (F9/F10), proxy IP blind everywhere (F2/F11), inconsistent fail-open vs fail-closed (F18/F25), unsafe Redis lock (F23), unbounded events list (F4) | mostly **B/R** | P1,P3,P4 | — |
| R6-S4 (jobs) F4 zero DLQ all tools, F8 /scheduler/jobs no auth (next_steps lies), F9 /tasks/* no auth | **B** | P1,P2,P4 | — |
| R6-S5 (scheduling) F1 multi-worker dup fire, F2 RedisJobStore hardcoded localhost, F4 `/scheduler/jobs` no auth | **B** | P2 | — |
| R6-S6 (storage) F1+F5+F6 `add_s3_storage` unauth full CRUD on bucket, F4 `stored_key` leak (dup), F7 prefix injection | **B** | P2 | Most exploitable in catalog |
| R6-S7 (compliance) F1 erasure soft-only, F2 cascade column-name match, F3 silent failure cert, F6 no consent system, F8 retention only purges own table, F11 encrypt returns plaintext + test contradicts | **B** | P4 | — |
| R6-S9 (api versioning) F1 @deprecated never emits headers, F2 Sunset ISO violates RFC 8594, F6 /deprecations no auth | **B/R** | P2,P4 | — |
| R6-S10 (db adapters) F2 replica unbounded pool, F3 no read-after-write, F5 Prometheus alert divisor `1` (alerts permanently firing in every deploy), F6 search_path injection in KNOWLEDGE.md | **B** | — | F5 is one-line |
| R6-S11 (deploy) F1 K8s same probe endpoint, F2 GracefulShutdown NameError, F3 K8s adapt template missing hardening, F4 /health/deep unauth + str(exc) leak | **B** | P2 | F2 crashes any install |
| R6-S12 (honesty) F1 sentinel 24h-auto-transition claim, F3 no contract rule audits notes, F4 social_login warnings-in-notes, F5 audit_log "ledger" but in-memory | **B/R** | P4 | F3 is the meta-fix |

### 2.4 Engine / kit infra (mostly clean)

| Finding | Bucket | Pattern | Note |
|---|---|---|---|
| R5-S12-F1 (`ALWAYS_VISIBLE_TOOL_NAMES` stale) | **B** | — | One-line fix; discovery tools currently hidden |
| R5-S12-F2 (dead code in `_load_mcp_tool_from_source`) | **L** | — | Future-proofing |
| R5-S12-F3 (test_paths wrong for dir-form) | **L** | — | Cosmetic; no consumer |
| R6-O2-O2-1 (GracefulShutdownAdapter on_event no-op under lifespan) | **B** | P6 | Decorator dead |
| R6-O2-O2-2 (bulk_ops Redis init at module-import) | **B** | P6 | Round-5 unfixed |
| R6-O2-O2-3 (tests bypass lifespan — green tests, broken prod) | **B** | — | Conftest fix |
| R6-O2-O2-4 (TenantMiddleware ordering breaks ContextVar) | **R** | — | — |
| R6-O2-O2-5 (no canonical middleware insertion anchor) | **R** | — | Introduce hooks |
| R6-O2-O2-6..O2-11 | **R/L** | — | Substring sentinels, idem cache pool, etc. |
| R6-O3 (pydantic) P1 systemic no-`extra="forbid"`, P2 Passkey credential dict[Any], P3 stored_key leak (Round-5 dup), P4 ORM-leak surface across 15 Public schemas, P5 EmailStr-imported-but-str, P7 DomainEvent fake discriminator, P8 push token in Read schema + mutable default, P16 protected_namespaces | mostly **B/R** | P5 | One systemic pass closes 22 tools |
| R6-O4 (alembic) A1 down_rev=0001 doesn't exist, A2 refactor_model `down_revision=None`, A3 CREATE INDEX CONCURRENTLY guidance-only, A4 _write_and_replace bypasses render contract, A5 hard-codes FK to "users.id", A6 lex-last head, A10 migration_diff over-flags, A11 PG-only types unguarded | **B/R** | P4,P6 | — |

### 2.5 Generators / scaffolding

| Finding | Bucket | Note |
|---|---|---|
| R6-S2 surface (generators/auth/) — all jti/refresh issues | **B** | Generator-level, not adapt-level |
| R6-S10-F1 pool_timeout divergence between generators | **R** | Two paths produce different code |
| R6-S11-F5 extract_service Dockerfile root + no HEALTHCHECK + broken `$port` exec form | **B** | Footgun shipped |

---

## 3. Anti-pattern clusters (the D inputs)

A finding clusters here if it shares root cause with ≥3 others. The goal: each pattern → one contract rule that makes the whole class unshippable.

### P1 — TODO/dead code shipped as feature (≥8 occurrences)

Templates ship `# TODO`/`# FIXME` in security-critical paths; the documented feature doesn't exist at runtime.

Citations:
- R6-S2-F1/F2/F9 — jti blocklist TODO, family-invalidation TODO, logout fence TODO
- R5-O4-C7 — DPoP `bind_access_token` dead code with wrong formula
- R6-O1-F9 — adaptive_throttle `cost_weight` never called
- R5-S2-F7 — feature_flags invalidation listener commented out
- R6-S4-F4 — DLQ documented but absent in all 4 tools
- R5-O3-F3 — refund flow never calls Stripe

**Proposed rule B0.10 — `no_dead_security_features`:**
AST-scan templates under `auth_access/`, `infrastructure/` security-tagged tools, and any template imported from primitive `RequestGuard`/`SessionStore`. If the template contains `# TODO`, `# FIXME`, or `pass  # placeholder` patterns AND the tool's `notes`/description claims the corresponding feature, REJECT. Bypass: tool sets `_FEATURE_INCOMPLETE = True` in `__init__.py` and `warnings=` (not `notes=`) lists the gap.

Tools impacted: ~12. Findings closed: ~8 BLOCKER + 4 REAL.

---

### P2 — Admin/diagnostic routes lack authentication (≥15 occurrences)

Routes that operate on cross-user/cross-tenant resources, scheduling, debugging, or storage admin lack any `Depends(get_current_user)` or `require_superuser` guard.

Citations:
- R5-O2-D2 (versioning 5 routes), D7 (event store)
- R5-S1-F1 (audit log append + verify + export)
- R5-S2-F1 (Cedar `/authz/check`), F15 (OPA `/authz/opa/check`), F17 (OPA health)
- R5-O3-F1 (notifications routes)
- R5-S6-F1 (`/health/deep`), F2 (`/health/map`)
- R5-S10-F3 (`/cors/config`)
- R6-S4-F8 (`/scheduler/jobs` — next_steps lies "requires auth")
- R6-S4-F9 (`/tasks/*` POST+GET+DELETE)
- R6-S5-F4 (scheduling `/scheduler/jobs` second variant)
- R6-S6-F1/F5/F6 (`add_s3_storage` unauth GET/DELETE/PUT)
- R6-S9-F6 (`/deprecations`)
- R6-S11-F4 (`/health/deep` adapt variant)

**Proposed rule B0.11 — `admin_routes_require_auth`:**
AST-scan `*route*.py.tmpl`. For each `@router.<verb>(path=...)` decorator, if `path` matches the regex
```
^(/api/v\d+)?/(admin|debug|scheduler|tasks|deprecations|authz|storage|health/(deep|map)|cors/config|events|event-store|audit-logs|notifications|versions|throttle/status|metrics-admin|secrets|migrate)
```
AND the handler signature does NOT include `current_user`, `superuser`, `principal`, `Security(...)`, or a `Depends()` whose target name matches `^(get_current_|require_|verify_).+$`, REJECT. Bypass: file declares `_PUBLIC_ROUTE_JUSTIFICATION: str = "..."` next to the route definition.

Tools impacted: ~14. Findings closed: ~15 BLOCKER.

---

### P3 — Module-level mutable state in templates (≥9 occurrences)

Templates declare module-level dicts/sets/lists and mutate them — silently per-worker in multi-worker deployments.

Citations:
- R5-O4-C8 — DPoP `DPoPNonceStore` + signing `NonceStore` module-level dicts with `threading.Lock`
- R5-O2-D6 — event store `dict[str, list[object]]`
- R6-S5 (canary registry, scheduler in-process)
- R5-S10-F15/F16 — fingerprint response cache module-level dict
- R6-O1-F10/F14/F15 — adaptive_throttle `_PENALTY_STORE` per-worker
- R6-S5-F5 — `_buckets: dict` mutated without lock
- R5-O3-F7 — ML registry compound `check-then-set` race
- R6-S2 challenge store in passkey (`R5-O4-H4`)
- R5-S5-F2 — Prometheus `_metrics` singleton without registry isolation

**Proposed rule B0.12 — `no_module_state_in_templates`:**
AST-scan templates. For each module-level `Name = <Dict|List|Set>()` or `Name: <Dict|List|Set>` assignment, if the same Name receives any mutation (`Subscript Store`, `Attribute .append/.add/.update/.pop`, `Assign`) in any function in the same module, REJECT. Bypass: tool declares `_SINGLE_PROCESS_OK = True` AND `warnings=` includes a "single-process only" disclosure.

Tools impacted: ~10. Findings closed: ~9 BLOCKER/REAL.

---

### P4 — Claims in `notes` contradict emitted code (≥12 occurrences)

The tool's `notes=`/description claims behavior the template does not deliver.

Citations:
- R5-S1-F6 — `add_file_upload`: "magic bytes, never trusts content-type" — only true for LocalStorage, not presign-S3 path
- R5-S1-F7 — virus quarantine 451 path unreachable; test grep passes
- R5-O2-D5 — versioning "append-only" but `archive()`/`publish()` mutate rows
- R5-O3-F9 — notifications "channel order in_app→push→email" but no fan-out exists
- R5-S5-F9 — OTEL `OTEL_TRACES_SAMPLER` config injected but never read; sampler always 100%
- R5-S5-F6 — correlation_id helpers generated but no middleware wires them
- R5-S9-R5-S04 — sentinel "24h automatic learning→enforcing transition" doesn't exist (also R6-S12-F1)
- R5-S9-R5-S09 — DLP `@sensitive` decorator inert
- R6-S2-F11 — KNOWLEDGE.md says hash refresh tokens; generator emits no DB model
- R6-S6-F9 — `add_s3_storage` claims encryption; presign params omit `ServerSideEncryption`
- R6-S7-F11 — `encrypt_field` returns plaintext when no key; emitted test asserts opposite
- R6-S12-F4 — social_login security defects disclosed in `notes` instead of `warnings`

**Proposed rule B0.13 — `notes_match_emitted_behaviour`:**
For each tool whose `__init__.py` returns a ToolResult with `notes=[...]`, AST-scan the notes list. Any string containing token patterns (`automatically|never trusts|append-only|fan-out|hot reload|verified|encrypted|hash-chained|distributed|cross-worker|production-grade`) AND not also containing escape word (`only when`, `requires manual`, `next_steps:`) MUST appear in a paired `engine/tests/test_<tool>_notes_invariants.py` honesty test that grep-asserts the corresponding code is present. Missing pair → REJECT.

This is the meta-rule (R6-S12-F3). It forces every "claim" to have a test that confirms emitted code backs it.

Tools impacted: ~18. Findings closed: ~12 BLOCKER/REAL.

---

### P5 — Schema accepts `dict[str, Any]` / `list[dict]` / missing `extra="forbid"` on write schemas (≥10 occurrences)

Pydantic write schemas accept arbitrary keys, enabling mass-assignment and smuggling.

Citations:
- R5-O2-D8 — `bulk_update` `updates: list[dict]`
- R6-O3-P1 — 22/25 schemas lack `extra="forbid"`
- R6-O3-P2 — passkey `credential: dict[str, Any]`
- R6-O3-P5 — Onboarding `admin_email: str` (EmailStr imported but unused)
- R6-O3-P9 — feature_flags `targeting_rules: list[dict[str, Any]]`
- R6-O3-P14 — bare `dict` in pdf_reports, email_templates, arq_worker, api_monetization
- R6-O3-P15 — ML server `input: Any`
- R5-S2-F12 — `FeatureFlagUpdate.kill_switch=False + enabled=True` race (schema allows)
- R6-O3-P13 — `status: str | None` instead of `Literal[...]`
- R6-S2-F2 (passkey schemas mass-assign)

**Proposed rule B0.14 — `write_schemas_strict_forbid`:**
AST-scan templates matching `*schema*.py.tmpl`. For each `class X(BaseModel):` whose name ends in `Create`, `Update`, `Request`, or starts with verb-form, REJECT unless the class body contains `model_config = ConfigDict(extra="forbid")` (or equivalent) AND no annotated field uses bare `dict`, `list`, `dict[str, Any]`, `list[dict]`, `list[dict[str, Any]]`, `Any`. Bypass: per-field `# pragma: schema-any` with one-line justification on the same line.

Tools impacted: ~22. Findings closed: ~10 BLOCKER/REAL.

---

### P6 — Resource init at module-import time, not in lifespan (≥5 occurrences)

`init_X` / `create_X_pool` called as bare module-level statements in patched `main.py` instead of inside the `lifespan` context manager.

Citations:
- R5-O2-D12 — `init_idempotency_cache` patched at EOF
- R6-O2-O2-1 — GracefulShutdownAdapter uses `@on_event` (ignored under lifespan=)
- R6-O2-O2-2 — same bulk_ops Redis init (Round-5 unfixed)
- R6-O4-A4 — `_write_and_replace` bypasses lifespan render contract for migrations
- R5-S5-F2 — `init_metrics()` re-registers globally → duplicate timeseries crash
- R6-S3-F4 — `_patch_main` for cache reads REDIS_URL but never calls `init_cache(...)`

**Proposed rule B0.15 — `init_inside_lifespan_only`:**
AST-scan `main_patch.py.tmpl` / any patcher that mutates `app/main.py`. Statements that call functions matching `init_*`, `create_*_pool`, `configure_*`, `start_*_listener`, `register_*` at module-top-level (not inside `async def lifespan(`) → REJECT. Bypass: patcher inserts into the lifespan ctx mgr via a documented `_ADAPT_HOOK:lifespan_pre_yield` / `:lifespan_post_yield` anchor.

Tools impacted: ~6. Findings closed: ~5 BLOCKER/REAL.

---

### P7 — `except Exception: pass` (silent fail-open in security-critical paths)

Citations:
- R5-S4-F10 — tenant_id fail-open via `except Exception: pass`
- R6-O1-F18 — api_key rate-limit Redis-down fails OPEN silently
- R5-O1-F4 — tenant filter mapper path catches AttributeError silently
- R5-S6-F4 — replay debugger swallows credential-extraction errors
- R5-S5-F8 — `cache_logger_on_first_use=True` silently bypasses PII redaction

**Proposed rule B0.16 — `no_silent_security_failures`:**
AST-scan templates under `auth_access/`, security-tagged, or files matching `*tenant*|*rate_limit*|*audit*|*csrf*|*cors*|*dlp*|*sentinel*`. Any `try` block with `except Exception` (or bare `except`) followed by `pass` (or only a log call without raise) → REJECT. Bypass: handler contains explicit raise OR error-counter metric increment AND `# pragma: silent-recoverable` justification.

Tools impacted: ~5. Findings closed: ~5 BLOCKER/REAL.

---

### Patterns NOT promoted to rules (too narrow / too noisy)

- **Cardinality explosion on raw paths** (R5-S5-F1) — only one tool; fix-PR.
- **PG-only types in migrations** (R6-O4-A11) — fix in alembic helper.
- **Path traversal via `locale`** (R6-S8-F1) — single instance.
- **SSRF via webhook URL** (R5-S3-R5-05) — fix in single Pydantic validator.

---

## 4. False-positive / duplicate roll-ups

| Marked | Actually |
|---|---|
| R5-S4-F1 (bulk_delete tx) | DUP of R5-O2-D11 |
| R5-S7-S03 (refund flow) | DUP of R5-O3-F3 |
| R5-S1-F8 (stored_key) | Same root as R6-O3-P3 |
| R5-S2-F22 (router prefix LOW) | F — Cedar/OPA test confirms `/api/v1/` lands; fixture-dependent claim |
| R5-S8-F2 (LIKE wildcards) | R but SQLite-only; safe in PG default |
| R5-S8-F4 (sort param dead) | R — fix or remove |
| R5-S9-R5-S04 docs-only sentinel transition | DUP of R6-S12-F1 |
| R5-S6-F9 (asyncio.get_event_loop deprecation) | L — Py 3.10/3.12 warning only |

**Net BLOCKER count after dedup:** ~52
**Net REAL (Wave 2):** ~38
**Net LOW (backlog):** ~30
**Falsies dropped:** ~6
**Duplicates collapsed:** ~12

---

## 5. Recommended waves

### Wave 0 — Engineering invariants (this week)
4 PRs, one per contract rule above (B0.10 / B0.11 / B0.12 / B0.13). Land first so subsequent fix-PRs cannot regress.
- **B0.10 `no_dead_security_features`** — closes P1 (~12 findings)
- **B0.11 `admin_routes_require_auth`** — closes P2 (~15 findings)
- **B0.12 `no_module_state_in_templates`** — closes P3 (~9 findings)
- **B0.13 `notes_match_emitted_behaviour`** — closes P4 (~12 findings)
- **B0.14 `write_schemas_strict_forbid`** — closes P5 (~10 findings)
- **B0.15 `init_inside_lifespan_only`** — closes P6 (~5 findings)
- **B0.16 `no_silent_security_failures`** — closes P7 (~5 findings)

Pick the 4 with highest finding density (B0.11 + B0.13 + B0.10 + B0.14) for the first wave. Remaining 3 in Wave 0.5.

### Wave 1 — Idiosyncratic BLOCKERs not killed by rules
The bugs that don't fit any pattern (single-tool, single-line, but ship-blocking):

1. **R6-S10-F5** — Prometheus alert formula `/ ({1})` — every deploy fires critical from connection 1
2. **R6-S11-F2** — `GracefulShutdown.py` missing `import signal/logging` — NameError on first call
3. **R6-O4-A1+A2** — alembic chain references nonexistent `0001_initial`; refactor_model forks chain
4. **R5-O3-F3 / R5-S7-S03** — refund flow never calls Stripe
5. **R5-O4-C5** — passkey trusts client `user_id`
6. **R5-O4-C2** — Apple id_token signature unverified
7. **R6-S6-F1/F5/F6** — `add_s3_storage` unauth bucket CRUD (when B0.11 doesn't pre-empt)
8. **R6-O3-P5** — Onboarding `admin_email: str` (EmailStr typo)
9. **R6-S8-F1** — email_templates locale path traversal
10. **R5-O1-F1+F2** — BOLA fail-open default + tenant INSERT bypass

### Wave 2 — REAL fixes
The ~38 REAL findings. Bucketed by tool, mergeable in batches.

### Wave 3 — LOW backlog
The ~30 LOWs go into `docs/wp/PHASE4_BACKLOG.md` as deferred.

---

## 6. Provenance

Source juror reports (transcripts at the worktree paths recorded in agent IDs):

- Round-5: `a96f3835e9f3a913e` (O1), `afa93f696199a807c` (O2), `a6284311c40bea03f` (O3), `acdd867db23e99170` (O4), `a312ed9a0b19fd709` (S1), `a0bc39d3b30ee51d0` (S2), `a68ea6aa42f800bad` (S3), `a7633747314582e29` (S4), `a1ac467d3ff468d3d` (S5), `a04f74fc03bb08311` (S6), `ae038fd8c3fedd165` (S7), `ab2719f701dda10f8` (S8), `af61e8135c49ac88e` (S9), `aa9eafbd01b22dea6` (S10), `ad601b879d4544bd9` (S11), `a0f59466f3fc23259` (S12)
- Round-6: `a25e709233c449634` (O1), `a5240f40ba8eea136` (O2), `a54942f265a9c30b6` (O3), `a2d32db8d4313e0bf` (O4), `aa00ac6e5d96074ef` (S1), `ab27df86cebeb5259` (S2), `a003d0ba6fa17a45e` (S3), `ae90e2e2f1490ec88` (S4), `a042bda8c7b406efa` (S5), `a077cc434dd7a8155` (S6), `a74de47da5eb4f315` (S7), `ac715e5db120663d5` (S8), `a616f9e44c46be762` (S9), `ad597adfde81405df` (S10), `aa1f49fe76936518b` (S11), `a75d12685f8f97c6d` (S12)

---

## 7. What this document does NOT cover

- Operational deploy state of fix-PRs (tracked in PR description + CI)
- Phase 4 backlog / older roadmap items (see `PHASE4_BACKLOG.md`)
- The architectural pivot question (gate compose as `experimental` — open decision)
