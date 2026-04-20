"""
10 builder briefings — one per Sonnet agent that implements primitives.

Loads the 115 primitive specs from the 8 research deliverables (the output of
the earlier research phase), assigns each primitive to exactly one builder
batch (1..10), sanity-checks the partition, and renders a token-tight prompt
for each builder agent.

Validated at import time. Any drift between the research catalog and the
assignment map aborts import.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import BaseModel, Field, field_validator, model_validator

HERE = Path(__file__).resolve().parent
ENGINE_ROOT = HERE.parent
SKILL_ROOT = ENGINE_ROOT.parent
REPO_ROOT = SKILL_ROOT.parent.parent
RESEARCH_OUT = REPO_ROOT / "docs" / "research" / "outputs"

sys.path.insert(0, str(ENGINE_ROOT))

from contracts.primitive_delivery_contract import Maturity  # noqa: E402


# ---------------------------------------------------------------------------
# Is-stateful heuristic — agents can override per primitive via the CLI.
# Primitives with in-memory/session state, shared registries, or async
# coordination are stateful; pure functions and value types are not.
# ---------------------------------------------------------------------------
_STATEFUL_NAMESPACES = frozenset({
    "auth", "data", "events", "jobs", "cache", "resiliency", "llm", "cost",
})
_STATELESS_NAME_PREFIXES = ("Config", "Value", "Semantic", "Resource", "Histogram",
                            "Encryption", "Policy", "Key", "Retention")


def _infer_stateful(name: str, namespace: str, api_signature: str) -> bool:
    if namespace not in _STATEFUL_NAMESPACES:
        return False
    for pref in _STATELESS_NAME_PREFIXES:
        if name.startswith(pref):
            return False
    # Protocol with only read-only @property-style attributes is stateless.
    # A rough signal: the presence of `async` or `register_*` strongly suggests state.
    if "async def" in api_signature or "register_" in api_signature or "acquire(" in api_signature:
        return True
    # Dataclass frozen without methods → value object → stateless.
    if "dataclass(frozen=True)" in api_signature and "def " not in api_signature.split("class ", 1)[-1]:
        return False
    return True


# ---------------------------------------------------------------------------
# PrimitiveAssignment — one primitive assigned to one builder batch.
# ---------------------------------------------------------------------------
class PrimitiveAssignment(BaseModel):
    name: str = Field(pattern=r"^[A-Z][a-zA-Z0-9]*$", max_length=40)
    namespace: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=30)
    maturity: Maturity
    is_stateful: bool
    source_agent_id: int = Field(ge=1, le=8)
    catalog_spec: dict = Field(description="Full PrimitiveSpec dict from the research deliverable.")

    @model_validator(mode="after")
    def catalog_matches_identity(self) -> "PrimitiveAssignment":
        if self.catalog_spec.get("name") != self.name:
            raise ValueError(
                f"catalog_spec['name']={self.catalog_spec.get('name')!r} != assignment name {self.name!r}"
            )
        if self.catalog_spec.get("namespace") != self.namespace:
            raise ValueError(
                f"catalog_spec['namespace']={self.catalog_spec.get('namespace')!r} "
                f"!= assignment namespace {self.namespace!r}"
            )
        if self.catalog_spec.get("maturity") != self.maturity.value:
            raise ValueError(
                f"catalog_spec['maturity']={self.catalog_spec.get('maturity')!r} "
                f"!= assignment maturity {self.maturity.value!r}"
            )
        return self


# ---------------------------------------------------------------------------
# BuilderBatchBriefing — sealed mission for one builder agent.
# ---------------------------------------------------------------------------
class BuilderBatchBriefing(BaseModel):
    batch_id: int = Field(ge=1, le=10)
    codename: str = Field(pattern=r"^[A-Z][A-Z0-9_]+$", max_length=40)
    rationale: str = Field(min_length=40, max_length=400)
    primitives: list[PrimitiveAssignment] = Field(min_length=5, max_length=25)
    contract_path: str = Field(default="skills/SKILL-001-fastapi-production/engine/contracts/primitive_delivery_contract.py")
    check_cli_path: str = Field(default="skills/SKILL-001-fastapi-production/engine/check_primitive.py")
    standards_doc_path: str = Field(default="docs/research/CONTRACT_STANDARDS.md")
    skill_engine_spec_path: str = Field(default="docs/research/SKILL_ENGINE_SPEC.md")
    target_root: str = Field(default="skills/SKILL-001-fastapi-production/core/venous")

    @field_validator("codename")
    @classmethod
    def codename_is_upper_snake(cls, v: str) -> str:
        if v != v.upper():
            raise ValueError(f"codename MUST be UPPER_SNAKE, got {v!r}")
        return v

    @model_validator(mode="after")
    def primitive_names_unique(self) -> "BuilderBatchBriefing":
        names = [p.name for p in self.primitives]
        if len(names) != len(set(names)):
            dup = {n for n in names if names.count(n) > 1}
            raise ValueError(f"Duplicate primitive names in batch {self.batch_id}: {sorted(dup)}")
        return self

    def render_prompt(self) -> str:
        bullets_per_prim = []
        for p in self.primitives:
            bullets_per_prim.append(
                f"  - **{p.name}** (namespace `{p.namespace}`, maturity `{p.maturity.value}`, "
                f"is_stateful={p.is_stateful}, source=Agent #{p.source_agent_id})"
            )
        prims_bullets = "\n".join(bullets_per_prim)

        return f"""\
# BUILDER AGENT {self.batch_id} — {self.codename}

## Mission
{self.rationale}

You implement {len(self.primitives)} primitives, each as a SOTA module under
`{self.target_root}/<namespace>/<Name>/`. Every primitive passes the **10-tier**
delivery contract (T0 STATIC → T9 META). No shortcuts, no soft-accepts.

## Primitives assigned
{prims_bullets}

## Per-primitive artefacts (stateless → skip `*.tla` / `state_machine_*` / `concurrent_*`)
```
{self.target_root}/<namespace>/<Name>/
  __init__.py                       # empty package marker (REQUIRED, avoids INP001)
  <Name>.py                         # Protocol + runtime invariant checkers + reference impl
  test_<Name>.py                    # 3 tests per invariant (confirms / prevents / under_failure)
  behavioral_<Name>.py              # ≥ 5 end-to-end scenarios that PROVE invariants at runtime
  state_machine_<Name>.py           # hypothesis.RuleBasedStateMachine (stateful only)
  metamorphic_<Name>.py             # algebraic laws + differential-parity tests
  concurrent_<Name>.py              # linearizability / race detection (stateful only)
  chaos_<Name>.py                   # fault injection + game-day scripts
  observability_<Name>.py           # OTel/log/metric assertion harness
  observability_schema.json         # {{ logs, metrics, spans }} matching ObservabilitySchema
  dashboard.json                    # Grafana / Honeycomb board spec (minimal is fine)
  persona_reviews.json              # stub; tier runner fills
  proposed_invariants.json          # stub; tier runner fills
  invariant_bindings.json           # {{"invariant_bindings": [ {{invariant_id, invariant_text,
                                    #   confirms_test, prevents_test, under_failure_test}}, ... ]}}
  <Name>.tla                        # TLA+ spec (stateful only — TLC model-checks it, see T2 below)
  <Name>.md                         # narrative spec: invariants w/ IDs, provenance, alternatives
  <Name>.contract.json              # PrimitiveSpec from catalog, verbatim (drift detection)
  <Name>.manifest.json              # gate-produced; check_primitive.py writes this
```
PLUS one `__init__.py` at each ancestor directory that does not have one:
`{self.target_root}/<namespace>/__init__.py` and
`{self.target_root}/__init__.py` if missing.

## The 10 tier gates (all PASS for battle_tested; auto-SKIPPED for stateless on T2/T3/T5)

| Tier | Check | Stateless? |
|---|---|---|
| **T0 STATIC** | mypy --strict + ruff --select ALL (curated) + rationale-attached suppressions | always |
| T1 BEHAVIORAL | pytest on `behavioral_<Name>.py` | always |
| T2 FORMAL | **TLC 2.19 model-checks your `.tla` spec** — it WILL run | stateful only |
| T3 STATE_MACHINE | pytest on `state_machine_<Name>.py` (hypothesis) | stateful only |
| T4 METAMORPHIC | pytest on `metamorphic_<Name>.py` | always |
| T5 CONCURRENCY | pytest on `concurrent_<Name>.py` | stateful only |
| T6 ADVERSARIAL | Claude Opus + Sonnet + Haiku ensemble red-team ≥ 20 attacks, 0 successful | always |
| T7 OBSERVABILITY | `observability_schema.json` validates + pytest assertions green | always |
| T8 CHAOS | pytest on `chaos_<Name>.py` | always |
| T9 META | LLM judge ≥ 8/10 on 6 axes + 5 personas understood | always |

## Hard rules — learned from the OBSERVABILITY pilot (things that broke T0)

- **`contextmanager` return type**: `Iterator[T]` from `collections.abc`, never `object`.
  ```python
  from collections.abc import Iterator
  @contextmanager
  def activate(self) -> Iterator[Span]:
      yield span
  ```
- **`dict` MUST be parameterized**: `dict[str, object]`, `dict[str, float]`, never bare `dict`.
  Exception: `isinstance(x, dict)` — parameterized generics are forbidden in isinstance.
- **`from __future__ import annotations` is default**. Use `collections.abc.Mapping`, not
  `typing.Mapping`. Don't quote annotations (`user: CurrentUser`, not `user: "CurrentUser"`).
- **Remove every `# type: ignore` mypy marks as `[unused-ignore]`**. If you keep one, attach
  a rationale after `—` or cite an INV-ID. Same rule for `# noqa: ...`.
- **Side-effect-free import**: no I/O, no env reads, no network calls at module load.
  Lazy-import optional SDKs inside function bodies.
- **Protocol match catalog exactly**. Method names, parameter names, annotations, return types,
  defaults — all byte-for-byte from `catalog_spec.api_signature`.
- **3 tests per invariant**: name them `test_inv_<slug>_confirms`, `test_inv_<slug>_prevents`,
  `test_inv_<slug>_under_failure`. Slug MUST be identical across the three. The contract rejects
  mismatches.
- **No marketing vocabulary anywhere** — `robust`, `seamless`, `innovative`, etc. banned in
  every prose field (purpose / why_essential / extension_contract / invariants / insights / gaps
  / alternatives). Describe what it DOES and what RULES it enforces.

## TLC availability

TLC 2.19 is installed (`~/.local/bin/tlc`). For every **stateful** primitive, write a real
TLA+ spec: declare variables, Init, Next, at least two SAFETY invariants mapped to the
catalog invariants. Run `tlc <Name>.tla` locally and fix until `Model checking completed.
No error has been found.`

## T6 ensemble adversarial — how to cooperate with the runner

The runner calls Claude Opus + Sonnet + Haiku. Each produces 7-10 attacks. YOUR job is to
make sure the impl actually rejects each attack category. Common shapes: empty / whitespace /
null-byte inputs, double-end races, clock skew, parameter-injection in carrier dicts, oversize
payloads, integer overflow, homogeneity breaks, exception-path leaks. Your `test_inv_*_prevents`
tests SHOULD exercise the same classes.

## Self-check BEFORE submitting (run from repo root)

For every primitive:
```bash
PYTHONPATH=skills/SKILL-001-fastapi-production \\
  skills/SKILL-001-fastapi-production/.venv/bin/python \\
  -m engine.check_primitive \\
  --primitive-dir {self.target_root}/<namespace>/<Name> \\
  --catalog-entry docs/research/outputs/AGENT_<source-id>_<CODENAME>.json \\
  --maturity <experimental|emerging|battle_tested> \\
  --builder-agent {self.batch_id} \\
  --invariant-bindings {self.target_root}/<namespace>/<Name>/invariant_bindings.json \\
  {{--is-stateful if the primitive carries shared state; omit otherwise}}
```
PATH must include `~/.local/bin` so the `tlc` wrapper is on PATH for T2 gate.

**Exit 0 on every primitive.** Anything else means the primitive is rejected — fix and retry.

## Return summary (≤ 300 words)

- Primitive count completed (your batch has {len(self.primitives)})
- Per-primitive: CLI exit code, tier pass summary (e.g. `T0-T9 PASS`, `T2/T3/T5 SKIPPED`),
  total gate duration, LLM cost
- Any primitive that could not reach exit 0: name + failing tier + specific rejection reason
- Engine changes you had to make to clear a real gate gap (if any) — the pilot shipped three
  such hardenings; follow the same bar

## Full contract + standards
- Contract classes: `{self.contract_path}`
- Delivery-gate CLI: `{self.check_cli_path}`
- Standards (CCs / INVs / QSs / DoD with rationale): `{self.standards_doc_path}`
- SkillEngine architecture: `{self.skill_engine_spec_path}`
"""


# ---------------------------------------------------------------------------
# Catalog loading
# ---------------------------------------------------------------------------
def _load_research_primitives() -> dict[str, tuple[int, dict]]:
    """
    Return `{primitive_name: (source_agent_id, catalog_spec_dict)}` for all 115 primitives.

    Collisions (HealthProbe, RateLimiter) keep the FIRST-seen agent id; the
    canonical merged form already lives in `docs/research/COLLISIONS_RESOLVED.md`
    and the assignment table below places each collision in exactly one batch.
    """
    by_name: dict[str, tuple[int, dict]] = {}
    for p in sorted(RESEARCH_OUT.glob("AGENT_*.json")):
        aid = int(p.stem.split("_")[1])
        data = json.loads(p.read_text())
        for prim in data["primitives"]:
            if prim["name"] not in by_name:
                by_name[prim["name"]] = (aid, prim)
    return by_name


# ---------------------------------------------------------------------------
# Assignment map — each primitive to exactly ONE batch.
# Batches align with research codenames; big batches are split by sub-namespace.
# ---------------------------------------------------------------------------
_BATCHES: list[tuple[int, str, str, list[str]]] = [
    (
        1, "FRAMEWORKS_CORE",
        "Request-scoped DI / lifecycle / config / guard primitives extracted from "
        "Spring Boot, Nest.js, ASP.NET Core, Rails, Phoenix, Quarkus.",
        [
            "DiContainer", "LifetimeScope", "RequestContext", "CurrentPrincipal",
            "CorrelationId", "MiddlewarePipeline", "RequestGuard", "ValueTransform",
            "ConfigBinding", "HealthProbe", "LifecycleHook", "FeatureToggle",
            "RouterPipeline", "EventBus",
        ],
    ),
    (
        2, "DISTRIBUTED_EVENTS",
        "Pub/sub, event envelope, streaming topology primitives from Dapr, Kafka, "
        "NATS, CloudEvents.",
        [
            "EventEnvelope", "TopicBus", "StreamSubject", "DeadLetterRoute",
            "PartitionLog", "DistributedLock", "KeyValueBucket",
            "StateStore",
        ],
    ),
    (
        3, "DISTRIBUTED_JOBS",
        "Durable workflow + job primitives from Temporal 1.24 (workflows, activities, "
        "signals, timers) plus Dapr bindings and virtual actors.",
        [
            "WorkflowRun", "ActivityCall", "DurableTimer", "WorkflowSignal",
            "VirtualActor", "TransactionalBatch", "OutboundBinding",
            "RpcInterceptor",
        ],
    ),
    (
        4, "PATTERNS_DATA",
        "Fowler PEAA + Evans DDD data-shape primitives (UnitOfWork, Repository, "
        "Aggregate, Value Object, Bounded Context, Data Mapper, Identity Map, ACL).",
        [
            "UnitOfWork", "Repository", "IdentityMap", "DataMapper", "Specification",
            "Aggregate", "ValueObject", "BoundedContext", "AntiCorruptionLayer",
            "MaterializedView", "ChangeDataCapture",
        ],
    ),
    (
        5, "PATTERNS_EVENTS_API",
        "Event-sourcing + saga + CQRS patterns from Richardson / Kleppmann plus "
        "context map and command/query separator.",
        [
            "DomainEvent", "TransactionalOutbox", "InboxDeduplicator",
            "IdempotentConsumer", "SagaOrchestrator", "EventStream",
            "EventSourcedStore", "ContextMap", "CommandQuerySeparator",
        ],
    ),
    (
        6, "RESILIENCY",
        "Nygard Release It! stability primitives + modern resiliency (Envoy, Hystrix "
        "aftermath). NOTE: HealthProbe and RateLimiter are co-produced with batches 1 / 7 "
        "and live canonically per `COLLISIONS_RESOLVED.md`; this batch owns the resiliency-lens "
        "implementations that compose with observability + security facades.",
        [
            "CircuitBreaker", "Bulkhead", "TimeoutBudget", "RetryPolicy",
            "LoadShedder", "BackpressureSignal", "FallbackChain",
            "OutlierEjection", "ChaosInjector", "RateLimiter", "RequestShape",
        ],
    ),
    (
        7, "SECURITY",
        "OWASP ASVS + RFC-backed auth + crypto + input/output hygiene primitives.",
        [
            "PasswordHasher", "CsrfGuard", "ContentSecurityPolicy", "OutputEncoder",
            "SecretsVault", "CryptoEnvelope", "SignatureVerifier", "InputValidator",
            "AuthorizationCodeFlow", "TokenIntrospector", "WebAuthnAuthenticator",
            "TotpVerifier", "SessionStore", "CorsPolicy",
        ],
    ),
    (
        8, "COMPLIANCE",
        "SOC 2 / HIPAA / GDPR / PCI-DSS / NIST primitives — audit trail, retention, "
        "consent, DSAR, PII classification, encryption policy.",
        [
            "TamperEvidentAuditLog", "RetentionPolicy", "ConsentLedger",
            "DataSubjectRequest", "PiiClassification", "AccessLog",
            "EncryptionPolicy", "KeyRotationSchedule", "ProcessingRecord",
            "LegalHold", "BreachNotificationQueue", "DataResidencyPolicy",
        ],
    ),
    (
        9, "OBSERVABILITY",
        "OpenTelemetry 1.32 + Prometheus + SRE Book primitives — tracer, metrics, "
        "structured logger, sampling, correlation, error tracking, resource descriptor.",
        [
            "Tracer", "MetricMeter", "StructuredLogger", "CorrelationContext",
            "ErrorSink", "SamplingPolicy", "SemanticAttributes", "CardinalityGuard",
            "HistogramBuckets", "ResourceDescriptor", "TelemetryExporter", "AuditEvent",
        ],
    ),
    (
        10, "LLM_ERA",
        "Anthropic MCP / OWASP LLM Top 10 / Langfuse / Portkey / Helicone / LiteLLM / "
        "Weave primitives — prompt, model registry, guardrails, HITL, eval, cost, "
        "cache, routing, tool-use, injection filter.",
        [
            "PromptTemplate", "ModelRegistry", "VectorStore", "InputGuardrail",
            "OutputGuardrail", "HumanCheckpoint", "EvalHarness", "TokenMeter",
            "ResponseCache", "ModelRouter", "ToolSchema", "LlmTrace",
            "BudgetGuard", "PromptInjectionFilter",
        ],
    ),
]


# ---------------------------------------------------------------------------
# Build + sanity-check
# ---------------------------------------------------------------------------
def _build_briefings() -> list[BuilderBatchBriefing]:
    research = _load_research_primitives()
    result: list[BuilderBatchBriefing] = []

    for batch_id, codename, rationale, names in _BATCHES:
        assignments: list[PrimitiveAssignment] = []
        for name in names:
            if name not in research:
                raise ValueError(
                    f"Batch {batch_id} lists primitive '{name}' which is absent from research output. "
                    f"Check docs/research/outputs/*.json."
                )
            aid, spec = research[name]
            assignments.append(PrimitiveAssignment(
                name=name,
                namespace=spec["namespace"],
                maturity=Maturity(spec["maturity"]),
                is_stateful=_infer_stateful(name, spec["namespace"], spec["api_signature"]),
                source_agent_id=aid,
                catalog_spec=spec,
            ))
        result.append(BuilderBatchBriefing(
            batch_id=batch_id,
            codename=codename,
            rationale=rationale,
            primitives=assignments,
        ))

    _sanity_check(result, research)
    return result


def _sanity_check(briefings: list[BuilderBatchBriefing], research: dict) -> None:
    if len(briefings) != 10:
        raise AssertionError(f"Expected 10 briefings, got {len(briefings)}")

    assigned_names: set[str] = set()
    duplicates: list[str] = []
    for b in briefings:
        for p in b.primitives:
            if p.name in assigned_names:
                duplicates.append(p.name)
            assigned_names.add(p.name)
    if duplicates:
        raise AssertionError(f"Primitives assigned to multiple batches: {sorted(set(duplicates))}")

    unassigned = sorted(set(research.keys()) - assigned_names)
    if unassigned:
        raise AssertionError(f"{len(unassigned)} primitives unassigned: {unassigned}")

    extra = sorted(assigned_names - set(research.keys()))
    if extra:
        raise AssertionError(f"Assigned names not in research output: {extra}")

    totals = {b.batch_id: len(b.primitives) for b in briefings}
    total = sum(totals.values())
    if total != len(research):
        raise AssertionError(
            f"Total assigned primitives {total} != research total {len(research)}."
        )


BRIEFINGS: list[BuilderBatchBriefing] = _build_briefings()


# ---------------------------------------------------------------------------
# CLI preview
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print(f"Builder briefings loaded: {len(BRIEFINGS)} batches, "
          f"{sum(len(b.primitives) for b in BRIEFINGS)} primitives.\n")
    for b in BRIEFINGS:
        mats = {p.maturity.value: 0 for p in b.primitives}
        for p in b.primitives:
            mats[p.maturity.value] = mats.get(p.maturity.value, 0) + 1
        stateful_count = sum(1 for p in b.primitives if p.is_stateful)
        print(
            f"Batch {b.batch_id:>2} {b.codename:26s}  "
            f"{len(b.primitives):2d} primitives  "
            f"({stateful_count} stateful)  "
            f"maturity={mats}"
        )
    print("\nPrompt length per batch (chars ~ tokens/4):")
    for b in BRIEFINGS:
        p = b.render_prompt()
        print(f"  Batch {b.batch_id}: {len(p)} chars (~{len(p)//4} tokens)")
