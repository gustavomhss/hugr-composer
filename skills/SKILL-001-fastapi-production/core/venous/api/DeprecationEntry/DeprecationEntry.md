# DeprecationEntry

`DeprecationEntry` captures everything an HTTP layer needs to emit RFC 8594
Sunset / Deprecation / Link headers for a single endpoint: the `path`, upper-
cased `method` (`DEPRECATION_ENTRY_INV_02`), an ISO `sunset` date that becomes
the verbatim Sunset header value via `sunset_header`
(`DEPRECATION_ENTRY_INV_01`), the `replacement` URL that callers should migrate
to, and a free-text `description`. It is a pure value object — no I/O, no
framework dependency — so it can be shared between the middleware that writes
response headers, the registry that indexes entries by `METHOD path`, and the
reporter that tallies usage.

`days_until_sunset` is a simple delta from `date.today()` that is allowed to go
negative (`DEPRECATION_ENTRY_INV_03`), and `should_warn` toggles True inside
the configured warn window (`DEPRECATION_ENTRY_INV_04`), so log-noise policy
and OpenAPI annotation can share the same predicate. Extracted from
`adapt/extend/api_design/add_api_deprecation.py` (lines 239–315); pairs with
`DeprecationRegistry` and `DeprecationReporter` in the same catalog namespace.

## Compose with:

- **Catalog + emit** → `DeprecationRegistry` + `DeprecationReporter`
  Entry is the frozen value; registry routes requests to it; reporter counts hits — three primitives, one lifecycle for RFC 8594.

- **Schema-aware deprecation** → `SchemaComparator` + `DeprecationRegistry`
  Comparator flags breaking changes between OpenAPI releases; the flagged endpoint becomes an Entry, scheduled for Sunset on the next release.

- **Sunset observability** → `DeprecationReporter` + `StructuredLogger`
  Reporter emits structured counters per endpoint; operators see real traffic to retiring paths before the Sunset date arrives.
