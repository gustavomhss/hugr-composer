# GracefulShutdown

**Namespace:** `resiliency`
**Maturity:** `emerging`
**Source tool:** `adapt/extend/infrastructure/add_graceful_shutdown.py`

## Purpose

`GracefulShutdown` coordinates process termination across three bounded
phases — **drain**, **wait-for-in-flight**, and **cleanup** — so a service
responding to SIGTERM or SIGINT never drops requests mid-flight and never
blocks the supervisor beyond `drain_seconds + timeout_seconds`. The
primitive exposes a small public surface (`register`, `is_draining`,
`increment_in_flight`, `decrement_in_flight`, `add_cleanup`,
`wait_complete`) that can wrap any ASGI/worker loop.

## Invariants

- **GRACEFUL_SHUTDOWN_INV_01** — `is_draining()` is monotonic: once the
  signal handler fires, it NEVER reverts to `False` for the remainder of
  the process lifetime.
- **GRACEFUL_SHUTDOWN_INV_02** — `wait_complete()` returns in bounded
  time: at most `drain_seconds + timeout_seconds`, regardless of how many
  requests are stuck in flight.
- **GRACEFUL_SHUTDOWN_INV_03** — The in-flight counter is a non-negative
  integer; unbalanced decrements clamp to zero rather than raise or go
  negative.

Tests: see `test_GracefulShutdown.py` for one confirms / prevents /
under-failure scenario per invariant.

## Compose with:

- **Drain-then-stop** → `LifecycleHook` + `HealthProbe`
  Shutdown flips readiness false first; hooks drain queues; in-flight requests complete within the phase budget — no 502 during deploys.

- **Coordinated with workflows** → `WorkflowRun` + `ActivityCall`
  Activities heartbeat through the drain phase; workflows survive the restart and resume on the next pod — no orphaned long-running work.

- **Bounded cleanup** → `TimeoutBudget` + `ErrorSink`
  Cleanup has a hard cap; lingering errors flush to the error sink before exit — nothing is silently lost on SIGTERM.
