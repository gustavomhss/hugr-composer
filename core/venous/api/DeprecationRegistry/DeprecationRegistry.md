# DeprecationRegistry

`DeprecationRegistry` is the process-wide index of
[`DeprecationEntry`](../DeprecationEntry/DeprecationEntry.md) objects keyed by
`'METHOD path'`. Request middleware asks the registry `get(path, method)` on
each request and, on a hit, stamps RFC 8594 Sunset / Deprecation / Link
headers onto the response; on a miss the registry returns `None` without
raising (`DEPRECATION_REGISTRY_INV_04`). Registration upper-cases the method
and uses the composite key so that `GET /v1/items` and `POST /v1/items` are
independent deprecations (`DEPRECATION_REGISTRY_INV_01`).

`list_all()` returns every entry serialized and sorted by sunset date
ascending (`DEPRECATION_REGISTRY_INV_03`), which is the payload used by
`/_meta/deprecations` dashboards and by CI checks that fail a build when a
sunset date has arrived. Re-registering the same (method, path) intentionally
overwrites (`DEPRECATION_REGISTRY_INV_02`) so a later migration plan can
supersede an earlier one without an explicit deregister step. Extracted from
`adapt/extend/api_design/add_api_deprecation.py` (lines 318–378).

## Compose with:

- **Middleware-stamped headers** → `MiddlewarePipeline` + `DeprecationEntry`
  Pipeline asks the registry on every request; a hit stamps Sunset/Deprecation/Link headers uniformly — individual handlers never remember to do this.

- **Usage-driven retirement** → `DeprecationReporter` + `MetricMeter`
  Registry lookups feed the reporter; hot deprecated endpoints are the signal not to retire on schedule.

- **Versioned rollout** → `SchemaComparator` + `FeatureToggle`
  Schema diff populates the registry with sunset entries; a toggle can force 410 Gone once usage falls below threshold.
