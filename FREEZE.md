# FREEZE — SKILL-001 v1.0 scope lock

> **Purpose:** draw the line between **v1.0 scope** and **post-v1.0 work**.
> Every item below is explicitly in-or-out. No silent additions.
> Without this line we never ship.
>
> **Ratified by Gustavo:** pending.
> **Post-ratification, this document is read-only.** Amendments require a
> new dated ratification line at the bottom.

---

## Principle

The skill is a standalone module that plugs into Maestro (consumer) and
Forge (host editor). v1.0 is a **working, stabilized, frozen surface** —
not a feature-complete one. Scope is set by what the skill promises to
do *today*, not what it could do. Anything not in §1 defers to §2.

---

## §1 — IN scope for v1.0.0

### §1.1 — Surface (Maestro-facing)

Total Maestro-visible tools at freeze: **217**
(201 catalog + 7 tier-1 meta + 9 tree dispatchers). Two `extend`
tools (`add_graphql_subscriptions`, `add_stripe_subscription`) were
Rails-connected in Wave 1.5 — same tool count, but
`primitives_used` / `imports_adapters` now reflect the real graph.

- **201 catalog tools** at canonical names `fastapi_<domain>_<verb>_<noun>`,
  indexed in `engine/index/catalog.json` (stable_hash pinned, see §1.5).
  Breakdown: 100 extend + 6 verify + 8 evolve + 8 operate + 1 proactive
  + 50 generator (tier 1) + 22 tier-1 scaffold + 6 module-level.
- **7 tier-1 meta tools** (registered separately, NOT in catalog; see
  `mcp_tools/tier1.py` + `mcp_tools/compose.py`): `fastapi_meta_home`,
  `fastapi_meta_search`, `fastapi_meta_describe`, `fastapi_meta_scaffold`,
  `fastapi_meta_compose`, `fastapi_meta_audit`, `fastapi_meta_verify`.
- **9 tree dispatchers** (registered separately via `register_tree_tools`;
  see `mcp_tools/tree/`): `fastapi_auth`, `fastapi_data`, `fastapi_api`,
  `fastapi_realtime`, `fastapi_resiliency`, `fastapi_observability`,
  `fastapi_compliance`, `fastapi_deployment`, `fastapi_testing`.
- **124 registered primitives** under `core/venous/<ns>/<Name>/` with
  full shell (contract.json + protocol + md + tests + TLA+ + dashboard +
  invariants + observability). Includes the Wave-1.5 additions
  `events.PubSub` and `billing.Billing` (see §1.6.5).
- **17 FastAPI adapters** under `core/venous/_adapters/fastapi/`. No new
  fastapi adapters in v1.0 beyond `BulkheadAdapter` (see §1.6).
- **2 provider adapters** outside fastapi/ —
  `core/venous/_adapters/redis/PubSubAdapter.py` +
  `core/venous/_adapters/stripe/BillingAdapter.py` (see §1.6.5). Both
  framework-isolated, lazy-SDK-imported, hermetically tested.
- **176 staged primitives** surfaced in catalog with `status="staged"`
  (discoverable; not promoted; `_staging/<ns>/` + `_staging/_quarantine/`
  combined PascalCase items).
- **56 generators** + **28 module packages** + **123 adapt tools**
  (100 extend + 8 evolve + 8 operate + 6 verify + 1 proactive;
  `adapt/contracts/` carries helpers but no MCP tools).
- **20 complete examples** at `/examples/` (5 baseline + 10 mid + 5
  adversarial) with README + MAESTRO_SESSION + working code + tests.

### §1.2 — Quality gates (all machine-verifiable)

- CONTRACT §A (12 inviolable rules, §A1..§A12) + §B (45 items
  across Phases 0-7; 37 machine-checked today, the remainder are
  §B5-§B7 post-v1.0 deferrals + §B1.4 subsumed by §B1.3's AST
  scan) all green on every commit. Rule count cited: `37/37` at
  v1.0-rc.1; ratchets up as Phase-5/6/7 rules land per ROADMAP
  §2.2.7.
- Plan-level benchmark: ≥ 70% overall on 20/20 specs. Current: 100.00.
- Code-level benchmark: ≥ 70% overall on 20/20 specs. Current: 100.00.
- All `/examples/` pass `pytest`.
- `install.sh` runs to completion in fresh `python:3.12-slim` Docker.
- Nightly CI workflow green 7 days running before cut.
- 38 promotion-pipeline unit tests pass (32 classifier + 6 disambiguation).

### §1.3 — Promotion pipeline tooling

- `engine/promotion/` module (schemas, classify, signals, state,
  promote, ledger).
- `engine/promotion/LEDGER.md` — 219-entry triage ledger (post-Wave-1.5
  pool cleanup — 225 → 219 after 3 NEEDS_REVIEW promotions + 3 twin
  deletions) with action-focused verdicts (promote_as_adapter /
  promote_as_primitive / extract_motor_pair / fill_and_promote /
  redundant / needs_caller / needs_review).
- Classifier: 10 decision rules; 38/38 unit tests (32 classifier +
  schemas + state + 6 disambiguation).
- Executor: atomic promote/delete with rollback. Ambiguity-safe:
  refuses to act when a primitive name matches multiple ledger
  entries without `--staged` / `--quarantined` disambiguator.
- Decision docs: `/docs/decisions/0004-tier-lite.md` (tier-lite
  proposal + §A12 amendment, ratified with this freeze).
- CONTRACT §B1.8 machine-check `_r_tier_lite_eligibility` added to
  `engine/audit/contract_check.py` (trivially green while 0 lite
  primitives are registered).

### §1.4 — Documentation

- `/PRODUCT.md`, `/ROADMAP.md` (post-v1.0 version), `/CONTRACT.md`,
  `/README.md`, `/CHANGELOG.md` (v1.0.0 entry), `/CONTRIBUTING.md`,
  `/FREEZE.md` (this file), `/GOLIVE.md`, `/INTERFACES.md`.
- `SKILL.md` v2 (Anthropic Agent Skills format, ≤500-line body).
- `INVENTORY.md` machine-generated, matches disk.
- Docs site at `engine/docs/build.py` output.

### §1.5 — Release artefacts

- Git tag `v1.0.0` on frozen commit.
- CHANGELOG.md `[1.0.0]` block naming plan/code benchmark scores +
  primitive/tool/adapter/example counts.
- VERSION file bumped to `1.0.0`.
- Release notes referencing this FREEZE doc.

### §1.6 — BulkheadAdapter promotion (landed Wave 1, pre-freeze)

The originally-deferred `BulkheadAdapter.py` promotion was brought
forward into the pre-freeze Wave-1 sprint because the alternative
(shipping v1.0 with 16 adapters + 2 pre-existing bulkhead test
failures + tool inlining the adapter wrapper) violated "SOTA, no
debt" ratification criteria.

What landed:

- Motor `core/venous/resiliency/Bulkhead/Bulkhead.py` extended with a
  public `async with bh.acquire():` context manager (additive; the
  existing `submit(fn)` now delegates to `acquire`). 5 new behavioral
  tests cover the new surface; the 15 pre-existing tests remained
  green.
- `core/venous/_adapters/fastapi/BulkheadAdapter.py` newly promoted
  (17th adapter): exports `Bulkhead` (multi-partition facade),
  `BulkheadConfig`, `BulkheadFullError`, `BulkheadMiddleware`. 16
  behavioral tests validate every claim (config validation, acquire
  semantics, partition isolation, middleware 503-with-X-Bulkhead-
  Group, status() shape).
- `adapt/extend/infrastructure/add_bulkhead_isolation.py` refactored
  to import the adapter instead of inlining the wrapper — restores
  Rails-style wiring (`imports_adapters` now declares the adapter).
- The 2 previously-deferred bulkhead behavior tests
  (`test_b02_bulkhead_rejects_when_full`, `test_b04_bulkhead_status`)
  now pass against the adapter API — originally listed in §2.8.
- The 2 `BulkheadMiddleware` ledger entries (staged + quarantined)
  were deleted as REDUNDANT after the adapter landed.

v1.0 freeze ships **17 FastAPI adapters** (16 pre-freeze + the new
`BulkheadAdapter`).

### §1.6.5 — PubSub + Billing extraction (landed Wave 1.5, pre-freeze)

Wave 1.5 closed the three NEEDS_REVIEW ledger entries (`PubSubManager`,
`RedisPubSubBackend`, `StripeBilling`) by splitting each into a
framework-free motor primitive + a thin provider adapter. Shipping
v1.0 with inline pub/sub and inline Stripe SDK wrappers in the extend
tools violated "SOTA, no débit" criteria once the scaffolding for
motor+adapter pairs had landed; Wave 1.5 made the tools Rails-style.

What landed:

- **Motor `core/venous/events/PubSub/`** — Protocol + `InMemoryPubSub`
  reference backend with 5 invariants (PS_INV_01 fanout, PS_INV_02
  ordering, PS_INV_03 topic isolation, PS_INV_04 subscriber cleanup,
  PS_INV_05 active-window). 17 tests (7 unit + 10 behavioural).
  Registered in `primitives_by_concern.yaml` under the existing
  `events` namespace (`TopicBus` nearby — PubSub.md spells out the
  broker-vs-fanout disambiguation).
- **Motor `core/venous/billing/Billing/`** — Protocol + `InMemoryBilling`
  reference backend with 5 invariants (BILL_INV_01 HMAC webhook
  verification, BILL_INV_02 lifecycle monotonicity, BILL_INV_03
  plan-change id preservation, BILL_INV_04 opaque-id checking,
  BILL_INV_05 no-PII errors). 25 tests (7 unit + 18 behavioural).
  Introduces a new `billing` namespace — additive, no existing
  primitive moves.
- **Adapter `core/venous/_adapters/redis/PubSubAdapter.py`** — new
  provider framework dir (first non-fastapi). Lazy `redis.asyncio`
  import; JSON codec; 13 hermetic tests against a fake redis module
  via `sys.modules` injection.
- **Adapter `core/venous/_adapters/stripe/BillingAdapter.py`** —
  second provider framework dir. Lazy `stripe` import; maps Stripe's
  wider status set onto the motor's 4-value enum; translates
  `SignatureVerificationError` / `InvalidRequestError` into motor
  errors; 22 hermetic tests against a fake stripe module injected
  via constructor kwarg.
- **Rails-connect `add_graphql_subscriptions.py`**: `_write_pubsub`
  glue shrunk ~200 LOC → ~40 LOC; imports the motor + adapter; ships
  them into the generated project via `ensure_primitives()`;
  idempotency guard accepts both `get_pubsub` (new) and
  `PubSubManager` (legacy) fingerprints.
- **Rails-connect `add_stripe_subscription.py`**: `_STRIPE_BILLING_TEMPLATE`
  shrunk ~140 LOC → ~50 LOC; retains `StripeBilling()` compat alias so
  legacy callers still work.
- **Scaffolder defensive fix**: `generators/scaffold_venous.copy_adapter`
  now ships each framework's source `__init__.py` (with attribution
  footer) instead of overwriting it with a bare docstring — so
  package-level re-exports survive the project copy. Matches the
  primitive copy behaviour.
- **Pool cleanup**: the 3 NEEDS_REVIEW ledger entries (and their
  `_quarantine/` twins) deleted — staged went 179 → 176, quarantined
  went 45 → 42, ledger entries went 225 → 219.

v1.0 freeze ships **124 registered primitives** (122 pre-Wave-1.5 +
`PubSub` + `Billing`) and **19 total adapters** (17 fastapi + 1 redis
+ 1 stripe).

---

## §2 — OUT of scope for v1.0.0 — explicitly deferred

### §2.1 — §B1.3 stretch goal

The §B1.3 floor stretch from 22 → 35 is deferred. Floor stays at 22
(non-regression). Rails-style refactors of the remaining 78 inline
extend tools wait for benchmark signals to prioritize them.

### §2.2 — Phase-5 #24 (weekly benchmark automation)

CI cadence for `engine.bench.code_level --publish` + weekly diff
summary emit. Deferred. Manual benchmark run on main commits is fine
post-v1.0.

### §2.3 — Phase-5 #26 (benchmark → promotion trigger)

Auto-promotion of staged primitives when a benchmark spec flags a
missing one. Deferred. Current flow is manual: classifier labels
`NEEDS_CALLER` and waits.

### §2.4 — 118 EXTRACT_MOTOR_PAIR items

Framework-coupled primitives requiring re-extraction into
(motor + adapter) pairs per §B1.0.1. ~2-4h each × 118 = substantial
work; deferred to post-v1.0 operational cleanup sprints. The
classifier has them documented; they stay in `_staging/` until
someone picks one up and refactors.

### §2.5 — 101 NEEDS_CALLER items

Staged primitives without §A12(b) signal. §A12 discipline preserved
— they wait for a tool/module/benchmark to reference them.

### §2.6 — Second skill (SKILL-002)

Django/Next.js/agent-backend skill. Post-v1.0 work per ROADMAP Phase 6.

### §2.7 — Ecosystem (external contributions, public scoreboard, SDK)

ROADMAP Phase 7 items. Post-v1.0.

### §2.8 — Known pre-existing test failures (CLOSED Wave 1)

**Resolved pre-freeze.** The two tests originally flagged here
(`test_b02_bulkhead_rejects_when_full`, `test_b04_bulkhead_status`)
were the symptom of missing adapter-layer wiring. Wave 1 of the
staged-primitive close-out sprint shipped:

- Motor extension: `InMemoryBulkhead.acquire()` async context manager
  (additive — `submit` now sugar over `acquire`).
- `core/venous/_adapters/fastapi/BulkheadAdapter.py` — the 17th
  shipped adapter, exposing `Bulkhead(BulkheadConfig(limits=...))` +
  `acquire(group)` + `status()` directly matching the test contract.
- Generator `add_bulkhead_isolation.py` refactored to import the
  adapter instead of inlining its wrapper.

All 10 behavioral tests in `test_add_bulkhead_isolation_behavior.py`
now pass; the adapter itself has 16 dedicated behavioral tests; the
motor has 20 tests including 5 new for `acquire()`. See FREEZE §1.6
for the detailed ledger.

No pre-existing test failures remain at v1.0.

---

## §3 — Hard invariants for freeze

These MUST be true at the freeze commit:

1. Git tree clean.
2. CONTRACT **37/37 items green** (§B1.7 FastAPI adapter coverage +
   §B1.8 tier-lite eligibility formally defined in §B; §B4.6 VERSION
   triplet sync + §B4.7 canonical counts sync added as part of the
   pre-freeze rigor audit).
3. Plan-level benchmark == 100.00 on 20/20 specs.
4. Code-level benchmark == 100.00 on 20/20 specs.
5. `engine.inventory` output matches `INVENTORY.md` on disk
   (byte-level diff is empty).
6. `engine.index.manifest verify` exits 0 (idempotent: `stable_hash`
   unchanged across two consecutive builds).
7. All 20 examples pass `pytest`.
8. `install.sh` Docker nightly workflow green for last 7 consecutive days.
9. Unit tests across the repo: 0 failures, 0 xfail, 0 unexplained skips.
10. CHANGELOG.md `[1.0.0]` block present + non-empty + cites
    `stable_hash`.
11. No uncommitted machine-generated files in the working tree
    (`git status --porcelain` is empty).
12. No ledger entry with a `PROMOTE_*` verdict + zero blockers
    remains unactioned — every such entry was either executed OR
    explicitly deferred in §2.
13. `engine/promotion/LEDGER.md` reflects post-promotion state
    (re-generated after §1.6 promotions land).

---

## §4 — Sign-off block

```
### Ratified YYYY-MM-DD by Gustavo
- v1.0.0 scope locked per §1.
- Deferrals per §2 explicitly acknowledged.
- §A12 amendment + §B1.8 tier-lite ratified (see CONTRACT.md §E).
```

Until the sign-off block is filled in with a real date, this document
is a **proposal** and no freeze action is binding.
