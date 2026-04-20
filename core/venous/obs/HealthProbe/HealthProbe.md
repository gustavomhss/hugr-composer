# HealthProbe

## What it does (plain language)

HealthProbe answers two separate questions that Kubernetes, load balancers, and
service meshes ask dozens of times per minute: *is this process alive?* and
*is this process ready to take traffic?* Conflating those two questions is how
deployments turn into crash loops — a slow database makes every pod "fail" and
the orchestrator helpfully restarts them in a storm. HealthProbe keeps the two
signals strictly separate.

## Purpose

Expose a typed liveness / readiness signal that reflects the real state of the
process and its dependencies so orchestrators route traffic and restart
processes correctly.

## When to use and when NOT to use

- USE for `/livez` and `/readyz` HTTP handlers, gRPC health probes, AWS ELB
  health checks, Kubernetes liveness / readiness / startup probes.
- USE when composing a service-level health view from multiple subsystems
  (database pool, message broker, feature-flag store, external API).
- DO NOT USE as a general "is this call going to work" oracle — that is what
  timeouts and circuit breakers are for.
- DO NOT USE to report business KPIs — those belong on a metrics pipeline.

## API surface

The canonical merged Protocol (see `docs/research/COLLISIONS_RESOLVED.md` §1)
exposes three members:

```python
class HealthProbe(Protocol):
    name: str
    async def liveness(self) -> HealthReport: ...
    async def readiness(self) -> HealthReport: ...
    def register_dependency(self, name: str, probe: HealthProbe) -> None: ...
```

`HealthStatus` is a three-valued enum (`UP`, `DEGRADED`, `DOWN`).
`HealthReport` is a frozen dataclass holding the status plus a `Mapping[str,
str]` of details. The reference implementation `BaseHealthProbe` provides
override points (`_check_process_liveness`, `_check_local_readiness`) for
concrete probes, composes registered dependencies via worst-wins aggregation,
and enforces every invariant at runtime.

## Invariants

| ID | Rule |
|---|---|
| HEALTHPROBE_INV_01 | Liveness MUST only report DOWN when the process itself CANNOT make forward progress; a slow or failing dependency SHALL NEVER flip liveness DOWN. |
| HEALTHPROBE_INV_02 | Readiness SHALL report DOWN when any required dependency reports DOWN; optional probes CANNOT force readiness false. |
| HEALTHPROBE_INV_03 | Both `liveness()` and `readiness()` MUST complete within a declared timeout; a hanging probe SHALL be treated as DOWN. |
| HEALTHPROBE_INV_04 | A probe MUST NEVER throw; unexpected exceptions SHALL be caught and turned into DOWN with the exception class as a `details` entry. |
| HEALTHPROBE_INV_05 | `name` MUST be unique within the registry; duplicate registrations SHALL be rejected. |
| HEALTHPROBE_INV_06 | `details` MUST NOT leak secrets (connection strings, tokens, stack traces). |
| HEALTHPROBE_INV_07 | Transitions from UP to DOWN SHALL be debounced by a configurable window to prevent routing-plane flapping. |

## Invariant → test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the authoritative binding.

## Thread and async safety

- All public methods are `async` and safe under concurrent callers; dependency
  checks fan out with `asyncio.gather` so readiness scales linearly with the
  slowest dep, not the sum.
- Dependency registration is protected against duplicate names and
  self-registration (HEALTHPROBE_INV_05).
- The debounce state is per-probe (not shared) so multiple probes in one
  process do not contaminate each other.

## Operational characteristics (for SRE)

- Per-check timeout defaults to 2s; tune down for latency-critical front doors
  and up for deep-dependency roll-ups.
- UP→DOWN debounce defaults to 10s; set to 0 for tests, raise for flaky
  upstreams that already have their own retries.
- `HealthProbeRegistry.aggregate_liveness` only considers the per-probe
  liveness signal (HEALTHPROBE_INV_01); dependency status NEVER surfaces
  through the liveness aggregate.
- Self-observability: `healthprobe.checks.total{probe,kind,status}`,
  `healthprobe.check.duration{probe,kind}`,
  `healthprobe.transitions.total{probe,from,to}`. A sustained UP→DOWN
  transition rate is the primary alert; paired with dependency counts it
  pinpoints the offender.

## Security considerations

- `details` is `Mapping[str, str]` by contract — no free-form blobs or nested
  JSON. The runtime enforces key-based and value-based secret scrubbing before
  any report leaves the process (HEALTHPROBE_INV_06).
- A malicious or buggy dependency probe CANNOT crash the readiness endpoint;
  exceptions are caught and folded into a DOWN report with only the exception
  class name (no message) recorded (HEALTHPROBE_INV_04).
- A hanging probe CANNOT freeze the readiness endpoint; the per-call timeout
  bounds worst-case latency (HEALTHPROBE_INV_03).
- The debounce window (HEALTHPROBE_INV_07) prevents an attacker-driven flap
  from turning a small blip into a routing-plane oscillation.

## Provenance

- Source agents: Agent #1 FRAMEWORKS (`docs/research/outputs/AGENT_1_FRAMEWORKS.json`)
  and Agent #4 RESILIENCY (merged per `docs/research/COLLISIONS_RESOLVED.md` §1).
- Primary sources:
  - Spring Boot 3.x Actuator — HealthIndicator (health, up, down, status).
  - ASP.NET Core 8.0 — IHealthCheck (CheckHealthAsync).
  - Kubernetes v1.29 — Configure Liveness, Readiness and Startup Probes.
  - Beyer et al., Google SRE Workbook (2018), ch. 22 "Addressing Cascading
    Failures" — Health Checks and Lame Duck.
  - Nygard, *Release It!* 2nd ed. (2018), ch. 17 "Transparency" — Health
    Checks and Observability.

## Alternatives considered and rejected

- Single monolithic `/health` endpoint — every team edits the same handler,
  and the two signals get confused.
- TCP port open as readiness — ignores application-level failures entirely.
- Per-service custom `/ping` format — blocks generic orchestrator checks.
- Readiness probes that run the full dependency graph on every call — cascade
  flaps and never recover quickly.

## Extension contract

Downstream tools implement the `HealthProbe` Protocol per dependency kind
(database, broker, cache, external API), register each via
`register_dependency`, and compose the result through an `AggregationRule`
adapter (worst-wins, quorum, weighted). New probe sources plug in without
changing the endpoint code. Semver: the Protocol is v1; additional aggregation
rules may be added without breaking existing callers.

## Schema of `HealthProbe.contract.json`

The contract file is a verbatim copy of the `PrimitiveSpec` dict from the
research catalog (`AGENT_1_FRAMEWORKS.json`); the merged Protocol in this
implementation follows `COLLISIONS_RESOLVED.md` §1.

## Usage

```python
from HealthProbe import BaseHealthProbe, DependencyRequirement, HealthProbeRegistry


class DbProbe(BaseHealthProbe):
    async def _check_local_readiness(self):
        # cheap query: SELECT 1 + pool.available > 0
        ...


registry = HealthProbeRegistry()
app = DbProbe("api")
app.register_dependency(
    "primary_db", DbProbe("primary_db"),
    requirement=DependencyRequirement.REQUIRED,
)
registry.register(app)

# In /readyz:
report = await registry.aggregate_readiness()
if report.status.value == "down":
    # Shed load: orchestrator stops routing new requests to this pod.
    ...
```

## Compose with:

- **Readiness-gated traffic** → `LifecycleHook` + `CircuitBreaker`
  Readiness flips false while dependencies warm up or a breaker stays open — the orchestrator drains traffic before the instance serves errors.

- **Real-state liveness** → `MetricMeter` + `ResourceDescriptor`
  Liveness reflects in-process signals (deadlock detectors, GC stalls) rather than a 200 OK — zombie processes are reclaimed.

- **Dependency rollup** → `CircuitBreaker` + `OutboundBinding`
  Outbound bindings report into the probe; readiness composes over real dependency health, not synthetic self-checks.
