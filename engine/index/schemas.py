"""Skill catalog schemas — vocabulary (skill-owned) + shape (hugr-core).

The catalog *shape* (ToolEntry/BundleEntry/SkillEntry/PrimitiveEntry/
RecipeEntry/CatalogManifest) is shared across every HuGR skill and now lives in
``hugr_core.scanner.schemas``; it is re-exported here so existing imports
(``from engine.index.schemas import ToolEntry``) keep working.

The closed *vocabulary* (``Verb``/``Domain`` + ``VERBS``/``DOMAINS``/
``TAG_VOCABULARY``) is THIS skill's data and stays here as code — the scanner
validates tools against it via ``ScannerConfig.verbs``/``.domains``/
``.tag_vocabulary``. Adding / removing a vocabulary entry is a protocol-version
bump (see `DUAL_INDEX_DESIGN.md` §3).
"""

from __future__ import annotations

from typing import Literal

# Catalog shape — shared shell, re-exported for backwards-compatible imports.
from hugr_core.scanner.schemas import (
    BundleEntry,
    CatalogManifest,
    PrimitiveEntry,
    PrimitiveStatus,
    RecipeEntry,
    SkillEntry,
    Tier,
    ToolEntry,
    ToolStatus,
)

__all__ = [
    "Verb",
    "Domain",
    "Tier",
    "ToolStatus",
    "PrimitiveStatus",
    "ToolEntry",
    "BundleEntry",
    "SkillEntry",
    "PrimitiveEntry",
    "RecipeEntry",
    "CatalogManifest",
    "TAG_VOCABULARY",
    "VERBS",
    "DOMAINS",
]

# ---------------------------------------------------------------------------
# Closed vocabularies (frozen 2026-04-20) — skill-owned data
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
