# HeterogeneousWorkerPool

## What it does (plain language)

A routing pool for inference workloads where workers are not uniform —
some have GPUs, some are CPU-only, and the fleet varies in advertised
model families. The pool observes per-worker queue depth and p50 latency,
prefers GPU workers when healthy, deprioritizes workers whose latency
doubles versus the pool median, and honors session-stickiness so a
conversation stays on one worker while that worker is healthy.

## Purpose

Route `submit(task, family)` across mixed CPU+GPU workers using observed
queue-depth + latency health signals so no single worker bottlenecks.

## When to use and when NOT to use

- USE: ML inference gateway where some models fit only on GPU but
  lighter heuristics run fine on CPU.
- USE: any capability-gated fleet where a task must land on a worker
  with a specific advertised capability.
- DO NOT USE: a homogeneous request/response pool — use a Bulkhead +
  LoadShedder pair instead.
- DO NOT USE: as a persistent job queue — this is an in-flight router;
  it has no durability guarantee.

## API surface

`HeterogeneousWorkerPool.contract.json` is the authority. Workers
register with capabilities, kind (`cpu`/`gpu`), and an executor
coroutine; callers `submit(task, family)` and receive an
`asyncio.Future[R]`; `on_result` is called by `submit` internally but
exposed so external adapters (batch servers) can feed their telemetry.

## Invariants

| ID | Rule |
|---|---|
| HWP_INV_01 | A task with `family=F` MUST land on a worker advertising F in its capabilities. |
| HWP_INV_02 | GPU workers preferred when any healthy GPU worker has queue_depth < pool median; fallback CPU otherwise. |
| HWP_INV_03 | A worker whose rolling p50 latency over the last 100 samples is ≥ 2.0× pool-wide rolling p50 is deprioritized (weight 0.1×) within 30 seconds. |
| HWP_INV_04 | Session-stickiness: same `session_id` routes to same worker while the worker is healthy; on unhealthy, fails over. |
| HWP_INV_05 | Burst of N tasks spreads such that no single worker's queue exceeds 1.5× pool median. |
| HWP_INV_06 | Once a worker's rolling p50 normalizes back within 1.5× pool p50, full weight is restored within 30 seconds. |

## Invariant -> test mapping

`test_HeterogeneousWorkerPool.py` has a `test_inv_<slug>_{confirms,prevents}`
pair for each invariant.

## Thread and async safety

- Single-loop, in-memory pool. Not safe across threads — callers must
  route `submit` from one asyncio loop.
- For multi-process or multi-host fleets, a Ray ActorPool adapter
  provides the same Protocol surface with distributed semantics.

## Operational characteristics (for SRE)

- `hwp.submit` (counter, labels: worker_id, kind, family) — routing
  distribution; skew here is an alert.
- `hwp.queue_depth` (gauge, labels: worker_id) — per-worker queue.
- `hwp.latency_ms` (histogram, labels: worker_id, kind) — per-worker
  p50/p99; the driver for HWP_INV_03.
- `hwp.unhealthy` (counter, labels: worker_id) — each 30s deprioritization
  window increments this; correlated spikes are a fleet-health alert.

## Security considerations

- Workers self-register with their capabilities — if any process can call
  `register` it can claim arbitrary families. Gate the registration
  endpoint with `RequestGuard`.
- The pool never inspects `task.payload`; authorization and PII redaction
  MUST happen before `submit`.

## Provenance

- Primary source: Ray ActorPool / actor utils —
  https://docs.ray.io/en/latest/ray-core/actors/actor-utils.html
- Secondary: Envoy Endpoint Discovery Service weighted + health-aware
  load balancing.

## Alternatives considered and rejected

- Round-robin router — ignores per-worker health and queue; a slow GPU
  starves throughput.
- Static weight table — cannot react to hot-loaded models or warm-cache
  advantages.
- Single-kind homogeneous pool — wastes GPU headroom when CPU tasks can
  absorb part of the load.

## Extension contract

Adopters register workers lazily; rolling-window size (50 samples) and
unhealthy window (30s) are internal defaults — override by subclassing
and setting the two private constants. The routing algorithm itself is
sealed; a different algorithm is a different primitive.

## Usage

```python
pool: InMemoryHeterogeneousWorkerPool = InMemoryHeterogeneousWorkerPool()

async def gpu_exec(task: Task[str]) -> str:
    ...  # your actual inference call

pool.register("gpu-a", frozenset({"llm-7b"}), "gpu", gpu_exec)
pool.register("cpu-a", frozenset({"classify", "llm-7b"}), "cpu", cpu_exec)

fut = pool.submit(Task(payload={"prompt": "..."}), family="llm-7b")
result = await fut
```

## Compose with:

- **Per-worker throughput isolation** → `Bulkhead` + `MetricMeter`
  Each worker's executor is wrapped in a Bulkhead of its own; failures on
  one worker cannot saturate the pool-level queue. Invariant gained:
  one-bad-worker isolation under burst load.

- **Failing-dependency backoff** → `CircuitBreaker` + `Bulkhead`
  A CircuitBreaker wraps the executor call for each worker; consecutive
  failures trip the breaker and the pool's `on_result(ok=False)` signals
  the router to avoid that worker. Invariant gained: the pool and the
  breaker agree on "unhealthy".

- **Routing observability** → `MetricMeter` + `CircuitBreaker`
  Every `submit` emits a metric tagged with `worker_id` and `kind`, and
  every breaker trip emits a state-transition event on the same bus.
  Invariant gained: routing skew and worker health are correlatable on
  the same dashboard.
