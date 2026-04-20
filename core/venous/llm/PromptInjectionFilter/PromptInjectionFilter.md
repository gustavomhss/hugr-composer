# PromptInjectionFilter

## What it does (plain language)

PromptInjectionFilter is the quarantine boundary between untrusted text
(retrieved documents, tool outputs, user messages) and the model. It wraps
every untrusted block in explicit delimiters the model is instructed to treat
as data, strips fragments that look like instructions (role overrides,
"ignore previous instructions", jailbreak tokens, delimiter escapes, exfiltration
directives), and records an audit trail so SREs can replay what was removed.

## Purpose

Make indirect prompt injection the single well-defined failure surface it
should be: one primitive every context-assembly path MUST traverse before
any untrusted string reaches the model.

## When to use and when NOT to use

- USE: every RAG retrieval, every tool-call stdout piped back to the model,
  every multi-turn user message entering a system-prompt template.
- DO NOT USE: first-party system text authored by the application
  (templates, rubrics). Use `ContextAssembler.add_raw_trusted_system` for
  that — and review it in code review.
- DO NOT USE: reply post-processing; the filter is a *context* primitive.
  Output sanitation is the OutputGuardrail primitive's job.

## API surface

The catalog `api_signature` in `PromptInjectionFilter.contract.json` is the
authority. Callers invoke `filter.quarantine(raw, kind)` where `kind ∈
{"user","retrieved","tool_output"}`. The returned `QuarantinedText` exposes
`wrapped` (the body with delimiters) and `stripped_fragments` (every span the
filter removed, verbatim for audit). `QuarantinedBlock` is **immutable**:
post-construction attribute mutation raises.

## Invariants

| ID | Rule |
|---|---|
| PIF_INV_01 | `quarantine()` MUST wrap the raw text in explicit delimiters the model is instructed to treat as data; raw insertion into system prompts is FORBIDDEN. |
| PIF_INV_02 | Fragments matching known instruction patterns SHALL be stripped and the removed text returned in `stripped_fragments` for audit. |
| PIF_INV_03 | The filter MUST NEVER execute or interpret raw text; it only transforms text (no eval, exec, templating, or subprocess). |
| PIF_INV_04 | Every quarantined block SHALL declare its `kind` so downstream guardrails CAN apply kind-specific rules. |
| PIF_INV_05 | Quarantining is NEVER optional for `retrieved` or `tool_output` content; skipping the filter on those sources is FORBIDDEN. |

## Invariant → test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the binding.

## Thread and async safety

- `DefaultPromptInjectionFilter` serializes rule-pipeline reads and audit-trail
  writes via an internal RLock — concurrent `quarantine` calls are safe.
- Rule mutation (`add_rule`, `remove_rule`) is safe to interleave with
  concurrent `quarantine` calls.
- The filter is thread-local by default at call time: state is the audit
  trail plus the rule set. Callers that need isolation per tenant SHOULD
  instantiate one filter per tenant.

## Operational characteristics (for SRE)

- Audit trail is bounded by `audit_limit` (default 10_000); oldest entries
  are evicted past the bound so memory is flat on long-running processes.
- Rule failures surface as Python exceptions — the filter NEVER silently
  drops a rule that raised. Wrap rule adapters in your own safety-net if
  you want degraded-mode fallback, but do so explicitly.
- Metrics: `pif.quarantines` (counter, `kind` label), `pif.stripped.fragments`
  (histogram, `kind` label), `pif.body.bytes` (histogram, `kind` label).
- A sudden rise in `pif.stripped.fragments` on `kind=retrieved` is the
  primary indicator of an RAG corpus poisoning campaign.

## Security considerations

- The filter is a defense-in-depth layer, not a cure. Combine with:
  OutputGuardrail on the response side, ModelRouter policy for high-risk
  kinds, and HumanCheckpoint for privileged tool invocations.
- Patterns are adapted from Rebuff and Lakera Guard — add project-specific
  rules as `StrippingRule` adapters; do NOT edit the default pattern set
  without a security review.
- `QuarantinedBlock` is immutable; downstream code must re-invoke the filter
  to change the stripped body. Rollback-after-fact is impossible by design.

## Provenance

- Source agent: Agent #8 LLM_ERA
  (`docs/research/outputs/AGENT_8_LLM_ERA.json`).
- Algorithm references (adapted, not re-derived):
  - [protectai/rebuff](https://github.com/protectai/rebuff) — detector list.
  - [Lakera Guard](https://www.lakera.ai/blog) — jailbreak heuristic families.
  - [Guardrails AI — restrict-to-topic](https://github.com/guardrails-ai/guardrails) — rule registry pattern.
  - OWASP Top 10 for LLM Applications (2023), LLM01 — indirect injection.
  - Anthropic Model Context Protocol (MCP) 1.x — untrusted-resource handling.

## Alternatives considered and rejected

- Concatenate retrieved content directly into the system prompt — the
  canonical exploit surface; rejected on first principles.
- Rely on model refusal — inconsistent, not auditable, and silently fails
  on open-source models.
- One-shot LLM detector without delimiters — raises cost and latency per
  call, and offers no audit trail.

## Extension contract

Projects extend the default rule set by registering new `StrippingRule`
adapters via `filter.add_rule(...)`. Each rule implements a `name`
attribute and a `match(text, kind)` method that returns `(start, end)`
spans. The filter composes rules in registration order; spans are merged
before redaction, so rule order is not semantically significant. Custom
rules MUST NOT call `eval`, `exec`, subprocess, or any I/O (PIF-INV-03).

## Schema of `PromptInjectionFilter.contract.json`

The contract file is a verbatim copy of the `PrimitiveSpec` dict from the
research catalog. Fields: `name`, `namespace`, `purpose`, `api_signature`,
`invariants[]`, `extension_contract`, `consumption_example`, `sources[]`,
`why_essential`, `alternatives_considered[]`, `maturity`.

## Usage

```python
from PromptInjectionFilter import DefaultPromptInjectionFilter, ContextAssembler

f = DefaultPromptInjectionFilter()
asm = ContextAssembler(f)
for snippet in rag_results:
    asm.add(snippet.text, kind="retrieved")
asm.add(user_turn, kind="user")
context = asm.render()
```

## Compose with:

- **Untrusted-context quarantine** → `InputGuardrail` + `PromptTemplate`
  Fetched documents, tool outputs, and memory are tagged and scanned; the template renders them inside a sandbox region the model cannot treat as instructions.

- **End-to-end safety** → `OutputGuardrail` + `LlmTrace`
  Inbound + outbound filter plus trace-level attribution: you can always answer 'which document triggered this refusal?'.

- **Tool-call gating** → `RequestGuard` + `OutputGuardrail`
  Tool invocations pass through the filter before RequestGuard runs — injected 'delete my account' never reaches the authorizer.
