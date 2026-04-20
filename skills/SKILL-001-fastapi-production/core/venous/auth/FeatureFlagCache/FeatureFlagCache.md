# FeatureFlagCache

**Namespace:** `auth`
**Maturity:** `emerging`
**Source tool:** `adapt/extend/auth_access/add_feature_flags.py`

## Purpose

`FeatureFlagCache` is a bounded in-process async LRU cache with per-entry
TTL, designed for feature-flag payloads where reads are 100x more
frequent than writes. Backed by `collections.OrderedDict`, guarded by
`asyncio.Lock`.

## Invariants

- **FEATURE_FLAG_CACHE_INV_01** — Read-through TTL eviction: `get()` on
  an expired entry returns `None` AND deletes the entry from the store
  in the same call.
- **FEATURE_FLAG_CACHE_INV_02** — Capacity bound: after any `set`, the
  store size never exceeds `MAX_CACHE_SIZE`; eviction is strict LRU.
- **FEATURE_FLAG_CACHE_INV_03** — Write-then-read consistency: within
  the TTL window, `get(k)` after `set(k, v)` returns `v`.

Tests: see `test_FeatureFlagCache.py`.

## Compose with:

- **Low-latency toggle evaluation** → `FeatureToggle` + `KeyValueBucket`
  Cache keeps per-cohort flag values hot; toggle evaluation is O(1) on the request path; misses refill via the bucket with bounded TTL.

- **Invalidation on change** → `EventBus` + `AuditEvent`
  Flag-change events invalidate cache entries and audit the change — stale reads are bounded and the change is attributable.

- **Safe fallback** → `CircuitBreaker` + `ConfigBinding`
  If the upstream provider is unreachable, the cache serves last-known-good; ConfigBinding supplies the default — a feature-flag outage never 500s a route.
