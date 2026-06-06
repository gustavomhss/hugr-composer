# ADR 0002 — Distribution strategy for `core.venous` primitives

Status: Accepted (2026-04-19)
Relates to: CONTRACT.md §B1.0, invariant A2, invariant A4
Supersedes: none

## Context

Tools under `adapt/extend/` are supposed to emit ≤ 20 lines of glue per
capability (invariant A1) by delegating real behaviour to primitives that
live in `core/venous/<ns>/<Name>/`. Today, every tool inlines that
behaviour as string-templated Python written into the generated project.
Result: ~500 LoC of boilerplate per tool, no single source of truth per
primitive, and the A1 / A2 contract is violated on every run.

Refactoring a tool to emit `from core.venous.resiliency.GracefulShutdown
import GracefulShutdown` immediately raises the question:

> The generated project has no `core/venous/` directory on disk and no
> pip-installed `hugr-venous` package. How does that import resolve
> at runtime in a freshly generated project?

Three strategies were considered:

- **A. Copy-in.** The skill copies the requested primitive source files
  into the generated project tree on first use. Generated project is
  self-contained; no runtime dependency on the skill repo.
- **B. PyPI package.** Publish `hugr-venous` to PyPI; generated project
  lists it in `requirements.txt` and imports from the installed package.
- **C. Path-bridge.** Generated project adds the skill repo to its
  `PYTHONPATH` / `sys.path` at startup so imports resolve against the
  live skill checkout.

## Decision

**Use strategy A (copy-in) for Phase 1.** Reassess PyPI (strategy B) when
we cut v1.0.

Strategy C is rejected outright.

## Rationale

- **Velocity over packaging overhead.** We are not yet in Phase 4
  (productize). A PyPI release cadence, semver contract, and
  backward-compat policy would cost us weeks of coordination for zero
  benefit while the primitive library is still churning. Copy-in
  lets us iterate on primitives without publishing every change.

- **Generated projects stay self-contained.** CONTRACT.md invariant
  for §B1.0 requires that a user who deletes the skill repo can still
  run the generated app. Copy-in satisfies that by construction.
  Path-bridge (strategy C) does not — a deleted skill repo would break
  every downstream project, and version drift between the repo and
  shipped code becomes undetectable.

- **Provenance is auditable.** A `.venous_manifest.json` at the root of
  every generated project records `{qualified_name, source_skill,
  source_commit, license}` per primitive. Running `ensure_primitives`
  twice is a no-op because the manifest tracks what's already shipped.

- **Idempotent + diff-reviewable.** Copy-in writes plain `.py` files the
  user can grep, diff, and hand-edit if needed. Each copied file carries
  an MIT attribution footer pointing back to the source commit — so a
  future `hugr upgrade-primitives` command can detect drift and surface
  it as a diff, not a silent overwrite.

- **Tests and formal artefacts stay in the skill.** We copy only the
  production surface — `<Name>.py`, `<Name>.md`, `<Name>.contract.json`,
  `invariant_bindings.json`, and `__init__.py`. TLA, audit reports,
  persona reviews, conftest, and tests stay in the skill because they
  are development artefacts, not runtime dependencies.

## Trade-offs

- **Duplicated source on disk.** A generated project with 12 primitives
  carries ~12 small directories it did not author. This is intentional:
  the user OWNS the code after generation, exactly like a Rails `rails
  new` drop. PyPI's "single shared install" is a non-goal in Phase 1.

- **Upgrading is a conscious action.** Users opt in to newer primitive
  versions by re-running the generating tool. Automatic background
  upgrades are out of scope; they become a v1.0 concern once the API
  surface stabilises.

- **Registry-level dependencies are a v1.0 concern.** Today the copy-in
  layer treats each primitive name the caller requests as a leaf — it
  copies that directory and stops. If a primitive depends on siblings,
  the caller lists them explicitly. When we add a formal `depends_on`
  key to `primitives_by_concern.yaml`, the resolver will traverse it;
  `compose_with` remains a composition hint and is NOT used for
  transitive copying (composition ≠ dependency).

## Consequences

- New module `generators/scaffold_venous.py` owns copy-in.
- `fastapi_generate_project` calls `ensure_primitives` once to smoke-test
  the pipe (`core.venous.resiliency.GracefulShutdown`).
- Tools refactored under §B1.3 begin their implementation with an
  `ensure_primitives(...)` call before emitting their ≤ 20 lines of glue.
- CONTRACT.md rule `B1.0` (added to `engine/audit/contract_check.py`)
  generates a sample project and asserts the import resolves.

## Revisit criteria

Revisit this ADR when any of the following holds:

- Benchmark score ≥ 50% AND ≥ 3 external users ask for a shared-install
  workflow.
- v1.0 ship criterion (CONTRACT §B5.2) clears and we need a SemVer
  contract for primitives.
- Generated-project disk footprint becomes a real complaint (unlikely
  at primitive sizes ~1-3 KB each).
