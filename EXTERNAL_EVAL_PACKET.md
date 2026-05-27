# HuGR Arsenal — External Evaluation Packet (cold run)

Hand this, unedited, to an independent evaluator (a frontier model with a fresh
context — Codex/GPT/Claude — or a human engineer). The point is a verdict from
someone who did NOT build it and has no stake. Run each evaluator **independently**
(no shared chat, no peeking at others' verdicts), then compare.

---

## Your role

You are a **skeptical senior backend engineer** assessing a commercial
code-generation product, **HuGR Arsenal**, for adoption by your team. You have
no prior knowledge of it and no loyalty to it. **Your job is to find the reasons
NOT to adopt it.** Sycophancy is worthless here; be adversarial and concrete.

## What the product claims to be

A library of **framework-free FastAPI primitives** + **tools** that an LLM agent
composes to **scaffold and extend production FastAPI backends** — faster and more
correct than writing from scratch, because it assembles audited pre-built pieces.

## The task

1. **Invent your OWN realistic spec** — 3–5 models, auth, some real domain logic.
   Something *you* would actually build. **Do NOT reuse any example in the repo**
   (`/examples`, `benchmarks/specs`). Pick a domain the repo doesn't obviously
   target.
2. **Drive the kit cold** to scaffold + extend a project for your spec.
   - Working dir: `skills/SKILL-001-fastapi-production`
   - Interpreter: `.venv/bin/python` with `PYTHONPATH=.`
   - Scaffold: `from generators.orchestrator import generate_project` →
     `generate_project(output_dir, name, models={"Foo": {"field": "str", ...}}, owner_models={"Foo": "user"}, with_auth=True, with_docker_compose=False, with_ci=False, with_otel=False, with_prometheus=False)`
   - Configure the emitted project's `.env`: `SECRET_KEY=<64 hex chars>`,
     `ENVIRONMENT=local`, `FIRST_SUPERUSER_EMAIL=...`, `FIRST_SUPERUSER_PASSWORD=testpassword123`
   - Extend via compose tools under `adapt/extend/*`:
     `from adapt.contracts import ToolInput; from adapt.extend.crud_data.add_search import add_search; add_search(ToolInput(project_dir=str(OUT)))`
     (browse `adapt/extend/` for the catalog: search, cursor_pagination,
     bulk_operations, audit_log, rbac, mfa, multi_tenancy, webhooks, etc.)
3. **Exercise the output**: boot it (`from app.main import app`), run its emitted
   `pytest tests/`, and **read the generated code** — judge security (auth,
   secrets, SQL), structure, and whether it's real vs stubbed.
4. **Judge it.**

## Output — fill EXACTLY this rubric

```
COLD SPEC:            <the spec you invented>
WHAT WORKED:          <bullets>
WHAT BROKE / RED FLAGS: <bullets — you MUST list at least 3 concrete concerns>
CODE QUALITY (1-5):   <score> — <one line why>
SHIP-READINESS (1-5): would you put the emitted app in production? <score> — <why>
WOULD YOU PAY:        as a senior eng, pay for this vs writing it yourself?
                      YES/NO + max $/seat/month + reasoning
ONE-LINE VERDICT:     ship / don't ship + the single biggest reason
```

Be brutal. A useless "looks great" helps no one.
