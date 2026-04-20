# Per-key rate limiter with priority classes

## Background

An internal API gateway protects a downstream service from abuse. Each
call is authenticated by an `X-Api-Key` header. Keys are divided into
**priority classes**:

- `gold`   — 20 requests per rolling second.
- `silver` — 5 requests per rolling second.
- `bronze` — 1 request per rolling second.

Each class has its own budget; a `silver` key's traffic MUST NOT
deplete a `gold` key's budget. Under overload, lower-priority classes
shed first.

For this exercise the registry is hard-coded:

```
gold-1, gold-2   → class "gold"
silver-1         → class "silver"
bronze-1         → class "bronze"
```

An unknown API key is rejected with 401.

## Requirements

1. `POST /call` — any JSON body is accepted. Required header
   `X-Api-Key: <string>`.
   - If the key is unknown → 401.
   - If the key is recognized but the class budget is exhausted for
     the current rolling second → 429 with a body
     `{"retry_after_ms": <int>}`.
   - Otherwise → 200 `{"ok": true, "class": "<gold|silver|bronze>"}`.
2. Rate-limit window is a **rolling 1-second** window per class (not
   per key). Two gold keys share the gold bucket.
3. Response headers on 200 and 429 MUST include
   `X-RateLimit-Class: <class>` and `X-RateLimit-Remaining: <int>`.
4. `GET /health` → 200 `{"ok": true}`.
5. Unknown keys MUST NOT consume any budget (do not bill a 401).

## Acceptance criteria

- Gold key can sustain 20 calls/sec; call 21 in the same second → 429.
- Silver key burst of 6 in one second → last one gets 429.
- Bronze burst of 2 in one second → second gets 429.
- Under sustained silver flood, a concurrent gold request still gets
  200 (class isolation).
- Unknown key gets 401; does not increment any counter.

## Non-requirements

- No persistence.
- No distributed limiter (single process is fine).
- No quota over longer windows.
