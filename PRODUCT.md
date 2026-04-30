# HuGR Smith — Product Understanding

> **Status:** canonical v1 — 2026-04-19.
> **Purpose:** the one document that answers "what are we actually building,
> for whom, and how do we know it's working." Supersedes every prior
> scattered claim in SKILL.md, README, and CLAUDE.md.

---

## 1. What HuGR Smith IS, in one paragraph

HuGR Smith is a **library of executable knowledge** that an LLM agent
(we call it the **Maestro**) can invoke to scaffold AND customize
production backend applications. The kit is structured like Ruby on Rails
— a macro scaffold, a catalogue of slice generators, and a curated library
of reusable building blocks the generated code references by import rather
than by copy-paste. The Maestro uses the kit to turn plain-English product
requirements into running, tested, production-grade code.

---

## 2. The three-layer architecture

Borrowing Rails terminology because it maps precisely:

| Layer | Rails analogue | HuGR name | Purpose |
|---|---|---|---|
| **Skill** | `rails new` | `SKILL-001-fastapi-production` | A macro scaffold that lays down a canonical project tree. One skill = one framework × one maturity (e.g. FastAPI production, Next.js production, Django lightweight). |
| **Tools** | `rails g model/controller/migration` | `adapt/extend/add_*.py` (and peers) | Slice generators. Each tool mutates a scaffolded project to add ONE capability (`add_stripe_webhook`, `add_rbac`, `add_soft_delete`). Tools are the "80% common path". |
| **Primitives** | `ActiveRecord::Base`, `ActiveSupport`, `ActionController` | `core/venous/<namespace>/<Name>/` | Reusable building blocks. Imported by generated code (Rails style), composed by the Maestro when tools don't cover a nuance. Primitives are the "20% customization headroom". |

**Crucial Rails lesson** (validated by research): generated code is a
SEED, not a cage. `rails g model User` emits five lines; the power lives
in `ActiveRecord::Base`. If a HuGR tool emits 80 lines of inline logic,
we've built Yeoman, not Rails. Tools MUST be thin scaffolds over
primitives.

---

## 3. Who uses it, in what mode

**Primary user: the Maestro LLM agent.**

- Discovers the skill via Claude Skills / MCP metadata (~100 tokens).
- On user intent (e.g. "build SaaS with auth + Stripe"), Maestro loads
  `SKILL.md` (~5k tokens), picks tools, and executes.
- When a tool doesn't fit exactly, Maestro **composes primitives**
  directly into the generated code using an indexed, searchable
  catalogue.
- Maestro NEVER hand-writes what a primitive already provides —
  primitives are load-bearing for generated output.

**Secondary user: the human developer.**

- Drops into the project post-scaffold, edits, tests, ships.
- Reads the same docs the Maestro reads (primitive reference, tool
  reference, composition recipes).
- Can run the MCP server locally against Claude Desktop / Cursor / Zed
  for interactive skill invocation.

---

## 4. Success criteria (how we know it works)

A single measurable outcome:

> **The Maestro, given a plain-English product spec, produces a running,
> tested, production-grade backend in a single session — passing all 10
> quality gates (T0-T9) with no human-authored code required.**

Concrete benchmark harness (Phase 3 of roadmap): 20 realistic specs (SaaS
auth, Stripe integration, multi-tenant admin, realtime chat, LLM agent
backend, etc.). Score: **% of specs where Maestro ships green in one
session**.

Target: **≥ 70% on the canonical benchmark** before declaring the kit
"SOTA". Measure per release.

---

## 5. Non-goals (explicit boundaries)

- **NOT a general-purpose agent framework.** No planning, no memory, no
  multi-agent orchestration. Maestro brings the brain; we bring the
  hands.
- **NOT a LangChain/CrewAI competitor.** We are ONE tier above: a skill
  the agent invokes, not an agent runtime.
- **NOT a code-generation gimmick.** If generated code can't be hand-
  edited by a senior engineer without friction, we've failed. Generated
  code must be idiomatic and boring.
- **NOT a framework lock-in.** One skill per framework; SKILL-001 is
  FastAPI. The architecture doesn't presume anything else.
- **NOT aspirational documentation.** Every claim in this doc must map
  to code on disk. See `ROADMAP.md` for the gap between current reality
  and this contract.

---

## 6. Design invariants (the rules we don't break)

1. **Tools emit ≤ 20 lines of glue.** Logic lives in primitives the
   generated code imports. Breaking this rule turns us into Yeoman.
2. **Primitives are orthogonal.** Each does one thing; composition is
   the user's job. No god-primitives.
3. **Generated code survives hand-editing.** Running a tool twice does
   not clobber user changes (idempotency fingerprints, verified).
4. **Every primitive has a docs page with ≥3 composition examples.**
   Discoverability is Rails-API-docs style: flat, searchable, per-
   symbol URL.
5. **Every tool has an MCP metadata block.** Auto-discovery by the MCP
   server is mandatory — no manual registration drift.
6. **A semantic registry indexes every primitive.**
   `engine/primitives_by_concern.yaml` lets the Maestro find the right
   Lego piece in one query.
7. **The SKILL.md manifest is the single source of truth for counts and
   capabilities.** Docs drift = audit bug.

---

## 7. Competitive positioning

| Alternative | What it does | What HuGR does differently |
|---|---|---|
| Raw LLM + FastAPI knowledge | Generates one-off code per request | Curated primitives → consistency + invariant-enforced quality |
| Yeoman / scaffolding CLIs | Emits boilerplate then walks away | Primitives + composition recipes → customization headroom without regeneration |
| LangChain / CrewAI | General-purpose agent frameworks | We are ONE skill invocable BY those agents; not a runtime |
| Anthropic reference skills | Domain tasks (PDF, Excel) | We target full-stack production backends |
| Rails / Django | Human-first frameworks | Maestro-first: every primitive designed for LLM composition (registry, compose-with recipes, structured contracts) |

---

## 8. Terminology lock

To end the terminological confusion that prompted this doc:

- **Skill** — macro scaffold + metadata. ONE per framework × stack. Right
  now we have SKILL-001 (FastAPI prod).
- **Tool** — atomic slice generator. `add_*.py` under `adapt/extend/`.
  Maestro-invocable via MCP.
- **Primitive** — reusable class/function in `core/venous/<ns>/<Name>/`.
  IMPORTABLE by generated code AND composable by the Maestro.
- **Generator** — (legacy term, used in older docs) = tool. Prefer
  "tool" going forward.
- **Adapter** — a kind of primitive that wraps a third-party SDK
  (boto3 / Redis / Stripe). Not a separate layer.
- **Verb** (in AS/AC sense) — a primitive method like `validates`,
  `before_action`. Not a separate concept in HuGR; just what primitives
  expose.
- **Recipe** — a `.md` section showing 1-3 primitives composed into a
  concrete pattern. Lives in the primitive's own `.md`.
- **Maestro** — the LLM agent that invokes the skill. Not our code;
  belongs to Anthropic / OpenAI / etc.
- **Benchmark harness** — the set of plain-English specs we evaluate
  Maestro-success-rate against. Lives in `benchmarks/`.

Any claim in any file that doesn't map to one of these terms is drift
and must be reconciled.

---

## 9. What exists today vs what this doc promises

See `ROADMAP.md` for the honest gap analysis and the phased plan to close
it. This doc describes the CONTRACT; the roadmap describes the CURRENT
STATE + HOW WE GET THERE.
