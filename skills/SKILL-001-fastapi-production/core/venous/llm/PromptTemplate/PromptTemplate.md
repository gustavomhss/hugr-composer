# PromptTemplate

## What it does (plain language)

A PromptTemplate is a named, versioned prompt whose text, declared variables,
and target model are frozen at publication. You publish version 1; if you need
to change the text, you publish version 2. Two identical (name, version, values)
triples always produce the same rendered payload, byte-for-byte. That lets
evaluations reproduce, incidents trace back to the exact text that generated
the bad output, and cost/quality experiments compare apples to apples.

## Purpose

Declare a named, versioned, parameterized prompt whose text, variables, and
target model are pinned so two runs of the same version produce identical
rendered payloads.

## When to use and when NOT to use

- USE: any prompt that is exercised in production, subject to eval, or a
  candidate for rollback.
- DO NOT USE: one-shot debugging prints or one-off research notebook calls
  where identity doesn't matter.
- DO NOT USE: system prompts that are themselves assembled dynamically at
  runtime from untrusted context — route that text through
  `PromptInjectionFilter` first, then render it as a declared variable.

## API surface

The catalog `api_signature` is the sole authority; see
`PromptTemplate.contract.json`. The reference implementation
`FrozenPromptTemplate` is immutable after construction, enforces declared-vs-
referenced variable set equality, and exposes `render(values)` plus
`fingerprint()`. A global-style `PromptRegistry` binds `(name, version)` to
exactly one `FrozenPromptTemplate` and rejects attempts to republish a
different body under the same version.

## Invariants

| ID | Rule |
|---|---|
| PROMPT_INV_01 | Rendered output MUST be byte-identical across two calls with the same (version, values) pair. |
| PROMPT_INV_02 | A published version MUST NEVER be mutated; changes SHALL produce a new integer version. |
| PROMPT_INV_03 | render() MUST raise when a declared variable is missing; empty-string default is FORBIDDEN. |
| PROMPT_INV_04 | fingerprint() MUST cover template text, target_model, and variable names. |
| PROMPT_INV_05 | Variable interpolation MUST use explicit delimiters and CANNOT treat user input as template syntax. |

## Invariant → test mapping

Each invariant has three tests (`test_inv_<slug>_{confirms,prevents,
under_failure}`) plus behavioral, metamorphic, state-machine, concurrent,
and chaos coverage. See `invariant_bindings.json` for the authoritative
binding.

## Thread and async safety

- `FrozenPromptTemplate` is immutable; `render()` is a pure function with no
  shared mutable state.
- `PromptRegistry` uses a `threading.Lock` around register/resolve so
  concurrent registers of a conflicting `(name, version)` collapse to exactly
  one winner.
- No asyncio-specific surface — the Protocol is synchronous because render
  cost is µs-scale and offering an async render would only add overhead.

## Operational characteristics (for SRE)

- Registry membership is the top surfaced metric: `prompt.registry.size` gauge
  per name. A steadily growing size with no corresponding release cadence is
  a symptom of ad-hoc prompt creation bypassing the deploy process.
- Render latency histogram (`prompt.render.latency`) is expected p95 < 1 ms;
  a regression usually means the template text grew pathologically large or
  a caller is rendering inside a hot loop (anti-pattern — render once,
  reuse the string).
- Render error counter (`prompt.render.errors`) with label `error_kind` in
  (`missing_variable`, `extra_variable`, `non_string_value`, `oversize_value`)
  is the primary correctness signal during a rollout.

## Security considerations

- Variable values are treated as literal data, not as template syntax. A
  value containing `{{other}}` survives verbatim — no recursive expansion.
- Extra values are REJECTED, not ignored, to close the smuggling channel
  where an attacker could ship undeclared keys hoping a future template
  version would pick them up.
- Non-string values (int, None, nested structures) are rejected — they are
  the common accidental-PII-leak shape (`span.set_attribute("user", user_dict)`
  style).
- Oversize values are rejected at 200 KB per value, 1 MB for the template
  itself, preventing pathological prompts from exhausting provider context.

## Provenance

- Source agent: Agent #8 LLM_ERA (`docs/research/outputs/AGENT_8_LLM_ERA.json`).
- Primary sources:
  - Langfuse 2.x — Prompt Management (versioned prompts, labels, compile()).
  - Weights & Biases Weave 0.50+ — `weave.Prompt` / `StringPrompt` as
    versioned prompt objects.

## Alternatives considered and rejected

- Inline f-strings per call site — loses version identity, makes rollback
  impossible.
- Loading prompts from files — no fingerprint, no immutability, no named
  versions.

## Extension contract

Downstream code registers new prompts by constructing a `FrozenPromptTemplate`
and calling `PromptRegistry.register`; the registry rejects a second
registration of `(name, version)` whose fingerprint differs. Semver: the
Protocol surface is v1; additive methods may be added without breaking
callers but NEVER rename or change the semantics of the four existing
surface attributes (`name`, `version`, `target_model`, `variables`).

## Usage

```python
def extract_fields(tpl: PromptTemplate, document: str, fields: str) -> tuple[str, str]:
    rendered = tpl.render({"fields": fields, "document": document})
    fp = tpl.fingerprint()
    # Fingerprint is logged alongside the span so trace → PromptTemplate is reconstructable.
    return rendered, fp
```

## Compose with:

- **Versioned prompt contract** → `LlmTrace` + `OutputGuardrail`
  Every generation records the template version, inputs, and schema; A/B comparisons are deterministic and traces are diffable across releases.

- **Guarded rendering** → `InputGuardrail` + `PromptInjectionFilter`
  Template variables are rendered through guardrails; untrusted substrings cannot rewrite the instruction region.

- **Cost-aware routing** → `MetricMeter` + `SamplingPolicy`
  Per-template token counters drive cost attribution; sampling policy retains a representative share of traces without blowing observability budget.
