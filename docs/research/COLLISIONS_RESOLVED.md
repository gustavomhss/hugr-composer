# Collisions Resolved

> Two primitives were co-produced by multiple research agents: `HealthProbe` and
> `RateLimiter`. This document records the canonical merged specifications that
> replace the per-agent variants in `VENOUS_SYSTEM_CATALOG.md`, along with the
> rationale for each merge decision.

## Summary

| Primitive | Agents | Final namespace | Rationale |
|---|---|---|---|
| `HealthProbe` | 1 FRAMEWORKS + 4 RESILIENCY | `obs` | Reporting is an observability concern; resiliency layer *consumes* the signal. Adopt Agent 4's liveness/readiness split (SOTA per k8s + SRE Workbook) and Agent 1's `HealthReport` / `HealthStatus` richness. |
| `RateLimiter` | 4 RESILIENCY + 5 SECURITY | `resiliency` | Runtime quota enforcement is a resiliency primitive; security-specific invariants (ASVS V11, NIST 800-63B §5.2.2) are preserved in the merged contract. |

---

## 1. `HealthProbe` — canonical merged spec

**Namespace.** `obs` (emission & shape). Consumed by `resiliency` and orchestration layers (k8s, load balancers, service mesh).

**Maturity.** `battle_tested`.

**Purpose.** Expose a typed liveness/readiness signal that reflects the real state of dependencies so orchestrators route traffic and restart processes correctly.

### api_signature (merged)

```python
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Protocol


class HealthStatus(str, Enum):
    UP = "up"
    DEGRADED = "degraded"
    DOWN = "down"


@dataclass(frozen=True)
class HealthReport:
    status: HealthStatus
    details: Mapping[str, str] = field(default_factory=dict)


class HealthProbe(Protocol):
    name: str

    async def liveness(self) -> HealthReport: ...
    async def readiness(self) -> HealthReport: ...

    def register_dependency(self, name: str, probe: "HealthProbe") -> None: ...
```

### Invariants (combined)

1. **Liveness MUST only report DOWN when the process itself CANNOT make forward progress**; a slow or failing dependency SHALL NEVER flip liveness DOWN (would cause pointless restarts).
2. **Readiness SHALL report DOWN when any required dependency (registered via `register_dependency`) reports DOWN**; optional probes CANNOT force readiness false.
3. **Both `liveness()` and `readiness()` MUST complete within a declared timeout**; a hanging probe SHALL be treated as DOWN by the aggregator.
4. **A probe MUST NEVER throw**; unexpected exceptions SHALL be caught and turned into DOWN with the exception class name as a `details` entry.
5. **`name` MUST be unique within the registry**; duplicate registrations SHALL be rejected.
6. **`details` MUST NOT leak secrets** (connection strings, tokens, stack traces).
7. **Transitions from UP → DOWN SHALL be debounced** by a configurable window to prevent routing-plane flapping.

### Extension contract

Downstream tools **implement** the `HealthProbe` Protocol per dependency kind (database, broker, cache, external API), **register** each via `register_dependency`, and bind an `AggregationRule` **adapter** that composes child statuses into the parent status (worst-wins, quorum, weighted). New probe sources plug in without changing the endpoint code.

### Consumption example

```python
class DbProbe:
    name = "primary_db"
    async def liveness(self) -> HealthReport:
        return HealthReport(HealthStatus.UP)
    async def readiness(self) -> HealthReport:
        return HealthReport(HealthStatus.UP, details={"pool_size": "18"})
    def register_dependency(self, name: str, probe: HealthProbe) -> None: ...

probe: HealthProbe = DbProbe()
report = await probe.readiness()
if report.status is HealthStatus.DOWN:
    raise NotReady("primary_db")
```

### Sources (union of both agents)

| Source | Locator |
|---|---|
| Spring Boot 3.x Actuator | `docs.spring.io/spring-boot/reference/actuator/endpoints.html` — `HealthIndicator.health()`, `Health.up()/down()/status()` |
| ASP.NET Core 8.0 — Health checks | `learn.microsoft.com/aspnet/core/host-and-deploy/health-checks` — `IHealthCheck.CheckHealthAsync` |
| Kubernetes docs — Configure Liveness, Readiness and Startup Probes | `kubernetes.io` v1.29, distinction liveness vs readiness |
| Google SRE Workbook (Beyer et al., O'Reilly, 2018) | Chapter 22 "Addressing Cascading Failures", subsection "Health Checks and Lame Duck" |
| Nygard, *Release It!* 2nd edition (2018) | Chapter 17 "Transparency", section "Health Checks and Observability" |

### Why essential

Kubernetes and load balancers make routing decisions from `/livez` and `/readyz`; if every tool owns its own probe shape *and* confuses the two signals, deployments fail to roll back safely and slow dependencies turn into crash-loops.

### Alternatives considered

- **Single monolithic `/health` endpoint** — every team edits the same file; confuses the two signals.
- **TCP port open as readiness** — ignores app-level failures.
- **Per-service custom `/ping` format** — blocks generic orchestrator checks.
- **Probes that run the full dependency graph** — cascade flaps and NEVER recover quickly.

---

## 2. `RateLimiter` — canonical merged spec

**Namespace.** `resiliency` (runtime quota enforcement). Critical security cross-cutting invariants are preserved (see V11 / 800-63B below).

**Maturity.** `battle_tested`.

**Purpose.** Enforce a maximum admission rate over a rolling window, keyed per-principal / per-tenant / per-route, with atomic check-and-decrement under concurrency and meaningful retry-after feedback.

### api_signature (merged)

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal, Protocol


Algorithm = Literal["token_bucket", "leaky_bucket", "sliding_window"]


@dataclass(frozen=True)
class RateDecision:
    allowed: bool
    retry_after_seconds: int
    remaining: int


class RateLimiter(Protocol):
    algorithm: Algorithm
    rate_per_second: float
    burst: int

    async def acquire(self, key: str, cost: int = 1, wait_ms: int = 0) -> RateDecision: ...
    def try_acquire(self, key: str, cost: int = 1) -> RateDecision: ...
    def current_rate(self, key: str) -> float: ...
    def reset(self, key: str) -> None: ...
```

### Invariants (combined — runtime + security)

1. **`acquire()` / `try_acquire()` MUST be atomic under concurrent callers**; lost-update races that under-count requests are FORBIDDEN.
2. **The long-run admitted rate per key MUST NEVER exceed `rate_per_second`** over any window longer than `burst / rate_per_second` seconds.
3. **A caller SHALL NEVER block longer than `wait_ms`**; after that the limiter MUST return `RateDecision(allowed=False, ...)`.
4. **`retry_after_seconds` MUST be non-negative** and computed from the current bucket depletion; it MUST NOT leak internal reset times beyond the current window.
5. **Key scoping is FORBIDDEN from being implicit**; state for a key CANNOT be shared across unrelated services.
6. **Authentication endpoints MUST be subject to stricter quotas** than general traffic (per OWASP ASVS V11 and NIST 800-63B §5.2.2).
7. **`cost > 1` SHALL consume proportional tokens** so large operations NEVER count equal to cost-1 operations.
8. **`reset()` MUST NEVER be reachable from unauthenticated request paths**; administrative reset is an out-of-band operation.

### Extension contract

Adopters **register** an `AlgorithmProvider` (`token_bucket`, `leaky_bucket`, `sliding_window_log`) and **bind** a `KeyExtractor` middleware that produces the partition key from request context (tenant, api_key, route_pattern, principal). Counter storage is pluggable via a `CounterAdapter` (in-memory, Redis, distributed-log); the registry refuses adapters that cannot guarantee atomic check-and-decrement.

### Consumption example

```python
async def admit(limiter: RateLimiter, tenant_id: str) -> None:
    decision = await limiter.acquire(key=f"tenant:{tenant_id}", cost=1, wait_ms=50)
    if not decision.allowed:
        raise TooManyRequests(retry_after=decision.retry_after_seconds)
```

### Sources (union of both agents)

| Source | Locator |
|---|---|
| Nygard, *Release It!* 2nd edition (2018) | Chapter 5 "Stability Patterns", "Governor" + "Shed Load", pp. 137-143 |
| Google SRE Workbook (O'Reilly, 2018) | Chapter 21 "Managing Load", "Handling Overload" — per-client quotas |
| Envoy proxy documentation | Local + global rate limiting — `api-v3/extensions/filters/http/local_ratelimit/v3`, token_bucket, descriptors |
| OWASP ASVS 4.0.3 | V11.1 Business Logic Security; V2.2 General Authenticator (anti-automation) |
| NIST SP 800-63B | §5.2.2 Throttling |
| OWASP Top 10 2021 | A07:2021 Identification and Authentication Failures |

### Why essential

Rate limits enforced only at the edge leave internal fan-out unbounded; login endpoints without throttling are a published attack surface. A shared primitive keyed per-principal makes atomicity-under-concurrency a solved problem no handler can reimplement wrong.

### Alternatives considered

- **Edge / CDN-only limits** — cannot key on authenticated principal; ignores internal fan-out amplification.
- **Fixed-window counter** — allows 2× burst at window boundary.
- **Per-handler counter in process memory** — fails under horizontal scale.
- **Quotas enforced by billing** — NEVER prevents real-time damage.
- **Connection-count limits** — cannot distinguish cheap from expensive calls.

---

## Merge method

1. **Union over sources** — every locator from both agents is preserved. More provenance, not less.
2. **Union over invariants** — invariants are *rules*; the canonical set is the union, renumbered for coherence and deduplicated where two agents stated the same rule in different words.
3. **Most-general api_signature wins** — when the two shapes diverge, we pick the one that *contains* the other's expressive surface (Agent 1's `HealthReport` subsumes Agent 4's `Literal['up'|...]`; Agent 5's `RateDecision` subsumes Agent 4's `bool` return).
4. **Namespace placement** by primary concern — `HealthProbe` reports → `obs`; `RateLimiter` enforces → `resiliency`. Cross-cutting concerns are documented in invariants, not in a second namespace entry.
5. **Extension contract** — combine mechanism vocabularies (`register`, `adapter`, `middleware`) to reflect the full plug-in surface.
