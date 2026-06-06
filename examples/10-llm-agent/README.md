# Example 10 — LLM agent backend

**Tier:** mid · **Benchmark spec:** `mid/05_llm_agent_backend.md`

Prompt-in / tokens-out with injection filtering, output redaction, and a
per-tenant daily token budget. Demonstrates the **`InputGuardrail` +
`OutputGuardrail` + `CostTracker`** recipe.

## What this example shows

- Injection patterns ("Ignore previous instructions…") rejected + logged.
- API-key-shaped substrings in model output are redacted before streaming.
- At 110% of the daily budget, the next invocation returns 402.
- Latency metrics distinguish time-to-first-token from total response time.

## How to run

```bash
cd examples/10-llm-agent
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q
```

## Tools used

| Tool                                 | Role                                            |
| ------------------------------------ | ----------------------------------------------- |
| `fastapi_add_llm_invoke`             | POST /agents/{agent}/invoke, streamed body.     |
| `fastapi_add_prompt_guard`           | Injection-filter on input.                      |
| `fastapi_add_output_redactor`        | API-key / PII redaction on output.              |
| `fastapi_add_token_budget`           | Per-tenant daily cost cutoff.                   |

## Primitives imported

| Primitive                | Role                                                |
| ------------------------ | --------------------------------------------------- |
| `InputGuardrail`         | Policy check on raw prompt.                         |
| `PromptInjectionFilter`  | Dedicated injection-pattern detector.               |
| `OutputGuardrail`        | Post-generation redaction / policy check.           |
| `CostTracker`            | Per-tenant token + cost accumulator.                |
| `LlmTrace`               | Spans with TTFT + total-latency attributes.         |

Reference pages at `docs.hugr.dev/primitive/<Name>`.
