"""Pydantic schemas for the skill catalog manifest.

All downstream consumers (MCP registration, human catalog page,
contract rule B2.4) validate against these. Adding / removing a field
is a protocol-version bump (see `DUAL_INDEX_DESIGN.md` §3).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Closed vocabularies (frozen 2026-04-20)
# ---------------------------------------------------------------------------

Verb = Literal[
    "add",  # adds a capability to an existing project
    "generate",  # scaffolds a project or a module from scratch
    "verify",  # validates an invariant (contract, T-gate)
    "operate",  # runs an operational command (db, deploy, ...)
    "evolve",  # deprecation / migration / refactor
    "proactive",  # suggests improvements against a best-practice
    "check",  # static analysis against a rule / linter
    "analyze",  # runtime / graph / perf analysis
    "search",  # retrieve from the catalog itself (meta)
]

Domain = Literal[
    "auth",  # identity, sessions, RBAC, MFA, OAuth
    "data",  # CRUD, persistence, migrations, soft-delete, audit
    "api",  # versioning, GraphQL, CQRS, batch, deprecations
    "realtime",  # WebSockets, SSE, webhooks, presence, chat
    "resiliency",  # rate-limit, circuit-breaker, retry, bulkhead
    "observability",  # logging, metrics, traces, error tracking
    "compliance",  # audit log, retention, consent, tamper evidence
    "deployment",  # Docker, K8s, CI, CD, compose, load-test
    "testing",  # coverage, fuzzer, property, soak, E2E
    "meta",  # discovery, describe, audit (tier-1 meta-tools)
]

Tier = Literal[1, 2]  # 1 = always-loaded; 2 = defer_loading

ToolStatus = Literal["experimental", "stable", "deprecated"]

# Primitive-only status. Adds "staged" for pre-audited primitives that live
# under `core/venous/_staging/` but still carry REPLACE_ME stubs. Staged
# primitives are surfaced in the catalog so the agent can see them, but
# they are NOT ready for production composition — promote through the
# extraction pipeline before relying on them.
PrimitiveStatus = Literal["experimental", "staged", "stable", "deprecated"]


# ---------------------------------------------------------------------------
# Entry types
# ---------------------------------------------------------------------------


class ToolEntry(BaseModel):
    """One MCP tool in the catalog.

    Fields marked "required for tier-1" are mandatory on tier-1 tools
    (the small always-loaded set). Tier-2 tools are allowed to inherit
    defaults (e.g. missing `when_not_to_call` is tolerated; the tool
    search index falls back to the general description).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str  # `fastapi_<domain>_<verb>_<noun>` after the rename
    legacy_name: str | None = None  # pre-rename name for the compat shim window
    verb: Verb
    domain: Domain
    synopsis: str  # one-line (≤100 chars), sentence case, no trailing dot
    when_to_call: str  # 1-3 sentences, LLM-oriented
    when_not_to_call: str = ""  # required on tier-1
    tags: tuple[str, ...] = ()  # ⊆ closed tag vocabulary
    tier: Tier = 2
    status: ToolStatus = "stable"
    since: str = ""  # e.g. "v0.1.0"
    module_path: str  # repo-relative .py
    test_paths: tuple[str, ...] = ()
    primitives_used: tuple[str, ...] = ()  # names registered in primitives_by_concern.yaml
    example_input: dict | None = None
    example_output: dict | None = None


class PrimitiveEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str  # PascalCase (matches registry)
    namespace: str  # e.g. "cache"
    concern: str  # coarser than namespace (e.g. "data.persistence")
    purpose: str  # one-line, <140 chars
    compose_with: tuple[str, ...] = ()
    module_path: str  # repo-relative
    status: PrimitiveStatus = "stable"


class RecipeEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str  # deterministic slug: `<primitive>__<intent-slug>`
    source_primitive: str  # the primitive whose Compose-with bullet produced this
    primitives: tuple[str, ...]  # all primitives referenced in the bullet
    intent: str  # the bold "→ intent" text
    description: str  # the prose after the arrow
    tags: tuple[str, ...] = ()


class CatalogManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str
    kit_commit: str
    generated_at: str  # UTC ISO-8601, seconds precision
    verbs: tuple[Verb, ...]
    domains: tuple[Domain, ...]
    tags: tuple[str, ...]  # closed vocabulary snapshot
    tools: tuple[ToolEntry, ...]
    primitives: tuple[PrimitiveEntry, ...]
    recipes: tuple[RecipeEntry, ...]
    counts: dict[str, int] = Field(
        default_factory=dict
    )  # shortcut: {tools: 180, primitives: 122, recipes: 290}
    stable_hash: str | None = Field(
        default=None,
        description=(
            "SHA-256 content hash (hex) over the catalog excluding "
            "`generated_at`, `kit_commit`, and `stable_hash` itself. "
            "Populated at write time by `engine.index.manifest.write`. "
            "Consumers (Forge, agent, CI) read this value to pin the "
            "skill surface version within a session / benchmark run."
        ),
    )


# ---------------------------------------------------------------------------
# Tag vocabulary (closed; extend via protocol bump)
# ---------------------------------------------------------------------------

TAG_VOCABULARY: frozenset[str] = frozenset(
    {
        # identity + access
        "oauth",
        "jwt",
        "rbac",
        "mfa",
        "session",
        "password",
        # data shape + patterns
        "crud",
        "pagination",
        "soft-delete",
        "audit",
        "event-sourcing",
        "idempotency",
        "optimistic-lock",
        "outbox",
        # api style
        "graphql",
        "rest",
        "versioning",
        "batch",
        "cqrs",
        "deprecation",
        # realtime
        "websocket",
        "sse",
        "webhook",
        "presence",
        # resiliency
        "rate-limit",
        "bulkhead",
        "circuit-breaker",
        "retry",
        "graceful-shutdown",
        "load-shedding",
        "causal-reorder",
        # observability
        "otel",
        "prometheus",
        "logging",
        "tracing",
        "metrics",
        # compliance
        "hash-chain",
        "retention",
        "consent",
        "gdpr",
        "tamper-evident",
        # infra / deployment
        "docker",
        "kubernetes",
        "ci",
        "compose",
        "load-test",
        # testing
        "coverage",
        "fuzz",
        "property",
        "soak",
        "chaos",
        # experimental / misc
        "experimental",
        "federated-identity",
        "ml",
        "workflow",
    }
)


VERBS: tuple[str, ...] = (
    "add",
    "generate",
    "verify",
    "operate",
    "evolve",
    "proactive",
    "check",
    "analyze",
    "search",
)

DOMAINS: tuple[str, ...] = (
    "auth",
    "data",
    "api",
    "realtime",
    "resiliency",
    "observability",
    "compliance",
    "deployment",
    "testing",
    "meta",
)
