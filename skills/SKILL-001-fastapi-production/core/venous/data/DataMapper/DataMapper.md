# DataMapper

## What it does (plain language)

A DataMapper is the only place in a codebase that knows both your domain
object AND your storage row format. It translates in both directions —
`row → entity` (load) and `entity → row` (insert / update / delete) — and
returns parameterised payloads that the UnitOfWork later flushes to the
database. The domain object stays pure; the mapper keeps the persistence
knowledge to itself.

## Purpose

Move state between in-memory domain objects and rows in storage while
keeping both ignorant of each other.

## When to use and when NOT to use

- USE: any aggregate that persists to rows, documents, or key-value pairs
  and whose schema can evolve independently of the domain model.
- USE: bounded contexts where pure-domain unit tests are mandatory.
- DO NOT USE: throw-away CRUD on a single table with no domain logic —
  Active Record is cheaper.
- DO NOT USE: read-only projections where a simple DTO will do.

## API surface

The catalog `api_signature` in `DataMapper.contract.json` is the authority.
Implementations subclass `AbstractDataMapper` and override four pure
extension points: `_row_to_entity`, `_entity_to_row`, `_identity_key`, and
optionally `_identity_key_from_row`. The Protocol methods (`load`, `insert`,
`update`, `delete`) are provided by the base class and wrap every extension
point with runtime invariant guards.

## Invariants

| ID | Rule |
|---|---|
| DM_INV_01 | The domain object MUST have no import-time or runtime dependency on storage types; persistence knowledge SHALL live exclusively in the mapper. |
| DM_INV_02 | Given a row `r`, `load(r)` followed by `insert` / `update` on the resulting entity MUST yield a row with the same identity key (round-trip identity); schema drift is detected before translation. |
| DM_INV_03 | The mapper CANNOT mutate the domain object for persistence convenience; derived columns MUST be computed inside map methods, never injected into the domain. |
| DM_INV_04 | A DataMapper NEVER issues database I/O directly; it returns parameterised payloads the UnitOfWork flush executes. |

## Invariant → test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the binding.

## Round-trip identity

`DataMapper.round_trip(row)` performs `load(row) → update(entity)` in one
shot and explicitly compares the identity key before and after. Any
implementation that rewrites the identity key — intentionally or by
bug — trips DM_INV_02 immediately.

## Schema drift detection

`detect_schema_drift(row, columns)` is called on every `load()` and every
returned payload row. Missing required columns or unknown columns raise
`SchemaDriftError` before any translation happens, so stale replicas and
forgotten migrations fail loudly at the edge instead of silently writing
partial data.

## Thread and async safety

- `AbstractDataMapper` instances are stateless beyond an I/O-attempt
  counter protected by an internal lock; concurrent callers NEVER observe
  a mutated domain object (DM_INV_03).
- `MapperRegistry.register` is atomic — a second register for the same
  domain class is rejected loudly rather than silently overriding.
- Real database I/O lives in the UnitOfWork flush path; the mapper is a
  pure translator. This enforces DM_INV_04 at both the code level and the
  TLA+ level (`persisted` is only mutated by the `Flush` action).

## Operational characteristics (for SRE)

- Schema-drift errors should fire during deploy / staging, not in
  production — a spike in `datamapper.schema.drift.count` means an
  upstream schema changed and the mapper was not updated. Treat as a
  page-worthy signal.
- `datamapper.map.calls{kind}` (counter) tracks load/insert/update/delete
  volume per table. Use to size flush batches.
- `datamapper.row.columns` (histogram) tracks produced-row width; sudden
  growth often means a derived column was added without downstream
  consumers being informed.

## Security considerations

- The mapper is the chokepoint where encryption / redaction adapters
  (`StorageAdapter`) plug in. PII fields MUST be encrypted inside
  `_entity_to_row` and decrypted inside `_row_to_entity` — never in the
  domain object.
- Returned payloads are plain dicts; reviewers MUST verify no domain
  instances leak across the boundary. The contract tests
  (`metamorphic_DataMapper.py`) assert payload rows are bit-equal to
  source rows after a round trip.

## Provenance

- Source agent: Agent #3 PATTERNS
  (`docs/research/outputs/AGENT_3_PATTERNS.json`).
- Primary source: Fowler — *Patterns of Enterprise Application
  Architecture* (2002), Chapter 10, Data Mapper pattern, pp. 165–182.

## Alternatives considered and rejected

- **Active Record** — collapses domain and persistence and prevents
  pure-domain unit tests.
- **Table Module with record sets** — suits simple CRUD but not rich
  aggregates.
- **ORM auto-mapping only** — magical, brittle across schema evolution,
  and ties the domain to ORM types.

## Extension contract

New persistent types extend `AbstractDataMapper` by implementing the four
protected extension points. Storage-specific encodings (JSONB, arrays,
encrypted columns) plug in through the `StorageAdapter` Protocol without
the domain being recompiled. `MapperRegistry.register(domain_cls, mapper)`
wires the pair; DM_INV_01 is enforced on register.

## Schema of `DataMapper.contract.json`

The contract file is a verbatim copy of the `PrimitiveSpec` dict from the
research catalog. Fields: `name`, `namespace`, `purpose`, `api_signature`,
`invariants[]`, `extension_contract`, `consumption_example`, `sources[]`,
`why_essential`, `alternatives_considered[]`, `maturity`.

## Usage

```python
@dataclass
class Account:
    id: int
    owner: str
    balance: int

class AccountMapper(AbstractDataMapper[Account]):
    columns = frozenset({"id", "owner", "balance"})
    identity_columns = ("id",)
    table = "accounts"
    def _row_to_entity(self, row):
        return Account(id=row["id"], owner=row["owner"], balance=row["balance"])
    def _entity_to_row(self, e):
        return {"id": e.id, "owner": e.owner, "balance": e.balance}
    def _identity_key(self, e):
        return (e.id,)

def persist(entity, mapper: DataMapper, uow) -> None:
    payload = mapper.update(entity) if entity.id else mapper.insert(entity)
    uow.enqueue_write(payload)
```

## Compose with:

- **Classic mapper sandwich** → `Repository` + `UnitOfWork`
  Repository is the collection-style façade; DataMapper is the translation layer; UoW is the transaction — each seam does exactly one job.

- **Identity-preserving load** → `IdentityMap` + `Repository`
  Loaded aggregates register in the identity map; a second load returns the same instance — mapper output is cached by identity, not duplicated.

- **Value-object hydration** → `ValueObject` + `Specification`
  Rows become frozen value objects at hydration; Specifications translate into storage queries — the domain never sees raw columns.
