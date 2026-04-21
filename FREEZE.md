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

- **201 catalog tools** at current canonical names (`fastapi_<domain>_<verb>_<noun>`).
- **7 tier-1 meta tools**: `home`, `search`, `describe`, `scaffold`,
  `compose`, `audit`, `verify`.
- **9 tree dispatchers**: auth, data, api, realtime, resiliency,
  observability, compliance, deployment, testing.
- **122 registered primitives** under `core/venous/<ns>/<Name>/` with
  full shell (contract.json + protocol + md + tests + TLA+ + dashboard +
  invariants + observability).
- **16 FastAPI adapters** under `core/venous/_adapters/fastapi/`.
- **180 staged primitives** surfaced in catalog with `status="staged"`
  (discoverable; not promoted).
- **56 generators** + **28 module packages** + **126 adapt tools**.
- **20 complete examples** at `/examples/` (5 baseline + 10 mid + 5
  adversarial) with README + MAESTRO_SESSION + working code + tests.

### §1.2 — Quality gates (all machine-verifiable)

- CONTRACT §A (12 rules) + §B (33 items) all green on every commit.
- Plan-level benchmark: ≥ 70% overall on 20/20 specs. Current: 100.00.
- Code-level benchmark: ≥ 70% overall on 20/20 specs. Current: 100.00.
- All `/examples/` pass `pytest`.
- `install.sh` runs to completion in fresh `python:3.12-slim` Docker.
- Nightly CI workflow green 7 days running before cut.

### §1.3 — Promotion pipeline tooling

- `engine/promotion/` module (schemas, classify, signals, state,
  promote, ledger).
- `engine/promotion/LEDGER.md` — 229-entry triage ledger with
  action-focused verdicts.
- Classifier: 7 decision rules, 32/32 unit tests.
- Executor: atomic promote/delete with rollback.
- Decision docs: `/docs/decisions/0004-tier-lite.md`.
- §B1.7 tier-lite in CONTRACT.md §E (ratified with this freeze).

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

### §1.6 — Specific in-scope promotions

The only staged → registered promotions IN v1.0:

- **`BulkheadMiddleware` → `core/venous/_adapters/fastapi/BulkheadAdapter.py`**.
  Motor `Bulkhead` is registered; adapter missing; staged item fills
  the gap. Completes the pair. Tests updated; contract stays 33/33.

No other staged item is promoted in v1.0. (See §2.3 for why.)

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
classifier has them documented; they stay in `_extracted/` until
someone picks one up and refactors.

### §2.5 — 104 NEEDS_CALLER items

Staged primitives without §A12(b) signal. §A12 discipline preserved
— they wait for a tool/module/benchmark to reference them.

### §2.6 — Second skill (SKILL-002)

Django/Next.js/agent-backend skill. Post-v1.0 work per ROADMAP Phase 6.

### §2.7 — Ecosystem (external contributions, public scoreboard, SDK)

ROADMAP Phase 7 items. Post-v1.0.

---

## §3 — Hard invariants for freeze

These MUST be true at the freeze commit:

1. Git tree clean.
2. CONTRACT 33/33 items green (or 34/34 after §B1.7 ratification adds
   its machine-check rule).
3. Plan-level benchmark == 100.00.
4. Code-level benchmark == 100.00.
5. `engine.inventory` output matches `INVENTORY.md` on disk.
6. `engine.index.manifest build` produces a stable catalog
   (`stable_hash` unchanged on re-run).
7. All 20 examples pass `pytest`.
8. `install.sh` Docker nightly green for last 7 days.
9. Unit tests across the repo: 0 failures, 0 xfail, 0 skip without
   reason.
10. CHANGELOG.md `[1.0.0]` block present + non-empty.
11. No uncommitted machine-generated files in the working tree.

---

## §4 — Sign-off block

```
### Ratified YYYY-MM-DD by Gustavo
- v1.0.0 scope locked per §1.
- Deferrals per §2 explicitly acknowledged.
- §A12 amendment + §B1.7 tier-lite ratified (see CONTRACT.md §E).
```

Until the sign-off block is filled in with a real date, this document
is a **proposal** and no freeze action is binding.
