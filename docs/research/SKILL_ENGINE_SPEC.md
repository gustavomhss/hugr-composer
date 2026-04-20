# SkillEngine — Architecture Specification (L0–L4)

> The SkillEngine is the intelligent orchestrator that turns a user request
> into a production-grade project by composing venous-system primitives and
> SkillKit templates. It is the missing layer between the research catalog
> (`VENOUS_SYSTEM_CATALOG.md`) and the generated code SKILL-001 ships today.
>
> Paradigm: **Template + LLM hybrid**. 10–25× cheaper than pure-LLM generation,
> 5–10× faster, quality measured (not guessed). The template library *is* the
> moat; the LLM does domain modeling only.
>
> This document specifies every layer, every contract, every handoff, grounded
> in the 113 primitives and 111 standards already published.

## 1. Design principles

| Principle | What it means in practice |
|---|---|
| **Convention over configuration** | L0 fills every production default; an app author touches config only to deviate. |
| **LLM once, deterministically everywhere else** | L2 is the single paid call per project; L0 / L1 / L3 / L4 are $0. |
| **Rule-first, LLM-last** | L1 covers 80 % of tool selection by keyword matching. L2 only runs when rules are ambiguous. |
| **Measured quality** | Every generated project passes L4 validation (lint, type, test, contract); no soft-accept. |
| **Composable primitives** | Every output wires venous-system primitives (`CurrentPrincipal`, `UnitOfWork`, …) by their canonical Protocol shape. |
| **Traceable everywhere** | Each handler written in the output can be traced back to: (primitive used, tool invoked, source-cited pattern). |
| **Zero trust in LLM output** | L2's result is a typed `DomainModel`; if it cannot be parsed, the engine retries with schema hints, never accepts raw text. |

## 2. Pipeline flow

```
┌────────────────────────────────────────────────────────────────────────┐
│ INPUT                                                                   │
│   UserRequest { target: "python/fastapi", description, constraints }    │
└───────────────────────────────────────────┬────────────────────────────┘
                                            ▼
┌─────────────────────────────┐  L0 Convention — $0, ~50 ms
│ Apply ConventionDefaults    │  → Fills 24 L0 primitives with defaults
│ (24 always-on primitives)   │  → Output: PartialProject (scaffolding + core)
└───────────────────────────────────────────┬────────────────────────────┘
                                            ▼
┌─────────────────────────────┐  L1 Rules — $0, ~10 ms
│ Keyword → Tool selection    │  → Matches request tokens (auth, stripe,
│ (Spring Boot style          │     websocket, ml, cedar, ...) to
│  @ConditionalOn*)           │     SkillKit tools + L1+ primitives
└───────────────────────────────────────────┬────────────────────────────┘
                                            ▼
┌─────────────────────────────┐  L2 LLM — $0.02–$0.05, 3–5 s (ONE call)
│ Domain modeling             │  → Extracts typed DomainModel:
│ (ONE structured-output call)│     entities, relationships, routes,
│                             │     auth shape, compliance class
└───────────────────────────────────────────┬────────────────────────────┘
                                            ▼
┌─────────────────────────────┐  L3 Templates — $0, ~500 ms
│ Parameterized generation    │  → Runs each selected tool with the
│ (SkillKit tools as          │     DomainModel as input; produces files
│  parameterized templates)   │     wired to venous-system primitives
└───────────────────────────────────────────┬────────────────────────────┘
                                            ▼
┌─────────────────────────────┐  L4 Validation — $0–$0.05, ~5 s
│ Lint + type + test +        │  → ruff / mypy / pytest / contract audit;
│   contract audit            │     REGENERATES on failure (≤3 retries)
└───────────────────────────────────────────┬────────────────────────────┘
                                            ▼
┌────────────────────────────────────────────────────────────────────────┐
│ OUTPUT                                                                  │
│   BuildResult { artifact_root, primitives_used, tools_invoked,          │
│                 validation_report, provenance }                         │
└────────────────────────────────────────────────────────────────────────┘
```

**Total cost per project:** $0.02–$0.10 (LLM only in L2).
**Total wall time:** ~8–20 seconds target.

## 3. Contracts (Pydantic skeletons)

These contracts mirror the rigor of `briefing_contract.py` — every field
is schema-validated, every cross-field rule is a model_validator, every
output passes a gate before the next layer consumes it.

### `UserRequest` (engine input)

```python
from enum import Enum
from pydantic import BaseModel, Field

class Target(str, Enum):
    PYTHON_FASTAPI = "python/fastapi"
    # Future: rust/axum, typescript/nest, go/gin, ...

class UserRequest(BaseModel):
    target: Target
    description: str = Field(min_length=20, max_length=2000)
    constraints: list[str] = Field(default_factory=list, max_length=20)
    compliance_class: list[str] | None = Field(default=None)
    auth_mode: str | None = Field(default=None)
    # Declared optional features override L1 rule inference when present.
    feature_flags: dict[str, bool] = Field(default_factory=dict)
```

### `ConventionDefaults` (L0 output)

```python
class ConventionDefaults(BaseModel):
    project_root: str
    layout: str   # e.g. "src/"
    primitives_enabled: list[str] = Field(min_length=24, max_length=24)  # L0
    # Each entry is the canonical primitive name from the catalog.
```

### `ToolSelection` (L1 output)

```python
class ToolSelection(BaseModel):
    tools: list[str]  # e.g. ["fastapi_add_rbac", "fastapi_add_stripe_checkout"]
    primitives_to_instantiate: list[str]  # L1+ primitives selected by keywords
    inferred_auth_mode: str | None
    inferred_compliance_class: list[str]
    confidence: dict[str, float]  # per-selection 0..1 score
```

### `DomainModel` (L2 output — the only LLM-produced structure)

```python
class Entity(BaseModel):
    name: str = Field(pattern=r"^[A-Z][a-zA-Z0-9]*$")
    fields: dict[str, str]  # name -> Python type hint
    owner_of: list[str] = Field(default_factory=list)

class Route(BaseModel):
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: str
    handler: str
    auth: Literal["public", "authenticated", "role"] = "authenticated"

class DomainModel(BaseModel):
    entities: list[Entity] = Field(min_length=1, max_length=25)
    routes: list[Route] = Field(min_length=1, max_length=100)
    relationships: list[tuple[str, Literal["owns", "belongs_to", "has_many"], str]] = Field(default_factory=list)
    # L2 also fills auth_mode / compliance_class if UserRequest left them blank.
```

### `BuildResult` (engine output)

```python
class ValidationSummary(BaseModel):
    ruff_clean: bool
    mypy_clean: bool
    tests_passed: int
    tests_failed: int
    contract_audit: dict[str, bool]  # primitive-name -> contract-satisfied

class Provenance(BaseModel):
    primitive_name: str
    source_agent: int
    sources_cited: list[str]

class BuildResult(BaseModel):
    artifact_root: str
    primitives_used: list[Provenance]
    tools_invoked: list[str]
    validation: ValidationSummary
    duration_ms: int
    cost_usd: float
    llm_calls: int  # must equal 1 in the happy path
```

## 4. Per-layer specification

### L0 — Convention ($0 · ~50 ms)

**Scope.** Fill the 24 L0 primitives from `L0_CONVENTION_CANDIDATES.md` with
hardcoded defaults. No config required.

**Inputs.** `UserRequest.target`.
**Outputs.** `ConventionDefaults`.
**Failures.** Only if the target is unsupported.

**Implementation.** `core/convention/defaults.py` holds:
- per-target layout (for `python/fastapi`, SKILL-001's scaffolding is the default)
- per-primitive default factories (e.g. `default_di_container()`, `default_structured_logger()`)

**L0 invariants (inherit from the catalog + `L0_CONVENTION_CANDIDATES.md`):**
- Every L0 primitive has zero required arguments.
- Every L0 primitive MUST boot without any secret or config present.
- L0 never produces files; it produces an in-memory `ConventionDefaults`.

### L1 — Rules ($0 · ~10 ms)

**Scope.** Keyword-match the request against the tool catalog + L1+ primitive
catalog; emit a `ToolSelection`. Spring-Boot-style `@ConditionalOnClass` /
`@ConditionalOnKeyword`.

**Inputs.** `UserRequest.description` (tokenized), `UserRequest.constraints`,
 `UserRequest.feature_flags`.
**Outputs.** `ToolSelection`.

**Rule shape:**

```python
class Rule(BaseModel):
    tool: str                 # SkillKit tool name
    triggers: list[str]       # keywords / phrases
    primitives: list[str]     # venous-system primitives this tool wires
    requires: list[str] = Field(default_factory=list)  # prerequisite tools
    excludes: list[str] = Field(default_factory=list)  # mutually exclusive tools
    confidence_fn: Literal["exact", "stem", "cooccurrence"] = "stem"
```

**Invariants.**
- Rules are read-only data, hand-authored initially, grown from telemetry.
- A rule MUST name at least one primitive or be rejected (preserves traceability).
- Mutually-exclusive conflicts (e.g. `celery` + `arq` simultaneously) fail the pipeline; the user picks one.

**Example rules** (abbreviated):

```python
Rule(tool="fastapi_add_rbac", triggers=["role", "rbac", "permission"], primitives=["RequestGuard", "CurrentPrincipal"])
Rule(tool="fastapi_add_stripe_checkout", triggers=["stripe", "checkout", "payment"], primitives=["OutboundBinding", "TamperEvidentAuditLog"])
Rule(tool="fastapi_add_websocket_chat", triggers=["chat", "realtime message", "websocket"], primitives=["EventBus"])
```

**Coverage goal.** L1 alone should cover ≥ 80 % of tool selection on benchmark
requests. Measured with a held-out set.

### L2 — LLM ($0.02–$0.05 · 3–5 s · **one call**)

**Scope.** Extract a typed `DomainModel` from the user's natural-language
description. Single structured-output call to Claude.

**Prompt skeleton** (tight, token-conscious):

```
System: You are a backend domain modeler. Given a user request, emit a JSON
DomainModel matching the attached schema. No prose. No commentary.

Constraints:
- Every entity name is PascalCase, ≤ 30 chars.
- Every field uses Python type annotations: str, int, Decimal, date, datetime, list[T], dict[str,T], Optional[T], T|None.
- Infer relationships strictly (owns / belongs_to / has_many).
- If a field is a monetary amount, use Decimal.
- If a field is a timestamp, use datetime.
- Reject the request if entities cannot be inferred.

Schema: <DomainModel JSON schema here>

Request: <UserRequest.description>
```

**Retries.** If the LLM's response fails `DomainModel.model_validate`, retry
up to 3 times with the validation error appended to the prompt. Beyond 3
retries, surface the failure to the caller.

**Model routing.** Default: Haiku (cheap). Escalate to Sonnet on retry.
This is the **only** layer that spends money.

**Output.** `DomainModel` — strongly typed.

**Invariants.**
- Exactly one LLM call per happy-path project build.
- LLM is **never** asked to produce code directly.
- LLM output is **never** used unvalidated.

### L3 — Templates ($0 · ~500 ms)

**Scope.** Run each selected tool from `ToolSelection.tools` with
`(ConventionDefaults, DomainModel)` as input. Each tool is a
**parameterized template**: it emits files wired to venous-system primitives.

**Tool contract** (matches SKILL-001's existing MCP_TOOL shape, extended):

```python
class ToolRunInput(BaseModel):
    project_root: str
    convention: ConventionDefaults
    domain: DomainModel

class ToolRunOutput(BaseModel):
    files_created: list[str]
    files_modified: list[str]
    primitives_wired: list[str]   # must be a subset of venous-system catalog
    notes: list[str]
```

**Invariants.**
- Every file emitted MUST import its primitives from the canonical
  `core.venous.<namespace>` module — no raw re-implementations.
- Every mutation handler MUST wrap in `UnitOfWork` and emit through
  `TamperEvidentAuditLog` (L0 defaults).
- Every tool MUST be idempotent — re-running is a no-op.

### L4 — Validation ($0–$0.05 · ~5 s)

**Scope.** Prove the generated project passes the bar.

**Gates:**
1. `ruff check` — clean
2. `mypy --strict` — clean
3. `pytest -q` — all tests pass (including the consumption_example from every wired primitive)
4. **Contract audit** — each primitive wired in L3 satisfies its
   `PrimitiveSpec` contract from the catalog (name, api shape, invariants
   observable via unit test)
5. **Boot test** — app starts, `/livez` + `/readyz` return UP

**Retry policy.** On L4 failure, the engine may (a) retry L3 with the same
inputs (templates are idempotent, deterministic — should not help);
(b) retry L2 with the validation error as a hint (regenerate domain model);
(c) surface the failure to the caller with a structured error.

L4 **never soft-accepts**. A failed project is not an output.

## 5. Orchestration — the Engine itself

```python
class SkillEngine(Protocol):
    async def build(self, request: UserRequest) -> BuildResult: ...

class DefaultEngine:
    def __init__(
        self,
        convention_layer: ConventionLayer,   # L0
        rules_layer: RulesLayer,             # L1
        llm_layer: LLMLayer,                 # L2
        templates_layer: TemplatesLayer,     # L3
        validation_layer: ValidationLayer,   # L4
        telemetry: TelemetryClient,
    ): ...

    async def build(self, request: UserRequest) -> BuildResult:
        with self.telemetry.span("skill_engine.build"):
            convention = self.convention_layer.apply(request)     # L0
            selection = self.rules_layer.select(request, convention)  # L1
            domain = await self.llm_layer.model(request)          # L2 (one call)
            emitted = self.templates_layer.run(                   # L3
                request, convention, selection, domain
            )
            report = self.validation_layer.check(emitted)         # L4
            if not report.ok:
                # retry once via L2 with hints; else raise
                domain = await self.llm_layer.model(request, hints=report.errors)
                emitted = self.templates_layer.run(request, convention, selection, domain)
                report = self.validation_layer.check(emitted)
                if not report.ok:
                    raise EngineBuildFailed(report)
            return BuildResult.from_emission(emitted, report)
```

### Telemetry (every build)

- `skill_engine.build.duration_ms`
- `skill_engine.build.cost_usd`
- `skill_engine.build.llm_calls` (goal: 1)
- `skill_engine.build.primitive_count`
- `skill_engine.build.validation_retries`
- `skill_engine.build.outcome` = `success | l4_retry | failure`

## 6. Integration with SKILL-001

SKILL-001 already ships 175 MCP tools. The SkillEngine consumes them as L3
templates; it does **not** replace them. Migration path:

1. **Publish venous-system primitives.** Implement the 24 L0 primitives in
   `skills/SKILL-001-fastapi-production/core/venous/` per namespace. Each gets
   the canonical Protocol from the catalog.
2. **Rewire existing tools.** Each SKILL-001 EXTEND tool that already
   implements a primitive (per `SKILL_001_AUDIT.md` PRESENT + PARTIAL) is
   rewritten to import from `core.venous.<ns>` instead of rolling its own
   shape. The 3 RENAME items (`SagaOrchestrator`, `ChaosInjector`,
   `SignatureVerifier`) move here with deprecation shims.
3. **Add L1 rule entries** for every existing tool (one Rule per tool,
   triggers drawn from the tool's docstring).
4. **Build the engine** (`skills/SKILL-001-fastapi-production/engine/`) as a
   new module with its own Pydantic contracts; reuse `briefing_contract`'s
   validator patterns.
5. **Benchmark.** Replay the FinHealth benchmark (`benchmarks/run_finhealth.py`)
   through the engine; confirm 100/100 with ≤ 1 LLM call per project.

## 7. Implementation sequencing (critical path)

| Phase | Deliverable | Depends on | Est. effort |
|---|---|---|---|
| **P1** | 24 L0 primitives implemented in `core/venous/` | `L0_CONVENTION_CANDIDATES.md` (done) | 1–2 weeks |
| **P2** | RENAME shims for `SagaOrchestrator`, `ChaosInjector`, `SignatureVerifier` | RECONCILIATION.md (done) | 2 days |
| **P3** | L1 rule catalog (one `Rule` per existing EXTEND tool) | L1 Rule schema (this doc) | 3 days |
| **P4** | L2 LLM layer with `DomainModel` schema + retry loop | `DomainModel` contract (this doc) | 1 week |
| **P5** | L3 refactor — each EXTEND tool consumes `(ConventionDefaults, DomainModel)` | P1, P2, P3 | 2 weeks |
| **P6** | L4 validation runner + contract audit | P1, P5 | 1 week |
| **P7** | Engine orchestrator + telemetry | P1–P6 | 1 week |
| **P8** | FinHealth benchmark through engine | P7 | 3 days |
| **P9** | 10 PROMOTE primitives from RECONCILIATION.md | P1 | 2 weeks |

**Total critical path:** ~8–10 weeks for a complete engine over SKILL-001.

## 8. Open decisions

1. **LLM model default.** Haiku-first, Sonnet on retry? Or always-Sonnet for
   quality on v1? Data-driven: run a 20-project benchmark with each policy,
   pick the cheaper one that keeps 100% pass rate.
2. **Rule catalog authoring.** Hand-written first (≤ 200 rules for SKILL-001)
   vs. extracted from docstrings automatically. Start hand-written for quality;
   add extraction once the schema stabilizes.
3. **Retry policy on L4 failure.** Current spec: one L2-retry with hints.
   Alternative: also retry L3 with alternate tool selection. Start conservative.
4. **Multi-target naming (`python/fastapi` → `rust/axum`).** Does the engine
   produce one artifact per target or is the `Target` enum expanded per build?
   Pick per-build target; multi-target orchestration is out of scope for v1.
5. **Streaming output.** Should `build()` stream progress events? Yes, via the
   telemetry span tree — every layer emits its span in real time.

## 9. Cross-references

- `VENOUS_SYSTEM_CATALOG.md` — the 113 primitives the engine composes
- `CONTRACT_STANDARDS.md` — 111 numbered rules every engine artifact satisfies
- `SKILL_001_AUDIT.md` — current gap between catalog and SKILL-001
- `VENOUS_SYSTEM_GAPS.md` — prioritized list driving P1 / P9 phases
- `L0_CONVENTION_CANDIDATES.md` — exact L0 primitive set
- `RECONCILIATION.md` — 7 PROMOTE + 3 RENAME decisions
- `COLLISIONS_RESOLVED.md` — canonical `HealthProbe` + `RateLimiter` specs
- `RESEARCH_PHASE_SPEC.md` — the process that produced this corpus

---

*Template + LLM hybrid. 1 LLM call per project. 113 primitives. $0.02 per build.
That is the moat.*
