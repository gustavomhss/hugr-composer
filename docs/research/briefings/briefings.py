"""
8 Sonnet research briefings — instances of ResearchAgentBriefing.

Each briefing is the sealed mission a Sonnet agent receives. Token-efficient
by design: no context dumps, only concrete sources + scope + namespaces +
quality floors.

Validated at import time. Any schema violation aborts the research phase.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "contracts"))

from briefing_contract import Namespace, ResearchAgentBriefing  # noqa: E402


# Literal phrases the validator scans for (rejection if they appear verbatim).
# Keep this list pragmatic — clear draft markers, not stylistic choices.
# All items must be ≥4 chars (validator silently skips shorter strings) and
# unlikely to appear in legitimate prose.
COMMON_FORBIDDEN: list[str] = [
    "TODO:",
    "lorem ipsum",
    "to be determined",
    "fill in the blank",
    "[FIXME]",
    "[WIP]",
]

# Behavioral anti-patterns shown in the prompt; NOT auto-scanned. These are
# judgment calls the agent is expected to honor.
COMMON_ANTI_PATTERNS: list[str] = [
    "marketing vocabulary — describe what it DOES and what RULES it enforces",
    "unverifiable benchmarks or vendor claims",
    "hypothetical primitives not grounded in the listed sources",
    "framework-specific names — use neutral PascalCase",
    "filler prose — every sentence must earn its place",
    "duplicating a primitive another agent already owns by the same name",
    "inventing sources — if you cannot cite it, do not claim it",
]


AGENT_1_FRAMEWORKS = ResearchAgentBriefing(
    agent_id=1,
    codename="FRAMEWORKS",
    mission=(
        "Extract dependency-injection, request-context, config-binding, and "
        "lifecycle primitives from six mature backend frameworks to anchor "
        "the venous system spec in 20+ years of battle-tested design."
    ),
    sources_required=[
        "Spring Boot 3.x Reference (ApplicationContext, @ConditionalOn*)",
        "Nest.js 10 Documentation (modules, providers, interceptors, guards, pipes)",
        "ASP.NET Core 8.0 Fundamentals (IServiceCollection, HttpContext, IOptions)",
        "Ruby on Rails 7 Guides (ActiveSupport, Concerns, request-level context)",
        "Phoenix 1.7 Documentation (Plug pipeline, PubSub, LiveView)",
        "Quarkus 3.x Guides (compile-time DI, extensions)",
    ],
    scope_in=[
        "DI/IoC container contracts and lifetime scopes (singleton/request/transient)",
        "Request-scoped context (current user, correlation id, tenant)",
        "Configuration binding and typed options",
        "Middleware/interceptor/plug chain contracts",
        "Lifecycle hooks (startup/shutdown/ready)",
        "Health endpoint conventions",
    ],
    scope_out=[
        "Frontend primitives",
        "IaC tooling",
        "Language-idiomatic syntax (Java/C#/Ruby-specific sugar)",
        "Packaging and deployment details",
    ],
    namespaces_owned=[Namespace.AUTH, Namespace.DATA, Namespace.API, Namespace.OBS, Namespace.FLAGS],
    min_primitives=12,
    min_sources_cited=6,
    deliverable_path="docs/research/outputs/AGENT_1_FRAMEWORKS.md",
    forbidden=COMMON_FORBIDDEN,
    anti_patterns=COMMON_ANTI_PATTERNS,
)


AGENT_2_DISTRIBUTED = ResearchAgentBriefing(
    agent_id=2,
    codename="DISTRIBUTED",
    mission=(
        "Catalog distributed-systems building blocks — state, pub/sub, secrets, "
        "bindings, actors, workflows, observability, crypto — from Dapr, "
        "Temporal, Kafka, NATS, CloudEvents, and gRPC to define the runtime "
        "primitives any SkillKit language target must expose."
    ),
    sources_required=[
        "Dapr 1.14 Building Blocks Specification (all 10 blocks)",
        "Temporal 1.24 Architecture (workflows, activities, signals, queries)",
        "Apache Kafka 3.x core concepts (topics, partitions, consumer groups)",
        "NATS 2.10 (subjects, JetStream, key-value)",
        "CloudEvents 1.0 specification",
        "gRPC core concepts (interceptors, deadlines, metadata)",
    ],
    scope_in=[
        "State management primitive (CRUD + transactional + query)",
        "Pub/sub messaging primitive (topic, delivery semantics, DLQ)",
        "Workflow orchestration primitive (durable, retriable, signal-able)",
        "Secrets/config management primitive (rotation, audit)",
        "Input/output bindings primitive (adapter contract)",
        "Actor primitive (state + mailbox + placement)",
        "Distributed interceptor/middleware contract",
    ],
    scope_out=[
        "Language-specific SDK APIs (document the pattern, not the client)",
        "Deployment/operator specifics",
        "Monitoring dashboard products",
    ],
    namespaces_owned=[Namespace.EVENTS, Namespace.JOBS, Namespace.DATA, Namespace.CACHE, Namespace.EXTRAS],
    min_primitives=12,
    min_sources_cited=6,
    deliverable_path="docs/research/outputs/AGENT_2_DISTRIBUTED.md",
    forbidden=COMMON_FORBIDDEN,
    anti_patterns=COMMON_ANTI_PATTERNS,
)


AGENT_3_PATTERNS = ResearchAgentBriefing(
    agent_id=3,
    codename="PATTERNS",
    mission=(
        "Extract enterprise, DDD, microservices, and data-intensive patterns "
        "that crystallize into shared primitives (UnitOfWork, Aggregate, "
        "Outbox, CQRS, Event Sourcing, ACL) from the canonical distinguished-"
        "engineer corpus."
    ),
    sources_required=[
        'Fowler "Patterns of Enterprise Application Architecture" (2002)',
        'Evans "Domain-Driven Design" (2003)',
        'Richardson "Microservices Patterns" (2018)',
        'Kleppmann "Designing Data-Intensive Applications" (2017)',
        'Vernon "Implementing Domain-Driven Design" (2013)',
    ],
    scope_in=[
        "UnitOfWork, Repository, Identity Map, Data Mapper, Specification",
        "Aggregate, Entity, Value Object, Domain Event, Bounded Context",
        "Anti-Corruption Layer, Context Map",
        "Outbox, Inbox, Idempotent Consumer, CQRS, Event Sourcing",
        "Saga (orchestration + choreography)",
        "Change Data Capture, materialized view primitive",
    ],
    scope_out=[
        "Language-specific implementations",
        "Framework mappings (covered by Agent 1)",
        "Toy/tutorial examples",
    ],
    namespaces_owned=[Namespace.DATA, Namespace.EVENTS, Namespace.API],
    min_primitives=12,
    min_sources_cited=5,
    deliverable_path="docs/research/outputs/AGENT_3_PATTERNS.md",
    forbidden=COMMON_FORBIDDEN,
    anti_patterns=COMMON_ANTI_PATTERNS,
)


AGENT_4_RESILIENCY = ResearchAgentBriefing(
    agent_id=4,
    codename="RESILIENCY",
    mission=(
        "Extract stability and resiliency patterns — circuit breakers, "
        "bulkheads, timeouts, retry policies, load shedding, backpressure, "
        "graceful degradation — from Nygard and modern production references "
        "to promote resiliency concerns to first-class primitives."
    ),
    sources_required=[
        'Nygard "Release It!" 2nd edition (2018)',
        "resilience4j 2.x documentation",
        "Netflix Hystrix (retirement notice + post-Hystrix guidance)",
        "Google SRE Workbook (overload, cascading failures chapters)",
        "Envoy proxy retry / circuit-breaker / outlier-detection semantics",
    ],
    scope_in=[
        "Circuit breaker (state transitions, half-open probing)",
        "Bulkhead (thread/semaphore isolation)",
        "Timeout (per-call, per-dependency, per-budget)",
        "Retry policy (backoff, jitter, budget, idempotency required)",
        "Load shedding (priority classes, adaptive)",
        "Backpressure signals and flow control",
        "Graceful degradation and fallback",
        "Chaos injection hooks",
    ],
    scope_out=[
        "Specific vendor libraries beyond naming the pattern",
        "Dashboarding and alerting UX",
    ],
    namespaces_owned=[Namespace.RESILIENCY, Namespace.EXTRAS],
    min_primitives=10,
    min_sources_cited=5,
    deliverable_path="docs/research/outputs/AGENT_4_RESILIENCY.md",
    forbidden=COMMON_FORBIDDEN,
    anti_patterns=COMMON_ANTI_PATTERNS,
)


AGENT_5_SECURITY = ResearchAgentBriefing(
    agent_id=5,
    codename="SECURITY",
    mission=(
        "Extract security primitives — auth protocols, crypto facades, secrets "
        "vault, input/output hygiene, session management, MFA, passkeys — from "
        "OWASP, IETF, and NIST to establish the non-negotiable security "
        "surface every SkillKit target must expose."
    ),
    sources_required=[
        "OWASP ASVS 4.0.3",
        "OWASP Top 10 2021",
        "RFC 6749 OAuth 2.0 Authorization Framework",
        "OpenID Connect Core 1.0",
        "WebAuthn Level 3 (W3C Recommendation)",
        "NIST SP 800-63B Digital Identity Guidelines",
    ],
    scope_in=[
        "OAuth 2.0 / OIDC / PKCE flows as primitives",
        "Passkey / WebAuthn registration and authentication",
        "MFA (TOTP, WebAuthn, SMS-with-risk-warning)",
        "Crypto facade (sign/verify, encrypt/decrypt, hash, KDF)",
        "Secrets vault (fetch, rotate, audit)",
        "CSRF protection, CORS policy, CSP headers",
        "Input sanitization and output encoding",
        "Session primitive (rotation, fixation resistance, revocation)",
    ],
    scope_out=[
        "Compliance-driven primitives (Agent 6 owns)",
        "Specific IdP products",
    ],
    namespaces_owned=[Namespace.SECURITY, Namespace.AUTH, Namespace.POLICY],
    min_primitives=12,
    min_sources_cited=6,
    deliverable_path="docs/research/outputs/AGENT_5_SECURITY.md",
    forbidden=COMMON_FORBIDDEN,
    anti_patterns=COMMON_ANTI_PATTERNS,
)


AGENT_6_COMPLIANCE = ResearchAgentBriefing(
    agent_id=6,
    codename="COMPLIANCE",
    mission=(
        "Extract compliance-driven primitives — tamper-evident audit trail, "
        "retention, consent, DSAR/RTBF, PII tagging, encryption policies, "
        "access logging — from SOC 2, HIPAA, GDPR, PCI-DSS, and NIST so every "
        "SkillKit target ships compliance surface by default, not as retrofit."
    ),
    sources_required=[
        "AICPA SOC 2 Trust Services Criteria (2017, 2022 revision)",
        "HIPAA Security Rule 45 CFR §§ 164.308-164.312",
        "EU GDPR Regulation 2016/679 Articles 5, 6, 7, 15, 17, 30, 32",
        "PCI-DSS v4.0",
        "NIST SP 800-53 revision 5",
    ],
    scope_in=[
        "Audit trail primitive (append-only, tamper-evident, signed)",
        "Retention policy primitive (class-based, enforced at write)",
        "Consent management primitive (granular, revocable, timestamped)",
        "DSAR / RTBF primitive (export + erase with cascade rules)",
        "PII/PHI tagging primitive (schema-level, enforced at serialization)",
        "Access-log primitive (who-read-what, separate from audit)",
        "Encryption policy primitive (at-rest, in-transit, key-rotation)",
    ],
    scope_out=[
        "Security implementations (Agent 5 owns)",
        "Legal interpretation of specific clauses",
        "Certification / audit processes",
    ],
    namespaces_owned=[Namespace.COMPLIANCE, Namespace.OBS, Namespace.DATA, Namespace.POLICY],
    min_primitives=10,
    min_sources_cited=5,
    deliverable_path="docs/research/outputs/AGENT_6_COMPLIANCE.md",
    forbidden=COMMON_FORBIDDEN,
    anti_patterns=COMMON_ANTI_PATTERNS,
)


AGENT_7_OBSERVABILITY = ResearchAgentBriefing(
    agent_id=7,
    codename="OBSERVABILITY",
    mission=(
        "Extract observability primitives — traces, metrics, structured logs, "
        "correlation, error tracking — unified under OpenTelemetry semantic "
        "conventions so every SkillKit target emits interoperable telemetry "
        "without tool-by-tool drift."
    ),
    sources_required=[
        "OpenTelemetry Specification 1.32",
        "OpenTelemetry Semantic Conventions 1.27 (HTTP, DB, messaging, GenAI)",
        'Majors / Fong-Jones / Miranda "Observability Engineering" (2022)',
        'Google SRE Book "Monitoring Distributed Systems" chapter',
        "Prometheus best practices (histograms, summaries, label cardinality)",
    ],
    scope_in=[
        "Tracer primitive (span, attributes, events, links, context propagation)",
        "Metrics primitive (counter, histogram, gauge, updown counter)",
        "Structured logger primitive (key/value, level, correlation)",
        "Correlation-id / request-id primitive across layers",
        "Error-tracking primitive (capture, fingerprint, sampling)",
        "Sampling strategy primitive (head/tail, parent-based)",
        "Semantic convention enforcement (service.name, deployment.environment)",
        "Cardinality guardrails",
    ],
    scope_out=[
        "Vendor products (Datadog, Honeycomb, New Relic)",
        "Dashboard / alerting UX",
        "Incident management workflow",
    ],
    namespaces_owned=[Namespace.OBS, Namespace.COMPLIANCE],
    min_primitives=10,
    min_sources_cited=5,
    deliverable_path="docs/research/outputs/AGENT_7_OBSERVABILITY.md",
    forbidden=COMMON_FORBIDDEN,
    anti_patterns=COMMON_ANTI_PATTERNS,
)


AGENT_8_LLM_ERA = ResearchAgentBriefing(
    agent_id=8,
    codename="LLM_ERA",
    mission=(
        "Extract LLM-era primitives — prompt management, model registry, vector "
        "store, guardrails, HITL, eval pipelines, cost tracking, response cache, "
        "model routing, tool use — so any SkillKit target that calls an LLM "
        "gets consistent, auditable AI surface out of the box."
    ),
    sources_required=[
        "Anthropic Model Context Protocol (MCP) 1.x specification",
        "OWASP Top 10 for LLM Applications (2023)",
        "Langfuse 2.x architecture and tracing model",
        "Portkey and Helicone gateway architecture",
        "LiteLLM 1.x unified completion interface",
        "Weights & Biases Weave + Models (eval + registry)",
        "OpenTelemetry Semantic Conventions for Generative AI (1.27+)",
    ],
    scope_in=[
        "Prompt management primitive (versioned, diffable, tested)",
        "Model registry primitive (model + config + capabilities metadata)",
        "Vector store primitive (embed, upsert, search, filter, delete)",
        "Input/output guardrails primitive (deterministic + LLM-judged)",
        "HITL checkpoint primitive (block until human approval)",
        "Eval primitive (golden set + automated judge)",
        "LLM cost tracker primitive (tokens, cache hits, per-user attribution)",
        "Response cache primitive (semantic + exact)",
        "Model router primitive (cheap vs expensive, fallback, budget)",
        "Tool use primitive (function calling, argument validation, retries)",
    ],
    scope_out=[
        "Specific provider API surface (OpenAI / Anthropic / Google verbatim)",
        "Training / fine-tuning infrastructure",
        "Embedding model comparison benchmarks",
    ],
    namespaces_owned=[Namespace.LLM, Namespace.COST, Namespace.OBS],
    min_primitives=12,
    min_sources_cited=6,
    deliverable_path="docs/research/outputs/AGENT_8_LLM_ERA.md",
    forbidden=COMMON_FORBIDDEN,
    anti_patterns=COMMON_ANTI_PATTERNS,
)


BRIEFINGS: list[ResearchAgentBriefing] = [
    AGENT_1_FRAMEWORKS,
    AGENT_2_DISTRIBUTED,
    AGENT_3_PATTERNS,
    AGENT_4_RESILIENCY,
    AGENT_5_SECURITY,
    AGENT_6_COMPLIANCE,
    AGENT_7_OBSERVABILITY,
    AGENT_8_LLM_ERA,
]


def _sanity_check() -> None:
    """Import-time invariants. Fails noisily at import if anything drifts."""
    assert len(BRIEFINGS) == 8, "Must have exactly 8 briefings."
    ids = [b.agent_id for b in BRIEFINGS]
    assert ids == sorted(ids) == list(range(1, 9)), f"agent_id must be 1..8 in order, got {ids}"
    codenames = {b.codename for b in BRIEFINGS}
    assert len(codenames) == 8, f"Codenames must be unique, got {codenames}"
    paths = [b.deliverable_path for b in BRIEFINGS]
    assert len(set(paths)) == 8, "Deliverable paths must be unique."


def namespace_overlap_report() -> dict[str, list[int]]:
    """Which namespace is owned by which agents?

    Overlap is ALLOWED (cross-cutting research angles — e.g. OBS from frameworks,
    compliance, observability, and LLM eras). Consolidation dedups by primitive
    name. This report surfaces the overlap so the orchestrator knows where to
    expect potential dupes.
    """
    report: dict[str, list[int]] = {}
    for b in BRIEFINGS:
        for ns in b.namespaces_owned:
            report.setdefault(ns.value, []).append(b.agent_id)
    return report


_sanity_check()


if __name__ == "__main__":
    for b in BRIEFINGS:
        owned = ", ".join(n.value for n in b.namespaces_owned)
        print(
            f"Agent {b.agent_id} {b.codename}: "
            f"min_primitives={b.min_primitives}, "
            f"min_sources_cited={b.min_sources_cited}, "
            f"namespaces=[{owned}]"
        )
    print("\nNamespace overlap (namespace → agents that own it):")
    for ns, owners in sorted(namespace_overlap_report().items()):
        tag = " (overlap)" if len(owners) > 1 else ""
        print(f"  {ns:12s} → {owners}{tag}")
