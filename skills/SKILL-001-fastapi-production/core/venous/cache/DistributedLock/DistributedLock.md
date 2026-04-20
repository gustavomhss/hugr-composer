# DistributedLock

## What it does (plain language)

DistributedLock is a named mutex across processes. One holder at a time per
`resource_id`; if the holder crashes, the lock auto-releases after the
`lease_s` window. Unlock requires the handle the holder received at acquire
time, so a thief cannot release a lock it does not own.

## Purpose

Give workers a single contract for rare, sequential, cross-process work such
as leader-only cron, serialized backfills, or tenant-scoped migrations.
Correctness is defined by three rules: mutual exclusion, lease-based auto
release, and owner-fenced unlock.

## When to use and when NOT to use

- USE: leader-only cron, one-shot backfills, serialized schema migrations,
  tenant-scoped critical sections.
- DO NOT USE: per-request concurrency control — that is a signature mismatch;
  use in-process locks or per-row database locks instead.
- DO NOT USE: transactional consistency — this is coordination, not a
  transaction boundary. For that, use `TransactionalBatch`.

## API surface

See `DistributedLock.contract.json` for the verbatim catalog Protocol. The
reference `InMemoryDistributedLock` stores holders in an in-process map and
evaluates lease expiry at acquire-time using a monotonic clock. A `FakeClock`
helper lets tests drive DL_INV_02 without sleeping.

## Invariants

| ID | Rule |
|---|---|
| DL_INV_01 | At most one caller MUST hold a given `resource_id` at a time; `try_lock` on a held lock returns `None`. |
| DL_INV_02 | Locks ALWAYS auto release after `lease_s` elapses so a crashed holder CANNOT deadlock the resource forever. |
| DL_INV_03 | `unlock` with a non-matching `owner_id` MUST be rejected so callers cannot release locks they do not own. |
| DL_INV_04 | `lease_s` MUST be positive; a zero or negative lease SHALL raise a configuration error. |
| DL_INV_05 | The primitive NEVER guarantees fairness across callers beyond the single-holder invariant. |

## Formal model

`DistributedLock.tla` declares a TLC-verified TLA+ specification with two
safety invariants:

- `AtMostOneHolder` — mutual exclusion (maps to DL_INV_01).
- `LeaseBounded` — a holder always has a future expiry (maps to DL_INV_02).

The TLC 2.19 model checker explores the bounded state space and reports
`Model checking completed. No error has been found.`

## Invariant → test mapping

See `invariant_bindings.json` for the authoritative binding to
`test_inv_<slug>_{confirms,prevents,under_failure}`.

## Thread and async safety

- Mutating operations serialize under `threading.Lock`.
- The reference implementation is safe to call from multiple threads or
  multiple asyncio tasks concurrently — at most one acquirer wins.

## Operational characteristics (for SRE)

- Self-observability: `lock.acquire.attempts` (outcome labelled `won | lost`),
  `lock.hold.duration` histogram, `lock.fence.rejections` counter,
  `lock.active` gauge. Schema in `observability_schema.json`.
- Failure policy: `try_lock` returns `None` on contention — callers choose
  their own backoff. `unlock` raises `LockOwnershipError` on owner mismatch.
- Lease sizing: choose `lease_s` > (worst-case critical-section duration +
  jitter). Too short = thrash on genuine work; too long = slow recovery.

## Security considerations

- `resource_id` and `owner_id` MUST be non-empty and null-byte-free (rejects
  log / header injection via namespace tricks).
- Owner-fencing (DL_INV_03) is the only cross-caller safety; it relies on
  the holder keeping `handle.owner_id` secret. Treat the handle as a bearer
  token.
- The primitive is coordination, not authorization; wrap with `RbacCheck` at
  entry points if the resource carries privilege.

## Provenance

- Source agent: Agent #2 DISTRIBUTED (`docs/research/outputs/AGENT_2_DISTRIBUTED.json`).
- Primary source: Dapr 1.14 Distributed Lock building block overview —
  Lease, TryLock, Unlock sections.

## Alternatives considered and rejected

- Advisory Postgres locks — rejected because correctness ties to one database
  and one transaction.
- Quorum-based leader election — rejected because it solves a larger problem
  and is often overkill for serial cron.

## Extension contract

Swap backends by implementing the `DistributedLock` Protocol as an adapter
(Redis `SET NX PX`, etcd lease, Consul session) and registering it as a
component. Higher guarantees (fencing tokens, lock re-acquisition on
partition heal) plug in by wrapping `try_lock` in a middleware that
annotates the handle.

## Usage

```python
async def with_critical_section(lock, resource: str, owner: str) -> bool:
    handle = await lock.try_lock(resource, owner, lease_s=30)
    if handle is None:
        return False
    try:
        return True
    finally:
        await lock.unlock(handle)
```

## Compose with:

- **Leader-only cron** → `WorkflowRun` + `TimeoutBudget`
  Only the lock holder runs the scheduled job; the lease is shorter than the budget so a stalled leader loses leadership before it can run twice.

- **Safe migration fence** → `KeyValueBucket` + `AuditEvent`
  A data migration acquires the lock and writes a revision record to the KV bucket; concurrent deploys observe the fence and abort cleanly.

- **Fault-tolerant acquisition** → `CircuitBreaker` + `RetryPolicy`
  Lock acquisition wraps the Redis/etcd call in a breaker so a backend outage fails fast rather than queuing a thundering herd.

- **Safe administrative reset** → `ShardedCounter` + `CorrelationContext`
  `ShardedCounter.reset` is wrapped in a `DistributedLock` so two admins cannot race to reset the same key; the correlation id attaches to the lock event for forensic review. Invariant gained: counter resets are single-writer globally.
