# IdentityMap

## What it does (plain language)

IdentityMap is the session-scoped cache that guarantees the domain NEVER
ends up with two different Python objects representing the same database
row. Inside one UnitOfWork / session, every `get(type, id)` for the same
pair returns the exact same object reference — so `order_a is order_b`
holds even when the caller asked for the order twice.

## Purpose

Cache loaded domain objects by identity inside one session so the same row
is never represented twice in memory.

## When to use and when NOT to use

- USE: every read path that goes through a `Repository` inside a
  `UnitOfWork`. The map is the only way to stop divergent copies when a row
  is fetched twice through different query surfaces.
- USE: aggregates whose in-memory state evolves during a session (debit +
  credit on the same account) — callers MUST see one canonical instance.
- DO NOT USE: read-only analytical workloads where objects are immutable
  snapshots — the cache adds memory pressure without payoff.
- DO NOT USE: as a global process cache — the map is single-session and
  disposed at the session boundary, by design (IDMAP-INV-03/04).

## API surface

The catalog `api_signature` in `IdentityMap.contract.json` is the authority.

```python
def get(self, type_: type, id: object) -> Any | None
def add(self, obj: Any) -> None          # (type, id) derived from obj and obj.id
def remove(self, type_: type, id: object) -> None
def contains(self, type_: type, id: object) -> bool
```

The reference implementation `InMemoryIdentityMap` adds session lifecycle
(`__enter__` / `__exit__` / `dispose`) and an `register_eviction_hook`
extension point. A convenience `session_scope()` context manager wires a
fresh map to a UnitOfWork-like lifetime; on exit (normal or exceptional)
the map is disposed and every further call raises.

## Invariants

| ID | Rule |
|---|---|
| IDMAP_INV_01 | Given the same (type, id) within one session, the IdentityMap MUST return the same Python object reference on every lookup. |
| IDMAP_INV_02 | An object CANNOT be inserted twice for the same identity; a second add with a new instance SHALL raise a conflict error. |
| IDMAP_INV_03 | The map MUST be scoped to a single UnitOfWork or session and NEVER shared across concurrent transactions. |
| IDMAP_INV_04 | On UnitOfWork disposal the map ALWAYS clears its contents; retaining references beyond the session is FORBIDDEN. |

## Invariant → test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the binding.

## Thread and async safety

- `InMemoryIdentityMap` serialises mutations via an internal lock so
  concurrent `add` attempts for the same `(type, id)` preserve a single
  canonical reference. The first writer wins; every subsequent writer with
  a DIFFERENT instance raises `IdentityMapInvariantError`.
- Readers do not block each other beyond the dict lookup; the returned
  reference is always the canonical one.
- `ThreadBoundIdentityMap` is a stricter variant that refuses access from
  any thread other than its owning thread (IDMAP-INV-03 hardened). Prefer
  it when your UoW is pinned to one thread and you want runtime detection
  of accidental cross-thread sharing.
- A map MUST NOT be shared across sessions; `session_scope()` returns a
  fresh map each time so concurrent transactions never observe one
  another's cached references.

## Operational characteristics (for SRE)

- Disposal is ALWAYS idempotent and non-raising — safe to dispose in a
  `finally` block even when rollback has already run.
- Eviction hooks are observation-only; a raising hook surfaces its
  exception to the caller of `remove` but the eviction itself ALREADY
  completed, so the cache stays consistent.
- Self-observability: `idmap.hits`, `idmap.misses`, `idmap.conflicts`
  (counters, `root_type` label), `idmap.size` (histogram, `result` label).
- A sustained rise in `idmap.conflicts` is the primary symptom of a
  repository that bypasses the map and materialises duplicates.

## Security considerations

- The map stores strong references to aggregates. Callers MUST NOT put
  secret-bearing objects in a map that outlives a request — dispose the
  session (or rely on `session_scope`) at the transaction boundary so the
  garbage collector can reclaim those references.
- `dispose()` clears the dict but does NOT zero memory pages. Treat it as
  reachability release, not cryptographic wiping.
- Cross-session sharing is the canonical security bug for this primitive.
  Prefer `ThreadBoundIdentityMap` in long-running workers to fail loudly
  when a map leaks across request scopes.

## Provenance

- Source agent: Agent #3 PATTERNS
  (`docs/research/outputs/AGENT_3_PATTERNS.json`).
- Primary source: Fowler — *Patterns of Enterprise Application
  Architecture* (2002), Chapter 11, Identity Map pattern, pp. 195–200.

## Alternatives considered and rejected

- Per-query result caching — does not guarantee referential identity
  across queries (same row, two objects if queried twice).
- ORM internal session cache only — obscures the contract and blocks
  non-ORM repositories from participating.
- Global process cache — violates session scoping and corrupts concurrent
  transactions sharing the process.

## Extension contract

Storage backends extend IdentityMap by implementing the `IdentityMap`
Protocol and binding it into the UnitOfWork factory. Eviction policies
attach via `register_eviction_hook`. The extension contract REFUSES to
weaken referential identity: a hook may observe evictions but CANNOT
mutate the cache on its own.

## Schema of `IdentityMap.contract.json`

The contract file is a verbatim copy of the `PrimitiveSpec` dict from the
research catalog. Fields: `name`, `namespace`, `purpose`, `api_signature`,
`invariants[]`, `extension_contract`, `consumption_example`, `sources[]`,
`why_essential`, `alternatives_considered[]`, `maturity`.

## Usage

```python
from IdentityMap import session_scope

def load_order(repo, order_id: int):
    with session_scope() as imap:
        cached = imap.get(Order, order_id)
        if cached is not None:
            return cached
        order = repo.get(order_id)
        imap.add(order)
        return order
```

Inside a full UnitOfWork transaction, the scope is opened for the duration
of the transaction and disposed on commit or rollback so no reference
survives the session (IDMAP-INV-04).

## Compose with:

- **Consistent-read guarantee** → `Repository` + `UnitOfWork`
  Within one UoW, two `get(id)` calls return the same instance — mutations applied to one reference are visible to all readers.

- **No lost updates** → `DataMapper` + `UnitOfWork`
  Mapper flushes only tracked instances; mutations applied outside the map are rejected at commit rather than silently skipped.

- **Aggregate coherence** → `Aggregate` + `Repository`
  The map holds aggregate roots; child entities are reached through the root — the same root is shared across all child accesses in the session.
