# CommandQuerySeparator

## What it does (plain language)

CommandQuerySeparator (CQS) splits the API surface into two disjoint halves:
*commands* that change state and return only an acknowledgement, and *queries*
that observe state and never mutate anything. Teams scale, evolve, cache, and
authorise each half independently because the split is enforced, not a
convention.

### One-minute mental model (junior-friendly)

- A **command** is a verb: "create user", "cancel order". It writes and
  returns ONLY an ack (a small envelope with `{ack, status, ids, event_offset}`
  — nothing else). Commands NEVER hand you back the full record they just wrote.
- A **query** is a noun: "get user by id", "list open orders". It reads and
  returns a view. Queries NEVER write, NEVER call commands, NEVER tick a
  counter or update a cache row.
- **Why keep them apart?** Because a system where "some calls secretly mutate"
  is impossible to cache, impossible to audit, and impossible to scale. CQS
  makes the separation a compile-time-visible, run-time-checked contract.

### Glossary (terms used below)

- **Event sourcing** — a style where state changes are recorded as an
  append-only log of events; the "current" state is derived by replaying them.
- **CQRS** — Command Query Responsibility Segregation; CQS's architectural
  cousin that adds a separate read database fed by the event stream.
- **Read model (projection)** — a view of the data optimised for queries,
  updated by subscribing to the event stream.
- **Compensating command** — a command that undoes the effect of an earlier
  command (you do not "delete" events; you append a counteracting one).

### Hello, world

```python
from CommandQuerySeparator import InMemoryCQS, CommandAck

class CreateUser:          # a command = a verb
    def __init__(self, name: str) -> None:
        self.name = name

class GetUser:             # a query = a noun
    def __init__(self, user_id: str) -> None:
        self.user_id = user_id

cqs = InMemoryCQS()

def handle_create_user(cmd: CreateUser) -> CommandAck:
    evt = cqs.emit_event("UserCreated", {"name": cmd.name})
    # Return ack-only. NEVER return `{"id": ..., "name": cmd.name, ...}`.
    return CommandAck(ack=True, status="accepted", ids=("u-1",),
                      event_offset=evt.offset)

def handle_get_user(q: GetUser) -> dict[str, object]:
    # Pure read over a projection. NEVER mutate anything.
    return {"id": q.user_id, "name": "Alice"}

cqs.register_command_handler(CreateUser, handle_create_user)
cqs.register_query_handler(GetUser, handle_get_user)

ack  = cqs.dispatch_command(CreateUser(name="Alice"))   # write path
view = cqs.answer_query(GetUser(user_id="u-1"))          # read path
```

## Purpose

Partitions the API into write commands that mutate state and read queries that
observe it so each side can scale and evolve independently.

## When to use and when NOT to use

- USE: services with divergent read and write workloads (high read fan-out,
  bursty writes), domains where authorisation differs between mutation and
  lookup, any system evolving toward event sourcing or CQRS.
- DO NOT USE: tiny CRUD apps where a single unified model is sufficient and
  the overhead of two pathways would obscure intent.
- DO NOT USE: as a transport-layer dispatcher — CQS is the *shape* of the API,
  not a message bus. Pair it with a real bus adapter when crossing processes.

## API surface

The catalog `api_signature` is the sole authority; see
`CommandQuerySeparator.contract.json` for the verbatim Protocol declaration.
The reference `InMemoryCQS` exposes `register_command_handler`,
`register_query_handler`, `dispatch_command`, and `answer_query` — plus two
write-side helpers (`emit_event`, `register_read_model`) that implement
CQS-INV-04. Command handlers return a `CommandAck` (or `None`, or a
bounded-key dict); query handlers return an arbitrary projection.

**CommandAck allowed keys** (`ACK_ALLOWED_KEYS`, enforced at dispatch time):

| key | meaning |
|---|---|
| `ack` | literal "accepted" marker (bool) |
| `id` / `ids` | primary key(s) of the write-model aggregate affected |
| `status` | one of `accepted`, `rejected`, `duplicate` (`ACK_STATUSES`) |
| `event_offset` | cursor published by the command on the write-side stream |

Any other key in the returned dict fails CQS-INV-01 loudly.

## Invariants

| ID | Rule |
|---|---|
| CQS_INV_01 | A command handler MUST NEVER return query results synthesized from the write model; it SHALL return only acknowledgement and identifiers. |
| CQS_INV_02 | A query handler CANNOT mutate state, invoke commands, or block on external side-effects. |
| CQS_INV_03 | Each command type MUST have at most one registered handler; duplicate handler registration is FORBIDDEN. |
| CQS_INV_04 | Read models ALWAYS receive updates through the same event stream as the write model; separate in-band write paths for reads are FORBIDDEN. |

## Invariant → test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the authoritative binding.

## Thread and async safety

- Handler registries (`_command_handlers`, `_query_handlers`) are guarded by
  an internal lock; concurrent `register_command_handler` calls race safely
  (one wins, others raise CQS-INV-03).
- The `EventStream` append path is lock-protected; offsets are strictly
  monotonic across threads.
- `answer_query` observes the event-stream and command-registry sizes before
  and after the handler runs; any delta proves CQS-INV-02 was violated.

## Operational characteristics (for SRE)

- Command path carries an asynchronous tail (read-model projectors subscribe
  to the event stream); dashboards track `cqs.commands.dispatched` and
  `cqs.command.duration` (see `dashboard.json`).
- Query path SHOULD be cacheable; CQS-INV-02 guarantees idempotency.
- Read-model lag between event append and projector apply is the primary
  SLO. Use `EventStream.events[-1].offset` minus `ReadModel._event_offset`
  as a gauge.
- Failure policy: command handler exceptions propagate. A partial
  `emit_event` followed by a crash leaves the event in the stream (consistent
  with event-sourcing append-only semantics); compensating commands must be
  authored in the domain layer.

## Security considerations

- Projection leakage: CQS-INV-01's runtime validator rejects command results
  that carry keys outside `ACK_ALLOWED_KEYS`. This closes a common data-leak
  vector where handlers return the full post-write aggregate.
- Authorisation split: middleware pipelines authorising the CQS boundary
  MUST check the role (command vs query) against different policies; a
  shared policy erases the split's security benefit.
- Read-model tampering: `ReadModel.direct_write` is a tripwire that always
  raises; any caller that attempts it is by definition malicious or buggy,
  and CQS-INV-04 fires loudly (with the attempted key in the message).
- Handler registration is one-shot per command type (CQS-INV-03), preventing
  a later module from silently rebinding a sensitive command (e.g.,
  `TransferFunds`) to an attacker-controlled handler.

## Provenance

- Source agent: Agent #3 PATTERNS
  (`docs/research/outputs/AGENT_3_PATTERNS.json`).
- Primary sources:
  - Richardson, *Microservices Patterns* (2018), Chapter 7, CQRS pp. 253–296.
  - Fowler, *Patterns of Enterprise Application Architecture* (2002), Chapter 9
    pp. 147–149 (Meyer's original Command-Query Separation).
  - Vernon, *Implementing Domain-Driven Design* (2013), Chapter 4, CQRS
    pp. 147–160.

## Alternatives considered and rejected

- Single unified model — breaks at scale when read and write workloads
  diverge; scaling reads drags write locks, scaling writes inflates read cost.
- Conventional CRUD over an ORM — entangles query projections with write
  invariants and smears validation across both paths.
- GraphQL resolvers without CQS — hides the mutation surface inside a typed
  graph, complicating authorisation and rate limits on the write path.

## Extension contract

New operations extend CommandQuerySeparator by registering a command or query
handler via a decorator and binding its schema to the API layer; cross-cutting
policies (authz, logging) plug in through middleware that MUST respect the
command/query split. Extensions MUST preserve the four invariants above.
Semver: the Protocol surface is v1; adding new handler registrations is
additive and does not break consumers.

## Schema of `CommandQuerySeparator.contract.json`

The contract file is a verbatim copy of the `PrimitiveSpec` dict from the
research catalog. Fields: `name`, `namespace`, `purpose`, `api_signature`,
`invariants[]`, `extension_contract`, `consumption_example`, `sources[]`,
`why_essential`, `alternatives_considered[]`, `maturity`. See
`docs/research/CONTRACT_STANDARDS.md` section 2 (PrimitiveSpec) for the
governing standards.

## Usage

```python
def place(api: CommandQuerySeparator, cmd: PlaceOrder) -> CommandAck:
    # Command path: write-side, returns ack-only envelope.
    ack = api.dispatch_command(cmd)
    # Query path: read-side, returns projection; side-effect free (INV-02).
    view = api.answer_query(GetOrderView(order_id=cmd.order_id))
    return ack, view
```

## Compose with:

- **Write-side pipeline** → `RouterPipeline` + `MiddlewarePipeline` + `ValueTransform`
  Commands flow through a write-only router group whose middleware enforces validation and UoW boundaries before any handler runs.

- **Read-side projection** → `RouterPipeline` + `RequestContext`
  Queries ride a distinct pipeline carrying only the caller's principal and correlation context, so read paths never inherit write-side transactions.

- **Typed command coercion** → `ValueTransform` + `RequestContext`
  Inbound payloads are coerced to typed command DTOs before the domain sees them; RequestContext captures the caller identity for authorization, never raw storage args.
