# SessionCache

## What it does (plain language)

In a stateless horizontally-scaled tier, any node might receive any
request. Per-caller state — quotas, feature flags, pagination cursors,
session metadata — has to be answerable within a single-digit
millisecond budget regardless of which node serves the request. A
SessionCache is the node-agnostic external store keyed by session token.
Reads are cheap and idempotent; misses return `None` (not raise) so the
caller can distinguish "unknown session" from "store unreachable" via an
explicit exception.

## Purpose

Provide a stateless-tier, node-agnostic read-through cache keyed by
session token for per-caller state with TTL and explicit miss/error
separation.

## When to use and when NOT to use

- USE: per-request quotas, feature-flag evaluations, pagination
  cursors, and other tiny per-caller state that every node must be able
  to answer without a round-trip to the source of truth.
- USE: when you want a deterministic miss/error contract — `None` vs.
  `raise` — so callers don't swallow outages.
- DO NOT USE: as a durable session store — TTL drives eviction, and the
  cache is intentionally lossy; the source of truth lives elsewhere.
- DO NOT USE: for per-object record caching — use `KeyValueBucket` for
  that; SessionCache is scoped to per-caller state keyed by token.

## API surface

`SessionCache.contract.json` is the authority. `get(token)` is the hot
path and MUST be read-only; `set(token, value, ttl_s)` overwrites;
`invalidate(token)` is idempotent and O(1). A cold node that has never
observed the token resolves via the external store through a loader
passed at construction (`ReadThroughSessionCache`).

## Invariants

| ID | Rule |
|---|---|
| SC_INV_01 | `get()` is read-only — never mutates server-side state. |
| SC_INV_02 | Missing key returns `None`, not raise; the caller distinguishes miss vs. error via explicit `SessionCacheError`. |
| SC_INV_03 | `invalidate()` is idempotent and completes in O(1). |
| SC_INV_04 | TTL is honored — an expired entry is equivalent to missing. |
| SC_INV_05 | A node that has never seen a token resolves its session via the external store (cold-cache tolerant). |

## Invariant -> test mapping

Each invariant has at least one test in `test_SessionCache.py` with the
name pattern `test_inv_<slug>_{confirms,prevents}`.

## Thread and async safety

- The in-memory reference implementation is not locked — callers that
  share an instance across threads MUST add their own lock or use a
  threadsafe adapter (Redis client, Memcached).
- `ReadThroughSessionCache` performs loader calls synchronously; wrap
  with an async-compatible loader if used from a coroutine.

## Operational characteristics (for SRE)

- `session_cache.hit_ratio` (gauge) — rolling ratio of cache hits to
  total `get`s; drops below ~0.9 suggest TTL is too short or cache is
  too cold.
- `session_cache.miss_count` (counter) — number of loader round-trips.
- `session_cache.loader_error_count` (counter) — number of
  `SessionCacheError` raised by the loader; spikes indicate external
  store degradation, not a product-side miss.

## Security considerations

- Tokens are opaque to the cache; the cache MUST NOT be used to derive
  additional authority (e.g., do not trust cached values to grant
  access without revalidation at session-creation time).
- The cache holds per-caller state — entries MUST be invalidated on
  logout and on privilege change (role adds/removes) or stale
  permissions will grant access until TTL expiry.
- Defensive-copy on `set` prevents caller mutations from leaking into
  the cached copy.

## Provenance

- Primary source: Redis `GETEX` read-through pattern —
  https://redis.io/docs/latest/commands/getex/
- Secondary: Envoy `ext_authz` filter uses a per-request external
  authorization call with local caching —
  https://www.envoyproxy.io/docs/envoy/latest/configuration/http/http_filters/ext_authz_filter

## Alternatives considered and rejected

- Per-node local-only cache — correctness hole: session mutations made
  on node A are invisible on node B until TTL expiry.
- Raise-on-miss API — callers end up catching an exception on the hot
  path; ambiguity between "unknown token" and "store down" conflates
  two very different operational signals.
- Cache the value forever — security hole: revoked tokens continue to
  grant access; TTL is mandatory.

## Extension contract

Adopters swap `InMemorySessionCache` for `ReadThroughSessionCache`
passing a `loader` that queries the source of truth (Redis, an
auth-service, etc.). Additional adapters MAY live under
`core/venous/_adapters/<backend>/SessionCacheAdapter.py`; all five
invariants MUST be preserved. The Protocol surface is sealed.

## Usage

```python
def load_session_from_redis(token: str) -> dict | None:
    raw = redis.get(f"sess:{token}")
    return json.loads(raw) if raw else None

cache = ReadThroughSessionCache(load_session_from_redis, ttl_s=60)

session = cache.get(token)   # None if unknown, dict if known
if session is None:
    raise HTTPException(401)
cache.invalidate(token)      # on logout
```

## Compose with:

- **Session payload storage** → `KeyValueBucket`
  The external-store loader typically reads from a KeyValueBucket
  implementation whose revision check guards against lost-update races
  during a rolling deploy. Invariant gained: per-session writes cannot
  silently clobber a concurrent update from another node.

- **Per-request binding** → `RequestContext`
  The SessionCache entry is materialized into `RequestContext.principal`
  at the edge of the request pipeline, so downstream handlers read from
  one canonical place and the cache is never touched a second time per
  request. Invariant gained: stable identity within a request.

- **Gated feature reads** → `FeatureToggle`
  FeatureToggle evaluations consult the SessionCache value as the
  evaluation context (e.g., `session["plan"] == "enterprise"`) so the
  toggle decision is node-agnostic and cached alongside the session.
  Invariant gained: consistent feature decisions per session across
  nodes within TTL.
