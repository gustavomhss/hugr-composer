# How I built this

This repository was built the way I think AI-infrastructure work is heading:
not one model in a chat window, but a **fleet of code agents driven by a
tech-lead orchestration layer, under a quality contract that machines
enforce.** I held the judgment — architecture, decomposition, the acceptance
gate — and delegated execution. The system below is the point of the
portfolio; the FastAPI skill is what it produced.

## The thesis

A single agent degrades on large, dependent work: context blows up, it
invents interfaces mid-stream, and "done" becomes a claim you can't trust.
The fix is the same one a good tech lead uses on humans — decompose,
contract, delegate, verify — but mechanized so the loop is cheap enough to
run at fleet scale. Every anti-pattern below has a corresponding gate.

## The loop

**1. Decompose, test-first.** The demand is externalized as a *failing
acceptance suite* before any work is sliced. An independent cold critic
confirms the suite actually covers the demand. Only then is the work cut into
atomic, conflict-disjoint work-packages. Completeness is anchored on the
red→green suite, never on the slice — so a bad cut is *slower*, never
half-built and shipped.

**2. Freeze the contract.** For dependent work, the shared types and
signatures are frozen up front and handed to each agent as anchor code to
*transcribe*, not design. Agents work in parallel against a compilable stub
of an interface that can't drift underneath them.

**3. Delegate with a pre-digested packet.** Each agent gets the target
marked, the blast radius chewed, and a return-shape it must honor — so it
executes without burning context on discovery and without dumping its raw
work back into the orchestrator. The orchestrator's context stays clean
enough to run the whole wave.

**4. Verify cold.** Every deliverable is reviewed by an agent that never saw
the author's conversation, against the spec and the invariants — with
mechanical evidence (AST-aware diffing, mutation-scoped tests), not vibes.
Findings are adversarially confirmed before they count.

**5. Integrate on green, roll forward.** Work merges as each branch seals
green under a change-scoped gate — the DAG is the *merge* order, not a
dispatch barrier. Post-flight sweeps catch off-baseline branches and leaks.

## The gates that make "done" mean something

- **The blind A/B eval** (`engine/bench/blind/`) is the acceptance gate for
  the toolset itself. It runs the same agent *with* and *without* the kit
  across sealed specs, boots each emitted app, and judges it on five layers —
  functional, property, concurrency, chaos, static-AST. If the kit doesn't
  measurably improve the output, it doesn't ship. This is how "the tools help"
  stops being a claim.
- **The AST contract audit** (`engine/audit/`, 47 rules) is the mechanical
  quality gate every change passes — no module-level mutable state, init
  inside lifespan, write-schemas `extra="forbid"`, authed admin routes, no
  dead security features. Drift between a doc and the machine count is itself
  a failing rule.
- **The promotion pipeline** (`engine/promotion/`) governs agent-generated
  building blocks into the production library: atomic backup → promote →
  re-verify → auto-rollback, gated on the contract check, with a
  human-reviewable ledger. Nothing enters the library on trust.

## Honest boundaries

- **Where the engine lives.** The reusable orchestration/audit/promotion core
  was lifted into an external `hugr_core` package; this repo is the instance
  that exercises it. Several modules here are thin shims over that library —
  visible in the commit history as "consumer flips." I'd showcase `hugr_core`
  as the reusable engine and this repo as its proving ground.
- **What agents did vs. what I did.** Agents wrote code against frozen
  contracts and failing suites. I owned the architecture, the decomposition,
  the acceptance criteria, and every merge decision. The interesting
  engineering is the harness that made fleet execution trustworthy — not any
  single generated file.

## Map to the code

| The idea | Where it lives |
|---|---|
| Blind A/B eval harness | `engine/bench/blind/` |
| AST contract audit (47 rules) | `engine/audit/` |
| Governed promotion + rollback | `engine/promotion/` |
| Progressive-disclosure MCP surface | `mcp_tools/` |
| Framework-free primitive library | `core/venous/` |
| Reusable engine core (external) | `hugr_core` package |
