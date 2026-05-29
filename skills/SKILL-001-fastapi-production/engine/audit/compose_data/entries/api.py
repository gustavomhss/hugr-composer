"""WP-17 — curated compose-data entries for the `api` namespace.

Pure-data module. Mirrors the source section that lived in
``engine/audit/_build_compose.py`` between the ``# === api`` marker
and the next namespace marker. No imports beyond ``annotations``; merged
into the master ``E`` dict by ``engine.audit.compose_data._assembly``.

Entry shape (preserved verbatim from the pre-split file):
    (purpose, compose_with_siblings, [(pattern_name, [siblings...], invariant), ...])
"""

from __future__ import annotations

ENTRIES: dict[str, tuple[str, list[str], list[tuple[str, list[str], str]]]] = {
    # ======================================================== api
    "CommandQuerySeparator": (
        "Partitions the API into write commands that mutate state and read queries that observe it so each side evolves independently.",
        ["RouterPipeline", "MiddlewarePipeline", "RequestContext", "ValueTransform"],
        [
            (
                "Write-side pipeline",
                ["RouterPipeline", "MiddlewarePipeline", "ValueTransform"],
                "Commands flow through a write-only router group whose middleware enforces validation and UoW boundaries before any handler runs.",
            ),
            (
                "Read-side projection",
                ["RouterPipeline", "RequestContext"],
                "Queries ride a distinct pipeline carrying only the caller's principal and correlation context, so read paths never inherit write-side transactions.",
            ),
            (
                "Typed command coercion",
                ["ValueTransform", "RequestContext"],
                "Inbound payloads are coerced to typed command DTOs before the domain sees them; RequestContext captures the caller identity for authorization, never raw storage args.",
            ),
        ],
    ),
    "ContextMap": (
        "Catalogs every BoundedContext and the integration relationship so upstream/downstream teams agree on a single translation contract.",
        ["BoundedContext", "AntiCorruptionLayer", "OutboundBinding", "DomainEvent"],
        [
            (
                "Customer/supplier integration",
                ["BoundedContext", "AntiCorruptionLayer"],
                "ContextMap declares the relationship; the ACL enforces it at runtime so upstream vocabulary never leaks into the downstream model.",
            ),
            (
                "Published-language contract",
                ["DomainEvent", "OutboundBinding"],
                "The map names which contexts publish vs consume domain events; OutboundBinding is the single adapter surface honoring that direction.",
            ),
            (
                "Conformist drift detection",
                ["BoundedContext", "AntiCorruptionLayer"],
                "When an upstream context changes its schema, the ACL is the one seam that fails fast — the context map tells you which downstream teams to page.",
            ),
        ],
    ),
    "MiddlewarePipeline": (
        "Ordered chain of components that each transform the RequestContext and decide whether to call the next stage or short-circuit the response.",
        ["RouterPipeline", "RequestContext", "RequestGuard", "CorrelationContext"],
        [
            (
                "Edge security chain",
                ["RequestGuard", "CsrfGuard", "RequestContext"],
                "Authn → authz → CSRF runs in a fixed order; downstream handlers receive a RequestContext already stamped with principal and verified origin.",
            ),
            (
                "Observability wrapping",
                ["CorrelationContext", "StructuredLogger", "Tracer"],
                "The outermost middleware stamps a correlation id and opens the root span so every log line and child span in the pipeline is automatically joined.",
            ),
            (
                "Resiliency envelope",
                ["TimeoutBudget", "LoadShedder", "CircuitBreaker"],
                "Pipeline entry computes the deadline and enqueues the request under a priority class; inner middleware inherits the remaining budget — no handler gets more time than the ingress contract promised.",
            ),
        ],
    ),
    "RequestContext": (
        "Per-request bag that carries identity, headers, correlation id, and free-form assigns through the handler chain.",
        ["MiddlewarePipeline", "CurrentPrincipal", "CorrelationContext", "RequestShape"],
        [
            (
                "Principal propagation",
                ["CurrentPrincipal", "RequestGuard"],
                "Authn middleware resolves the principal once and stamps the context; downstream RequestGuard reads the same frozen identity — no re-validation, no drift.",
            ),
            (
                "Cross-cutting correlation",
                ["CorrelationContext", "StructuredLogger"],
                "Every log line emitted inside a handler inherits the request's correlation id via the context, so a single grep stitches the whole call graph.",
            ),
            (
                "Deadline-aware handlers",
                ["RequestShape", "TimeoutBudget"],
                "The context carries the remaining budget and priority class; handlers query it before issuing downstream calls rather than racing an invisible timer.",
            ),
        ],
    ),
    "RouterPipeline": (
        "Named bundle of middleware that a route joins with `pipe_through` so groups share edge policy without re-declaring it.",
        ["MiddlewarePipeline", "CommandQuerySeparator", "RequestGuard", "CorsPolicy"],
        [
            (
                "Browser vs API split",
                ["MiddlewarePipeline", "CsrfGuard", "CorsPolicy"],
                "The 'browser' pipeline enforces CSRF and session cookies; the 'api' pipeline enforces bearer tokens and CORS — one route cannot accidentally inherit the wrong edge.",
            ),
            (
                "Read/write separation",
                ["CommandQuerySeparator", "MiddlewarePipeline"],
                "Query pipelines skip UoW and write-locks; command pipelines mount them — the router is the single place this contract lives.",
            ),
            (
                "Tenanted edge",
                ["RequestGuard", "CurrentPrincipal"],
                "Per-tenant pipelines stamp tenant id into the context before authorization runs, so downstream handlers never need to re-extract it from headers.",
            ),
        ],
    ),
    "ValueTransform": (
        "Strongly-typed parse/validate step that converts a raw inbound argument into the domain type or rejects the request with a precise error.",
        ["InputValidator", "RequestContext", "MiddlewarePipeline", "ValueObject"],
        [
            (
                "Schema-to-domain coercion",
                ["InputValidator", "ValueObject"],
                "Raw JSON is validated by the schema then coerced into frozen value objects before the handler sees it — domain code never touches a dict.",
            ),
            (
                "Typed path/query params",
                ["MiddlewarePipeline", "RequestContext"],
                "Each route declares transforms for its params; a failure raises one well-typed exception the pipeline maps to 400 — handlers never check types.",
            ),
            (
                "Canonical on-the-wire",
                ["InputValidator", "OutputEncoder"],
                "Inbound ValueTransform + outbound OutputEncoder form a round-trip contract: the same canonical form crosses the edge in both directions.",
            ),
        ],
    ),
}
