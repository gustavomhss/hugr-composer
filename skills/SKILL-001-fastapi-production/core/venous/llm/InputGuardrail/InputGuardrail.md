# InputGuardrail

## What it does (plain language)

InputGuardrail intercepts user text BEFORE it reaches any LLM call and lets a
chain of validators inspect it. Each validator returns a deterministic verdict —
`allow`, `redact`, or `block` — plus a human-readable `reason`. A `block` halts
the pipeline immediately; a `redact` rewrites the text so downstream validators
(and the model) only see the sanitized version; `allow` lets the text through.
The reference `Chain` keeps an audit log with the raw inputs hashed (BLAKE2b,
16-byte digest) so operators can explain verdicts without leaking the inputs.

## Purpose

Intercept user input before it reaches a model and reject, redact, or transform
it according to deterministic rules (PII, injection markers) and optional
LLM-judged classifications.

## When to use and when NOT to use

- USE: every user-facing endpoint that forwards text into an LLM — chat,
  completion, RAG queries, agent invocations.
- USE: compliance-driven PII redaction (GDPR/HIPAA) and prompt-injection
  mitigation (OWASP LLM01).
- DO NOT USE: post-generation filtering — that is `OutputGuardrail`'s job.
- DO NOT USE: authorization or rate limiting — use `AuthZ` and `RateLimiter`
  primitives respectively.

## API surface

The catalog `api_signature` is the sole authority; see
`InputGuardrail.contract.json` for the verbatim Protocol declaration.
`InputGuardrail.evaluate(text, context) -> GuardDecision` returns one of three
actions. The reference `Chain` composes an ordered pipeline of guards; callers
invoke `chain.apply(text, context)` which either returns the (possibly redacted)
text or raises `GuardBlocked`.

## Invariants

| ID | Rule |
|---|---|
| GUARD_INV_01 | `evaluate()` MUST be deterministic for a given (text, context) unless the guardrail declares itself probabilistic via a `:probabilistic` name suffix. |
| GUARD_INV_02 | A `block` decision MUST halt the pipeline; the caller CANNOT silently downgrade it to `allow`. `Chain.apply()` raises `GuardBlocked`. |
| GUARD_INV_03 | `redact` decisions SHALL return `redacted_text` and MUST NEVER return the original text under a redact verdict. |
| GUARD_INV_04 | Every decision MUST carry a non-empty `reason` so downstream audit can explain the verdict. |
| GUARD_INV_05 | Guardrails MUST NEVER store raw blocked inputs in clear form; storage SHALL be hashed (BLAKE2b, 16 bytes). |

## Invariant → test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the authoritative binding.

## Thread and async safety

- `Chain.apply` and `Chain.seal` are thread-safe; the internal state transition
  (`open` → `sealed`) and audit ring buffer are guarded by a single lock.
- `Decision` is effectively immutable (`__slots__`); callers SHOULD construct a
  new instance rather than mutate existing fields.

## Operational characteristics (for SRE)

- Hot-path cost: O(number-of-guards) per `apply()`; every built-in guard is
  O(len(text)) in the worst case.
- Audit ring buffer is bounded by `MAX_AUDIT_ENTRIES` (1 000 rows); older rows
  are dropped FIFO.
- `seal()` is an operational kill-switch: once sealed, no further text is
  evaluated. Pair with a watchdog that monitors block rate per guard.
- Self-observability metrics: `inputguardrail.decisions.total`,
  `inputguardrail.blocks.total`, `inputguardrail.redactions.total`,
  `inputguardrail.apply.duration`, `inputguardrail.audit.depth`.

## Security and privacy considerations

- **Privacy-first by construction.** Blocked inputs are hashed with BLAKE2b
  (16-byte digest) before ever touching the audit log. Raw clear text MUST NOT
  be stored, even under `redact`.
- The `GuardBlocked` exception also carries only the hashed input, so upstream
  logs that capture exceptions cannot accidentally leak the raw text.
- `PromptInjectionBlocker` detects a deterministic list of classic markers
  (NeMo Guardrails + Guardrails AI heuristics); deployments SHOULD add an
  LLM-judged probabilistic guardrail named `*:probabilistic` for advanced
  attacks — the `:probabilistic` suffix opts out of GUARD-INV-01 determinism.
- Redaction replaces PII with fixed sentinels (`[REDACTED_EMAIL]`,
  `[REDACTED_SSN]`, `[REDACTED_CARD]`) — downstream processes MUST NOT attempt
  to reverse the redaction.

## Provenance

- Source agent: Agent #8 LLM_ERA
  (`docs/research/outputs/AGENT_8_LLM_ERA.json`).
- Primary sources:
  - OWASP Top 10 for LLM Applications (2023): LLM01 Prompt Injection,
    LLM06 Sensitive Information Disclosure.
  - NVIDIA NeMo Guardrails — validator-chain / short-circuit-on-block pattern.
  - Guardrails AI — validator Protocol + redact/block verdict shape.

## Alternatives considered and rejected

- Regex inside each endpoint — impossible to centrally audit or update when
  threat patterns change.
- Relying on the model itself to refuse — bypassable and not auditable.

## Extension contract

Projects add a guardrail by implementing the `InputGuardrail` Protocol
(`name: str`, `evaluate(text, context) -> GuardDecision`) and registering it in
an ordered `Chain`. The chain runs guards as a pipeline of interceptors,
stopping at the first `block` verdict. Extensions MUST preserve all five
invariants; probabilistic guardrails MUST append `:probabilistic` to `name`.

## Schema of `InputGuardrail.contract.json`

The contract file is a verbatim copy of the `PrimitiveSpec` dict from the
research catalog (`docs/research/outputs/AGENT_8_LLM_ERA.json`). Fields:
`name`, `namespace`, `purpose`, `api_signature`, `invariants[]`,
`extension_contract`, `consumption_example`, `sources[]`, `why_essential`,
`alternatives_considered[]`, `maturity`.

## Usage

```python
from InputGuardrail import Chain, PIIRedactor, PromptInjectionBlocker, GuardBlocked

chain = Chain([
    PromptInjectionBlocker(),
    PIIRedactor(),
])

def check_prompt(text: str) -> str:
    # GUARD-INV-02: block halts — GuardBlocked propagates; caller CANNOT swallow.
    # GUARD-INV-03: redact swaps text in flight — the returned text is sanitized.
    try:
        return chain.apply(text, {"user_role": "customer"})
    except GuardBlocked as blocked:
        # GUARD-INV-05: `blocked.hashed_input` is a BLAKE2b digest; never clear text.
        raise PermissionError(f"{blocked.guard_name}: {blocked.reason}") from blocked
```

## Compose with:

- **Sanitize-then-prompt** → `PromptInjectionFilter` + `PromptTemplate`
  Input is scrubbed for injection patterns before it enters the template; the template's policy cannot be overridden by user text.

- **Schema + policy** → `InputValidator` + `PromptInjectionFilter`
  Typed schema validation runs first; guardrail runs second — malformed structure never reaches the policy layer.

- **Symmetric I/O filtering** → `OutputGuardrail` + `PromptInjectionFilter`
  Input and output guardrails share threat taxonomy; a pattern blocked inbound is also blocked in the response — no one-way leaks.
