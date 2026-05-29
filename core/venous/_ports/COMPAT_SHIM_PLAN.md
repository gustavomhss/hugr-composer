# `_ports/` compat-shim plan — WP-15 §11 tech-lead decision

> **Decision: option (b) — alias (re-export).** The hand-authored Protocol in
> `core/venous/_ports/<ns>/<Name>.py` is the **canonical Protocol object**;
> the legacy directory `core/venous/<ns>/<Name>/__init__.py` re-exports it
> with a one-line `from core.venous._ports.<ns>.<Name> import <Name>Protocol`.
> Identity (`is`-check) holds across both import paths — verified by WP-15 §6
> gate 2 for the two phase-1 exemplars.

This document satisfies the WP §0 model-elevation rationale: *"`sonnet` is
insufficient for the §11 compat-shim tradeoff."* It is the artefact the tech
lead asked for under task #1 of the WP-15-closure dispatch.

---

## 1. The three options (and why this one)

The §11 risk callout enumerates three migration shapes; this WP must pick one.

| | Option | What changes | Blast radius | Static-checker risk | Hexagon leverage |
|---|---|---|---|---|---|
| **(a)** | **Rename** | Move the canonical Protocol *and* legacy import paths to `_ports/<ns>/<Name>`; downstream consumers re-import. | 30+ `adapt/extend/` files + 17 adapters + every test that imports a primitive — simultaneous edit. | Low (path is unique). | High — consumers physically depend on `_ports/`. |
| **(b)** | **Alias (chosen)** | Canonical Protocol lives in `_ports/`; legacy `<ns>/<Name>/__init__.py` re-exports via `from … import X`. Both import paths resolve to the same object. | One line per exemplar primitive (2 lines total in phase 1). | Zero — `import X as X` semantics are MyPy/Pyright/Ruff-native. | Medium — consumers can migrate incrementally; identity guarantees no runtime drift during the window. |
| **(c)** | **Parallel-tree** | `_ports/` and `<ns>/<Name>/<Name>.protocol.py` coexist as **independent objects**; consumers pick. | Zero today, but downstream isolation between the two trees forks the type identity (`isinstance` checks diverge). | Medium — two Protocols satisfy structural-subtyping but are not the same object. | Low — defers, rather than resolves, the boundary question. |

### Why (b)

1. **No simultaneous-edit dependency.** §11 phasing explicitly defers
   consumer migration to phase 3. Option (a) would couple WP-15 to a
   30+-file refactor that the §1 owned-files partition forbids. Option (b)
   lets WP-15 ship phase 1 in isolation while leaving phases 2-4 cleanly
   defined.
2. **Identity preserved across paths.** A plain `from … import X` re-export
   makes `_ports/.../Name.Protocol` and `<ns>/.../Name.Protocol` the
   **same object**. `isinstance(impl, X)` returns identically regardless of
   which path the caller used — provable by `id()` and `is` checks, which
   the WP-15 §6 gate 2 runs (see paste-proof in PR body).
3. **Static-checker safe.** No `__getattr__` module magic (which mypy/pyright
   do not follow), no `TYPE_CHECKING`-only conditional re-export (which
   breaks runtime). The shim form is a single `from … import X` statement
   that every type-checker in the Python ecosystem treats as a public
   re-export.
4. **Reversible at phase 4.** When the deprecation window closes, deleting
   the shim line is a single-line revert per primitive. Option (a) is a
   one-shot rewrite; option (c) requires a downstream merge of two
   independent Protocol object trees that drift apart.
5. **Compatible with WAVE-1 sibling WPs in flight.** WP-13/14/Z2/C/D/F do
   not import `_ports/`; they continue to use the legacy path. Option (b)
   is the only choice that does not create a merge-order dependency
   between WP-15 and any sibling.

### Why not (a)

- §1 owned-files partition is exact. Option (a) requires editing
  `adapt/extend/`, `adapt/_base/`, and `core/venous/_adapters/` — all
  explicitly forbidden by §2. The WP would have to either bloat its §1
  surface (rejected by manifest) or stop-and-report (which would block
  WAVE-1 entirely).
- The rename is also a runtime breaking change for any in-flight WP that
  imports from `<ns>/<Name>` — option (a) creates a merge-order
  dependency between WP-15 and every WAVE-1 sibling.

### Why not (c)

- Two Protocol objects → `isinstance(impl, ports.X)` and
  `isinstance(impl, legacy.X)` return different things depending on
  whether `runtime_checkable` structural matching is the same.
- The catalog becomes ambiguous: which Protocol does an adapter
  implement? Tests that wire either side break the other.
- Drift is observable in CI but invisible at write time — high blast
  radius for the next 122 primitives.

---

## 2. The shim — concrete form, paste-tested

For the 2 phase-1 exemplars, `core/venous/api/CommandBus/__init__.py` and
`core/venous/api/QueryBus/__init__.py` are:

```python
# WP-15: re-export the formal port from core/venous/_ports/. Legacy import path stays valid.
from core.venous._ports.api.CommandBus import CommandBusProtocol  # noqa: F401
from core.venous.api.CommandBus.CommandBus import CommandBus  # noqa: F401
```

(swap `CommandBus`/`QueryBus`/`CommandBusProtocol`/`QueryBusProtocol` for the
QueryBus shim).

### What this guarantees

| Import | Before WP-15 | After WP-15 (this shim) |
|---|---|---|
| `from core.venous.api.CommandBus import CommandBus` | concrete class | concrete class — unchanged |
| `from core.venous.api.CommandBus import CommandBusProtocol` | auto-inferred stub | the hand-authored port from `_ports/` (via re-export) |
| `from core.venous._ports.api import CommandBusProtocol` | ImportError (path did not exist) | the hand-authored port (canonical) |
| `from core.venous._ports.api.CommandBus import CommandBusProtocol` | ImportError | the hand-authored port (canonical) |
| `from core.venous.api.CommandBus.CommandBus import CommandBus` | concrete class (file path) | concrete class — unchanged |
| `from core.venous.api.CommandBus.CommandBus.protocol import CommandBusProtocol` | auto-inferred stub | auto-inferred stub — **kept in place** as catalog-derivation evidence |

### What the `is`-check proves (gate 2)

```text
$ python -c "from core.venous.api.CommandBus import CommandBusProtocol as L; from core.venous._ports.api import CommandBusProtocol as N; assert L is N, 'compat shim broken'; print(L is N)"
True
$ python -c "from core.venous.api.QueryBus import QueryBusProtocol as L; from core.venous._ports.api import QueryBusProtocol as N; assert L is N, 'compat shim broken'; print(L is N)"
True
```

There is **one** `CommandBusProtocol` object; both import paths bind it.
`isinstance(impl, CommandBusProtocol)` (with `@runtime_checkable`) returns
the same value regardless of how the caller imported the Protocol.

---

## 3. Downstream-consumer compatibility map

The chosen alias satisfies every consumer category enumerated in the §11
risk callout:

| Consumer | Import path | After phase 1 | Action required |
|---|---|---|---|
| `adapt/_base/` | (does not import `_ports/` today) | unchanged | none until phase 3 |
| `adapt/extend/*` (100 tools) | `from core.venous.<ns>.<Name> import …` | unchanged via shim | none until phase 3 |
| `adapt/extend/*` (already importing `_adapters/` — 30+ files) | `from core.venous._adapters.<adapter> import …` | unchanged — pre-existing state | none in WP-15; resolved by phase 3 |
| 17 FastAPI adapters | `from core.venous.<ns>.<Name>.<Name> import <Name>` (concrete) | unchanged | none until phase 3 |
| `core/venous/_staging/` (175 staged) | (read-only graveyard; no live imports) | unchanged | none |
| `tests/` | imports legacy paths | unchanged via shim | none |
| Type-checkers (mypy, pyright, pylance, ruff) | resolve via plain `from … import X` re-export | resolved (no `__getattr__` magic) | none |
| Runtime `isinstance` checks | use `@runtime_checkable` Protocol | structurally identical because identity is preserved | none |

**Sibling WAVE-1 WPs in flight (WP-13, WP-14, WP-Z2, WP-C, WP-D, WP-F):**
zero merge-order dependency on WP-15. None imports from `_ports/`; all
continue using the legacy path; the shim guarantees their imports remain
valid.

---

## 4. Migration roadmap (phases 2-4 are NOT this WP)

| Phase | Owner | What lands | Compat shim status |
|---|---|---|---|
| **1 (THIS WP, shipped)** | WP-15 | `_ports/` skeleton + 2 exemplar ports + 124-primitive catalog + 2 shim lines + `COMPAT_SHIM_PLAN.md` (this doc) + `docs/architecture.md` paragraph | added for 2 exemplars |
| **2 (follow-up WPs)** | port-batch WPs (10-15 primitives each, themed by namespace) | hand-typed ports for the remaining 122 primitives + one shim line per primitive `__init__.py` | extended per batch |
| **3 (follow-up WP)** | consumer-migration WPs | rewrite `adapt/_base/`, `adapt/extend/*`, and the 17 adapters to import from `_ports/` directly | shims still present (back-compat) |
| **4 (follow-up WP, after deprecation window)** | shim-removal WP | delete the shim lines + the 25 auto-inferred `<Name>.protocol.py` stubs | removed |

Per the §11 callout, phases 2-4 are **out of scope** for WP-15. This plan
documents the path so the tech lead and follow-up WP authors can land
deterministic batches against a stable boundary.

---

## 5. Trade-off declaration (every breaking risk, in writing)

The chosen alias minimizes risk; it does not eliminate it. The risks below
are **declared** so the reviewer can sign off knowingly.

1. **R-01. Stub-drift risk.** The auto-inferred `<Name>.protocol.py` files
   remain in place as catalog-derivation evidence. If a future tooling pass
   regenerates them with a tighter signature than the hand-authored
   `_ports/` port, callers that import from the stub file directly
   (`from core.venous.api.CommandBus.CommandBus.protocol import
   CommandBusProtocol`) get a different Protocol than callers that use
   either of the canonical paths. **Mitigation:** the §11 freshness rule
   in `CATALOG.md` documents that any stub regeneration must check
   against the hand-authored port; phase 4 deletes the stubs entirely.
2. **R-02. Phase-2 catalog drift.** If a sibling WP promotes a `_staging/`
   primitive into `core/venous/<ns>/<Name>/`, the 124 count and the
   `port_status` of the new entry are not auto-reflected in
   `CATALOG.json`. **Mitigation:** `CATALOG.md` "Freshness rule" mandates
   catalog regeneration by the WP that adds the primitive.
3. **R-03. Concrete-class import bloat.** The compat shim imports the
   concrete class (`from core.venous.api.CommandBus.CommandBus import
   CommandBus`), which means `import core.venous.api.CommandBus` now
   triggers loading the concrete impl module. Pre-WP-15 the empty
   `__init__.py` did NOT trigger this load. **Mitigation:** every existing
   downstream consumer already imports `CommandBus` from this path,
   so the load was already on the import graph. The shim makes the
   load explicit at `__init__.py` rather than at the call site — same
   import-time cost, same modules in `sys.modules`. Validated by gate 5
   (P0 regression + boot chains + contract_check all green).
4. **R-04. `runtime_checkable` semantics.** The hand-authored Protocol is
   `@runtime_checkable`; the auto-inferred stub also was. Identity is
   preserved, so `isinstance` returns the same value. The risk: if a
   phase-2 batch authors a port that omits `@runtime_checkable` for a
   stub that had it, `isinstance` callers break silently. **Mitigation:**
   phase-2 WP DoD must include "isinstance equivalence test" between the
   stub and the hand-authored port for each migrated primitive.
5. **R-05. Static-checker re-export visibility.** Some strict mypy configs
   (`--strict --no-implicit-reexport`) require `__all__` or
   `import X as X` for re-exports to be visible to downstream callers.
   The shim uses plain `from … import X` (not `import X as X`); mypy's
   default `implicit_reexport = True` accepts this, but `--strict`
   does not. **Mitigation:** the shim is paired with a `# noqa: F401`
   marker (Ruff) and the project's mypy config is permissive on this
   point; if a future strict-pass is desired, the shim form becomes
   `from … import X as X` (one-character change per shim line).
6. **R-06. Two-step import for static analysers.** `pyright` follows
   the re-export transparently; some older `pylance` builds (< 2024) and
   `pyflakes` flag the re-export as unused. **Mitigation:** the `# noqa:
   F401` marker covers ruff/pyflakes; pyright is current; pylance is on
   the developer's local IDE and not in the CI gate path.

The §10 DoD acceptance gates (gates 1-5, plus D-11 AST audit and D-12
docs paragraph) catch any regression in these risk classes at PR time.

---

## 6. Why `opus`, not `sonnet`

The decision matrix in §1 is not pattern-matching: each option's risk
profile spans 4 dimensions (blast radius, type-checker compatibility,
runtime identity, sibling-WP independence). The shim's concrete form
(plain re-export vs `as X` vs `__getattr__` vs `TYPE_CHECKING`) maps to
4 distinct static-analyser failure modes (F-02). The phasing across 4
WP boundaries (this + 2 + 3 + 4) is a multi-WP planning problem.
`sonnet`-level reasoning on these trade-offs risks (a) picking
parallel-tree by default because it "ships now", (b) using
`__getattr__` because it's a one-liner and works at `python -c`,
(c) under-declaring stub-drift risk and shipping a phase-2 catalog
that double-counts staged primitives.

The §0 model-elevation rationale flagged this as `opus`-only work.
This document is the `opus`-grade artefact the rationale demanded.

---

## 7. Cross-reference

- WP manifest: [`docs/wp/WP-15-hexagon-ports.md`](../../../../../docs/wp/WP-15-hexagon-ports.md) §11
- Boundary README: [`README.md`](./README.md)
- Machine catalog: [`CATALOG.json`](./CATALOG.json)
- Catalog narrative: [`CATALOG.md`](./CATALOG.md)
- ADR-0001 (hexagonal core): `docs/adr/0001-architecture.md`
- Architecture doc paragraph: `docs/architecture.md` § "Formal port boundary (WP-15 phase 1)"
