# ADR-0001: Architecture — hexagonal core + plugin tools + phased pipeline, as a modular monolith

- **Status:** accepted
- **Date:** 2026-05-27
- **Deciders:** Gustavo + maintainers

## Context
HuGR Arsenal is not a web app — it is a **code-generation toolkit / meta-framework**
delivered over MCP and gated by a license API. So its ideal architecture is that of
successful code generators (JHipster, Yeoman, OpenAPI Generator, Nx), not of the apps
it emits. The current code already has good bones (a framework-agnostic `core/venous`
primitive layer + `_adapters/fastapi`, a plugin set of 99 compose tools, a scaffold
generator, an audit engine) but they are buried under: ~12 monolithic 1200–2100 LOC
tool files (embedded code-as-strings), a 3000-file `_staging/_quarantine` staging
graveyard in the main tree, 724 of 759 markdown files scattered through the code, and
ad-hoc discovery/patching duplicated across tools (the source of repeated composition
bugs found by external eval panels).

## Decision
Adopt a **hybrid by layer**, matching how mature code generators are built:
- **Hexagonal (ports & adapters)** for `core/venous` — framework-agnostic primitives
  (the hexagon) + `_adapters/fastapi` (driven adapters). Formalize the ports. This is
  what allows emitting other frameworks later by adding adapters.
- **Plugin architecture** for the compose tools — each `add_*` is a plugin against a
  stable contract (`ToolInput`/`ToolResult` + `MCP_TOOL` registry).
- **Phased pipeline** per tool — `discover() → plan() → write() → patch() → verify()`
  over a shared `adapt/_base/`, replacing per-tool ad-hoc discovery/patching.
- **Externalized templates** — emitted code lives in `templates/*.py.tmpl`, never in
  Python string literals.
- **Modular monolith** packaging — one repo, bounded modules (core/generators/adapt/
  engine/hugr_auth), in-process; the MCP server + license API is the one separate service.

NOT event-driven for the kit itself (a generator is a synchronous transform; EDA belongs
in the *emitted* apps). NOT microservices (over-engineering for a toolkit).

## Alternatives considered
- **Pure modular monolith, no hexagon** — rejected: loses the framework-agnostic core
  that makes multi-framework emission possible.
- **Event-driven kit** — rejected: codegen is synchronous; EDA adds no value to the transform.
- **Rename `adapt/extend/` → `tools/`** — deferred: clearer but churns import paths repo-wide;
  navigability is recovered via the per-tool directory layout instead.

## Consequences
- **Positive:** superfiles shrink to ~300 LOC of logic (templates externalized); discovery/
  patching deduped (kills a whole bug class); core stays swappable; repo becomes navigable.
- **Trade-offs:** a one-time large refactor (parallelized into Work Packages, see `docs/wp/`);
  more, smaller files.
- **Follow-ups:** the WP waves (`docs/wp/`), file-size + structure checks (`scripts/checks/`),
  relocate `_staging` to `_staging/`, concentrate docs in `docs/`.
