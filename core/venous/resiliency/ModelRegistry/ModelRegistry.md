# ModelRegistry

**Namespace:** `resiliency`
**Maturity:** `emerging`
**Source tool:** `adapt/extend/infrastructure/add_ml_model_server.py`

## Purpose

`ModelRegistry` is a dict-based singleton that maps
`"{name}:{version}"` keys to zero-argument loader callables. Models are
constructed lazily on first `get()` and memoised. It is a minimal
building block behind any system that needs named, versioned, lazily-
instantiated resources (ML models, embeddings, rule engines).

## Invariants

- **MODEL_REGISTRY_INV_01** — Memoisation: the loader for any given
  `name:version` is invoked at most once over the registry's lifetime
  (provided the loader succeeds).
- **MODEL_REGISTRY_INV_02** — Fail-loud lookup: `get()` on an
  unregistered key raises `KeyError`; there is no implicit registration
  and no silent `None` return.
- **MODEL_REGISTRY_INV_03** — Version isolation: distinct version
  strings under the same name are independent cache slots.

Tests: see `test_ModelRegistry.py`.

## Compose with:

- **Lazy versioned loading** → `KeyValueBucket` + `LifecycleHook`
  Registry caches loaded models keyed by name:version; lifecycle hooks warm the hot set at boot — the first request isn't a cold-start cliff.

- **Safe A/B rollout** → `FeatureToggle` + `LlmTrace`
  Toggle routes a cohort to a new model version; traces carry the version attribute — quality diffs are per-version, not per-deploy.

- **Bounded memory** → `MetricMeter` + `CardinalityGuard`
  Loaded-model count is metered and bounded; one stray version cannot OOM the server.
