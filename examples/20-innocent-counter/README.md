# Example 20 — Per-user lifetime event counter

**Tier:** adversarial · **Benchmark spec:**
`adversarial/05_hidden_scaling_innocent_counter.md`

"Just a counter" — until you hit 50M users, hot keys, and p99 read SLA.
Demonstrates the **`ShardedCounter`** recipe (Phase-3 primitive that closes
the hidden-scaling trap).

## What this example shows

- Concurrent increments on a hot user: no duplicate or lost counts.
- A cold user's first read returns 0 fast.
- Per-shard write throughput + hot-key identification on a dashboard.
- Monotonic: counter never decrements.

## How to run

```bash
cd examples/20-innocent-counter
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q
```

## Tools used

| Tool                                 | Role                                            |
| ------------------------------------ | ----------------------------------------------- |
| `fastapi_add_event_counter`          | `POST /events/{user}` → increment.              |
| `fastapi_add_counter_dashboard`      | Per-shard throughput + hot-key view.            |

## Primitives imported

| Primitive                | Role                                                |
| ------------------------ | --------------------------------------------------- |
| `ShardedCounter`         | Per-key counter distributed across N shards.        |
| `MetricMeter`            | Per-shard throughput gauge.                         |
| `CardinalityGuard`       | Bounds high-cardinality hot-key labels.             |
| `CorrelationContext`     | Per-request correlation id threaded through incrs.  |
| `HealthProbe`            | Exposes hot-keys + per-shard throughput.            |

Reference pages at `docs.hugr.dev/primitive/<Name>`.
