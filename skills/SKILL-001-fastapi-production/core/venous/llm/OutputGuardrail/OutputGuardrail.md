# OutputGuardrail

## What it does (plain language)

An `OutputGuardrail` is a post-inference check that inspects what an LLM just
produced and returns a verdict: `pass` (let it through), `rewrite` (here is a
safer replacement), or `block` (do not return this to the caller or any
downstream tool). You compose an ordered chain of these guards — schema,
policy, safety — and run it against every model output before any further
processing. A single `block` anywhere in the chain halts delivery and
records who blocked it and why.

## Purpose

Inspect model output after generation and reject, rewrite, or annotate it
against schema, policy, and safety rules before the caller or downstream
tools receive it (OWASP LLM02 — Insecure Output Handling).

## When to use and when NOT to use

- USE: any place model output is forwarded to a tool executor, renderer, or
  downstream agent — the second-leading class of LLM vulnerability is
  treating model text as trusted.
- USE: any place the output should conform to a schema (function-call args,
  structured extraction, API response shape).
- DO NOT USE: in hot creative paths where the caller has already committed
  to post-process the text themselves — guardrails add latency per check.
- DO NOT USE: as a substitute for prompt-side constraints; the provider's
  structured-output mode, when available, catches shape errors earlier.

## API surface

The catalog `api_signature` is the sole authority; see
`OutputGuardrail.contract.json`. The reference implementations are:

- `SchemaOutputGuardrail` — JSON-Schema conformance check (falls back to a
  minimal internal type/required/properties checker when `jsonschema` is
  absent, so the module boots without the optional dependency).
- `PolicyOutputGuardrail` — regex-based block / rewrite (redaction).
- `SafetyOutputGuardrail` — refuses output carrying tool-call-shaped tokens
  (`<tool_call>`, `<function_call>`, `<invoke>`, `` ```tool_code ``) on the
  wire; such tokens MUST arrive via the model's structured tool-use channel,
  never as rendered text.

Composition is through `apply_chain(guards, raw, *, schema_ref, ledger)`,
which enforces GUARD-INV-02 (block halts delivery) and GUARD-INV-05 (every
verdict recorded in the ledger).

## Invariants

| ID | Rule |
|---|---|
| GUARD_INV_01 | evaluate() MUST reject output that fails schema validation when schema_ref is provided; malformed JSON CANNOT be returned as `pass`. |
| GUARD_INV_02 | A BLOCK verdict MUST prevent the output from being returned to the caller or passed to any downstream tool. |
| GUARD_INV_03 | REWRITE verdicts MUST provide a non-None string replacement; `replacement=None` under rewrite is a contract violation. |
| GUARD_INV_04 | Output guardrails MUST NEVER execute tool calls embedded in the output before passing safety checks. |
| GUARD_INV_05 | Every verdict SHALL be recorded with the guardrail name so post-hoc analysis can attribute the decision. |

## Invariant → test mapping

Each invariant has three tests
(`test_inv_<slug>_{confirms,prevents,under_failure}`) plus behavioral,
metamorphic, state-machine, concurrent, and chaos coverage. See
`invariant_bindings.json` for the authoritative binding.

## Thread and async safety

- `Verdict` is immutable after construction; `__setattr__` is locked down.
- `VerdictLedger` wraps its internal list in a `threading.Lock`, making
  `record`, `entries`, `entries_for`, `size`, and `clear` atomic relative
  to one another.
- All three reference guardrails are stateless after construction; their
  `evaluate()` methods are pure functions of `(output, schema_ref)`.

## Operational characteristics (for SRE)

- The primary correctness signal is `guardrail.verdicts.total` with label
  `action`. A sudden spike in `action="block"` means either the model has
  regressed or an adversarial input wave has arrived.
- `guardrail.evaluate.latency` p95 should be sub-millisecond for policy and
  safety guards, sub-5 ms for schema (dominated by `json.loads`).
- `guardrail.ledger.size` is a steady gauge per deployed guard; it grows
  with traffic but a persistently empty ledger means instrumentation has
  detached from the chain.
- A block always carries a structured reason; include the full reason in
  the outgoing `guardrail.block` log event for forensic attribution.

## Security considerations

- Tool-call-shaped tokens are refused on the output channel (GUARD-INV-04).
  Legitimate function calling MUST flow through the model provider's
  structured tool-use API.
- `replacement=None` under `rewrite` is rejected at construction to close a
  class of bug where a guard emits a rewrite verdict but forgets to supply
  the safer text, silently passing the unsafe original (GUARD-INV-03).
- Unknown `schema_ref` is blocked (fail-closed) rather than passed.
- Oversize outputs (> 2 MB) and reasons (> 500 chars) are rejected to bound
  memory and log-line cost.

## Provenance

- Source agent: Agent #8 LLM_ERA
  (`docs/research/outputs/AGENT_8_LLM_ERA.json`).
- OSS references (algorithm source, NOT re-derived):
  - NVIDIA NeMo Guardrails — `output rails`, chained output validators.
  - Guardrails AI — post-inference validator classes
    (`PIIFilter`, `ValidJson`, `RestrictToTopic`).
- Primary policy sources:
  - OWASP Top 10 for LLM Applications (2023) — LLM02 Insecure Output
    Handling; LLM09 Overreliance.

## Alternatives considered and rejected

- Ad-hoc JSON parsing at each call site — silent failures, no shared
  policy, attribution impossible.
- Relying on function-calling schemas alone — catches shape only, misses
  policy and safety classes.

## Extension contract

Additional checks register as adapters in an ordered chain. Any class that
matches the `OutputGuardrail` Protocol (`.name` plus `.evaluate(output,
schema_ref)`) can be dropped into the chain; downstream libraries compose
schema, policy, and safety checks by appending adapters. The Protocol
surface is v1; new methods may be added but the four existing surface
elements (`name`, `evaluate`, `OutputVerdict.action`,
`OutputVerdict.replacement`) will never be renamed or change semantics.

## Usage

```python
from OutputGuardrail import (
    PolicyOutputGuardrail, SafetyOutputGuardrail,
    SchemaOutputGuardrail, VerdictLedger, apply_chain,
)

schemas = {"answer.v1": {"type": "object", "required": ["answer"]}}
chain = [
    SafetyOutputGuardrail(name="safety"),
    PolicyOutputGuardrail(name="pii", rewrite_patterns=((r"\b\d{3}-\d{2}-\d{4}\b", "[SSN]"),)),
    SchemaOutputGuardrail(name="schema", schemas=schemas),
]
ledger = VerdictLedger()
final = apply_chain(chain, model_output, schema_ref="answer.v1", ledger=ledger)
```

## Compose with:

- **Schema-shaped answer** → `PromptTemplate` + `InputValidator`
  Template pins the output schema; OutputGuardrail validates the generation — responses that fail validation trigger a bounded retry, not a 500.

- **Policy compliance** → `InputGuardrail` + `PromptInjectionFilter`
  Outbound safety checks catch what inbound guardrails missed (e.g., exfil via prompt injection) — defense in depth.

- **Observable generations** → `LlmTrace` + `MetricMeter`
  Rejection/rewrite rates are metered; every rejection emits a trace — policy regressions show up as metric jumps, not support tickets.
