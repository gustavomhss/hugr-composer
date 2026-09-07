---
name: fastapi-production
description: Scaffolds and customizes production-grade FastAPI backends in Python — canonical project tree (auth, CRUD, Stripe, jobs, observability, deployment) plus composable slices (RBAC, MFA, pagination, event sourcing, webhooks, rate limiting, sagas, SSE, WebSockets, audit). Use when the user asks to start, extend, audit, or harden a FastAPI project; mentions a Python backend / API / microservice; names FastAPI, SQLAlchemy, Pydantic, Alembic, Celery, Stripe, Redis; or asks for concrete capabilities (auth, payments, webhooks, realtime, jobs, compliance) on an existing FastAPI app. Also use when the user names a production concern (idempotency, transactional outbox, rate limit, circuit breaker, retry budget, graceful shutdown, saga, tamper-evident audit) in a Python web-API context. Do NOT use for non-Python backends (Node, Go, Rails, Django, Flask), frontend or mobile work, data-science notebooks, ML training, bare Python libraries without an HTTP surface, or document-manipulation tasks (PDF, Word, Excel).
license: Proprietary
---

# FastAPI Production

## Overview

Turns a plain-English backend spec into a running, tested, production-grade FastAPI service. Emits idiomatic code that imports from a curated library of 124 registered + 0 staged framework-free primitives (the "venous system"), so generated output survives hand-editing. Ships 207 MCP tools behind 8 tier-1 meta tools + 9 domain-tree dispatchers — drive the skill exclusively through those, never by listing the full catalog.

## When to use

- User wants to start a new Python backend and mentions FastAPI, Python web API, Stripe + Python, or a SaaS backend.
- User wants to add a named capability (auth, payments, rate limiting, RBAC, sagas, realtime, audit log) to an existing FastAPI repo.
- User names a production-engineering concern (idempotency, outbox, graceful shutdown, retry budget, circuit breaker) in a Python context.
- Repo already contains `pyproject.toml` with `fastapi` or `app/main.py` instantiating `FastAPI()`.

## When NOT to use

- Non-Python backends (Node, Go, Rails, Django, Flask-only, Quart).
- Frontend, mobile, or CLI work.
- Data-science notebooks, ML training, or ETL without an HTTP surface.
- Document-manipulation tasks (PDF, Word, Excel, Google Docs).
- Bare Python libraries with no web surface.

## Machine-readable metadata

```yaml
hugr_skill_version: "1.0.0"
spec_compat: ">=1.0.0,<2.0.0"
kind: "framework-scaffold"
domains: ["backend", "python", "fastapi", "web-api"]
entry_tools:
  - fastapi_meta_home
  - fastapi_meta_search
  - fastapi_meta_describe
  - fastapi_meta_scaffold
  - fastapi_meta_compose
  - fastapi_meta_audit
  - fastapi_meta_verify
  - fastapi_auth
catalog_path: "engine/index/catalog.json"
phases: [orient, clarify, scaffold, compose, business, audit]
invariants:
  - "Tools emit ≤ 20 lines of glue; logic lives in imported primitives."
  - "Generated code survives hand-editing (idempotent fingerprints)."
  - "Every tool auto-registers via MCP_TOOL metadata (no manual decorators)."
  - "Primitives are framework-free under core/venous/; adapters bridge to FastAPI."
```

## Workflow phases

1. **Orient.** Call `fastapi_meta_home` to load the catalog landscape — catalog counts (tools / primitives / recipes), the 10 domains, and the top-3 canonical tools per domain. The result does NOT include repo state; inspect the working directory yourself (ls / Read) to learn whether an `app/main.py` already exists.
2. **Clarify.** Ask at most three specific questions — each must offer 2–4 concrete answer branches. Never open-ended. Skip this phase only if the user's request is literally unambiguous.
3. **Scaffold.** After confirming the working directory is empty (or lacks `app/main.py`) via your own file inspection, call `fastapi_meta_scaffold(output_dir, name, models=..., owner_models=...)` once. Not idempotent across runs.
4. **Compose.** For each requested capability: `fastapi_meta_search(query)` → `fastapi_meta_describe(id)` → `fastapi_meta_compose(primitives=...)`. Prefer `fastapi_auth(action=...)` for any auth branch instead of hunting individual slice tools.
5. **Business.** Add domain-specific routes, models, and rules. Business logic (Aggregate + Specification) is authored by the agent, NOT by compose — compose refuses domain-shaped primitives by design.
6. **Audit.** Two layers — do NOT conflate them:
   - **Skill-kit integrity:** `fastapi_meta_audit` runs `engine.audit.contract_check` against the *skill tree itself* (the 37 binding rules in CONTRACT §A/§B). Close with `fastapi_meta_verify` which runs the 10-tier primitive gate. These validate that the HuGR kit is intact on disk; they do NOT validate the project you just emitted.
   - **Emitted-project integrity:** the generated project ships its own `tests/` directory + pre-commit config. Run `pytest` inside the emitted project (or instruct the agent to) to validate runtime behaviour of the scaffold. This is out of scope for the meta tools by design.

## Tier-1 tool index

| Tool | Purpose | When to call |
|---|---|---|
| `fastapi_meta_home` | Catalog landscape — counts, verbs, domains, top-3 per domain, workflow hint. Does NOT read the caller's repo. | First call of every session. |
| `fastapi_meta_search` | BM25 over catalog (tools + primitives + recipes). | Know what you need, not the exact name. |
| `fastapi_meta_describe` | Full spec + examples for one catalog id. | After `search`, before invoking. |
| `fastapi_meta_scaffold` | Emit a production FastAPI project tree. | Scaffold phase, once per session. |
| `fastapi_meta_compose` | Wire primitives into `app/compositions/<slug>.py` exporting `install(app)`. | Compose phase, when no slice fits exactly. |
| `fastapi_meta_audit` | Run `engine.audit.contract_check` on the skill tree (37 §A/§B rules). Skill-kit integrity ONLY; does not validate emitted projects. | Before declaring the kit sound; NOT as the sole gate on a generated project. |
| `fastapi_meta_verify` | 10-tier primitive quality gate on the registry. Skill-kit integrity ONLY. | After adding / editing a primitive in the kit. |
| `fastapi_auth` | Tree dispatcher for 17 auth slice tools (bundle / slice / primitive granularities). | Any auth-related request. |

All other tools (~185) are discovered on demand via `fastapi_meta_search`.

## Few-shot transcripts

Three compressed tool-call traces that demonstrate the correct phase sequence. The agent pattern-matches these more strongly than prose.

### Transcript A — Fresh scaffold

```
USER: Build me a SaaS backend with email auth and Stripe subscriptions.

STEP 1  → orient
TOOL    fastapi_meta_home()
RESULT  {counts: {tools: 201, primitives: 299, recipes: 392},
         domains: 10, landscape: [...]}
# agent then inspects the working directory itself (Read / ls);
# confirms /workspace/myapp is empty → scaffold is needed.

STEP 2  → clarify
ASSISTANT  "Two quick questions before I scaffold:
            1. Do you need RBAC (roles + permissions), or is one user tier OK?
            2. Stripe: subscriptions only, or also one-off purchases?"
USER       "RBAC with admin/user roles. Subscriptions only."

STEP 3  → scaffold
TOOL    fastapi_meta_scaffold(
            output_dir="/workspace/myapp", name="myapp",
            models={"User":{"email":"str","role":"str"},
                    "Subscription":{"stripe_sub_id":"str","status":"str"}},
            owner_models={"Subscription":"user"},
        )
RESULT  {files: 47, app/main.py booted OK}

STEP 4  → compose (auth)
TOOL    fastapi_auth(action="bundle",
                     params={"output_dir":"/workspace/myapp"})
RESULT  {installed: [add_oauth2, add_rbac, add_mfa, ...], 8 slices}

STEP 5  → compose (stripe)
TOOL    fastapi_meta_search(query="stripe subscription webhook idempotent", k=5)
RESULT  top hit: fastapi_resiliency_add_stripe_subscription (primitives: IdempotentConsumer + AuditEvent)
TOOL    fastapi_meta_compose(output_dir="/workspace/myapp",
                              primitives=["IdempotentConsumer","AuditEvent"],
                              name="stripe_webhook", mount_path="/stripe/webhook")
RESULT  {mode: "recipe_template", files: ["app/compositions/stripe_webhook.py"]}

STEP 6  → audit
TOOL    fastapi_meta_audit()        # skill-kit integrity
RESULT  {47/47 green}
# Emitted-project integrity — run the generated pytest suite:
SHELL   cd /workspace/myapp && pytest -q
RESULT  passed

ASSISTANT  "Done. http://localhost:8000/health returns 200.
            Login at /auth/login (admin@myapp / setup_password).
            Stripe webhook at /stripe/webhook (configure endpoint with
            STRIPE_WEBHOOK_SECRET). Call me back to add more features."
```

### Transcript B — Extend existing repo

```
USER: Add rate limiting and idempotency to my /api/orders endpoint.

STEP 1  → orient
TOOL    fastapi_meta_home()
RESULT  {counts: {tools: 201, primitives: 299, recipes: 392},
         domains: 10, landscape: [...]}
# agent inspects /workspace/store: app/main.py + app/routes/ present
# → existing fastapi repo, scaffold will be skipped.

STEP 2  → clarify (skipped — request is specific)

STEP 3  → scaffold (skipped — repo already has one, confirmed by file inspection)

STEP 4  → compose (rate limit + idempotency)
TOOL    fastapi_meta_search(query="rate limit per api key", k=3)
RESULT  top hit: fastapi_resiliency_add_rate_limiting (primitive: RateLimiter + Bulkhead)
TOOL    fastapi_meta_search(query="exactly-once idempotent api endpoint", k=3)
RESULT  top hit: IdempotentConsumer + IdempotencyStore
TOOL    fastapi_meta_compose(output_dir="/workspace/store",
                              primitives=["RateLimiter","Bulkhead",
                                          "IdempotentConsumer","IdempotencyStore"],
                              name="orders_guards", mount_path="/api/orders")
RESULT  {mode: "ad_hoc",
         warning: "no canonical recipe — review the emitted wiring"}

STEP 5  → business (agent review)
ASSISTANT  "Ad-hoc composition. Reviewing emitted code…" (reads file)
ASSISTANT  "Adjusting the rate-limit window from the default 60s to your
            stated 1000/min = 1000/60s. Updating…" (edits composition)

STEP 6  → audit
TOOL    fastapi_meta_audit()        # skill-kit integrity
RESULT  {47/47 green}
# Emitted-project integrity — rerun the project's test suite:
SHELL   cd /workspace/store && pytest -q
RESULT  passed

ASSISTANT  "/api/orders now enforces 1000 req/min per X-API-Key + rejects
            duplicate Idempotency-Key. Tested locally; ready."
```

### Transcript C — Ambiguous request

```
USER: Make it secure.

STEP 1  → orient
TOOL    fastapi_meta_home()
RESULT  {counts: {tools: 201, primitives: 299, recipes: 392},
         domains: 10, landscape: [...]}
# agent inspects /workspace/app: app/main.py + 12 route modules,
# no `app/api/routes/auth.py` → no auth is wired yet.

STEP 2  → clarify (MANDATORY — "secure" is too broad)
ASSISTANT  "'Secure' can mean a few things — which do you want first?
            1. Require login (email+password or OAuth/Google)?
            2. Block brute-force on login (rate limiting, account lockout)?
            3. Add RBAC so only certain users can hit certain routes?
            4. Encrypt data at rest + in transit (TLS + field encryption)?
            5. Audit trail (who-did-what, tamper-evident)?
            Pick one or two to start — others we add as follow-ups."
USER       "Login + audit trail."

STEP 3  → scaffold (skipped — repo exists, confirmed by file inspection)

STEP 4  → compose
TOOL    fastapi_auth(action="list")
TOOL    fastapi_auth(action="add_oauth2",
                     params={"output_dir":"/workspace/app",
                             "providers":["google"]})
TOOL    fastapi_meta_compose(output_dir="/workspace/app",
                              primitives=["TamperEvidentAuditLog","AuditEvent"],
                              name="audit_trail")
RESULT  {mode: "recipe_template", recipe: "AccessLog__01"}

STEP 5  → business (agent adds audit calls inside existing handlers)

STEP 6  → audit
TOOL    fastapi_meta_audit()        # skill-kit integrity
RESULT  {47/47 green}
# Emitted-project integrity — rerun the project's test suite:
SHELL   cd /workspace/app && pytest -q
RESULT  passed

ASSISTANT  "Login via Google OAuth at /auth/login; every route now
            appends to a tamper-evident audit log. Want me to add the
            other items (rate limiting, RBAC, field encryption)?"
```

## Anti-patterns

- Do not skip `fastapi_meta_home`. It's the catalog map the rest of the workflow steers from.
- Do not treat `fastapi_meta_audit` as validation of the generated project. It audits the skill kit's own tree (§A/§B rules). For emitted-project validation, run `pytest` inside the output directory.
- Do not call `fastapi_meta_scaffold` twice in one session. Not idempotent.
- Do not list all 17 auth tools. Always go through `fastapi_auth`.
- Do not write business-logic code inline that duplicates a primitive — always `describe` first to check.
- Do not mark a session "done" before `fastapi_meta_verify` returns green.
- Do not ask more than three clarify questions. If three are not enough, scaffold with sensible defaults and let the user redirect.
- Do not emit domain logic via `fastapi_meta_compose` — compose is infrastructure only. Domain rules (Aggregate + Specification) are hand-authored.

## Reference files

- `STATUS.md` — machine-verified counts and health metrics (human-audience only).
- `/docs/research/SKILL_META_FORMAT.md` — the design doc this SKILL.md ships against.
- `/docs/research/COMPOSE_TOOL_DESIGN.md` — `fastapi_meta_compose` design.
- `/docs/research/DUAL_INDEX_DESIGN.md` — overall tier-1/tier-2 architecture.

---

*version: 1.0.0 · spec_compat: >=1.0.0,<2.0.0 · kit: SKILL-001-fastapi-production*
