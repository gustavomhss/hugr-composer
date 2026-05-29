# `core/venous/_ports/` — Catalog (WP-15 phase 1)

Ground-truth enumeration of every **registered primitive** under
`core/venous/<ns>/<Name>/` and its port-status. The machine-readable
counterpart is [`CATALOG.json`](./CATALOG.json) — that file is the
source of truth for downstream WPs; this Markdown is its narrative.

> **Scope.** Registered primitives only — the 124 directories that
> ship as the HuGR primitives layer. Staged primitives (`_staging/*`,
> 175 entries + 42 quarantined) and adapters (`_adapters/*`, 17
> FastAPI + redis/stripe sub-trees) are **excluded by design**;
> WP-15 catalogues only the surface that follow-up port-consumer WPs
> will migrate.

## Headline

| Metric | Value |
|---|---:|
| Registered primitives catalogued | **124** |
| Namespaces present | **15** (api, auth, billing, cache, compliance, data, events, extras, flags, jobs, llm, obs, policy, resiliency, security) |
| Primitives with auto-inferred `<Name>.protocol.py` stub | **25** |
| Primitives without a stub | **99** |
| Hand-authored ports in this WP (`port_status: exemplar`) | **2** (`api/CommandBus`, `api/QueryBus`) |
| Queued with stub (`port_status: queued`) | **23** |
| Queued without stub (`port_status: missing-stub`) | **99** |

The `cost` namespace exists on disk (`core/venous/cost/`) but ships
**zero registered primitives** — INVENTORY.md row `cost = 0` confirms.
`cost` is therefore **not** represented in `_ports/`; the §1 owned-files
list omits it deliberately. Follow-up WPs that promote a `cost`
primitive will add `_ports/cost/` at that point.

## Derivation procedure (reproducible)

Run from `skills/SKILL-001-fastapi-production` on a fresh checkout:

```bash
# Enumerate the 124 registered primitive directories.
find core/venous \
    -mindepth 2 -maxdepth 2 -type d \
    ! -path 'core/venous/_staging*' \
    ! -path 'core/venous/_adapters*' \
    ! -name '__pycache__' \
  | sort
```

Expected output: 124 paths of the form `core/venous/<ns>/<Name>/`.
For each path, the catalog row is computed as:

| Field | Value |
|---|---|
| `namespace` | the `<ns>` segment (`api`, `auth`, …) |
| `name` | the `<Name>` segment (`CommandBus`, `RateLimiter`, …) |
| `has_protocol_stub` | `True` iff `<Name>/<Name>.protocol.py` exists |
| `port_status` | `exemplar` for the 2 hand-authored ports in `_ports/api/`; otherwise `queued` if `has_protocol_stub`, else `missing-stub` |

A reviewer can re-derive `CATALOG.json` from this procedure
deterministically. If the count drifts from 124, **the source of
truth is `INVENTORY.md`** (`python -m engine.inventory`), not a hand
edit to the catalog — see §9 F-01 of the WP manifest.

## Per-namespace breakdown

| Namespace | Primitives | With stub | Exemplar ports (WP-15) | Queued (with stub) | Missing stub |
|---|---:|---:|---:|---:|---:|
| `api` | 17 | 11 | 2 | 9 | 6 |
| `auth` | 8 | 1 | 0 | 1 | 7 |
| `billing` | 1 | 0 | 0 | 0 | 1 |
| `cache` | 3 | 1 | 0 | 1 | 2 |
| `compliance` | 7 | 0 | 0 | 0 | 7 |
| `data` | 19 | 2 | 0 | 2 | 17 |
| `events` | 13 | 1 | 0 | 1 | 12 |
| `extras` | 5 | 1 | 0 | 1 | 4 |
| `flags` | 1 | 0 | 0 | 0 | 1 |
| `jobs` | 3 | 0 | 0 | 0 | 3 |
| `llm` | 4 | 0 | 0 | 0 | 4 |
| `obs` | 17 | 0 | 0 | 0 | 17 |
| `policy` | 4 | 0 | 0 | 0 | 4 |
| `resiliency` | 14 | 8 | 0 | 8 | 6 |
| `security` | 8 | 0 | 0 | 0 | 8 |
| **TOTAL** | **124** | **25** | **2** | **23** | **99** |

(Per-namespace cell counts derived from `CATALOG.json`; recompute by
filtering entries on `namespace` and `port_status`.)

## Exemplar ports — port_status: exemplar

| Namespace | Name | Existing stub | Hand-authored port |
|---|---|---|---|
| `api` | `CommandBus` | `core/venous/api/CommandBus/CommandBus.protocol.py` | [`_ports/api/CommandBus.py`](./api/CommandBus.py) |
| `api` | `QueryBus` | `core/venous/api/QueryBus/QueryBus.protocol.py` | [`_ports/api/QueryBus.py`](./api/QueryBus.py) |

These two were chosen because (a) both share the bus-style
register-then-dispatch shape, so a single design decision validates
both; (b) the existing auto-inferred stubs are well-typed enough to
seed a verbatim hand-authored port (see WP §9 F-03 — tightening
semantics is out of scope for phase 1); (c) the compat-shim plan
(WP §11) collapses to a single re-export line per `__init__.py`.

## Queued ports — port_status: queued (23 entries)

Primitives that already ship an auto-inferred `<Name>.protocol.py`
and are therefore ready for hand-typed port authoring in a follow-up
WP (phase 2). The follow-up WP will batch these by namespace.

See `CATALOG.json` for the authoritative list; the entries with
`port_status: "queued"` are the 23 primitives below:

- `api/BatchCore`, `api/DataLoader`, `api/DeprecationEntry`,
  `api/DeprecationRegistry`, `api/DeprecationReporter`,
  `api/IdempotencyStore`, `api/InboundVerifier`,
  `api/MemoryPubSubBackend`, `api/PersistedQueryRegistry`
- `auth/FeatureFlagCache`
- `cache/SessionCache`
- `data/OptimisticConcurrency`, `data/ShardedCounter`
- `events/CausalReorderBuffer`
- `extras/SchemaComparator`
- `resiliency/CostTracker`, `resiliency/ExcelExporter`,
  `resiliency/GracefulShutdown`, `resiliency/HeterogeneousWorkerPool`,
  `resiliency/ModelRegistry`, `resiliency/Redactor`,
  `resiliency/RetryBudget`, `resiliency/TracingBuffer`

## Missing-stub ports — port_status: missing-stub (99 entries)

Primitives that ship neither a hand-authored port nor an auto-inferred
stub. Phase 2 (or a separate WP) will run
`engine.extraction.infer_protocol` on these first to seed an
auto-inferred stub, then hand-author the port in a follow-up batch.

See `CATALOG.json` for the authoritative list (filter
`port_status: "missing-stub"`).

## Freshness rule

The catalog is a snapshot at WP-15 merge time. The 124 count can
shift only via:

1. A `_staging/` → registered promotion under `core/venous/<ns>/`.
2. A new `core/venous/<ns>/<Name>/` directory landing in a WP whose
   §1 explicitly authorises it.

Either event invalidates this catalog and the follow-up WP that
introduces the change MUST regenerate `CATALOG.json` using the
derivation procedure above. WP-15 itself does not promote anything
out of `_staging/` and does not add any primitive.

## Cross-reference

- WP manifest: [`docs/wp/WP-15-hexagon-ports.md`](../../../../../docs/wp/WP-15-hexagon-ports.md)
- INVENTORY source of truth: [`INVENTORY.md`](../../../INVENTORY.md) §5
- ADR-0001 (hexagonal core): `docs/adr/0001-architecture.md`
- Boundary doc: [`README.md`](./README.md)
