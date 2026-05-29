# Work Package Contract — `WP-15-hexagon-ports`

> **Binding contract, not a suggestion.** An agent executing this WP MUST satisfy
> every section below. The WP is *done* only when every acceptance gate is green
> and every Definition-of-Done box is checked, with proof pasted. Anything less
> is "in progress", never "done".
>
> Authored against `docs/wp/WP-CONTRACT-TEMPLATE.md`. Section order and headers
> are verbatim from the template; WP-15-specific content fills each section.
> Theme: **hexagonal port formalization** per ADR-0001 — formalize a
> `core/venous/_ports/` boundary so adapters (`core/venous/_adapters/`) and
> compose tools (`adapt/extend/_base/`) consume *Protocols*, not concrete
> implementations.
>
> **This WP is structurally different from WP-13/14.** WP-13/14 migrate a list
> of compose tools to a per-tool dir layout. WP-15 audits the existing
> primitives layer (124 registered primitives per INVENTORY.md) and produces a
> port catalog plus exemplar port-migration for 1-2 primitives, plus a
> backward-compatibility shim plan (§11) so the import surface does not break
> downstream consumers (`adapt/_base/`, `adapt/extend/*`, the 17 FastAPI
> adapters, the `_staging/` graveyard).
>
> **Model elevation:** WP-15 runs on `opus`. Architecture work involves
> reasoning about an import-graph rewrite that touches the most-imported
> directory in the repo; a compat-shim plan that satisfies type-checkers and
> runtime; and a tradeoff (rename vs. alias vs. parallel-tree) the tech lead
> must make. `sonnet` is insufficient for this class of work.

---

## 0. Identity
| Field | Value |
|---|---|
| **WP id** | `WP-15-hexagon-ports` |
| **Title** | Formalize `core/venous/_ports/` per ADR-0001 — audit 124 primitives + exemplar port migration + compat-shim plan |
| **Wave** | `1` |
| **Depends on** | `WP-F0-staging-rename` (PR #24, merged) — `_staging/` must already be at its renamed path (this WP audits across `_staging/` and registered tiers). |
| **Blocks** | (advisory) any future WP that imports from `core.venous.<ns>.<Name>` should consume the new port boundary; WP-15 ships a compat shim so this is non-blocking for in-flight WAVE-1 WPs. |
| **Branch** | `wp/15-hexagon-ports` (off the post-dependency main, i.e. main with WP-F0 merged) |
| **Isolation** | dedicated git worktree |
| **Model** | `opus` — architecture/import-graph reasoning + compat-shim design + per-primitive port-catalog judgement; `sonnet` is insufficient for the §11 compat-shim tradeoff. |

## 1. Context bundle (the ONLY context the agent gets)
The agent must operate with exactly this set — nothing wider. WP-15's owned files are split into three groups: the new port boundary (write), the audit catalog (write), and the exemplar port-migration (write). Everything else is read-only.

- **Owned files (exclusive write surface):**
  ```
  # Group A — formal port boundary (new directory tree)
  skills/SKILL-001-fastapi-production/core/venous/_ports/
    __init__.py
    README.md                            # boundary doc, single source of truth
    api/__init__.py                      # mirrors core/venous/api namespace
    api/CommandBus.py                    # exemplar #1 — Protocol-only
    api/QueryBus.py                      # exemplar #2 — Protocol-only
    auth/__init__.py
    billing/__init__.py
    cache/__init__.py
    compliance/__init__.py
    data/__init__.py
    events/__init__.py
    extras/__init__.py
    flags/__init__.py
    jobs/__init__.py
    llm/__init__.py
    obs/__init__.py
    policy/__init__.py
    resiliency/__init__.py
    security/__init__.py
  # Group B — port catalog (machine-checkable, ground-truth for downstream WPs)
  skills/SKILL-001-fastapi-production/core/venous/_ports/CATALOG.md
  skills/SKILL-001-fastapi-production/core/venous/_ports/CATALOG.json
  # Group C — compat shim (back-compat for existing `from core.venous.api.CommandBus import …`)
  skills/SKILL-001-fastapi-production/core/venous/api/CommandBus/__init__.py   [MODIFY ONE LINE]
  skills/SKILL-001-fastapi-production/core/venous/api/QueryBus/__init__.py     [MODIFY ONE LINE]
  # (Only the 2 exemplar primitives get a shim line in this WP. The remaining 122
  #  primitives are catalogued and queued for follow-up WPs per the §3 phasing.)
  # Group D — docs hook
  docs/wp/WP-15-hexagon-ports.md                                                 [THIS FILE]
  docs/architecture.md                                                           [APPEND-ONE-PARAGRAPH]
  ```
- **Golden reference (read-only, copy the consumed-surface pattern):** `skills/SKILL-001-fastapi-production/adapt/_base/` — the hexagon helpers from PR #28 (`__init__.py` + `discover.py` + `patch.py` + `render.py`). WP-15 does NOT migrate a tool; instead, it formalizes the type-only ports that `_base/` and future compose tools should consume. Read `_base/__init__.py` to understand the *consumer* shape so the port surface matches it.
- **Shared base/contract to import (read-only):** `skills/SKILL-001-fastapi-production/adapt/contracts/` (for `ToolInput`/`ToolResult` typing the ports may reference); `skills/SKILL-001-fastapi-production/core/venous/<ns>/<Name>/<Name>.protocol.py` for all 25 existing protocol stubs.
- **Spec to follow:** `docs/architecture.md`, `docs/adr/0001-architecture.md` (hexagonal core + plugin rationale), `docs/tool-contract.md`, `skills/SKILL-001-fastapi-production/INVENTORY.md` (the 124 registered primitives + 17 FastAPI adapters count).
- **Staging pool (read-only reference, not a write surface):** `core/venous/_staging/` (175 staged primitives) — WP-15 catalogues them but does NOT promote any.

## 2. Forbidden surface (collision guard)
The agent MUST NOT create, modify, move, or delete anything outside §1 owned files.
Explicitly off-limits:
- **WP-13 (Evolve) tools** — the 8 tools listed in §1 of `docs/wp/WP-13-evolve.md`.
- **WP-14 (Verify) tools** — the 6 tools listed in §1 of `docs/wp/WP-14-verify.md`.
- **Sibling WAVE-1 batches** — WP-Z2 (infra 04-06), WP-C (crud+auth 07-09), WP-D (rt/test/api 10-12), WP-F (engine-split 16-17). Read each sibling's §1 for canonical ownership.
- **`adapt/_base/`** — owned by WP-F1; read-only here. WP-15 produces *ports* that `_base/` may consume in a later WP — it does NOT modify `_base/` itself.
- **`adapt/extend/`** — 100 tools across 6 sub-domains; OUT OF SCOPE. WP-15 does NOT migrate any compose tool's import to use the new ports — that is the work of follow-up port-consumer WPs.
- **`adapt/evolve/`, `adapt/verify/`, `adapt/operate/`, `adapt/proactive/`** — OUT OF SCOPE.
- **`engine/`, `generators/`, `tests/`, `pyproject.toml`, CI config** — out of scope.
- **`core/venous/_adapters/`** — 17 FastAPI adapters (plus redis/stripe sub-trees) — read-only here. WP-15 catalogues which adapter implements which port but does NOT migrate any adapter to consume the new port directory in this WP.
- **`core/venous/<ns>/<Name>/<Name>.py`** (the concrete primitive impls) — read-only. WP-15 only touches the 2 exemplar primitives' `__init__.py` to add a one-line shim (Group C).
- **`core/venous/<ns>/<Name>/<Name>.protocol.py`** (the existing 25 auto-inferred Protocol stubs) — read-only. WP-15 supersedes the auto-inferred stubs with hand-authored ports in `_ports/` for the 2 exemplars; the 25 source stubs stay in place untouched as the catalog's source-of-derivation.
- `hugr_auth/` — license/auth gate is a separate service; touching it is an instant reject.

If the task seems to require touching a forbidden file, **stop and report** — do not edit it.

## 3. Transformation (exact before → after)
- **Goal:** Establish `core/venous/_ports/` as the formal hexagonal port boundary per ADR-0001. Audit the 124 registered primitives, catalog their existing protocol-stub coverage (currently 25 of 124 carry an auto-inferred `<Name>.protocol.py`), produce a hand-authored exemplar port for 2 primitives (`CommandBus`, `QueryBus`), and ship a backward-compatibility shim plan (§11) so existing import paths continue to resolve.
- **Before:**
  - `core/venous/<ns>/<Name>/` is the primitives layer. Each `<Name>/` directory ships a concrete `<Name>.py`, an auto-inferred `<Name>.protocol.py` (25 of 124 primitives have it — measured at branch creation), tests, contract.json, docs.
  - Adapters (`core/venous/_adapters/fastapi/` + `redis/` + `stripe/`) consume the *concrete* primitives directly via `from core.venous.<ns>.<Name> import …`.
  - Compose tools (`adapt/extend/`) import primitives the same way — coupling them to concrete impls, not Protocols.
  - There is no formal port directory and no machine-checkable port catalog; ADR-0001's "Formalize the ports" line is unimplemented.
- **After:**
  - `core/venous/_ports/` exists as a flat type-only Protocol tree: one sub-package per namespace (16 namespaces per INVENTORY: api / auth / billing / cache / compliance / data / events / extras / flags / jobs / llm / obs / policy / resiliency / security; INVENTORY lists 16 namespaces with `cost`=0 so 15 non-empty + `cost` placeholder = 16).
  - Each non-empty namespace has an `__init__.py` that re-exports the port Protocols defined under it. **Empty namespaces ship an `__init__.py` with a single `__all__: list[str] = []`** to keep the tree uniform and importable.
  - `_ports/CATALOG.md` and `_ports/CATALOG.json` enumerate, for each of the 124 registered primitives: `(namespace, name, has_protocol_stub: bool, port_status: "exemplar" | "queued" | "missing-stub")`. The catalog is the source of truth that follow-up WPs consume.
  - **Exactly 2 exemplar ports are hand-authored** in this WP: `_ports/api/CommandBus.py` (Protocol with `register` + `dispatch`) and `_ports/api/QueryBus.py` (Protocol with `register` + `query`). These two are chosen because their existing `<Name>.protocol.py` stubs are well-typed enough to seed a hand-authored port without inventing semantics.
  - The 2 exemplar primitives' `__init__.py` (Group C in §1) gains a single re-export line so that `from core.venous._ports.api import CommandBusProtocol` AND the legacy `from core.venous.api.CommandBus import CommandBusProtocol` both resolve — see §11 compat shim.
  - `docs/architecture.md` is appended with a single paragraph pointing at `core/venous/_ports/README.md` as the boundary's source of truth.
  - The remaining 122 primitives are queued for follow-up WPs via the catalog; no other code in `core/venous/<ns>/<Name>/` is touched in this WP.
- **Why exemplar-only, not all-124:** the architecture decision (port boundary location, Protocol-vs-ABC choice, runtime_checkable trade-off, naming convention `<Name>Protocol`) needs validation against a real downstream consumer before being applied 124 times. Two ports that already share a shape (bus-style register+dispatch) catch the patterns the catalog needs; the remaining 122 are staged behind a clear catalog so port-consumer WPs land deterministically. This is explicitly framed as a tech-lead decision in §11 — if the tech lead prefers a different exemplar pair (e.g. `IdempotencyStore` + `RequestContext` to seed the data-namespace shape), the agent must **stop and ask**.
- **Out of scope:**
  - Migrating any compose tool to use the new port directory. That is the job of port-consumer WPs (post-WAVE 1).
  - Migrating any of the 17 FastAPI adapters to depend on `_ports/` rather than the concrete primitive. Same reason.
  - Promoting any of the 176 `_staging/` primitives out of staging. Catalog only.
  - Renaming or relocating the existing 25 `<Name>.protocol.py` stubs. They stay in place as catalog-derivation evidence.
  - Inventing new primitives or expanding the port surface beyond the 2 exemplars.
  - Modifying `core/venous/_adapters/` in any way.

## 4. Invariants (must hold — verified, not asserted)
- [ ] **Zero behavior change at runtime.** `pytest tests/` (full suite) passes byte-equivalently before/after WP-15. The new `_ports/` tree is type-only; it adds zero runtime code paths.
- [ ] **Import paths stable — legacy paths still resolve.** `from core.venous.api.CommandBus import CommandBus, CommandBusProtocol` MUST resolve after WP-15 (verified by `python -c "from core.venous.api.CommandBus import CommandBus, CommandBusProtocol"`). Same for `QueryBus`. The compat shim (§11) is what guarantees this.
- [ ] **New ports importable.** `from core.venous._ports.api import CommandBusProtocol, QueryBusProtocol` MUST resolve. `from core.venous._ports import api, auth, billing, cache, compliance, data, events, extras, flags, jobs, llm, obs, policy, resiliency, security` MUST resolve (one import per non-empty namespace).
- [ ] **Type-only.** No file under `core/venous/_ports/` contains a runtime class body other than `Protocol`. No `__init__`, no `__call__` implementation, no class-level mutable state. Verified by AST audit (§5).
- [ ] **No new dependencies.** No `pyproject.toml` change. `typing.Protocol` + `typing.runtime_checkable` are stdlib.
- [ ] **Catalog completeness.** `CATALOG.json` lists exactly 124 entries (matching INVENTORY's `124 registered primitives`). Each entry has `namespace`, `name`, `has_protocol_stub`, `port_status` populated.
- [ ] **Catalog ground-truth derivation reproducible.** The catalog is generated by a documented procedure (described in `CATALOG.md`); a reviewer can re-derive it by running the same `find … -name '*.protocol.py'` style enumeration.
- [ ] **Forbidden surface untouched.** `git diff --name-only main..HEAD` lists only paths inside §1 write surface. No `adapt/_base/`, no `adapt/extend/`, no `_adapters/`.
- [ ] **Compat shim is one-line per exemplar.** The shim modifies exactly the 2 exemplar primitives' `__init__.py`, exactly one line each (a re-export). Anything larger = stop and report.

## 5. Port-conformance test plan (this WP's analog of P1 #15)
P1 #15 mandates emitted-tests for compose tools. WP-15 ships no compose tool, so its analog is a **port-conformance test plan** — what tests prove the new boundary is real and stays real. This WP authors the *plan* (machine-checkable list); follow-up port-consumer WPs author the conformance tests themselves.

The plan lives in `core/venous/_ports/README.md` and enumerates, for each exemplar port:

1. **Catalog completeness check (this WP runs it).** A test that re-derives the 124-entry catalog from filesystem evidence and diff-compares to `CATALOG.json`. Drift = catalog stale = port boundary unverifiable.
2. **Type-only AST audit (this WP runs it).** A test that AST-parses every file under `_ports/` and asserts no `def __init__`, no `def __call__` with a body, no `class … (Protocol):` body other than `... # docstring + method stubs`.
3. **Compat-shim resolution test (this WP runs it).** A test that imports both the legacy path (`from core.venous.api.CommandBus import CommandBusProtocol`) and the new path (`from core.venous._ports.api import CommandBusProtocol`) and asserts they are the same object (`is` comparison).
4. **Adapter-conformance test (deferred to port-consumer WP).** For each adapter that implements `CommandBusProtocol`, a test that `isinstance(adapter, CommandBusProtocol)` returns True (uses `runtime_checkable`). Deferred because WP-15 does not migrate any adapter; the test is part of the port-consumer follow-up WP that wires the first adapter to the new port.
5. **Compose-tool-conformance test (deferred).** For each compose tool that consumes a `_ports/` Protocol, a test that the consumed surface remains stable across the WP. Deferred — same reason.

Tests (1)-(3) are owned by this WP and live in `core/venous/_ports/conftest.py` (NOT in the project-side `tests/` tree, because `_ports/` is a kit-local namespace; tests/conformance live next to the boundary they test). Wait — the §1 write surface lists `core/venous/_ports/{__init__.py, README.md, ...}` but does NOT list a `conftest.py`. Resolve: **STOP-and-report point if the agent believes a conformance test file needs to live outside the §1 write surface**. Otherwise, the conformance plan is a `README.md` section listing the three checks as `pytest`-collectable snippets the follow-up WP will author. (Deliberately conservative: §1 is exact.)

## 6. Validation gates (deterministic — copy/paste, must be GREEN)
Run from `skills/SKILL-001-fastapi-production` with the shared interpreter; paste each result in §7.

```bash
PY=.venv/bin/python ; export PYTHONPATH=. SECRET_KEY=ci-test-secret-key-must-be-32-chars-long!!! RATE_LIMITING_ENABLED=false ENVIRONMENT=local
# Mandatory gate 1 — ruff (lint + format) on the new _ports/ tree
$PY -m ruff check core/venous/_ports
$PY -m ruff format --check core/venous/_ports
# Mandatory gate 2 — port-import audit: legacy and new paths BOTH resolve, are the SAME object.
$PY -c "from core.venous.api.CommandBus import CommandBusProtocol as L; from core.venous._ports.api import CommandBusProtocol as N; assert L is N, 'compat shim broken'"
$PY -c "from core.venous.api.QueryBus import QueryBusProtocol as L;   from core.venous._ports.api import QueryBusProtocol as N;   assert L is N, 'compat shim broken'"
# Mandatory gate 3 — adapt/extend/ MUST NOT import from _adapters/ (hexagonal boundary check).
# This gate enforces that compose tools depend on ports (or concrete primitives via compat shim), not on adapters.
! grep -r 'from core.venous._adapters' skills/SKILL-001-fastapi-production/adapt/extend/
! grep -r 'import core.venous._adapters' skills/SKILL-001-fastapi-production/adapt/extend/
# Mandatory gate 4 — adapt/_base/ also MUST NOT import from _adapters/.
! grep -r 'from core.venous._adapters' skills/SKILL-001-fastapi-production/adapt/_base/
# Mandatory gate 5 — full suite stays green (no behavior change introduced by the new _ports/ tree).
$PY tests/test_p0_regression_gates.py
$PY tests/test_boot_chains.py
$PY -m engine.audit.contract_check
```

Gate 1 = ruff. Gate 2 = compat shim works for both exemplars. Gate 3+4 = port-import audit (the hexagonal direction-of-dependency check that ADR-0001 promises). Gate 5 = regression / contract suite stays green. All five gates must be GREEN. Paste verbatim tails in §7.

## 7. File-disjoint guarantee (your WP's surface + EXPLICIT forbidden list)

**WP-15 owns (write surface):** the `core/venous/_ports/` tree (Group A), the catalog (Group B), the 2 exemplar primitive `__init__.py` one-line shims (Group C), and the appended paragraph in `docs/architecture.md` (Group D), all listed exactly in §1.

**WP-15 must NOT touch (forbidden):**

| Owner | Forbidden tools / paths |
|---|---|
| WP-13 Evolve | the 8 tools listed in §1 of `docs/wp/WP-13-evolve.md` |
| WP-14 Verify | the 6 tools listed in §1 of `docs/wp/WP-14-verify.md` |
| WP-Z2 (04-06) | all infrastructure tools in `adapt/extend/infrastructure/` |
| WP-C (07-09) | crud + auth-access tools owned by `wp/crud-auth` |
| WP-D (10-12) | realtime + testing-tools + api-design tools owned by `wp/rt-test-api` |
| WP-F (16-17) | engine-split tools owned by `wp/engine-split` |
| WP-F1 | `adapt/_base/`, golden `crud_data/add_cursor_pagination/` |
| Adapters | `core/venous/_adapters/` (17 FastAPI + redis + stripe) |
| Concrete primitives | `core/venous/<ns>/<Name>/<Name>.py` for all 124 — read-only |
| Existing protocol stubs | `core/venous/<ns>/<Name>/<Name>.protocol.py` for the 25 that have one — read-only |
| Staging | `core/venous/_staging/` (175 staged + 42 quarantined) — read-only catalog reference |
| Shared | `engine/`, `generators/`, `tests/`, `pyproject.toml`, CI, `hugr_auth/` |

`git diff --name-only main..HEAD` MUST list only paths inside the §1 write surface.

## 8. Estimated effort (architecture-shape, not per-tool)

Measurements taken on `main` at branch creation (HEAD `bd634a5`); `find` counts; `INVENTORY.md` headline numbers.

| Activity | Count / volume | Wall-clock | Model |
|---|---:|---:|---|
| Read ADR-0001 + architecture.md + tool-contract.md + INVENTORY.md | 4 files | 0.5 h | `opus` |
| Read `adapt/_base/__init__.py` + `discover.py` + `patch.py` + `render.py` (consumer shape) | 4 files | 0.5 h | `opus` |
| Read 25 existing `<Name>.protocol.py` stubs to extract derivation patterns | 25 files | 2.0 h | `opus` |
| Enumerate 124 registered primitives + 17 FastAPI adapters; derive `CATALOG.json` from filesystem | 141 paths | 2.0 h | `opus` |
| Author `CATALOG.md` narrative + derivation procedure | 1 doc | 1.0 h | `opus` |
| Design port boundary surface (`_ports/__init__.py` + 16 namespace stubs + `README.md`) | 18 files | 2.0 h | `opus` |
| Author 2 exemplar ports (`CommandBus.py` + `QueryBus.py`) — hand-typed Protocols, not auto-inferred | 2 files | 1.5 h | `opus` |
| Author 2 one-line compat shims (Group C) | 2 lines | 0.5 h | `opus` |
| Append boundary paragraph to `docs/architecture.md` | 1 paragraph | 0.25 h | `opus` |
| Run §6 gates 1-5 + paste output | 5 gates | 0.5 h | `opus` |
| Self-review as adversarial reviewer (does the boundary actually formalize what ADR-0001 promises?) | — | 1.0 h | `opus` |
| **TOTAL** | **141 paths read, 18 new files written, 2 lines modified, 1 paragraph appended** | **~11.75 h** | `opus` |

**Model recommendation: `opus`.** This WP is not mechanical — it requires:
- Reading 25 auto-inferred Protocol stubs and judging which derivation patterns survive into hand-typed ports.
- Designing a directory tree that matches the *consumer* shape (`adapt/_base/`) without over-fitting to the current 2 exemplars.
- Authoring a compat-shim plan (§11) that the tech lead can validate against the import surface.
- Producing a catalog that is the ground truth for an unbounded number of follow-up WPs — a wrong derivation procedure ships as a wrong catalog 124 times over.

`sonnet`-level reasoning on this WP risks: (a) cataloguing 25 stubs as "exemplar candidates" when only 2 are; (b) producing a port directory layout that doesn't survive contact with the first port-consumer; (c) shipping a compat shim that satisfies `python -c` but breaks `mypy` or vice-versa.

## 9. Failure modes (≥6 anticipated traps)

1. **F-01. Catalog derivation procedure not reproducible.**
   - *Symptom:* `CATALOG.json` lists 123 or 125 entries, not 124; OR the reviewer re-runs the documented derivation and gets a different result.
   - *Cause:* the documented procedure relies on a `find` invocation that races against `_staging/` (which has its own `<Name>.protocol.py` files for the 175 staged primitives). The 124 number is *registered* primitives (excluding `_staging/`), so the find must `-prune` `_staging/` AND `_adapters/`.
   - *STOP-and-report rule:* before generating the catalog, run the documented find on a fresh checkout and confirm count = 124. If count ≠ 124, the INVENTORY.md derivation procedure is the source of truth; reconcile with INVENTORY's `engine.inventory` invocation, NOT by hand-tweaking the count.

2. **F-02. Compat shim resolves at import but fails at type-check.**
   - *Symptom:* `python -c "from core.venous.api.CommandBus import CommandBusProtocol"` succeeds (gate 2 green), but `mypy core/venous/api/CommandBus/__init__.py` reports `Module has no attribute "CommandBusProtocol"`.
   - *Cause:* the one-line shim uses `__getattr__` module-level magic that runtime accepts but mypy does not follow.
   - *STOP-and-report rule:* the shim MUST be a plain `from core.venous._ports.api.CommandBus import CommandBusProtocol` re-export (or equivalent `import X as X` form). Any `__getattr__` magic = stop and report. The tech lead picks the form; do not invent it.

3. **F-03. Port surface differs from existing protocol stub semantics.**
   - *Symptom:* the hand-authored `_ports/api/CommandBus.py` Protocol has a different method signature than `core/venous/api/CommandBus/CommandBus.protocol.py`, so the concrete `CommandBus` no longer satisfies `CommandBusProtocol`.
   - *Cause:* the auto-inferred stub used `async def dispatch(self, command: object, **kwargs) -> Any: ...` but the hand-authored port tightened the return type — and a concrete adapter relies on the looser type.
   - *STOP-and-report rule:* the exemplar port MUST be type-equivalent or a strict-supertype of the existing stub. If tightening is desirable (it usually is), **stop and report** — that is a separate design decision the tech lead must approve, not a WP-15 in-scope change. Default: copy the existing stub's signatures verbatim into the hand-authored port.

4. **F-04. Empty-namespace `__init__.py` breaks discovery.**
   - *Symptom:* `from core.venous._ports import cost` succeeds but `dir(cost)` is empty AND some downstream test expects at least one symbol.
   - *Cause:* INVENTORY lists `cost` as 0 primitives; the agent ships `_ports/cost/__init__.py` empty. A reviewer or follow-up WP assumes a non-empty namespace.
   - *STOP-and-report rule:* every empty namespace's `__init__.py` MUST contain `__all__: list[str] = []` AND a one-line module docstring documenting the empty state. Reviewers seeing the docstring know it is intentional.

5. **F-05. Exemplar choice contested.**
   - *Symptom:* tech-lead review rejects the choice of `CommandBus` + `QueryBus` as the 2 exemplars and prefers e.g. `IdempotencyStore` + `RequestContext` for data-namespace seeding.
   - *Cause:* the exemplar choice was made by the agent without confirmation.
   - *STOP-and-report rule:* the §3 framing explicitly flags the exemplar choice as a tech-lead decision. The agent MUST `STOP-AND-ASK` before authoring the 2 exemplar ports if there is ANY signal that the chosen pair is contested. Authoring against a contested choice = rework loop.

6. **F-06. Catalog drifts under merge with sibling WAVE-1 WPs.**
   - *Symptom:* CATALOG.json shipped by WP-15 is stale on the day a sibling WP (e.g. WP-C, WP-D) merges and changes the registered primitives count.
   - *Cause:* siblings touch `adapt/extend/` not `core/venous/`, so technically should NOT change the 124 count — but a side-effect (e.g. a primitive promotion from `_staging/`) could.
   - *STOP-and-report rule:* the catalog is a snapshot at WP-15 merge time. The `CATALOG.md` derivation procedure section MUST document "re-derive after any `_staging/` promotion or `core/venous/` directory addition". Catalog freshness is a follow-up WP responsibility, not WP-15's.

7. **F-07. Compat shim breaks `runtime_checkable`.**
   - *Symptom:* `isinstance(some_command_bus_impl, CommandBusProtocol)` returned True before WP-15 and returns False after.
   - *Cause:* the hand-authored port forgot `@runtime_checkable` decoration, OR the shim re-exports a different Protocol object than the one the auto-inferred stub provided.
   - *STOP-and-report rule:* the gate-2 `is`-check covers identity; an extra runtime_checkable conformance check belongs in §5's adapter-conformance test (deferred). For this WP, the agent MUST include `@runtime_checkable` on every authored Protocol unless the existing stub explicitly omitted it for a documented reason.

8. **F-08. Boundary doc is hand-wavy.**
   - *Symptom:* `core/venous/_ports/README.md` says "ports formalize the hexagon" but does not enumerate which namespaces are non-empty, which 2 are exemplary, what the derivation procedure is, or which follow-up WPs consume the catalog.
   - *Cause:* author wrote prose without the catalog's machine-checkable shape.
   - *STOP-and-report rule:* the README MUST cross-reference `CATALOG.json` as the source of truth. Prose without enumeration = stop and report; the tech-lead's adversarial-review pass catches it otherwise.

9. **F-09. `_ports/` accidentally re-implements an adapter.**
   - *Symptom:* `_ports/api/CommandBus.py` contains a `register` method with a default body (e.g. raises `NotImplementedError`) — i.e. it is an ABC, not a Protocol.
   - *Cause:* author over-typed and started adding "helpful" stubs.
   - *STOP-and-report rule:* §4 invariant "Type-only" is hard. Any method body other than `...` = stop and report. The AST audit in §5 catches it.

10. **F-10. Side-effect import at `_ports/__init__.py`.**
    - *Symptom:* importing `core.venous._ports` triggers a chain that loads concrete primitives (eager registration, logging setup, etc.).
    - *Cause:* author wrote `from .api import *` at the top-level `__init__.py`.
    - *STOP-and-report rule:* the top-level `_ports/__init__.py` MUST be empty except for `__all__: list[str] = []` and a module docstring pointing at `README.md`. Each namespace `__init__.py` re-exports only its own Protocol symbols, NOT cross-namespace imports.

## 10. DoD checklist (every box, or it's not done)

- [ ] **D-01.** `core/venous/_ports/` directory exists with `__init__.py` + `README.md` + 16 namespace sub-packages.
- [ ] **D-02.** 2 exemplar ports authored: `_ports/api/CommandBus.py` + `_ports/api/QueryBus.py`. Both are `@runtime_checkable Protocol`-only, method bodies = `...`, signatures verbatim from existing `<Name>.protocol.py` stubs.
- [ ] **D-03.** `_ports/CATALOG.md` + `_ports/CATALOG.json` exist; JSON has exactly 124 entries; each entry has the 4 keys (`namespace`, `name`, `has_protocol_stub`, `port_status`).
- [ ] **D-04.** Catalog derivation procedure documented in `CATALOG.md`; a reviewer can re-derive 124 by running the documented `find … -prune` invocation.
- [ ] **D-05.** Compat shim added to `core/venous/api/CommandBus/__init__.py` and `core/venous/api/QueryBus/__init__.py` — exactly one re-export line each. Both legacy imports continue to resolve.
- [ ] **D-06.** Gate 1 (ruff on `_ports/`) green.
- [ ] **D-07.** Gate 2 (compat-shim `is` checks on both exemplars) green — verbatim `python -c` output pasted.
- [ ] **D-08.** Gate 3 (`adapt/extend/` does not import `_adapters/`) green — empty grep output proves it.
- [ ] **D-09.** Gate 4 (`adapt/_base/` does not import `_adapters/`) green — empty grep output proves it.
- [ ] **D-10.** Gate 5 (`tests/test_p0_regression_gates.py` + `tests/test_boot_chains.py` + `engine.audit.contract_check`) green; counts pasted verbatim.
- [ ] **D-11.** Type-only AST audit performed against every file under `_ports/`: zero non-stub method bodies, zero `def __init__`, zero top-level side-effects.
- [ ] **D-12.** `docs/architecture.md` appended with a single paragraph pointing at `core/venous/_ports/README.md` as the boundary's source of truth.
- [ ] **D-13.** `git diff --name-only main..HEAD` lists only paths inside §1 write surface; forbidden surface untouched.
- [ ] **D-14.** Self-review: agent re-read its own diff as an adversarial reviewer asking "does this actually formalize ADR-0001's hexagonal port promise, or just shuffle directories?" Findings pasted in PR body.

## 11. Risk callout (WP-15-specific — compat-shim plan, breaking-change risk, tech-lead decisions)

**Why this section exists:** WP-15 changes the import surface of the most-imported directory in the repo (`core/venous/`). A breaking change here ships as an `ImportError` on every consumer — `adapt/_base/`, the 100 `adapt/extend/` tools, the 17 FastAPI adapters, the `_staging/_quarantine` graveyard, every test in `tests/`. The shim plan is the difference between "ports formalized" and "WAVE 1 broken".

**The compat-shim plan — what changes, what doesn't, why it's safe.**

*Status quo (pre-WP-15) for the two exemplars:*

```
core/venous/api/CommandBus/
  __init__.py                    # re-exports CommandBus + CommandBusProtocol from sibling files
  CommandBus.py                  # the concrete CommandBus class
  CommandBus.protocol.py         # the auto-inferred CommandBusProtocol (Protocol with register + dispatch)
```

Consumers today import via:

```python
from core.venous.api.CommandBus import CommandBus               # the concrete class
from core.venous.api.CommandBus import CommandBusProtocol       # the auto-inferred Protocol
```

*Post-WP-15 (target):*

```
core/venous/_ports/
  api/CommandBus.py              # hand-authored CommandBusProtocol (THE port — single source of truth)
core/venous/api/CommandBus/
  __init__.py                    # MODIFIED: now re-exports CommandBusProtocol from _ports
  CommandBus.py                  # UNCHANGED (the concrete impl)
  CommandBus.protocol.py         # UNCHANGED (kept in place as catalog-derivation evidence)
```

*The one-line compat shim in `core/venous/api/CommandBus/__init__.py`:*

```python
# WP-15: re-export the formal port from core/venous/_ports/. Legacy import path stays valid.
from core.venous._ports.api.CommandBus import CommandBusProtocol  # noqa: F401
from core.venous.api.CommandBus.CommandBus import CommandBus  # noqa: F401
```

*What this guarantees:*

- `from core.venous.api.CommandBus import CommandBus` — still works (concrete class re-exported as before).
- `from core.venous.api.CommandBus import CommandBusProtocol` — still works, now resolves to the hand-authored port via re-export.
- `from core.venous._ports.api import CommandBusProtocol` — new canonical path, works.
- Both paths resolve to the same Protocol object (`is` check in gate 2), so `isinstance(x, CommandBusProtocol)` returns the same result regardless of which import path the caller used.
- The auto-inferred `CommandBus.protocol.py` is NOT deleted — it stays as catalog-derivation evidence. Callers that imported from it (`from core.venous.api.CommandBus.CommandBus.protocol import CommandBusProtocol`) are not broken either. The hand-authored port is the source of truth; the auto-inferred stub is now legacy evidence.

*Migration phasing (this WP ships phase 1 only):*

- **Phase 1 (THIS WP).** Establish `_ports/` directory + 2 exemplar ports + catalog + compat shim for the 2 exemplars. 122 primitives are catalogued as `port_status: queued`.
- **Phase 2 (follow-up WP, NOT this WP).** Author hand-typed ports for the remaining 122 registered primitives (in batches of 10-15 per WP, themed by namespace), with one-line shim per primitive.
- **Phase 3 (follow-up WP, NOT this WP).** Migrate `adapt/_base/` and `adapt/extend/` consumers to import from `_ports/` directly, deprecating the legacy import paths.
- **Phase 4 (follow-up WP, NOT this WP).** After a deprecation window, drop the auto-inferred `<Name>.protocol.py` stubs and the compat shim re-export lines. Legacy paths break at this point — but by then no consumer uses them.

*Tech-lead decisions flagged here (any "no" requires STOP-AND-ASK):*

| Decision | Default (this WP assumes) | If different, STOP-AND-ASK |
|---|---|---|
| Port directory location | `core/venous/_ports/` | If tech lead prefers `core/venous/ports/` (no underscore) or `core/ports/` (sibling of venous), stop |
| Exemplar pair | `CommandBus` + `QueryBus` (both `api` namespace, shared bus shape) | If tech lead prefers a cross-namespace pair (e.g. `IdempotencyStore` + `RequestContext`), stop |
| Empty-namespace handling | Ship `__init__.py` with `__all__ = []` + docstring | If tech lead prefers omitting empty namespaces entirely, stop |
| Compat shim form | Plain `from … import X` re-export | If tech lead prefers `__getattr__` module magic or a `TYPE_CHECKING`-gated form, stop |
| Auto-inferred stub fate | Keep `<Name>.protocol.py` in place as legacy evidence | If tech lead prefers deletion in this WP, stop (deletion is phase 4, not phase 1) |
| `runtime_checkable` | Apply on every hand-authored Protocol | If tech lead prefers opt-in only for ports with active runtime conformance use, stop |

**Backward-compatibility guarantee for in-flight WAVE-1 WPs:** because phase 1 ships a shim, every in-flight WAVE-1 sibling (WP-13, WP-14, WP-Z2, WP-C, WP-D, WP-F) sees zero ImportError-class regressions when WP-15 merges. WP-13's emitted event-driven code that imports `from core.venous.api.CommandBus import CommandBus` continues to work. WP-14's verify tools, which do not import from `core/venous/` at all, are unaffected. There is no merge-order dependency between WP-15 and sibling WAVE-1 WPs — they can land in any order.

**The one regression class the shim does NOT protect against:** if a sibling WP adds a NEW import of a third primitive (say `core.venous.events.OutboxRelay`) and WP-15's exemplars do not include `OutboxRelay`, the sibling's import works (because WP-15 did not touch `OutboxRelay`'s directory) — but `OutboxRelay` is not in the new port tree yet, so any code that wants to consume it as a port must use the legacy path. This is the *expected* state during the phased migration; it is NOT a regression.

**Model elevation rationale:** the 6 tech-lead decisions in the table above are not pattern-matching; they are architecture judgement calls. `opus` reasoning is required to (a) read 25 existing protocol stubs and decide which derivation patterns survive, (b) design a shim that satisfies both runtime `is`-identity AND static type-checkers, (c) produce a phasing plan that does not force a merge-order between WAVE-1 WPs. `sonnet` on this WP risks shipping a shim that passes `python -c` but breaks `mypy`, or a catalog that double-counts staged primitives, or a port directory layout that the first phase-3 consumer rejects on contact. The cost of getting this wrong is a re-do of phases 2-4, which is the bulk of the port-formalization work.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
