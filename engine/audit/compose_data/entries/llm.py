"""WP-17 — curated compose-data entries for the `llm` namespace.

Pure-data module. Mirrors the source section that lived in
``engine/audit/_build_compose.py`` between the ``# === llm`` marker
and the next namespace marker. No imports beyond ``annotations``; merged
into the master ``E`` dict by ``engine.audit.compose_data._assembly``.

Entry shape (preserved verbatim from the pre-split file):
    (purpose, compose_with_siblings, [(pattern_name, [siblings...], invariant), ...])
"""

from __future__ import annotations

ENTRIES: dict[str, tuple[str, list[str], list[tuple[str, list[str], str]]]] = {
    # ======================================================== llm
    "InputGuardrail": (
        "Intercept user input before it reaches a model and reject, redact, or transform it against deterministic policy.",
        ["PromptInjectionFilter", "PromptTemplate", "OutputGuardrail", "InputValidator"],
        [
            (
                "Sanitize-then-prompt",
                ["PromptInjectionFilter", "PromptTemplate"],
                "Input is scrubbed for injection patterns before it enters the template; the template's policy cannot be overridden by user text.",
            ),
            (
                "Schema + policy",
                ["InputValidator", "PromptInjectionFilter"],
                "Typed schema validation runs first; guardrail runs second — malformed structure never reaches the policy layer.",
            ),
            (
                "Symmetric I/O filtering",
                ["OutputGuardrail", "PromptInjectionFilter"],
                "Input and output guardrails share threat taxonomy; a pattern blocked inbound is also blocked in the response — no one-way leaks.",
            ),
        ],
    ),
    "OutputGuardrail": (
        "Inspect model output after generation and reject, rewrite, or annotate it against schema, policy, and safety predicates.",
        ["InputGuardrail", "PromptInjectionFilter", "PromptTemplate", "LlmTrace"],
        [
            (
                "Schema-shaped answer",
                ["PromptTemplate", "InputValidator"],
                "Template pins the output schema; OutputGuardrail validates the generation — responses that fail validation trigger a bounded retry, not a 500.",
            ),
            (
                "Policy compliance",
                ["InputGuardrail", "PromptInjectionFilter"],
                "Outbound safety checks catch what inbound guardrails missed (e.g., exfil via prompt injection) — defense in depth.",
            ),
            (
                "Observable generations",
                ["LlmTrace", "MetricMeter"],
                "Rejection/rewrite rates are metered; every rejection emits a trace — policy regressions show up as metric jumps, not support tickets.",
            ),
        ],
    ),
    "PromptInjectionFilter": (
        "Make indirect prompt injection a single well-defined failure surface: one primitive evaluates untrusted context and quarantines suspicious input.",
        ["InputGuardrail", "OutputGuardrail", "PromptTemplate", "LlmTrace"],
        [
            (
                "Untrusted-context quarantine",
                ["InputGuardrail", "PromptTemplate"],
                "Fetched documents, tool outputs, and memory are tagged and scanned; the template renders them inside a sandbox region the model cannot treat as instructions.",
            ),
            (
                "End-to-end safety",
                ["OutputGuardrail", "LlmTrace"],
                "Inbound + outbound filter plus trace-level attribution: you can always answer 'which document triggered this refusal?'.",
            ),
            (
                "Tool-call gating",
                ["RequestGuard", "OutputGuardrail"],
                "Tool invocations pass through the filter before RequestGuard runs — injected 'delete my account' never reaches the authorizer.",
            ),
        ],
    ),
    "PromptTemplate": (
        "Declare a named, versioned, parameterized prompt whose text, variables, and target model are pinned and reviewable.",
        ["InputGuardrail", "OutputGuardrail", "LlmTrace", "PromptInjectionFilter"],
        [
            (
                "Versioned prompt contract",
                ["LlmTrace", "OutputGuardrail"],
                "Every generation records the template version, inputs, and schema; A/B comparisons are deterministic and traces are diffable across releases.",
            ),
            (
                "Guarded rendering",
                ["InputGuardrail", "PromptInjectionFilter"],
                "Template variables are rendered through guardrails; untrusted substrings cannot rewrite the instruction region.",
            ),
            (
                "Cost-aware routing",
                ["MetricMeter", "SamplingPolicy"],
                "Per-template token counters drive cost attribution; sampling policy retains a representative share of traces without blowing observability budget.",
            ),
        ],
    ),
}
