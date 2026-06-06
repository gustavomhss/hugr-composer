# agent session — 10-llm-agent

Plan-level transcript for `mid/05_llm_agent_backend.md`.

## Requirement → kit mapping

1. **Injection rejected + logged.**
   → `PromptInjectionFilter` evaluates the prompt; match → `InputGuardrail`
     returns `reject` and emits an `AuditEvent`.
2. **Secret-shape redaction on output.**
   → `OutputGuardrail` runs a regex pass for `sk-*`, `AKIA*`, etc.
3. **Daily token budget → 402.**
   → `CostTracker` with `tenant_id` key; over 110% → reject.
4. **TTFT vs total latency.**
   → `LlmTrace` records two timestamps per call.

## Tool call sequence

```
1. fastapi_generate_project(name="llm_svc")
2. fastapi_add_prompt_guard(patterns=["ignore previous", "disregard"])
3. fastapi_add_output_redactor(patterns=["sk-[A-Za-z0-9]+", "AKIA[0-9A-Z]+"])
4. fastapi_add_token_budget(tokens_per_day=100_000, cutoff_ratio=1.10)
```

## Benchmark outcome

Scaffold: 25 · Tests: 25 · Primitive gate: 25 · Hand-edit: 25 — **100**
