# Agent 2 - DISTRIBUTED

Research of distributed-systems runtime primitives extracted from Dapr 1.14, Temporal 1.24, Apache Kafka 3.x, NATS 2.10, CloudEvents 1.0.2, and gRPC core concepts. The primitives below define the runtime surface any Arsenal language target must expose across the namespaces `events`, `jobs`, `data`, `cache`, and `extras`.

Machine-verified structured output: `docs/research/outputs/AGENT_2_DISTRIBUTED.json`.

## Summary

- **Primitives:** 16 (floor 12).
- **Unique sources cited:** 16 (floor 6; max share of any single source ~19%).
- **Cross-cutting insights:** 7.
- **Gaps observed:** 6.
- **Namespace distribution:** events 5, jobs 4, data 2, cache 2, extras 3.

## Primitives by namespace

### events

- **EventEnvelope** - CloudEvents 1.0.2 shape (`id`, `source`, `type`, `specversion`, optional `subject`, `time`, `data`, extensions). The `(source, id)` tuple is the dedup key. `specversion` MUST equal `1.0`. Extension names follow CloudEvents naming rules.
- **TopicBus** - Publish / subscribe facade over a broker topic. At-least-once by default. One message per consumer group goes to exactly one handler at a time. Nack triggers redelivery or dead letter routing. No cross-partition ordering.
- **StreamSubject** - Hierarchical dot-delimited routing name following NATS rules. `*` matches exactly one token, `>` only appears as the trailing token and matches one or more. `$`-prefixed names reserved for system use. Publishers never use wildcards.
- **DeadLetterRoute** - Named destination for messages that exceed `max_deliveries`. Original `EventEnvelope` id and source survive routing. DLQ routes cannot recursively dead-letter to themselves.
- **PartitionLog** - Per-partition ordered append-only log with monotonic offsets and stable replays. `read_committed` isolation hides open or aborted transactions. Cross-partition ordering is never an assumption.

### jobs

- **WorkflowRun** - Durable replayable orchestration keyed by `workflow_id` / `run_id` / `task_queue`. Workflow code MUST be deterministic; all side effects flow through activities, timers, signals, child workflows. Closed runs never resume under the same `run_id`.
- **ActivityCall** - Workflow-scoped side-effectful work with explicit `start_to_close_s`, `schedule_to_close_s`, `heartbeat_s`, and `RetryPolicy`. Execution semantics are at-least-once, so activities MUST be idempotent. Missed heartbeat is never success.
- **DurableTimer** - Persisted workflow-scoped sleep. Recorded as an event for replay. Wall-clock sleep is forbidden inside workflows. Canceled timers never fire. A single worker can host millions of concurrent timers because the state is server-side.
- **WorkflowSignal** - Asynchronous, fire-and-forget write to an open workflow run, recorded in the event history. No return value. Signals to closed runs are rejected. `send_with_start` atomically starts or targets the existing open run.

### data

- **StateStore** - Key-addressed CRUD (`get`, `save`, `delete`, `bulk_get`) with ETag-based optimistic concurrency and optional TTL. ETag conflicts reject writes. `bulk_get` returns an entry for every requested key, absent markers included.
- **TransactionalBatch** - Atomic multi-key write boundary against one store. Either every queued operation commits or none do. Any ETag conflict aborts the entire batch. Reads are forbidden inside the batch.

### cache

- **DistributedLock** - Named mutex with lease expiry keyed by `resource_id` / `owner_id` / `lease_s`. At most one holder. Auto-release on lease expiry prevents deadlock. Unlock by a non-matching owner is rejected. Fairness is not guaranteed beyond the single-holder invariant.
- **KeyValueBucket** - Named compare-and-swap bucket with monotonic revisions and a watch channel. `create` fails if the key exists; `update` fails if the supplied revision does not match. Watchers emit in revision order.

### extras

- **VirtualActor** - Location-transparent single-writer object addressed by `(actor_type, key)`. Turn-based concurrency - at most one invocation at a time. State never escapes the actor. Reminders survive deactivation; timers do not. Callers never cache the physical host.
- **RpcInterceptor** - Per-call middleware around an RPC. `next` is called exactly once per invocation unless the interceptor short-circuits. `-bin` metadata keys carry binary values; `grpc-` prefix is reserved. Deadlines may only be shortened.
- **OutboundBinding** - Declarative adapter for invoking an external resource via `(binding_name, operation, data, metadata)`. `operation` MUST be one declared by the component. Secrets never belong in metadata. Binary payloads round-trip unchanged.

## Cross-cutting insights

1. Every durable transport ships at-least-once by default; idempotency and dedup keys live in the application contract.
2. Identity tuples recur across sources: `(source, id)` (CloudEvents), `(topic, partition, offset)` (Kafka), `(workflow_id, run_id)` (Temporal), `(actor_type, key)` (Dapr actors).
3. Optimistic concurrency is the shared write gate: ETags (Dapr state), revisions (NATS KV), sequence numbers (Kafka idempotent producer), `maximum_attempts` (Temporal retry policy).
4. Component adapters and interceptor chains are the universal extension seam.
5. Determinism boundaries mark orchestration primitives - workflows forbid direct IO and wall-clock and funnel effects through activities, timers, and signals recorded in an event history.
6. Dead-letter and retry topology is explicit in every durable broker.
7. Placement transparency appears in Dapr virtual actors and Temporal task queues - callers address logical ids and the runtime chooses the host.

## Gaps observed (versus SKILL-001 today)

- No durable workflow primitive; long-running orchestration is still chained background jobs without event history.
- `EventEnvelope`-style CloudEvents shape is not enforced on the event bus, so `(source, id)` dedup is not guaranteed across producers.
- Virtual-actor single-writer entities are missing.
- No `DistributedLock` with lease expiry.
- Dead-letter routes are ad hoc and not a first-class primitive tied to the pub/sub contract.
- No key-value bucket with compare-and-swap plus watch.

## Sources cited

1. Dapr 1.14 State Management building block overview (x2)
2. Confluent Kafka Design: Message Delivery Semantics (x3)
3. CloudEvents 1.0.2 Core Specification (x1)
4. Dapr 1.14 Publish and Subscribe building block overview (x2)
5. NATS 2.10 Subjects concept documentation (x1)
6. NATS 2.10 JetStream overview (x2)
7. Apache Kafka 3.x documentation concepts (x2)
8. Temporal 1.24 Workflows concept page (x3)
9. Temporal 1.24 Activities concept page (x1)
10. Temporal 1.24 Python timers guide (x1)
11. Temporal 1.24 Encyclopedia: Workflow Message Passing (x1)
12. Dapr 1.14 Actors building block overview (x1)
13. Dapr 1.14 Distributed Lock building block overview (x1)
14. gRPC Core Concepts guide (x1)
15. gRPC Interceptors guide (x1)
16. Dapr 1.14 Bindings building block overview (x1)

## Self-check

```
$ skills/SKILL-001-fastapi-production/.venv/bin/python docs/research/contracts/check_deliverable.py \
    --agent 2 --deliverable docs/research/outputs/AGENT_2_DISTRIBUTED.json
[OK] DELIVERABLE VALID
  Agent 2 (DISTRIBUTED)
  Primitives: 16 (min 12)
  Unique sources: 16 (min 6)
  Insights: 7
  Gaps observed: 6
```
