# ADR 0003 — Adapter layer between primitives and tools

Status: Accepted (2026-04-19)
Relates to: CONTRACT.md §B1.0.1, invariant A1, invariant A3, ADR 0002
Supersedes: none

## Context

ADR 0002 commits us to copy primitives from `core/venous/<ns>/<Name>/`
into the generated project and to emit tools that import them. But the
first candidate we tried — `GracefulShutdown` — exposes a gap:

- `core.venous.resiliency.GracefulShutdown.GracefulShutdown` is a pure
  state machine: `register()`, `increment_in_flight()`,
  `wait_complete()`. Zero FastAPI awareness.
- The current `add_graceful_shutdown` tool writes ~500 lines of inline
  code that wires `@app.on_event("shutdown")`, a drain middleware,
  and a health-gate dependency into the primitive.

A naive refactor would either:

1. Push FastAPI-specific code INTO the primitive (breaking A3
   framework-agnostic primitives, and preventing SKILL-002 from
   reusing it), or
2. Leave the tool's 500 lines untouched (breaking A1 ≤ 20-line glue).

Neither is acceptable. We need a third tier.

## Decision

Introduce an **adapter layer** at `core/venous/_adapters/<framework>/`.

- One adapter per `(framework, primitive)` pair where framework glue
  is needed. Not every primitive needs one.
- Adapter imports the primitive and exposes a framework-idiomatic
  API (`install(app, ...)`, middleware factory, `Depends`-compatible
  helpers).
- Adapter is ≤ 30 LoC of pure glue. It may NOT contain business logic
  beyond wiring the primitive to the framework's hooks.
- Tool refactor: the tool copies the primitive + copies the adapter,
  then emits ≤ 20 lines of glue whose only job is to call
  `<Name>Adapter.install(app, ...)`.

## Invariant enforced

```
grep -rlE 'from (fastapi|starlette|sqlalchemy)' core/venous/ \
  | grep -v _adapters   # → empty
```

No framework import leaks into `core/venous/<ns>/`. Only
`core/venous/_adapters/<framework>/` may import the framework.
Added as rule `B1.0.1` in `engine/audit/contract_check.py`.

## Rationale

- **Primitives stay reusable across skills.** SKILL-002 (e.g. Django,
  Litestar, Go) can ship its own `_adapters/<framework>/` directory
  over the same primitives with no changes to the primitive itself.
  This is how we hit CONTRACT §B6.2 ("≥ 30 shared primitives").

- **Composability is preserved.** An adapter depends on ≤ 2 primitives
  (enforced by review). Multi-primitive adapters would become
  "god-primitives" in disguise and erode orthogonality (A3).

- **Tools shrink honestly.** The ≥ 40% LoC drop that §B1.3 demands
  is unreachable if glue has nowhere to go. With an adapter tier, a
  tool legitimately collapses to: copy primitive → copy adapter →
  write 15-line caller.

## Why not a god-primitive?

An adapter is deliberately narrower than a primitive:

- An adapter has NO invariants of its own. All correctness lives in
  the primitive.
- An adapter has NO state. All state lives in the primitive.
- An adapter does NOT appear in the primitives registry
  (`primitives_by_concern.yaml`). It is not a composable building
  block; it is last-mile plumbing.
- An adapter has exactly one import: the primitive it wraps (plus the
  framework itself).

If an "adapter" ever grows state, invariants, or multi-primitive
awareness, it has become a primitive and must move into
`core/venous/<ns>/` and gain a manifest.

## Trade-offs

- **Two files to maintain per capability** (primitive + adapter) versus
  one monolithic tool-emitted blob. This is a deliberate Rails-style
  separation: primitive = model/service, adapter = Rails concern,
  tool = generator.

- **Adapter test surface is small** (3 tests per adapter: import, wiring,
  behaviour delta). Primitive tests remain authoritative for
  correctness; adapter tests only prove the framework hook fires.

- **New rule in contract_check** ups the CI line count by ~15 lines.
  Trivial cost for the invariant gain.

## Consequences

- `core/venous/_adapters/fastapi/GracefulShutdownAdapter.py` is the
  reference; 14 more adapters come in §B1.3 cohort agents.
- `add_graceful_shutdown` refactor is the reference tool shape for
  the §B1.3 cohort.
- Rule `B1.0.1` joins `engine/audit/contract_check.py`.
- A new primitive that needs FastAPI glue adds an adapter in the same
  PR that adds the primitive.

## Revisit criteria

Revisit when we add a second framework (SKILL-002) and learn whether
`core/venous/_adapters/<framework>/` is the right location, or whether
adapters should live alongside the framework skill.
