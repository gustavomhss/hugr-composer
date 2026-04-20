# Bulkhead

## What it does (plain language)

A Bulkhead partitions concurrency so that saturation or stalls inside one
dependency cannot exhaust the resources needed by unrelated dependencies. Each
partition has a bounded slot count and a bounded wait deadline. When both are
exceeded, the bulkhead refuses the call with ``BulkheadFull`` and emits a
rejection metric labelled with the partition name.

Named after the watertight compartments on a ship: one flooded compartment
must not sink the whole vessel.

## Purpose

Partition concurrency so that saturation or stalls inside one dependency
cannot exhaust the resources needed by unrelated dependencies.

## When to use and when NOT to use

- USE: any service that fans out to multiple downstream dependencies with
  different latency envelopes (payments + fraud + notifications), or
  multi-tenant services where one tenant must not starve another.
- USE: async I/O paths with a well-defined concurrency budget per dependency.
- DO NOT USE: a single homogeneous pool with a single dependency and a single
  latency envelope — a plain ``asyncio.Semaphore`` suffices.
- DO NOT USE: replacing a circuit breaker. A bulkhead bounds *parallelism*; a
  circuit breaker bounds *failure contagion*. They COMPOSE; they do not
  substitute.

## API surface

The catalog ``api_signature`` in ``Bulkhead.contract.json`` is the authority.
Callers construct an ``InMemoryBulkhead`` (or register one via the
``PartitionRegistry``) with a ``name``, ``max_concurrent_calls``, and
``max_wait_duration_ms``; they call ``await bulkhead.submit(fn, *args,
**kwargs)``. A ``request_id`` kwarg enlists the call in the
``RequestRejectionLedger`` so BH_INV_03 can block intra-request retries.

## Invariants

| ID | Rule |
|---|---|
| BH_INV_01 | The number of in-flight calls per partition MUST NEVER exceed ``max_concurrent_calls``. |
| BH_INV_02 | A caller that waits longer than ``max_wait_duration_ms`` for a permit SHALL receive ``BulkheadFull`` and NEVER be admitted. |
| BH_INV_03 | A rejection by Bulkhead MUST NOT be retried inside the same partition in the same request. |
| BH_INV_04 | Permits CANNOT be shared across partitions; each partition holds an isolated counter. |
| BH_INV_05 | The bulkhead SHALL emit a rejection metric labelled with the partition name on every rejection. |

## Invariant → test mapping

Each invariant is covered by three tests named
``test_inv_<slug>_{confirms,prevents,under_failure}``. See
``invariant_bindings.json`` for the binding.

## Slot-count invariant (formal)

The core safety property is ``0 <= in_flight <= capacity`` at every observable
moment. It is modelled in two places:

- ``Bulkhead.tla`` — TLA+ spec with four safety invariants:
  ``CapacityCeiling``, ``HoldingEqualsInFlight``, ``RejectionStaysRejected``,
  ``RejectionNeverHolds``. Verified with TLC on Capacity=2 and 3 callers.
- ``state_machine_Bulkhead.py`` — hypothesis ``RuleBasedStateMachine`` that
  explores acquire / release / reject sequences and asserts the slot-count
  invariant after every transition.

## Thread and async safety

- ``InMemoryBulkhead`` uses an ``asyncio.Semaphore`` to gate admission and a
  ``threading.Lock`` to serialise counter snapshots.
- A cancelled ``submit`` task releases its permit in the ``finally`` branch,
  so cancellation CANNOT leak slots.
- A wrapped callable that raises releases its permit identically — failure
  does not erode capacity.

## Operational characteristics (for SRE)

- Rejections are always metered with a ``partition`` label (BH_INV_05). An
  alert on ``rate(bulkhead_rejections_total[5m]) > X`` per partition surfaces
  a saturating dependency.
- ``bulkhead.in_flight`` is an up-down counter; a p99 sustained at the
  capacity ceiling means the partition is right-sized or under-sized — size
  it so that steady-state p95 ≤ 70% of capacity.
- Choose ``max_wait_duration_ms`` smaller than the caller's deadline budget:
  queuing beyond that budget is wasted work.

## Security considerations

- Partition names are treated as a low-cardinality label. Do NOT derive the
  partition name from untrusted input — a malicious input could explode the
  ``RejectionMeter`` cardinality. Keep partitions enumerable.
- The ``RequestRejectionLedger`` stores ``(request_id, partition)`` pairs in
  memory. The integration layer MUST call ``ledger.clear_request(request_id)``
  at the end of each request to prevent unbounded growth.

## Provenance

- Source agent: Agent #4 RESILIENCY
  (``docs/research/outputs/AGENT_4_RESILIENCY.json``).
- Primary sources:
  - Nygard — *Release It! 2nd edition* (2018), Chapter 5 "Stability Patterns",
    section "Bulkheads", pp. 98–103.
  - resilience4j 2.2.0 reference documentation — ``core-modules/bulkhead``,
    comparison of SemaphoreBulkhead vs FixedThreadPoolBulkhead.

## Alternatives considered and rejected

- **Global connection pool** — shares resources but allows one slow
  dependency to exhaust everything.
- **Process-per-dependency isolation** — provides strong isolation yet
  multiplies operational cost and cold-start overhead.
- **Cooperative quotas enforced in application code** — relies on every call
  site to behave correctly and NEVER composes.

## Extension contract

Adopters register a partition by name and select a kind adapter
(``semaphore`` for async I/O, ``thread_pool`` for blocking code). A
``PartitionRouter`` hook maps requests to partition names, enabling
per-tenant or per-dependency isolation. The permit accounting is sealed —
downstream code can observe (``in_flight``, ``available_permits``,
``total_admitted``, ``total_rejected``) but cannot mutate the counters.

## Schema of ``Bulkhead.contract.json``

The contract file is a verbatim copy of the ``PrimitiveSpec`` dict from the
research catalog. Fields: ``name``, ``namespace``, ``purpose``,
``api_signature``, ``invariants[]``, ``extension_contract``,
``consumption_example``, ``sources[]``, ``why_essential``,
``alternatives_considered[]``, ``maturity``.

## Usage

```python
from Bulkhead import InMemoryBulkhead, BulkheadFull

fraud = InMemoryBulkhead(
    name="fraud",
    max_concurrent_calls=8,
    max_wait_duration_ms=150,
)

async def score(principal: Principal) -> FraudScore:
    try:
        return await fraud.submit(_fraud_client.score, principal)
    except BulkheadFull:
        # Partition saturated — fall back or fail fast.
        raise
```

## Compose with:

- **Dependency isolation** → `CircuitBreaker` + `RequestShape`
  Each downstream has its own bulkhead; a slow dependency saturates its own pool without starving the rest of the service.

- **Priority lanes** → `LoadShedder` + `RequestShape`
  Priority classes get dedicated pools; low-priority work is shed before high-priority work even notices contention.

- **Deadline + capacity** → `TimeoutBudget` + `CircuitBreaker`
  Admission combines remaining budget and pool availability; a request is rejected fast rather than queuing past its deadline.

- **Per-worker throughput isolation** → `HeterogeneousWorkerPool` + `MetricMeter`
  Each worker in the `HeterogeneousWorkerPool` runs its executor inside its own `Bulkhead`, so a single slow worker cannot saturate the pool-level queue; `MetricMeter` correlates bulkhead saturation with router routing skew. Invariant gained: one-bad-worker isolation under burst load.
