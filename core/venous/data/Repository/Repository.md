# Repository

## What it does (plain language)

Repository is the collection-style front door for one aggregate root. Callers
`add`, `remove`, `get` by id, and `find` by Specification — the Repository
hides storage mechanics, keeps one logical aggregate type under exactly one
front door, and routes every mutation through the active UnitOfWork so
partial writes can never leak.

## Purpose

Mediate between the domain model and the data-mapping layer using a
collection-like interface to access aggregate roots.

## When to use and when NOT to use

- USE: any domain read or write that targets an aggregate root (Account,
  Order, Customer, Document). One repository per root type — period.
- DO NOT USE: for child entities inside another aggregate. Those are reached
  by navigating from the parent root, never exposed by their own repository.
- DO NOT USE: for cross-aggregate reports or ad-hoc projections — use a
  dedicated query service or read model, not the Repository.

## API surface

`Repository.contract.json` carries the authoritative `api_signature`. The
four collection methods are:

| Method | Purpose |
|---|---|
| `get(id)` | Return the aggregate root by id, or `None`. Consults the IdentityMap first (REPO-INV-05). |
| `add(entity)` | Insert a new aggregate; enlists with the active UnitOfWork (REPO-INV-04). |
| `remove(entity)` | Remove an aggregate; enlists with the UnitOfWork and drops any IdentityMap cache. |
| `find(spec)` | Returns all roots matching a `Specification` or a registered named finder (REPO-INV-02). |

Extension points: `register_finder(name, fn)` adds a named query; `mark_dirty`
reports an in-place mutation through the UnitOfWork.

## Invariants

| ID | Rule |
|---|---|
| REPO_INV_01 | A Repository MUST only expose aggregate roots, NEVER internal child entities of another aggregate. |
| REPO_INV_02 | Query methods MUST accept a Specification object or a named finder and SHALL NOT leak SQL, ORM, or storage syntax to callers. |
| REPO_INV_03 | A single logical aggregate type MUST have exactly one Repository; duplicate repositories for the same root are FORBIDDEN. |
| REPO_INV_04 | Mutations (add, remove) MUST enlist with the active UnitOfWork and NEVER issue direct writes bypassing it. |
| REPO_INV_05 | The Repository CANNOT return stale in-memory copies when an IdentityMap is present; it MUST consult the map first. |

## Invariant → test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the binding.

## Thread and async safety

- `ConcreteRepository` uses an internal lock for its local store plus a
  process-wide lock for the one-repository-per-root registry. `add` / `remove`
  are safe under concurrent writers.
- `get` reads the IdentityMap before falling through to the loader; the
  loader runs outside the repository lock so application code never deadlocks
  on it.
- The repository MUST be scoped to one logical transaction per request. Share
  it across requests only if its backing storage is itself thread-safe.

## Operational characteristics (for SRE)

- Self-observability: `repo.get.calls` (counter, labels root_type/result),
  `repo.find.matched` (histogram, matched count), `repo.mutations`
  (counter, op label), `repo.identity.map.hit.ratio` (histogram).
- A falling `repo.identity.map.hit.ratio` on a hot path signals the
  IdentityMap is being evicted too aggressively — check the session scope.
- A rising `repo.mutations{op="removed"}` without matching `op="new"` is the
  canonical leak symptom for `remove()` paths that should have been
  `mark_dirty()`.

## Security considerations

- `find()` rejects raw string specs that look like SQL — REPO-INV-02 is the
  firewall between the domain and storage syntax. Any code review that sees
  a call like `repo.find("WHERE ...")` MUST treat it as a bug.
- `direct_write()` ALWAYS raises. Static review should grep for any bypass
  method added in subclasses.
- IdentityMap references share object identity with the domain. Callers must
  NOT place secrets into an aggregate root and rely on garbage collection to
  sanitise them — prefer keeping secrets out of the aggregate entirely.

## Provenance

- Source agent: Agent #3 PATTERNS
  (`docs/research/outputs/AGENT_3_PATTERNS.json`).
- Primary sources:
  - Evans — *Domain-Driven Design* (2003), Chapter 6, Repositories,
    pp. 147–154.
  - Fowler — *Patterns of Enterprise Application Architecture* (2002),
    Chapter 18, Repository pattern, pp. 322–327.
  - Vernon — *Implementing Domain-Driven Design* (2013), Chapter 12,
    Repositories, pp. 397–446.

## Alternatives considered and rejected

- Active Record per entity — couples persistence with domain behavior;
  breaks aggregate boundaries at scale.
- Raw DAO returning rows — leaks storage shape into the domain layer.
- Query objects without a collection facade — loses the get/add/remove
  symmetry Evans requires.

## Extension contract

Subclass `ConcreteRepository` per aggregate root, or register a new
Specification translator via `register_finder(name, fn)`. The collection
contract (`get`, `add`, `remove`, `find`) is invariant under extension; new
behavior must preserve the four-method surface.

## Schema of `Repository.contract.json`

The contract file is a verbatim copy of the `PrimitiveSpec` dict from the
research catalog. Fields: `name`, `namespace`, `purpose`, `api_signature`,
`invariants[]`, `extension_contract`, `consumption_example`, `sources[]`,
`why_essential`, `alternatives_considered[]`, `maturity`.

## Usage

```python
from Repository import ConcreteRepository, InMemoryIdentityMap

def close_dormant_accounts(repo, policy) -> int:
    closed = 0
    for account in repo.find(policy.dormancy_spec):
        account.close()
        repo.mark_dirty(account)
        closed += 1
    return closed
```

## Business summary

Repository guarantees that every piece of code in the domain layer asks the
same question — "give me the Account with this id", "add this new Order" —
in exactly the same shape, with the same atomicity and the same caching
story. Bypasses are refused at runtime; partial reads are refused at runtime;
two competing Account repositories are refused at construction time. That is
why downstream tools can safely depend on it.

## Compose with:

- **DDD persistence sandwich** → `UnitOfWork` + `IdentityMap`
  Repo enlists every mutation with the active UoW and consults the identity map first on reads — no silent direct writes and no stale in-memory copies.

- **Query via Specification** → `Specification` + `Aggregate`
  find() accepts a Specification and returns only aggregate roots; ORM syntax never crosses the boundary.

- **Aggregate-only surface** → `Aggregate` + `DomainEvent`
  One repo per root; child entities are reached through navigation; mutations emit domain events the outbox relays — the repo stays pure.
