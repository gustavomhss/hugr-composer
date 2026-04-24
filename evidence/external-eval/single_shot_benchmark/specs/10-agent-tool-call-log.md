# agent-tool-call-log

> **Status:** STUB — content authoring deferred to Gustavo pre-tag.

## Requirements

[Gustavo: LLM agent endpoint that logs every tool call (name, input,
output, duration, error). Tool call log is append-only and queryable
per session.]

## Acceptance criteria

- POST `/agent/run {prompt}` returns 200 + session_id + answer.
- GET `/agent/sessions/{id}/calls` returns chronological tool calls.
- A failed tool call appears in the log with `error` field set.
- Concurrent sessions do not interleave their tool call logs.

## Non-requirements

- No actual LLM provider integration at v1 (mock-only is acceptable).
- No tool sandboxing beyond signature validation.
