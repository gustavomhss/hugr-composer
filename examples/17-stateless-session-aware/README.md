# Example 17 — Stateless API with session-aware behavior

**Tier:** adversarial · **Benchmark spec:**
`adversarial/02_contradiction_stateless_but_session_aware.md`

Per-caller rate limit, quota, and cursor — with stateless API nodes that
fetch/write shared session state on every request. Demonstrates the
**`SessionCache`** recipe (the Phase-3 primitive for this contradiction).

## What this example shows

- Killing a node mid-session does not lose remaining quota or last cursor.
- A feature flag flipped on any node propagates to the others within 1s.
- Random caller-to-node routing gives identical per-caller behavior vs sticky.
- A cold-cache node does not reset per-caller rate limits to zero.

## How to run

```bash
cd examples/17-stateless-session-aware
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q
```

## Tools used

| Tool                                 | Role                                            |
| ------------------------------------ | ----------------------------------------------- |
| `fastapi_add_shared_session`         | External KV-backed session cache.               |
| `fastapi_add_feature_flags`          | Read-through flag cache with TTL.               |
| `fastapi_add_per_caller_rate_limit`  | Counters keyed by caller, stored externally.    |

## Primitives imported

| Primitive                | Role                                                |
| ------------------------ | --------------------------------------------------- |
| `SessionCache`           | Stateless-tier read-through per-caller state.       |
| `KeyValueBucket`         | External store for session payloads.                |
| `FeatureFlagCache`       | TTL-bounded flag cache, invalidated via pub/sub.    |
| `RateLimiter`            | Counters keyed by caller_id, shared across nodes.   |
| `CurrentPrincipal`       | Resolved caller identity per request.               |

Reference pages at `docs.hugr.dev/primitive/<Name>`.
