# LifecycleHook

## What it does (plain language)

LifecycleHook lets each tool register a small callback that fires at a named
phase of the application: just-booting, fully-ready, starting-to-stop, or
stopped. A single registry decides the order, enforces per-hook timeouts, and
guarantees that a failed startup never masquerades as a ready service.

## Purpose

Named callback fired at a defined application phase (starting, ready,
stopping) so tools can initialize resources and shut down cleanly.

## When to use and when NOT to use

- USE: warm caches, open connection pools, flush buffers, drain subscribers.
- DO NOT USE: per-request setup (belongs to middleware / RequestContext).
- DO NOT USE: long-running work that should be a background task.

## API surface

See `LifecycleHook.contract.json` for the verbatim Protocol declaration. The
implementation exposes `LifecyclePhase`, `LifecycleHook`, and a reference
`LifecycleRegistry` with `register`, `run_starting`, `run_ready`,
`run_stopping`, `run_stopped`, plus `ready_fired` / `starting_failed` /
`stopped` observability probes.

## Invariants

| ID | Rule |
|---|---|
| LIFE_INV_01 | READY MUST fire exactly once, after STARTING succeeded. |
| LIFE_INV_02 | STOPPING hooks MUST run in reverse registration order (LIFO). |
| LIFE_INV_03 | A failing STARTING hook MUST prevent READY from firing. |
| LIFE_INV_04 | Hooks MUST NOT block indefinitely; per-hook timeout enforced. |
| LIFE_INV_05 | Re-registering the same callback in the same phase SHALL raise. |

## Invariant → test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}` per the contract. See
`invariant_bindings.json` for the authoritative binding.

## Thread and async safety

Lifecycle wiring runs on the main event loop at boot and shutdown. The
registry is single-threaded by design — invariant violations fail loudly
rather than hide behind locks. Multi-worker processes register hooks per
process at import.

## Operational characteristics (for SRE)

- `default_timeout_s` is 30.0s by default; override per hook with
  `register(hook, timeout_s=N)`.
- A failing STARTING hook sets `starting_failed=True`, blocks READY, and
  surfaces the original exception to the caller so a process manager can
  exit non-zero.
- STOPPING hooks continue on per-hook failure (drain-other-resources policy
  per LIFE_INV_02). STOPPED is the terminal phase and also drains past
  failures.

## Security considerations

- Hooks execute arbitrary registered callbacks; the registry MUST be
  populated only from trusted wiring code, not user input.
- Timeouts cap wall-clock per hook so a malicious or broken hook cannot
  indefinitely wedge boot or shutdown (LIFE_INV_04).
- No secrets flow through the registry; hooks SHOULD NOT log their phase
  payload if it references credential material.

## Provenance

- Source agent: Agent #1 FRAMEWORKS
  (`docs/research/outputs/AGENT_1_FRAMEWORKS.json`).
- Primary sources: Spring Boot 3.x (ApplicationReadyEvent), Quarkus 3.x
  (StartupEvent / ShutdownEvent), ASP.NET Core 8.0 (IHostApplicationLifetime).

## Alternatives considered and rejected

- atexit-style hooks only — no STARTING phase, no async support.
- Per-tool startup scripts — ordering is ad-hoc, failures invisible.
- Single giant startup function — monolithic, blocks parallel init.

## Extension contract

Downstream tools instantiate `LifecycleHook(phase, cb)` and call
`registry.register(hook, timeout_s=...)`. Alternative sources (Spring,
Quarkus, ASP.NET) plug in through adapters that map native events onto
`LifecyclePhase` while preserving LIFO stopping and one-shot READY.

## Schema of `LifecycleHook.contract.json`

Verbatim copy of the catalog `PrimitiveSpec` dict. Fields: `name`,
`namespace`, `purpose`, `api_signature`, `invariants[]`,
`extension_contract`, `consumption_example`, `sources[]`, `why_essential`,
`alternatives_considered[]`, `maturity`.

## Usage

```python
registry = LifecycleRegistry(default_timeout_s=10.0)

async def warm_cache() -> None:
    await cache.preload()

async def drain_db() -> None:
    await db.close()

registry.register(LifecycleHook(LifecyclePhase.STARTING, warm_cache))
registry.register(LifecycleHook(LifecyclePhase.STOPPING, drain_db))

await registry.run_starting()
await registry.run_ready()  # after STARTING succeeds
# ... serve traffic ...
await registry.run_stopping()
await registry.run_stopped()
```

## Compose with:

- **Ordered startup** → `DiContainer` + `HealthProbe`
  Hooks fire in dependency order; readiness flips true only after every 'ready' hook returns — no premature traffic.

- **Graceful shutdown** → `HealthProbe` + `EventBus`
  Stopping hooks drain queues, flush telemetry, close connections — SIGTERM-to-exit is a predictable sequence, not best effort.

- **Self-describing process** → `ResourceDescriptor` + `StructuredLogger`
  Hooks emit phase events with the resource descriptor attached — deploys and rollouts appear as discrete events in the log stream.
