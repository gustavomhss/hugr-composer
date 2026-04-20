# LLM agent backend

## Requirements

- Users `POST /agents/{agent}/invoke` with a prompt and receive a streamed response.
- Prompt input is filtered to detect and reject prompt-injection attempts before reaching the model.
- Output is filtered to strip leaked secrets and to enforce a per-agent content policy.
- Every invocation records: input tokens, output tokens, latency, model, cost estimate.
- A runaway agent consuming tokens beyond a per-tenant daily budget is cut off with 402.

## Acceptance criteria

- A prompt containing a known injection pattern ("Ignore previous instructions…") is blocked with a logged event.
- Output containing an API key pattern is redacted before being streamed to the client.
- At 110% of the daily budget, the next invocation returns 402 and the meter shows correct cost attribution.
- Latency metrics distinguish time-to-first-token from total response time.

## Non-requirements

- No fine-tuning interface.
- No vector-store / RAG — prompts are self-contained.
- No multi-model routing — one model per agent.
- No UI; API only.
