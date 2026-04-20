# Venous System Catalog

> Consolidated from 8 research deliverables. 113 unique primitives across 15 namespaces, rooted in 260 total citations.

Every primitive below is validated by the research contract (`docs/research/contracts/briefing_contract.py`) — passing all `PrimitiveSpec` CCs and INVs from `CONTRACT_STANDARDS.md`.

Primitives co-produced by multiple agents are marked `[co-produced]` — the entry merges their invariants and sources; the definitive api_signature selection happens during `SKILL_001_AUDIT.md`.

## Index

- [`api`](#namespace-api) — 6 primitives
- [`auth`](#namespace-auth) — 7 primitives
- [`cache`](#namespace-cache) — 2 primitives
- [`compliance`](#namespace-compliance) — 7 primitives
- [`cost`](#namespace-cost) — 2 primitives
- [`data`](#namespace-data) — 18 primitives
- [`events`](#namespace-events) — 12 primitives
- [`extras`](#namespace-extras) — 4 primitives
- [`flags`](#namespace-flags) — 1 primitive
- [`jobs`](#namespace-jobs) — 4 primitives
- [`llm`](#namespace-llm) — 11 primitives
- [`obs`](#namespace-obs) — 17 primitives
- [`policy`](#namespace-policy) — 4 primitives
- [`resiliency`](#namespace-resiliency) — 10 primitives
- [`security`](#namespace-security) — 8 primitives

**Total: 113 primitives.**

## Namespace `api`

6 primitives.

| Primitive | Maturity | Agents | Sources | Invariants |
|---|---|---|---|---|
| **CommandQuerySeparator** | `battle_tested` | #3 | 3 | 4 |
| **ContextMap** | `battle_tested` | #3 | 2 | 4 |
| **MiddlewarePipeline** | `battle_tested` | #1 | 3 | 5 |
| **RequestContext** | `battle_tested` | #1 | 3 | 5 |
| **RouterPipeline** | `battle_tested` | #1 | 2 | 5 |
| **ValueTransform** | `battle_tested` | #1 | 2 | 5 |

### Details

#### `CommandQuerySeparator`

**Purpose.** Partitions the API into write commands that mutate state and read queries that observe it so each side can scale and evolve independently.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 3 PATTERNS

**Sources (3):** Fowler 'Patterns of Enterprise Application Architecture' (2002); Richardson 'Microservices Patterns' (2018); Vernon 'Implementing Domain-Driven Design' (2013)

**api_signature:**
```python
from typing import Protocol, Any

class CommandQuerySeparator(Protocol):
    def dispatch_command(self, command: Any) -> Any: ...
    def answer_query(self, query: Any) -> Any: ...
    def register_command_handler(self, command_type: type, handler) -> None: ...
    def register_query_handler(self, query_type: type, handler) -> None: ...
```

#### `ContextMap`

**Purpose.** Catalogs every BoundedContext and the integration relationship (Partnership, Customer-Supplier, Conformist, Open Host) between each pair.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 3 PATTERNS

**Sources (2):** Evans 'Domain-Driven Design' (2003); Vernon 'Implementing Domain-Driven Design' (2013)

**api_signature:**
```python
from typing import Protocol, Iterable, Tuple

class ContextMap(Protocol):
    def contexts(self) -> Iterable[str]: ...
    def relationship(self, upstream: str, downstream: str) -> str: ...
    def add_relationship(self, upstream: str, downstream: str, kind: str) -> None: ...
    def integrations(self) -> Iterable[Tuple[str, str, str]]: ...
```

#### `MiddlewarePipeline`

**Purpose.** Ordered chain of components that each transform the RequestContext and decide whether to call the next, enabling cross-cutting concerns.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 1 FRAMEWORKS

**Sources (3):** ASP.NET Core 8.0 — Middleware order; Nest.js 10 — Interceptors (NestInterceptor.intercept); Plug 1.x — Plug specification (init/1, call/2)

**api_signature:**
```python
from typing import Awaitable, Callable, Protocol

Next = Callable[[], Awaitable[None]]

class Middleware(Protocol):
    async def __call__(self, ctx: RequestContext, call_next: Next) -> None: ...

class MiddlewarePipeline(Protocol):
    def use(self, mw: Middleware) -> 'MiddlewarePipeline': ...
    async def run(self, ctx: RequestContext) -> None: ...
```

#### `RequestContext`

**Purpose.** Per-request bag that carries identity, headers, correlation id, and free-form assigns through the handler stack without global state.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 1 FRAMEWORKS

**Sources (3):** ASP.NET Core 8.0 — HttpContext; Plug 1.x — Plug.Conn struct; Ruby on Rails 7 Guides — ActiveSupport::CurrentAttributes

**api_signature:**
```python
from typing import Any, Mapping, Protocol

class RequestContext(Protocol):
    request_id: str
    principal: object | None
    headers: Mapping[str, str]
    assigns: dict[str, Any]

    def put(self, key: str, value: Any) -> 'RequestContext': ...
    def halt(self) -> 'RequestContext': ...
```

#### `RouterPipeline`

**Purpose.** Named bundle of middleware (e.g. 'browser', 'api') that a route joins with pipe_through so groups of endpoints share the same pre-dispatch chain.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 1 FRAMEWORKS

**Sources (2):** Phoenix 1.7 Router — pipeline/2, pipe_through/1; Plug 1.x — Plug.Builder pipelines

**api_signature:**
```python
from typing import Protocol, Sequence

class RouterPipeline(Protocol):
    name: str
    middleware: Sequence['Middleware']

    def attach(self, route: str) -> None: ...
```

#### `ValueTransform`

**Purpose.** Strongly-typed parse/validate step that converts a raw inbound argument (body/query/param) into the typed value the handler expects.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 1 FRAMEWORKS

**Sources (2):** ASP.NET Core 8.0 — Model binding and validation; Nest.js 10 — Pipes (PipeTransform, ArgumentMetadata)

**api_signature:**
```python
from typing import Protocol, TypeVar
from dataclasses import dataclass

I = TypeVar('I')
O = TypeVar('O')

@dataclass(frozen=True)
class ArgumentMetadata:
    kind: str
    metatype: type | None
    data: str | None

class ValueTransform(Protocol):
    def transform(self, value: I, meta: ArgumentMetadata) -> O: ...
```

## Namespace `auth`

7 primitives.

| Primitive | Maturity | Agents | Sources | Invariants |
|---|---|---|---|---|
| **AuthorizationCodeFlow** | `battle_tested` | #5 | 3 | 6 |
| **CurrentPrincipal** | `battle_tested` | #1 | 3 | 5 |
| **RequestGuard** | `battle_tested` | #1 | 2 | 5 |
| **SessionStore** | `battle_tested` | #5 | 2 | 6 |
| **TokenIntrospector** | `battle_tested` | #5 | 3 | 6 |
| **TotpVerifier** | `battle_tested` | #5 | 3 | 5 |
| **WebAuthnAuthenticator** | `emerging` | #5 | 2 | 6 |

### Details

#### `AuthorizationCodeFlow`

**Purpose.** Execute the OAuth 2.0 authorization-code grant with PKCE, enforcing state, nonce, redirect URI pinning, and one-time code exchange against the token endpoint.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 5 SECURITY

**Sources (3):** OpenID Connect Core 1.0; RFC 6749; RFC 7636

**api_signature:**
```python
from dataclasses import dataclass
from typing import Protocol

@dataclass(frozen=True)
class AuthorizationRequest:
    authorization_url: str
    state: str
    nonce: str
    code_verifier: str

class AuthorizationCodeFlow(Protocol):
    def begin(self, scopes: list[str]) -> AuthorizationRequest: ...
    def exchange(self, code: str, state: str, stored: AuthorizationRequest) -> dict: ...
```

#### `CurrentPrincipal`

**Purpose.** Read-only view of the authenticated identity for the active request, including subject id, tenant, roles, and claim set.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 1 FRAMEWORKS

**Sources (3):** ASP.NET Core 8.0 — HttpContext.User (ClaimsPrincipal); Nest.js 10 — CanActivate and ExecutionContext; Ruby on Rails 7 — ActiveSupport::CurrentAttributes

**api_signature:**
```python
from dataclasses import dataclass
from typing import FrozenSet, Mapping

@dataclass(frozen=True)
class CurrentPrincipal:
    subject_id: str
    tenant_id: str | None
    roles: FrozenSet[str]
    claims: Mapping[str, str]
    is_anonymous: bool
```

#### `RequestGuard`

**Purpose.** Predicate invoked before a handler runs that returns allow/deny based on RequestContext and CurrentPrincipal, short-circuiting the pipeline on deny.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 1 FRAMEWORKS

**Sources (2):** ASP.NET Core 8.0 — Authorization policies; Nest.js 10 — Guards (CanActivate)

**api_signature:**
```python
from typing import Protocol

class RequestGuard(Protocol):
    async def allow(self, ctx: RequestContext, principal: CurrentPrincipal) -> bool: ...
```

#### `SessionStore`

**Purpose.** Issue, rotate, and revoke server-side session records keyed by high-entropy identifiers, with fixation resistance and explicit lifetime boundaries.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 5 SECURITY

**Sources (2):** OWASP ASVS 4.0.3; OWASP Top 10 2021

**api_signature:**
```python
from dataclasses import dataclass
from typing import Protocol

@dataclass(frozen=True)
class Session:
    id: str
    subject: str
    created_at: int
    idle_expires_at: int
    absolute_expires_at: int

class SessionStore(Protocol):
    def create(self, subject: str) -> Session: ...
    def load(self, session_id: str) -> Session | None: ...
    def rotate(self, session_id: str) -> Session: ...
    def revoke(self, session_id: str) -> None: ...
    def revoke_all_for_subject(self, subject: str) -> int: ...
```

#### `TokenIntrospector`

**Purpose.** Validate access tokens by signature, issuer, audience, expiry, and not-before claims, with optional RFC 7662 introspection for opaque tokens.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 5 SECURITY

**Sources (3):** OpenID Connect Core 1.0; RFC 6749; RFC 7662

**api_signature:**
```python
from dataclasses import dataclass
from typing import Protocol

@dataclass(frozen=True)
class TokenClaims:
    subject: str
    scopes: frozenset[str]
    audience: frozenset[str]
    issuer: str
    expires_at: int

class TokenIntrospector(Protocol):
    def introspect(self, token: str, required_audience: str) -> TokenClaims: ...
```

#### `TotpVerifier`

**Purpose.** Generate and verify six-digit time-based one-time passwords per RFC 6238 with constant-time comparison, clock-skew tolerance, and replay prevention.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 5 SECURITY

**Sources (3):** NIST SP 800-63B; OWASP ASVS 4.0.3; RFC 6238

**api_signature:**
```python
from typing import Protocol

class TotpVerifier(Protocol):
    def provision_uri(self, account: str, issuer: str, secret: bytes) -> str: ...
    def verify(self, secret: bytes, code: str, last_used_step: int | None) -> int: ...
```

#### `WebAuthnAuthenticator`

**Purpose.** Register and assert passkey credentials per the Web Authentication API, binding credentials to an RP ID and verifying attestation, challenge, origin, and signature counter.

**Maturity.** `emerging` — **Contributing agents.** Agent 5 SECURITY

**Sources (2):** OWASP ASVS 4.0.3; W3C WebAuthn Level 3 Recommendation

**api_signature:**
```python
from dataclasses import dataclass
from typing import Protocol

@dataclass(frozen=True)
class RegistrationResult:
    credential_id: bytes
    public_key: bytes
    sign_count: int
    aaguid: bytes

class WebAuthnAuthenticator(Protocol):
    def begin_registration(self, user_id: bytes, user_name: str) -> dict: ...
    def finish_registration(self, challenge: bytes, response: dict) -> RegistrationResult: ...
    def begin_assertion(self, credential_ids: list[bytes]) -> dict: ...
    def finish_assertion(self, challenge: bytes, response: dict, stored_public_key: bytes, stored_sign_count: int) -> int: ...
```

## Namespace `cache`

2 primitives.

| Primitive | Maturity | Agents | Sources | Invariants |
|---|---|---|---|---|
| **DistributedLock** | `emerging` | #2 | 1 | 5 |
| **KeyValueBucket** | `emerging` | #2 | 1 | 5 |

### Details

#### `DistributedLock`

**Purpose.** Named mutex with lease expiry that grants one holder exclusive access across processes and is released explicitly or by lease timeout on crash.

**Maturity.** `emerging` — **Contributing agents.** Agent 2 DISTRIBUTED

**Sources (1):** Dapr 1.14 Distributed Lock building block overview

**api_signature:**
```python
from dataclasses import dataclass
from typing import Protocol

@dataclass(frozen=True)
class LockHandle:
    resource_id: str
    owner_id: str
    lease_s: int

class DistributedLock(Protocol):
    async def try_lock(self, resource_id: str, owner_id: str, lease_s: int) -> LockHandle | None: ...
    async def unlock(self, handle: LockHandle) -> None: ...
```

#### `KeyValueBucket`

**Purpose.** Named bucket of key value entries with optimistic create and update and a watch channel for change notifications derived from an underlying stream.

**Maturity.** `emerging` — **Contributing agents.** Agent 2 DISTRIBUTED

**Sources (1):** NATS 2.10 JetStream overview

**api_signature:**
```python
from typing import Protocol, AsyncIterator
from dataclasses import dataclass

@dataclass(frozen=True)
class KvEntry:
    key: str
    value: bytes
    revision: int

class KeyValueBucket(Protocol):
    async def create(self, key: str, value: bytes) -> KvEntry: ...
    async def update(self, key: str, value: bytes, revision: int) -> KvEntry: ...
    async def get(self, key: str) -> KvEntry | None: ...
    async def delete(self, key: str, revision: int | None = None) -> None: ...
    def watch(self, key: str) -> AsyncIterator[KvEntry]: ...
```

## Namespace `compliance`

7 primitives.

| Primitive | Maturity | Agents | Sources | Invariants |
|---|---|---|---|---|
| **AuditEvent** | `battle_tested` | #7 | 3 | 6 |
| **BreachNotificationQueue** | `emerging` | #6 | 2 | 5 |
| **ConsentLedger** | `battle_tested` | #6 | 2 | 5 |
| **DataSubjectRequest** | `emerging` | #6 | 2 | 5 |
| **ProcessingRecord** | `emerging` | #6 | 1 | 5 |
| **RetentionPolicy** | `battle_tested` | #6 | 3 | 5 |
| **TamperEvidentAuditLog** | `battle_tested` | #6 | 3 | 6 |

### Details

#### `AuditEvent`

**Purpose.** Emit a tamper-evident, append-only record of a security-relevant action with actor, subject, action verb, outcome, and a cryptographic chain link.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 7 OBSERVABILITY

**Sources (3):** Majors, Fong-Jones, Miranda — Observability Engineering (2022); NIST Special Publication 800-92 — Guide to Computer Security Log Management; OpenTelemetry Semantic Conventions 1.27 — General

**api_signature:**
```python
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Protocol

@dataclass(frozen=True)
class AuditEvent:
    event_id: str
    occurred_at: datetime
    actor_id: str
    actor_type: str
    action: str
    resource_type: str
    resource_id: str
    outcome: str
    attributes: Mapping[str, str]
    prev_hash: str
    event_hash: str

class AuditEventSink(Protocol):
    def emit(self, event: AuditEvent) -> None: ...
    def verify_chain(self, from_event_id: str | None = None) -> bool: ...
```

#### `BreachNotificationQueue`

**Purpose.** Tracks suspected and confirmed personal-data incidents with a statutory notification clock, so the 72-hour window is enforced in code.

**Maturity.** `emerging` — **Contributing agents.** Agent 6 COMPLIANCE

**Sources (2):** EU GDPR Regulation 2016/679 Articles 5, 6, 7, 15, 17, 30, 32; HIPAA Security Rule 45 CFR §§ 164.308-164.312

**api_signature:**
```python
from typing import Protocol, Literal
from datetime import datetime

Severity = Literal['low', 'medium', 'high', 'critical']

class BreachNotificationQueue(Protocol):
    def open_incident(self, detected_at: datetime, severity: Severity, summary: str) -> str: ...
    def confirm(self, incident_id: str, confirmed_at: datetime, data_classes: tuple[str, ...]) -> None: ...
    def notify_authority(self, incident_id: str, authority: str, at: datetime, reference: str) -> None: ...
    def close(self, incident_id: str, outcome: str) -> None: ...
```

#### `ConsentLedger`

**Purpose.** Records granular per-subject, per-purpose consent grants and revocations with timestamp and version of the notice accepted.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 6 COMPLIANCE

**Sources (2):** AICPA SOC 2 Trust Services Criteria (2017, 2022 revision); EU GDPR Regulation 2016/679 Articles 5, 6, 7, 15, 17, 30, 32

**api_signature:**
```python
from typing import Protocol
from datetime import datetime

class ConsentLedger(Protocol):
    def grant(self, subject_id: str, purpose: str, notice_version: str, at: datetime) -> str: ...
    def revoke(self, subject_id: str, purpose: str, at: datetime) -> None: ...
    def is_granted(self, subject_id: str, purpose: str, at: datetime | None = None) -> bool: ...
    def history(self, subject_id: str) -> list[dict]: ...
```

#### `DataSubjectRequest`

**Purpose.** Coordinates the lifecycle of an access or erasure request across all stores that hold data about the subject, with a SLA clock.

**Maturity.** `emerging` — **Contributing agents.** Agent 6 COMPLIANCE

**Sources (2):** EU GDPR Regulation 2016/679 Articles 5, 6, 7, 15, 17, 30, 32; HIPAA Security Rule 45 CFR §§ 164.308-164.312

**api_signature:**
```python
from typing import Protocol, Literal
from datetime import datetime

DsrKind = Literal['access', 'portability', 'erasure', 'rectification']

class DataSubjectRequest(Protocol):
    def open(self, subject_id: str, kind: DsrKind, received_at: datetime) -> str: ...
    def attach_artifact(self, request_id: str, store: str, manifest: bytes) -> None: ...
    def close(self, request_id: str, outcome: str) -> None: ...
    def due_at(self, request_id: str) -> datetime: ...
```

#### `ProcessingRecord`

**Purpose.** Machine-readable record of processing activities that a controller must maintain, generated from code rather than a separate document.

**Maturity.** `emerging` — **Contributing agents.** Agent 6 COMPLIANCE

**Sources (1):** EU GDPR Regulation 2016/679 Articles 5, 6, 7, 15, 17, 30, 32

**api_signature:**
```python
from dataclasses import dataclass
from typing import Protocol

@dataclass(frozen=True)
class ProcessingRecord:
    activity: str
    controller: str
    purposes: tuple[str, ...]
    data_classes: tuple[str, ...]
    recipients: tuple[str, ...]
    retention_ref: str
    legal_basis: str
    transfers_outside_eea: tuple[str, ...] = ()

class ProcessingRegistry(Protocol):
    def register(self, record: ProcessingRecord) -> None: ...
    def export_ropa(self) -> bytes: ...
```

#### `RetentionPolicy`

**Purpose.** Declarative binding of a data class to a maximum lifetime, enforced by scheduled purge and blocked at write-time if unclassified.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 6 COMPLIANCE

**Sources (3):** EU GDPR Regulation 2016/679 Articles 5, 6, 7, 15, 17, 30, 32; NIST SP 800-53 revision 5; PCI-DSS v4.0

**api_signature:**
```python
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

@dataclass(frozen=True)
class RetentionPolicy:
    data_class: str
    max_age: timedelta
    legal_basis: str
    deletion_mode: str  # 'hard' | 'crypto_shred' | 'anonymize'

class RetentionEnforcer(Protocol):
    def bind(self, policy: RetentionPolicy) -> None: ...
    def enforce_on_write(self, data_class: str, record_id: str) -> None: ...
    def sweep(self) -> int: ...
```

#### `TamperEvidentAuditLog`

**Purpose.** Append-only record of security-relevant events, hash-chained and signed so any retroactive mutation is detectable by verification.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 6 COMPLIANCE

**Sources (3):** AICPA SOC 2 Trust Services Criteria (2017, 2022 revision); HIPAA Security Rule 45 CFR §§ 164.308-164.312; NIST SP 800-53 revision 5

**api_signature:**
```python
from typing import Protocol, Mapping, Any

class TamperEvidentAuditLog(Protocol):
    def append(self, actor: str, action: str, resource: str, outcome: str, attributes: Mapping[str, Any]) -> str: ...
    def verify_chain(self, start_seq: int | None = None, end_seq: int | None = None) -> bool: ...
    def get(self, seq: int) -> Mapping[str, Any]: ...
    def export(self, since_seq: int) -> bytes: ...
```

## Namespace `cost`

2 primitives.

| Primitive | Maturity | Agents | Sources | Invariants |
|---|---|---|---|---|
| **BudgetGuard** | `emerging` | #8 | 2 | 5 |
| **TokenMeter** | `battle_tested` | #8 | 2 | 5 |

### Details

#### `BudgetGuard`

**Purpose.** Enforce per-tenant, per-feature, and per-time-window spending ceilings by consulting the TokenMeter and rejecting or throttling new model calls when the configured budget is exhausted.

**Maturity.** `emerging` — **Contributing agents.** Agent 8 LLM_ERA

**Sources (2):** Helicone gateway architecture (helicone.ai); Portkey gateway architecture (portkey-ai 1.x)

**api_signature:**
```python
from __future__ import annotations
from typing import Protocol, Literal

class BudgetVerdict(Protocol):
    action: Literal["allow", "throttle", "deny"]
    remaining_usd_cents: int
    window_seconds: int

class BudgetGuard(Protocol):
    def check(self, tenant_id: str, feature: str, est_cost_usd_cents: int) -> BudgetVerdict: ...
    def set_limit(self, tenant_id: str, feature: str, ceiling_usd_cents: int, window_seconds: int) -> None: ...
```

#### `TokenMeter`

**Purpose.** Record prompt tokens, completion tokens, cache-read tokens, and provider-reported cost for every model call, attributing each unit of consumption to a tenant, user, and feature label.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 8 LLM_ERA

**Sources (2):** OpenTelemetry Semantic Conventions for Generative AI (1.27+); Portkey gateway architecture (portkey-ai 1.x)

**api_signature:**
```python
from __future__ import annotations
from typing import Protocol

class TokenUsage(Protocol):
    prompt_tokens: int
    completion_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: float

class TokenMeter(Protocol):
    def record(self, model_handle: str, usage: TokenUsage, labels: dict[str, str]) -> None: ...
    def sum(self, labels: dict[str, str], window_seconds: int) -> TokenUsage: ...
```

## Namespace `data`

18 primitives.

| Primitive | Maturity | Agents | Sources | Invariants |
|---|---|---|---|---|
| **Aggregate** | `battle_tested` | #3 | 2 | 5 |
| **AntiCorruptionLayer** | `battle_tested` | #3 | 2 | 4 |
| **BoundedContext** | `battle_tested` | #3 | 2 | 4 |
| **ChangeDataCapture** | `battle_tested` | #3 | 2 | 4 |
| **ConfigBinding** | `battle_tested` | #1 | 2 | 5 |
| **DataMapper** | `battle_tested` | #3 | 1 | 4 |
| **DiContainer** | `battle_tested` | #1 | 3 | 5 |
| **IdentityMap** | `battle_tested` | #3 | 1 | 4 |
| **LegalHold** | `battle_tested` | #6 | 2 | 5 |
| **LifetimeScope** | `battle_tested` | #1 | 4 | 5 |
| **MaterializedView** | `battle_tested` | #3 | 2 | 4 |
| **PiiClassification** | `emerging` | #6 | 3 | 5 |
| **Repository** | `battle_tested` | #3 | 3 | 5 |
| **Specification** | `battle_tested` | #3 | 2 | 4 |
| **StateStore** | `battle_tested` | #2 | 1 | 6 |
| **TransactionalBatch** | `battle_tested` | #2 | 2 | 5 |
| **UnitOfWork** | `battle_tested` | #3 | 2 | 6 |
| **ValueObject** | `battle_tested` | #3 | 2 | 4 |

### Details

#### `Aggregate`

**Purpose.** Defines a consistency boundary around a cluster of entities and value objects governed by a single root responsible for invariants.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 3 PATTERNS

**Sources (2):** Evans 'Domain-Driven Design' (2003); Vernon 'Implementing Domain-Driven Design' (2013)

**api_signature:**
```python
from typing import Protocol, TypeVar, Generic, Iterable

ID = TypeVar('ID')

class Aggregate(Protocol, Generic[ID]):
    @property
    def id(self) -> ID: ...
    @property
    def version(self) -> int: ...
    def pull_events(self) -> Iterable[object]: ...
```

#### `AntiCorruptionLayer`

**Purpose.** Translates between a local model and a foreign or legacy model so upstream semantics cannot leak into the local BoundedContext.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 3 PATTERNS

**Sources (2):** Evans 'Domain-Driven Design' (2003); Vernon 'Implementing Domain-Driven Design' (2013)

**api_signature:**
```python
from typing import Protocol, TypeVar

Local = TypeVar('Local')
Foreign = TypeVar('Foreign')

class AntiCorruptionLayer(Protocol):
    def to_local(self, foreign: Foreign) -> Local: ...
    def to_foreign(self, local: Local) -> Foreign: ...
    def guard(self, foreign: Foreign) -> None: ...
```

#### `BoundedContext`

**Purpose.** Declares the explicit linguistic and model boundary within which one ubiquitous language and one set of invariants apply.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 3 PATTERNS

**Sources (2):** Evans 'Domain-Driven Design' (2003); Vernon 'Implementing Domain-Driven Design' (2013)

**api_signature:**
```python
from typing import Protocol, Mapping

class BoundedContext(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def language(self) -> Mapping[str, str]: ...
    def owns(self, aggregate_type: type) -> bool: ...
    def translator_to(self, other: 'BoundedContext') -> object: ...
```

#### `ChangeDataCapture`

**Purpose.** Publishes an ordered stream of row-level changes from a source database so downstream systems can consume mutations without dual writes.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 3 PATTERNS

**Sources (2):** Kleppmann 'Designing Data-Intensive Applications' (2017); Richardson 'Microservices Patterns' (2018)

**api_signature:**
```python
from typing import Protocol, Iterator, Any

class ChangeDataCapture(Protocol):
    def subscribe(self, table: str, from_position: object) -> Iterator[Any]: ...
    def checkpoint(self, position: object) -> None: ...
    def schema(self, table: str) -> dict: ...
```

#### `ConfigBinding`

**Purpose.** Binds a namespaced slice of the runtime configuration to a typed record, validated at startup so misconfiguration fails loud, not silent.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 1 FRAMEWORKS

**Sources (2):** ASP.NET Core 8.0 — Options pattern; Spring Boot 3.x Reference — Type-safe Configuration Properties

**api_signature:**
```python
from typing import Protocol, Type, TypeVar

T = TypeVar('T')

class ConfigBinding(Protocol):
    def bind(self, prefix: str, schema: Type[T]) -> T: ...
    def reload(self) -> None: ...
```

#### `DataMapper`

**Purpose.** Moves state between in-memory domain objects and rows in storage while keeping both ignorant of each other.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 3 PATTERNS

**Sources (1):** Fowler 'Patterns of Enterprise Application Architecture' (2002)

**api_signature:**
```python
from typing import Protocol, TypeVar, Generic, Any

T = TypeVar('T')

class DataMapper(Protocol, Generic[T]):
    def load(self, row: dict) -> T: ...
    def insert(self, entity: T) -> dict: ...
    def update(self, entity: T) -> dict: ...
    def delete(self, entity: T) -> dict: ...
```

#### `DiContainer`

**Purpose.** Registry that resolves a typed request for a dependency into a constructed instance obeying the declared lifetime scope.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 1 FRAMEWORKS

**Sources (3):** ASP.NET Core 8.0 Fundamentals — Dependency Injection; Quarkus 3.x Guide — Contexts and Dependency Injection; Spring Framework Reference — Core Container

**api_signature:**
```python
from typing import Callable, Protocol, Type, TypeVar

T = TypeVar('T')

class DiContainer(Protocol):
    def register(self, iface: Type[T], impl: Type[T] | Callable[..., T], *, scope: str) -> None: ...
    def resolve(self, iface: Type[T]) -> T: ...
    def create_scope(self) -> 'DiContainer': ...
```

#### `IdentityMap`

**Purpose.** Caches loaded domain objects by identity inside one session so the same row is never represented twice in memory.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 3 PATTERNS

**Sources (1):** Fowler 'Patterns of Enterprise Application Architecture' (2002)

**api_signature:**
```python
from typing import Protocol, Any, Optional

class IdentityMap(Protocol):
    def get(self, type_: type, id: object) -> Optional[Any]: ...
    def add(self, obj: Any) -> None: ...
    def remove(self, type_: type, id: object) -> None: ...
    def contains(self, type_: type, id: object) -> bool: ...
```

#### `LegalHold`

**Purpose.** Suspends retention-driven deletion and erasure cascades for records covered by a litigation or regulatory hold until the hold is released.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 6 COMPLIANCE

**Sources (2):** AICPA SOC 2 Trust Services Criteria (2017, 2022 revision); NIST SP 800-53 revision 5

**api_signature:**
```python
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

@dataclass(frozen=True)
class LegalHold:
    hold_id: str
    scope_query: str
    opened_at: datetime
    opened_by: str

class LegalHoldRegistry(Protocol):
    def open(self, hold: LegalHold) -> None: ...
    def release(self, hold_id: str, released_by: str) -> None: ...
    def covers(self, record_id: str) -> bool: ...
```

#### `LifetimeScope`

**Purpose.** Typed enumeration that fixes how long a resolved instance lives: the whole process, one request, or one injection point.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 1 FRAMEWORKS

**Sources (4):** ASP.NET Core 8.0 Fundamentals — Service lifetimes; Nest.js 10 Documentation — Injection scopes; Quarkus 3.x CDI Guide; Spring Framework Reference — Bean Scopes

**api_signature:**
```python
from enum import Enum

class LifetimeScope(str, Enum):
    SINGLETON = 'singleton'
    SCOPED = 'scoped'
    TRANSIENT = 'transient'
```

#### `MaterializedView`

**Purpose.** Maintains a pre-computed query result kept up to date by an incremental feed so read queries never recompute from base tables.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 3 PATTERNS

**Sources (2):** Kleppmann 'Designing Data-Intensive Applications' (2017); Richardson 'Microservices Patterns' (2018)

**api_signature:**
```python
from typing import Protocol, Any, Iterable

class MaterializedView(Protocol):
    @property
    def name(self) -> str: ...
    def apply(self, event: Any) -> None: ...
    def rebuild(self, source: Iterable[Any]) -> None: ...
    def query(self, criteria: object) -> Iterable[Any]: ...
```

#### `PiiClassification`

**Purpose.** Schema-level annotation that tags every field as one of PII, PHI, PCI, or public, gating serialization and logging through a central mask.

**Maturity.** `emerging` — **Contributing agents.** Agent 6 COMPLIANCE

**Sources (3):** HIPAA Security Rule 45 CFR §§ 164.308-164.312; NIST SP 800-53 revision 5; PCI-DSS v4.0

**api_signature:**
```python
from enum import Enum
from typing import Protocol, Any, Mapping

class PiiClass(str, Enum):
    PUBLIC = 'public'
    INTERNAL = 'internal'
    PII = 'pii'
    PHI = 'phi'
    PCI = 'pci'

class PiiClassification(Protocol):
    def classify(self, model: type, field: str) -> PiiClass: ...
    def mask(self, obj: Any, audience: str) -> Mapping[str, Any]: ...
    def audit_leak(self, obj: Any, sink: str) -> None: ...
```

#### `Repository`

**Purpose.** Mediates between the domain model and data mapping layer using a collection-like interface to access aggregate roots.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 3 PATTERNS

**Sources (3):** Evans 'Domain-Driven Design' (2003); Fowler 'Patterns of Enterprise Application Architecture' (2002); Vernon 'Implementing Domain-Driven Design' (2013)

**api_signature:**
```python
from typing import Protocol, Generic, TypeVar, Optional, Iterable

T = TypeVar('T')

class Repository(Protocol, Generic[T]):
    def get(self, id: object) -> Optional[T]: ...
    def add(self, entity: T) -> None: ...
    def remove(self, entity: T) -> None: ...
    def find(self, spec: object) -> Iterable[T]: ...
```

#### `Specification`

**Purpose.** Encapsulates a predicate over a domain object so selection, validation, and building criteria share one reusable rule.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 3 PATTERNS

**Sources (2):** Evans 'Domain-Driven Design' (2003); Fowler and Evans 'Specifications' white paper (2002)

**api_signature:**
```python
from typing import Protocol, TypeVar, Generic

T = TypeVar('T')

class Specification(Protocol, Generic[T]):
    def is_satisfied_by(self, candidate: T) -> bool: ...
    def and_(self, other: 'Specification[T]') -> 'Specification[T]': ...
    def or_(self, other: 'Specification[T]') -> 'Specification[T]': ...
    def not_(self) -> 'Specification[T]': ...
```

#### `StateStore`

**Purpose.** Key addressed durable key-value CRUD surface with optimistic concurrency tokens and optional TTL for language neutral state access.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 2 DISTRIBUTED

**Sources (1):** Dapr 1.14 State Management building block overview

**api_signature:**
```python
from typing import Protocol, Any

class StateStore(Protocol):
    async def get(self, key: str) -> tuple[bytes, str | None]: ...
    async def save(self, key: str, value: bytes, etag: str | None = None, ttl_s: int | None = None) -> str: ...
    async def delete(self, key: str, etag: str | None = None) -> None: ...
    async def bulk_get(self, keys: list[str]) -> dict[str, tuple[bytes, str | None]]: ...
```

#### `TransactionalBatch`

**Purpose.** Atomic multi key write unit that commits a set of upsert and delete operations to one state store under a single transaction boundary.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 2 DISTRIBUTED

**Sources (2):** Confluent Kafka Design: Message Delivery Semantics; Dapr 1.14 State Management building block overview

**api_signature:**
```python
from typing import Protocol, Literal, Any
from dataclasses import dataclass

@dataclass
class _Op:
    op: Literal['upsert', 'delete']
    key: str
    value: bytes | None
    etag: str | None

class TransactionalBatch(Protocol):
    def upsert(self, key: str, value: bytes, etag: str | None = None) -> 'TransactionalBatch': ...
    def delete(self, key: str, etag: str | None = None) -> 'TransactionalBatch': ...
    async def commit(self) -> None: ...
```

#### `UnitOfWork`

**Purpose.** Tracks object changes during a business transaction and flushes them to storage as one atomic commit or rollback.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 3 PATTERNS

**Sources (2):** Fowler 'Patterns of Enterprise Application Architecture' (2002); Vernon 'Implementing Domain-Driven Design' (2013)

**api_signature:**
```python
from typing import Protocol, Any

class UnitOfWork(Protocol):
    def register_new(self, obj: Any) -> None: ...
    def register_dirty(self, obj: Any) -> None: ...
    def register_removed(self, obj: Any) -> None: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def __enter__(self) -> 'UnitOfWork': ...
    def __exit__(self, exc_type, exc, tb) -> bool: ...
```

#### `ValueObject`

**Purpose.** Represents a descriptive concept whose identity is defined entirely by its attributes and which is immutable once constructed.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 3 PATTERNS

**Sources (2):** Evans 'Domain-Driven Design' (2003); Vernon 'Implementing Domain-Driven Design' (2013)

**api_signature:**
```python
from typing import Protocol

class ValueObject(Protocol):
    def __eq__(self, other: object) -> bool: ...
    def __hash__(self) -> int: ...
    def with_changes(self, **kwargs) -> 'ValueObject': ...
```

## Namespace `events`

12 primitives.

| Primitive | Maturity | Agents | Sources | Invariants |
|---|---|---|---|---|
| **DeadLetterRoute** | `battle_tested` | #2 | 2 | 5 |
| **DomainEvent** | `battle_tested` | #3 | 3 | 4 |
| **EventEnvelope** | `battle_tested` | #2 | 1 | 5 |
| **EventSourcedStore** | `battle_tested` | #3 | 3 | 4 |
| **EventStream** | `battle_tested` | #3 | 2 | 4 |
| **IdempotentConsumer** | `battle_tested` | #3 | 2 | 4 |
| **InboxDeduplicator** | `battle_tested` | #3 | 2 | 4 |
| **PartitionLog** | `battle_tested` | #2 | 2 | 5 |
| **SagaOrchestrator** | `battle_tested` | #3 | 2 | 4 |
| **StreamSubject** | `battle_tested` | #2 | 2 | 5 |
| **TopicBus** | `battle_tested` | #2 | 2 | 5 |
| **TransactionalOutbox** | `battle_tested` | #3 | 2 | 4 |

### Details

#### `DeadLetterRoute`

**Purpose.** Named destination where undeliverable or repeatedly failed messages are routed after the redelivery budget is exhausted so they can be inspected or replayed.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 2 DISTRIBUTED

**Sources (2):** Apache Kafka 3.x documentation concepts; Dapr 1.14 Publish and Subscribe building block overview

**api_signature:**
```python
from dataclasses import dataclass
from typing import Protocol

@dataclass(frozen=True)
class DeadLetterRoute:
    source_topic: str
    destination_topic: str
    max_deliveries: int

class DeadLetterSink(Protocol):
    async def send(self, route: DeadLetterRoute, envelope: 'EventEnvelope', reason: str, attempt: int) -> None: ...
```

#### `DomainEvent`

**Purpose.** Records an immutable fact about something meaningful that happened in the domain and can be published to downstream consumers.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 3 PATTERNS

**Sources (3):** Evans 'Domain-Driven Design' (2003); Richardson 'Microservices Patterns' (2018); Vernon 'Implementing Domain-Driven Design' (2013)

**api_signature:**
```python
from typing import Protocol, Mapping, Any

class DomainEvent(Protocol):
    @property
    def event_id(self) -> str: ...
    @property
    def aggregate_id(self) -> str: ...
    @property
    def occurred_at(self) -> str: ...
    @property
    def version(self) -> int: ...
    @property
    def payload(self) -> Mapping[str, Any]: ...
```

#### `EventEnvelope`

**Purpose.** Canonical CloudEvents 1.0 shape that normalizes id, source, type, time and payload so downstream handlers parse the same structure regardless of transport.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 2 DISTRIBUTED

**Sources (1):** CloudEvents 1.0.2 Core Specification

**api_signature:**
```python
from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class EventEnvelope:
    id: str
    source: str
    type: str
    specversion: str = '1.0'
    datacontenttype: str | None = None
    dataschema: str | None = None
    subject: str | None = None
    time: str | None = None
    data: Any = None
    extensions: dict[str, str] | None = None
```

#### `EventSourcedStore`

**Purpose.** Persists aggregate state as an ordered sequence of domain events and reconstructs current state by folding them on load.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 3 PATTERNS

**Sources (3):** Fowler 'Patterns of Enterprise Application Architecture' (2002); Richardson 'Microservices Patterns' (2018); Vernon 'Implementing Domain-Driven Design' (2013)

**api_signature:**
```python
from typing import Protocol, Iterable, Any

class EventSourcedStore(Protocol):
    def load(self, aggregate_id: str) -> Iterable[Any]: ...
    def append(self, aggregate_id: str, expected_version: int, events: Iterable[Any]) -> int: ...
    def snapshot(self, aggregate_id: str, version: int, state: Any) -> None: ...
    def latest_snapshot(self, aggregate_id: str) -> Any: ...
```

#### `EventStream`

**Purpose.** An ordered, append-only log of events partitioned by key and replayable from any offset by any number of consumers.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 3 PATTERNS

**Sources (2):** Kleppmann 'Designing Data-Intensive Applications' (2017); Richardson 'Microservices Patterns' (2018)

**api_signature:**
```python
from typing import Protocol, Any, Iterator

class EventStream(Protocol):
    def append(self, partition_key: str, event: Any) -> int: ...
    def read_from(self, partition_key: str, offset: int) -> Iterator[Any]: ...
    def tail(self, partition_key: str) -> int: ...
    def truncate_before(self, offset: int) -> None: ...
```

#### `IdempotentConsumer`

**Purpose.** Applies a message's effect at most once per logical key while tolerating at-least-once delivery from the transport.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 3 PATTERNS

**Sources (2):** Kleppmann 'Designing Data-Intensive Applications' (2017); Richardson 'Microservices Patterns' (2018)

**api_signature:**
```python
from typing import Protocol, Any

class IdempotentConsumer(Protocol):
    def key_for(self, message: Any) -> str: ...
    def handle(self, message: Any) -> None: ...
    def on_duplicate(self, message: Any) -> None: ...
```

#### `InboxDeduplicator`

**Purpose.** Records processed message identifiers in the consumer's database so redelivered messages are detected and skipped exactly once.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 3 PATTERNS

**Sources (2):** Kleppmann 'Designing Data-Intensive Applications' (2017); Richardson 'Microservices Patterns' (2018)

**api_signature:**
```python
from typing import Protocol

class InboxDeduplicator(Protocol):
    def seen(self, message_id: str, consumer: str) -> bool: ...
    def record(self, message_id: str, consumer: str) -> None: ...
    def purge_older_than(self, iso_timestamp: str) -> int: ...
```

#### `PartitionLog`

**Purpose.** Ordered append only per partition event log identified by topic and partition number whose position is addressed by a monotonically increasing offset.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 2 DISTRIBUTED

**Sources (2):** Apache Kafka 3.x documentation concepts; Confluent Kafka Design: Message Delivery Semantics

**api_signature:**
```python
from dataclasses import dataclass
from typing import Protocol, AsyncIterator

@dataclass(frozen=True)
class PartitionLog:
    topic: str
    partition: int

class PartitionReader(Protocol):
    async def read_from(self, log: PartitionLog, offset: int) -> AsyncIterator[tuple[int, bytes]]: ...
    async def committed_offset(self, log: PartitionLog, group: str) -> int: ...
```

#### `SagaOrchestrator`

**Purpose.** Coordinates a multi-step business transaction across services by driving each step and triggering compensations when a later step fails.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 3 PATTERNS

**Sources (2):** Garcia-Molina and Salem 'Sagas' (1987) as cited in Richardson; Richardson 'Microservices Patterns' (2018)

**api_signature:**
```python
from typing import Protocol, Any, Iterable, Tuple

class SagaOrchestrator(Protocol):
    def start(self, correlation_id: str, input: Any) -> None: ...
    def step(self, correlation_id: str, name: str, outcome: Any) -> None: ...
    def compensate(self, correlation_id: str, from_step: str) -> None: ...
    def status(self, correlation_id: str) -> Tuple[str, Iterable[str]]: ...
```

#### `StreamSubject`

**Purpose.** Hierarchical dot separated event routing name that supports single token and trailing wildcard matching for consumer filters and stream captures.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 2 DISTRIBUTED

**Sources (2):** NATS 2.10 JetStream overview; NATS 2.10 Subjects concept documentation

**api_signature:**
```python
from dataclasses import dataclass

@dataclass(frozen=True)
class StreamSubject:
    name: str

    def matches(self, pattern: str) -> bool:
        name_tokens = self.name.split('.')
        pattern_tokens = pattern.split('.')
        for i, tok in enumerate(pattern_tokens):
            if tok == '>':
                return i <= len(name_tokens)
            if i >= len(name_tokens):
                return False
            if tok != '*' and tok != name_tokens[i]:
                return False
        return len(pattern_tokens) == len(name_tokens)
```

#### `TopicBus`

**Purpose.** Publish and subscribe facade over a broker topic that delivers CloudEvents at least once to named subscriber groups with optional dead letter routing.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 2 DISTRIBUTED

**Sources (2):** Confluent Kafka Design: Message Delivery Semantics; Dapr 1.14 Publish and Subscribe building block overview

**api_signature:**
```python
from typing import Protocol, Callable, Awaitable

Ack = Callable[[], Awaitable[None]]
Nack = Callable[[str], Awaitable[None]]

class TopicBus(Protocol):
    async def publish(self, topic: str, envelope: 'EventEnvelope') -> None: ...
    def subscribe(self, topic: str, group: str, handler: Callable[['EventEnvelope', Ack, Nack], Awaitable[None]]) -> None: ...
```

#### `TransactionalOutbox`

**Purpose.** Stores outgoing messages in the same local transaction as the state change so a relay can publish them atomically with the commit.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 3 PATTERNS

**Sources (2):** Kleppmann 'Designing Data-Intensive Applications' (2017); Richardson 'Microservices Patterns' (2018)

**api_signature:**
```python
from typing import Protocol, Any, Iterable

class TransactionalOutbox(Protocol):
    def enqueue(self, destination: str, payload: Any, key: str) -> None: ...
    def pending(self, limit: int) -> Iterable[dict]: ...
    def mark_published(self, message_id: str) -> None: ...
    def mark_failed(self, message_id: str, reason: str) -> None: ...
```

## Namespace `extras`

4 primitives.

| Primitive | Maturity | Agents | Sources | Invariants |
|---|---|---|---|---|
| **OutboundBinding** | `battle_tested` | #2 | 1 | 5 |
| **RequestShape** | `emerging` | #4 | 3 | 5 |
| **RpcInterceptor** | `battle_tested` | #2 | 2 | 5 |
| **VirtualActor** | `battle_tested` | #2 | 1 | 5 |

### Details

#### `OutboundBinding`

**Purpose.** Declarative adapter that lets the application invoke an external resource through a named operation and metadata without embedding the vendor SDK.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 2 DISTRIBUTED

**Sources (1):** Dapr 1.14 Bindings building block overview

**api_signature:**
```python
from typing import Protocol
from dataclasses import dataclass

@dataclass(frozen=True)
class BindingInvocation:
    binding_name: str
    operation: str
    data: bytes
    metadata: dict[str, str]

class OutboundBinding(Protocol):
    async def invoke(self, request: BindingInvocation) -> tuple[bytes, dict[str, str]]: ...
```

#### `RequestShape`

**Purpose.** Capture a request's resiliency context (priority class, deadline, idempotency key, retry-count-so-far) in a single immutable record propagated across boundaries.

**Maturity.** `emerging` — **Contributing agents.** Agent 4 RESILIENCY

**Sources (3):** Envoy proxy documentation, HTTP connection manager; Google SRE Workbook (Beyer et al., O'Reilly, 2018); Nygard, Release It! 2nd edition (2018), Pragmatic Bookshelf

**api_signature:**
```python
from __future__ import annotations
from typing import Protocol, Literal

Priority = Literal['critical', 'normal', 'sheddable_plus', 'sheddable']

class RequestShape(Protocol):
    request_id: str
    priority: Priority
    deadline_ns: int
    idempotency_key: str | None
    attempt: int
    origin: str
    def to_headers(self) -> dict[str, str]: ...
    @classmethod
    def from_headers(cls, headers: dict[str, str]) -> 'RequestShape': ...
```

#### `RpcInterceptor`

**Purpose.** Per call middleware that wraps a remote procedure invocation to read or mutate metadata, enforce deadlines and translate errors consistently across services.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 2 DISTRIBUTED

**Sources (2):** gRPC Core Concepts guide; gRPC Interceptors guide

**api_signature:**
```python
from typing import Protocol, Callable, Awaitable, Any
from dataclasses import dataclass

@dataclass(frozen=True)
class RpcContext:
    method: str
    deadline_ms: int | None
    metadata: dict[str, str]

Handler = Callable[[RpcContext, bytes], Awaitable[bytes]]

class RpcInterceptor(Protocol):
    async def intercept(self, ctx: RpcContext, payload: bytes, next: Handler) -> bytes: ...
```

#### `VirtualActor`

**Purpose.** Location transparent single writer object addressed by type and id that holds private state and processes one message at a time on activation.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 2 DISTRIBUTED

**Sources (1):** Dapr 1.14 Actors building block overview

**api_signature:**
```python
from typing import Protocol, Any
from dataclasses import dataclass

@dataclass(frozen=True)
class ActorId:
    actor_type: str
    key: str

class VirtualActor(Protocol):
    async def invoke(self, id: ActorId, method: str, payload: bytes) -> bytes: ...
    async def set_reminder(self, id: ActorId, name: str, period_s: int, ttl_s: int | None = None) -> None: ...
    async def cancel_reminder(self, id: ActorId, name: str) -> None: ...
```

## Namespace `flags`

1 primitive.

| Primitive | Maturity | Agents | Sources | Invariants |
|---|---|---|---|---|
| **FeatureToggle** | `battle_tested` | #1 | 3 | 5 |

### Details

#### `FeatureToggle`

**Purpose.** Named boolean (or variant) predicate, evaluated against the current context, that controls whether a code path is live for a given request.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 1 FRAMEWORKS

**Sources (3):** Spring Boot 3.x Reference — Conditional beans; Spring Framework — Profiles; Togglz 4.x — Feature enum and isActive()

**api_signature:**
```python
from typing import Protocol
from dataclasses import dataclass

@dataclass(frozen=True)
class ToggleContext:
    principal_id: str | None
    tenant_id: str | None
    environment: str

class FeatureToggle(Protocol):
    key: str
    def is_active(self, ctx: ToggleContext) -> bool: ...
```

## Namespace `jobs`

4 primitives.

| Primitive | Maturity | Agents | Sources | Invariants |
|---|---|---|---|---|
| **ActivityCall** | `battle_tested` | #2 | 1 | 5 |
| **DurableTimer** | `battle_tested` | #2 | 2 | 5 |
| **WorkflowRun** | `battle_tested` | #2 | 1 | 5 |
| **WorkflowSignal** | `battle_tested` | #2 | 2 | 5 |

### Details

#### `ActivityCall`

**Purpose.** Workflow scoped unit of side effectful work scheduled with explicit timeouts and a retry policy that the runtime executes at least once on a worker.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 2 DISTRIBUTED

**Sources (1):** Temporal 1.24 Activities concept page

**api_signature:**
```python
from dataclasses import dataclass
from typing import Protocol, Any

@dataclass(frozen=True)
class RetryPolicy:
    initial_interval_s: float
    backoff_coefficient: float
    maximum_attempts: int

@dataclass(frozen=True)
class ActivityCall:
    name: str
    task_queue: str
    start_to_close_s: int
    schedule_to_close_s: int | None
    heartbeat_s: int | None
    retry: RetryPolicy
    args: tuple[Any, ...] = ()

class ActivityExecutor(Protocol):
    async def execute(self, call: ActivityCall) -> Any: ...
```

#### `DurableTimer`

**Purpose.** Workflow scoped sleep that persists across worker outages and fires after a logical delay so long delays do not hold process resources.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 2 DISTRIBUTED

**Sources (2):** Temporal 1.24 Python timers guide; Temporal 1.24 Workflows concept page

**api_signature:**
```python
from dataclasses import dataclass
from typing import Protocol

@dataclass(frozen=True)
class DurableTimer:
    workflow_id: str
    timer_id: str
    delay_s: float

class TimerService(Protocol):
    async def start(self, timer: DurableTimer) -> None: ...
    async def cancel(self, workflow_id: str, timer_id: str) -> None: ...
```

#### `WorkflowRun`

**Purpose.** Durable replayable orchestration identified by a workflow id that survives worker restarts and reconstructs state from a recorded event history.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 2 DISTRIBUTED

**Sources (1):** Temporal 1.24 Workflows concept page

**api_signature:**
```python
from typing import Protocol, Any
from dataclasses import dataclass

@dataclass(frozen=True)
class WorkflowRun:
    workflow_id: str
    run_id: str
    task_queue: str

class WorkflowClient(Protocol):
    async def start(self, workflow_type: str, workflow_id: str, task_queue: str, args: tuple[Any, ...]) -> WorkflowRun: ...
    async def describe(self, workflow_id: str) -> WorkflowRun: ...
    async def cancel(self, workflow_id: str) -> None: ...
```

#### `WorkflowSignal`

**Purpose.** Asynchronous fire and forget write that delivers named input to an open workflow run and is recorded into the event history for replay.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 2 DISTRIBUTED

**Sources (2):** Temporal 1.24 Encyclopedia: Workflow Message Passing; Temporal 1.24 Workflows concept page

**api_signature:**
```python
from dataclasses import dataclass
from typing import Protocol, Any

@dataclass(frozen=True)
class WorkflowSignal:
    workflow_id: str
    name: str
    payload: Any

class SignalSender(Protocol):
    async def send(self, signal: WorkflowSignal) -> None: ...
    async def send_with_start(self, signal: WorkflowSignal, workflow_type: str, task_queue: str) -> str: ...
```

## Namespace `llm`

11 primitives.

| Primitive | Maturity | Agents | Sources | Invariants |
|---|---|---|---|---|
| **EvalHarness** | `emerging` | #8 | 2 | 5 |
| **HumanCheckpoint** | `emerging` | #8 | 2 | 5 |
| **InputGuardrail** | `emerging` | #8 | 1 | 5 |
| **ModelRegistry** | `battle_tested` | #8 | 2 | 5 |
| **ModelRouter** | `emerging` | #8 | 2 | 5 |
| **OutputGuardrail** | `emerging` | #8 | 1 | 5 |
| **PromptInjectionFilter** | `emerging` | #8 | 2 | 5 |
| **PromptTemplate** | `battle_tested` | #8 | 2 | 5 |
| **ResponseCache** | `emerging` | #8 | 2 | 5 |
| **ToolSchema** | `emerging` | #8 | 2 | 5 |
| **VectorStore** | `emerging` | #8 | 2 | 5 |

### Details

#### `EvalHarness`

**Purpose.** Execute a golden dataset against a prompt-plus-model pair and compute graded verdicts via deterministic metrics and optional judge models, emitting a replayable run record.

**Maturity.** `emerging` — **Contributing agents.** Agent 8 LLM_ERA

**Sources (2):** Langfuse 2.x architecture and tracing model; Weights & Biases Weave (weave-python 0.50+)

**api_signature:**
```python
from __future__ import annotations
from typing import Protocol, Sequence

class EvalCase(Protocol):
    case_id: str
    inputs: dict[str, str]
    expected: dict[str, str]

class EvalResult(Protocol):
    case_id: str
    scores: dict[str, float]
    passed: bool

class EvalHarness(Protocol):
    def run(self, dataset: Sequence[EvalCase], prompt_version: int, model_handle: str) -> tuple[EvalResult, ...]: ...
    def aggregate(self, results: Sequence[EvalResult]) -> dict[str, float]: ...
```

#### `HumanCheckpoint`

**Purpose.** Block an agent workflow at a named step until an authorized human approves, rejects, or edits the proposed action, persisting the decision and the reviewer identity.

**Maturity.** `emerging` — **Contributing agents.** Agent 8 LLM_ERA

**Sources (2):** Anthropic Model Context Protocol (MCP) 1.x specification; OWASP Top 10 for LLM Applications (2023)

**api_signature:**
```python
from __future__ import annotations
from typing import Protocol, Literal

class CheckpointDecision(Protocol):
    verdict: Literal["approved", "rejected", "edited"]
    reviewer_id: str
    edited_payload: dict[str, str] | None
    decided_at_iso: str

class HumanCheckpoint(Protocol):
    step_name: str
    def request(self, payload: dict[str, str], required_role: str) -> str: ...
    def await_decision(self, ticket_id: str, timeout_seconds: int) -> CheckpointDecision: ...
```

#### `InputGuardrail`

**Purpose.** Intercept user input before it reaches a model and reject, redact, or transform it according to deterministic rules (PII, injection markers) and optional LLM-judged classifications.

**Maturity.** `emerging` — **Contributing agents.** Agent 8 LLM_ERA

**Sources (1):** OWASP Top 10 for LLM Applications (2023)

**api_signature:**
```python
from __future__ import annotations
from typing import Protocol, Literal

class GuardDecision(Protocol):
    action: Literal["allow", "redact", "block"]
    reason: str
    redacted_text: str | None

class InputGuardrail(Protocol):
    name: str
    def evaluate(self, text: str, context: dict[str, str]) -> GuardDecision: ...
```

#### `ModelRegistry`

**Purpose.** Resolve a logical model handle to a concrete provider endpoint plus declared capabilities (context window, tool-use, streaming, max output tokens) so call sites never hardcode provider identifiers.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 8 LLM_ERA

**Sources (2):** LiteLLM 1.x unified completion interface; Weights & Biases Models (wandb 0.17+)

**api_signature:**
```python
from __future__ import annotations
from typing import Protocol, Literal

class ModelSpec(Protocol):
    handle: str
    provider: str
    context_window_tokens: int
    max_output_tokens: int
    supports_tools: bool
    supports_streaming: bool
    modality: Literal["text", "vision", "audio"]

class ModelRegistry(Protocol):
    def resolve(self, handle: str) -> ModelSpec: ...
    def list_handles(self) -> tuple[str, ...]: ...
```

#### `ModelRouter`

**Purpose.** Select a concrete model handle for a request based on declared policy (cheapest-first, quality-floor, tenant override) and fall back to the next candidate on rate limit, timeout, or provider error.

**Maturity.** `emerging` — **Contributing agents.** Agent 8 LLM_ERA

**Sources (2):** LiteLLM 1.x unified completion interface; Portkey gateway architecture (portkey-ai 1.x)

**api_signature:**
```python
from __future__ import annotations
from typing import Protocol, Sequence

class RoutePolicy(Protocol):
    candidates: tuple[str, ...]
    quality_floor: str
    budget_usd_cents: int

class ModelRouter(Protocol):
    def choose(self, policy: RoutePolicy, tenant_id: str) -> str: ...
    def failover(self, exhausted: Sequence[str], policy: RoutePolicy) -> str: ...
```

#### `OutputGuardrail`

**Purpose.** Inspect model output after generation and reject, rewrite, or annotate it against schema, policy, and safety rules before the caller or downstream tools receive it.

**Maturity.** `emerging` — **Contributing agents.** Agent 8 LLM_ERA

**Sources (1):** OWASP Top 10 for LLM Applications (2023)

**api_signature:**
```python
from __future__ import annotations
from typing import Protocol, Literal

class OutputVerdict(Protocol):
    action: Literal["pass", "rewrite", "block"]
    reason: str
    replacement: str | None

class OutputGuardrail(Protocol):
    name: str
    def evaluate(self, output: str, schema_ref: str | None) -> OutputVerdict: ...
```

#### `PromptInjectionFilter`

**Purpose.** Quarantine untrusted text (retrieved documents, tool outputs, user messages) by wrapping it in delimiters and stripping instruction-like fragments that target the model.

**Maturity.** `emerging` — **Contributing agents.** Agent 8 LLM_ERA

**Sources (2):** Anthropic Model Context Protocol (MCP) 1.x specification; OWASP Top 10 for LLM Applications (2023)

**api_signature:**
```python
from __future__ import annotations
from typing import Protocol, Literal

class QuarantinedText(Protocol):
    kind: Literal["user", "retrieved", "tool_output"]
    wrapped: str
    stripped_fragments: tuple[str, ...]

class PromptInjectionFilter(Protocol):
    def quarantine(self, raw: str, kind: str) -> QuarantinedText: ...
```

#### `PromptTemplate`

**Purpose.** Declare a named, versioned, parameterized prompt whose text, variables, and target model are pinned so two runs of the same version produce identical rendered payloads.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 8 LLM_ERA

**Sources (2):** Langfuse 2.x architecture and tracing model; Weights & Biases Weave (weave-python 0.50+)

**api_signature:**
```python
from __future__ import annotations
from typing import Protocol, Mapping

class PromptTemplate(Protocol):
    name: str
    version: int
    target_model: str
    variables: tuple[str, ...]
    def render(self, values: Mapping[str, str]) -> str: ...
    def fingerprint(self) -> str: ...
```

#### `ResponseCache`

**Purpose.** Reuse a prior model response when a call resolves to the same cache key (exact prompt hash or semantic embedding match within a threshold), returning the cached payload.

**Maturity.** `emerging` — **Contributing agents.** Agent 8 LLM_ERA

**Sources (2):** Helicone gateway architecture (helicone.ai); Langfuse 2.x architecture and tracing model

**api_signature:**
```python
from __future__ import annotations
from typing import Protocol, Literal

class CacheKey(Protocol):
    mode: Literal["exact", "semantic"]
    value: str
    namespace: str

class ResponseCache(Protocol):
    def lookup(self, key: CacheKey, threshold: float | None = None) -> str | None: ...
    def store(self, key: CacheKey, response: str, ttl_seconds: int) -> None: ...
```

#### `ToolSchema`

**Purpose.** Describe a callable tool by name, JSON-schema input, side-effect class, and required scopes so function calling validates arguments and enforces authorization before executing the tool.

**Maturity.** `emerging` — **Contributing agents.** Agent 8 LLM_ERA

**Sources (2):** Anthropic Model Context Protocol (MCP) 1.x specification; OWASP Top 10 for LLM Applications (2023)

**api_signature:**
```python
from __future__ import annotations
from typing import Protocol, Literal

class ToolSchema(Protocol):
    name: str
    description: str
    input_schema: dict[str, object]
    side_effect: Literal["read", "write", "external"]
    required_scopes: tuple[str, ...]
    def validate_arguments(self, args: dict[str, object]) -> dict[str, object]: ...
```

#### `VectorStore`

**Purpose.** Expose upsert, similarity search, metadata filter, and delete over embedded documents with per-tenant scoping so retrieval augmentation cannot leak rows across tenants or return deleted content.

**Maturity.** `emerging` — **Contributing agents.** Agent 8 LLM_ERA

**Sources (2):** Anthropic Model Context Protocol (MCP) 1.x specification; OWASP Top 10 for LLM Applications (2023)

**api_signature:**
```python
from __future__ import annotations
from typing import Protocol, Mapping, Sequence

class VectorHit(Protocol):
    doc_id: str
    score: float
    metadata: Mapping[str, str]

class VectorStore(Protocol):
    def upsert(self, tenant_id: str, doc_id: str, embedding: Sequence[float], metadata: Mapping[str, str]) -> None: ...
    def search(self, tenant_id: str, query_embedding: Sequence[float], top_k: int, filter: Mapping[str, str] | None = None) -> tuple[VectorHit, ...]: ...
    def delete(self, tenant_id: str, doc_id: str) -> bool: ...
```

## Namespace `obs`

17 primitives.

| Primitive | Maturity | Agents | Sources | Invariants |
|---|---|---|---|---|
| **AccessLog** | `battle_tested` | #6 | 2 | 5 |
| **CardinalityGuard** | `emerging` | #7 | 3 | 7 |
| **CorrelationContext** | `battle_tested` | #7 | 3 | 6 |
| **CorrelationId** | `battle_tested` | #1 | 3 | 5 |
| **ErrorSink** | `battle_tested` | #7 | 3 | 6 |
| **EventBus** | `battle_tested` | #1 | 2 | 5 |
| **HealthProbe** [co-produced] | `battle_tested` | #1, #4 | 5 | 10 |
| **HistogramBuckets** | `battle_tested` | #7 | 3 | 6 |
| **LifecycleHook** | `battle_tested` | #1 | 3 | 5 |
| **LlmTrace** | `emerging` | #8 | 2 | 5 |
| **MetricMeter** | `battle_tested` | #7 | 3 | 6 |
| **ResourceDescriptor** | `battle_tested` | #7 | 3 | 6 |
| **SamplingPolicy** | `battle_tested` | #7 | 3 | 6 |
| **SemanticAttributes** | `emerging` | #7 | 3 | 6 |
| **StructuredLogger** | `battle_tested` | #7 | 3 | 6 |
| **TelemetryExporter** | `battle_tested` | #7 | 3 | 6 |
| **Tracer** | `battle_tested` | #7 | 3 | 6 |

### Details

#### `AccessLog`

**Purpose.** Records every successful read of classified data with actor, purpose-of-use, and record identifier, distinct from the security audit log.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 6 COMPLIANCE

**Sources (2):** AICPA SOC 2 Trust Services Criteria (2017, 2022 revision); HIPAA Security Rule 45 CFR §§ 164.308-164.312

**api_signature:**
```python
from typing import Protocol
from datetime import datetime

class AccessLog(Protocol):
    def record_read(self, actor: str, record_id: str, data_class: str, purpose_of_use: str, at: datetime) -> None: ...
    def query(self, record_id: str | None = None, actor: str | None = None) -> list[dict]: ...
    def count_by_actor(self, actor: str, since: datetime) -> int: ...
```

#### `CardinalityGuard`

**Purpose.** Bound the unique attribute-value combinations attached to a metric or log stream to prevent label explosion from breaking time-series databases.

**Maturity.** `emerging` — **Contributing agents.** Agent 7 OBSERVABILITY

**Sources (3):** Majors, Fong-Jones, Miranda — Observability Engineering (2022); OpenTelemetry Specification 1.32 — Metrics SDK Views; Prometheus Documentation — Instrumentation (prometheus.io/docs/practices)

**api_signature:**
```python
from typing import Protocol, Mapping

class CardinalityGuard(Protocol):
    def admit(self, metric_name: str, attributes: Mapping[str, str]) -> Mapping[str, str]: ...
    def configure(self, *, per_metric_limit: int, per_key_limit: int, overflow_label: str = 'overflow') -> None: ...
    def stats(self, metric_name: str) -> Mapping[str, int]: ...
```

#### `CorrelationContext`

**Purpose.** Propagate a stable request identifier and optional baggage across threads, async tasks, and network hops so every downstream record can be joined back to the originating request.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 7 OBSERVABILITY

**Sources (3):** Majors, Fong-Jones, Miranda — Observability Engineering (2022); OpenTelemetry Specification 1.32 — Context and Propagation; W3C Baggage Recommendation

**api_signature:**
```python
from contextlib import AbstractContextManager
from typing import Protocol, Mapping

class CorrelationContext(Protocol):
    @property
    def request_id(self) -> str: ...
    @property
    def trace_id(self) -> str | None: ...
    def baggage(self) -> Mapping[str, str]: ...
    def activate(self) -> AbstractContextManager[None]: ...
    @classmethod
    def current(cls) -> 'CorrelationContext': ...
    @classmethod
    def from_headers(cls, headers: Mapping[str, str]) -> 'CorrelationContext': ...
    def to_headers(self) -> Mapping[str, str]: ...
```

#### `CorrelationId`

**Purpose.** Opaque string that travels with a request across services and log lines so a reader can stitch together the work done for one user action.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 1 FRAMEWORKS

**Sources (3):** ASP.NET Core 8.0 — HttpContext.TraceIdentifier; Plug 1.x — Plug.RequestId; Ruby on Rails 7 — CurrentAttributes request_id example

**api_signature:**
```python
from typing import NewType, Protocol

CorrelationId = NewType('CorrelationId', str)

class CorrelationIdProvider(Protocol):
    def current(self) -> CorrelationId: ...
    def generate(self) -> CorrelationId: ...
```

#### `ErrorSink`

**Purpose.** Capture uncaught exceptions with fingerprint grouping, attach current trace and correlation context, apply sampling, and forward to an error-tracking backend.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 7 OBSERVABILITY

**Sources (3):** Google SRE Book — Monitoring Distributed Systems; Majors, Fong-Jones, Miranda — Observability Engineering (2022); OpenTelemetry Specification 1.32 — Exceptions

**api_signature:**
```python
from typing import Protocol, Mapping, Callable

class ErrorSink(Protocol):
    def capture_exception(
        self,
        exc: BaseException,
        *,
        level: str = 'error',
        tags: Mapping[str, str] | None = None,
        extras: Mapping[str, object] | None = None,
    ) -> str: ...
    def capture_message(self, message: str, *, level: str = 'error', tags: Mapping[str, str] | None = None) -> str: ...
    def register_fingerprinter(self, fn: Callable[[BaseException], list[str]]) -> None: ...
    def before_send(self, fn: Callable[[dict], dict | None]) -> None: ...
```

#### `EventBus`

**Purpose.** In-process publish/subscribe point for named framework and application events (e.g. sql.active_record, http.request) with structured payloads.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 1 FRAMEWORKS

**Sources (2):** Ruby on Rails 7 — ActiveSupport::Notifications; Spring Boot 3.x — Application Events and @EventListener

**api_signature:**
```python
from typing import Any, Callable, Mapping, Protocol

Subscriber = Callable[[str, Mapping[str, Any]], None]

class EventBus(Protocol):
    def publish(self, name: str, payload: Mapping[str, Any]) -> None: ...
    def subscribe(self, pattern: str, handler: Subscriber) -> Callable[[], None]: ...
```

#### `HealthProbe` *(co-produced)*

**Purpose.** Small probe that reports UP/DOWN/DEGRADED with optional detail so orchestrators (Kubernetes, load balancers) can route traffic safely.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 1 FRAMEWORKS, Agent 4 RESILIENCY

**Sources (5):** ASP.NET Core 8.0 — Health checks; Google SRE Workbook (Beyer et al., O'Reilly, 2018); Kubernetes documentation, 'Configure Liveness, Readiness and Startup Probes' (kubernetes.io, v1.29); Nygard, Release It! 2nd edition (2018), Pragmatic Bookshelf; Spring Boot 3.x Actuator — HealthIndicator

**api_signatures** (multiple agents contributed — reconcile in audit):
*From Agent 1:*
```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Protocol

class HealthStatus(str, Enum):
    UP = 'up'
    DOWN = 'down'
    DEGRADED = 'degraded'

@dataclass(frozen=True)
class HealthReport:
    status: HealthStatus
    details: Mapping[str, str] = field(default_factory=dict)

class HealthProbe(Protocol):
    name: str
    async def check(self) -> HealthReport: ...
```
*From Agent 4:*
```python
from __future__ import annotations
from typing import Protocol, Literal

Status = Literal['up', 'degraded', 'down']

class HealthProbe(Protocol):
    name: str
    status: Status
    async def liveness(self) -> Status: ...
    async def readiness(self) -> Status: ...
    def register_dependency(self, name: str, check: 'HealthProbe') -> None: ...
```

#### `HistogramBuckets`

**Purpose.** Define explicit latency and size bucket boundaries for histogram instruments so quantile estimation is accurate and comparable across services.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 7 OBSERVABILITY

**Sources (3):** Google SRE Book — Monitoring Distributed Systems; OpenTelemetry Semantic Conventions 1.27 — HTTP Metrics; Prometheus Documentation — Histograms and Summaries (prometheus.io/docs/practices)

**api_signature:**
```python
from dataclasses import dataclass
from typing import Sequence

@dataclass(frozen=True)
class HistogramBuckets:
    name: str
    unit: str
    boundaries: Sequence[float]

    @classmethod
    def latency_ms_default(cls) -> 'HistogramBuckets': ...
    @classmethod
    def payload_bytes_default(cls) -> 'HistogramBuckets': ...
```

#### `LifecycleHook`

**Purpose.** Named callback fired at a defined application phase (starting, ready, stopping) so tools can initialize resources and shut down cleanly.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 1 FRAMEWORKS

**Sources (3):** ASP.NET Core 8.0 — IHostApplicationLifetime; Quarkus 3.x Lifecycle Guide; Spring Boot 3.x Reference — Application Events and Listeners

**api_signature:**
```python
from enum import Enum
from typing import Awaitable, Callable

class LifecyclePhase(str, Enum):
    STARTING = 'starting'
    READY = 'ready'
    STOPPING = 'stopping'
    STOPPED = 'stopped'

LifecycleCallback = Callable[[], Awaitable[None]]

class LifecycleHook:
    def __init__(self, phase: LifecyclePhase, cb: LifecycleCallback) -> None:
        self.phase = phase
        self.cb = cb
```

#### `LlmTrace`

**Purpose.** Emit structured spans for each model call with attributes aligned to OpenTelemetry GenAI semantic conventions so token counts, model identity, and prompt/response linkage land in traces consistently.

**Maturity.** `emerging` — **Contributing agents.** Agent 8 LLM_ERA

**Sources (2):** Langfuse 2.x architecture and tracing model; OpenTelemetry Semantic Conventions for Generative AI (1.27+)

**api_signature:**
```python
from __future__ import annotations
from typing import Protocol, ContextManager

class LlmTrace(Protocol):
    def start(self, operation: str, model_handle: str, prompt_fingerprint: str) -> ContextManager["LlmSpan"]: ...

class LlmSpan(Protocol):
    def set_usage(self, input_tokens: int, output_tokens: int) -> None: ...
    def set_finish_reason(self, reason: str) -> None: ...
    def record_error(self, code: str, message: str) -> None: ...
```

#### `MetricMeter`

**Purpose.** Record numeric measurements through four instrument shapes — counter, up-down counter, histogram, asynchronous gauge — under OpenTelemetry metric semantics.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 7 OBSERVABILITY

**Sources (3):** OpenTelemetry Semantic Conventions 1.27 — Metric Naming; OpenTelemetry Specification 1.32 — Metrics API; Prometheus Documentation — Histograms and Summaries (prometheus.io/docs/practices)

**api_signature:**
```python
from typing import Protocol, Mapping, Callable, Sequence

class Counter(Protocol):
    def add(self, value: int | float, attributes: Mapping[str, str] | None = None) -> None: ...

class UpDownCounter(Protocol):
    def add(self, value: int | float, attributes: Mapping[str, str] | None = None) -> None: ...

class Histogram(Protocol):
    def record(self, value: int | float, attributes: Mapping[str, str] | None = None) -> None: ...

class MetricMeter(Protocol):
    def counter(self, name: str, *, unit: str, description: str) -> Counter: ...
    def up_down_counter(self, name: str, *, unit: str, description: str) -> UpDownCounter: ...
    def histogram(self, name: str, *, unit: str, description: str, boundaries: Sequence[float] | None = None) -> Histogram: ...
    def observable_gauge(self, name: str, callback: Callable[[], float], *, unit: str, description: str) -> None: ...
```

#### `ResourceDescriptor`

**Purpose.** Describe the entity producing telemetry — service, version, deployment environment, instance id — and attach that identity to every span, metric, and log record.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 7 OBSERVABILITY

**Sources (3):** Google SRE Book — Monitoring Distributed Systems; OpenTelemetry Semantic Conventions 1.27 — Resource; OpenTelemetry Specification 1.32 — Resource SDK

**api_signature:**
```python
from dataclasses import dataclass
from typing import Mapping

@dataclass(frozen=True)
class ResourceDescriptor:
    service_name: str
    service_namespace: str | None
    service_version: str
    service_instance_id: str
    deployment_environment: str
    attributes: Mapping[str, str]

    def merged_with(self, overrides: Mapping[str, str]) -> 'ResourceDescriptor': ...
    def to_attributes(self) -> Mapping[str, str]: ...
```

#### `SamplingPolicy`

**Purpose.** Decide whether a given trace or span is retained, combining head-based (at span start) and tail-based (post hoc) rules and honoring the parent sampling decision.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 7 OBSERVABILITY

**Sources (3):** Google SRE Book — Monitoring Distributed Systems; Majors, Fong-Jones, Miranda — Observability Engineering (2022); OpenTelemetry Specification 1.32 — Sampling

**api_signature:**
```python
from dataclasses import dataclass
from typing import Protocol, Mapping, Sequence

@dataclass(frozen=True)
class SamplingDecision:
    sampled: bool
    attributes: Mapping[str, str]
    trace_state: str | None

class SamplingPolicy(Protocol):
    def should_sample(
        self,
        *,
        parent_context: object | None,
        trace_id: str,
        name: str,
        kind: str,
        attributes: Mapping[str, object],
        links: Sequence[object],
    ) -> SamplingDecision: ...
    def description(self) -> str: ...
```

#### `SemanticAttributes`

**Purpose.** Expose the OpenTelemetry semantic-convention attribute keys as typed constants and enforce that primitives populate required keys for HTTP, database, messaging, and GenAI operations.

**Maturity.** `emerging` — **Contributing agents.** Agent 7 OBSERVABILITY

**Sources (3):** OpenTelemetry Semantic Conventions 1.27 — GenAI; OpenTelemetry Semantic Conventions 1.27 — General; OpenTelemetry Semantic Conventions 1.27 — HTTP

**api_signature:**
```python
from typing import Final

class SemanticAttributes:
    SERVICE_NAME: Final[str] = 'service.name'
    SERVICE_VERSION: Final[str] = 'service.version'
    DEPLOYMENT_ENVIRONMENT: Final[str] = 'deployment.environment.name'
    HTTP_REQUEST_METHOD: Final[str] = 'http.request.method'
    HTTP_ROUTE: Final[str] = 'http.route'
    HTTP_RESPONSE_STATUS_CODE: Final[str] = 'http.response.status_code'
    DB_SYSTEM: Final[str] = 'db.system'
    DB_STATEMENT: Final[str] = 'db.statement'
    MESSAGING_SYSTEM: Final[str] = 'messaging.system'
    MESSAGING_DESTINATION_NAME: Final[str] = 'messaging.destination.name'
    GEN_AI_SYSTEM: Final[str] = 'gen_ai.system'
    GEN_AI_REQUEST_MODEL: Final[str] = 'gen_ai.request.model'
    GEN_AI_USAGE_INPUT_TOKENS: Final[str] = 'gen_ai.usage.input_tokens'
    GEN_AI_USAGE_OUTPUT_TOKENS: Final[str] = 'gen_ai.usage.output_tokens'
```

#### `StructuredLogger`

**Purpose.** Emit machine-parseable key/value log records with a fixed level taxonomy, attached trace and span identifiers, and no positional string formatting.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 7 OBSERVABILITY

**Sources (3):** Google SRE Book — Monitoring Distributed Systems; Majors, Fong-Jones, Miranda — Observability Engineering (2022); OpenTelemetry Specification 1.32 — Logs Data Model

**api_signature:**
```python
from typing import Protocol, Mapping, Any

class StructuredLogger(Protocol):
    def debug(self, event: str, **fields: Any) -> None: ...
    def info(self, event: str, **fields: Any) -> None: ...
    def warn(self, event: str, **fields: Any) -> None: ...
    def error(self, event: str, *, exc: BaseException | None = None, **fields: Any) -> None: ...
    def bind(self, **fields: Any) -> 'StructuredLogger': ...
    def with_context(self, context: Mapping[str, Any]) -> 'StructuredLogger': ...
```

#### `TelemetryExporter`

**Purpose.** Serialize batched spans, metrics, or log records into an OTLP-compatible envelope and deliver them to a configured endpoint with retry and backpressure.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 7 OBSERVABILITY

**Sources (3):** Google SRE Book — Monitoring Distributed Systems; OpenTelemetry Specification 1.32 — OTLP Protocol; OpenTelemetry Specification 1.32 — SDK Exporters

**api_signature:**
```python
from enum import Enum
from typing import Protocol, Sequence

class Signal(str, Enum):
    TRACES = 'traces'
    METRICS = 'metrics'
    LOGS = 'logs'

class ExportResult(str, Enum):
    SUCCESS = 'success'
    FAILURE = 'failure'
    TIMEOUT = 'timeout'

class TelemetryExporter(Protocol):
    signal: Signal

    def export(self, batch: Sequence[object], *, timeout_s: float) -> ExportResult: ...
    def force_flush(self, *, timeout_s: float) -> bool: ...
    def shutdown(self, *, timeout_s: float) -> bool: ...
```

#### `Tracer`

**Purpose.** Create spans that represent a unit of work, attach attributes and events, link related spans, and propagate context across process and network boundaries.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 7 OBSERVABILITY

**Sources (3):** Majors, Fong-Jones, Miranda — Observability Engineering (2022); OpenTelemetry Specification 1.32 — Trace API; W3C Trace Context Recommendation Level 1

**api_signature:**
```python
from contextlib import AbstractContextManager
from typing import Protocol, Mapping, Sequence

class Span(Protocol):
    def set_attribute(self, key: str, value: str | int | float | bool) -> None: ...
    def add_event(self, name: str, attributes: Mapping[str, object] | None = None) -> None: ...
    def record_exception(self, exc: BaseException) -> None: ...
    def set_status(self, code: str, description: str | None = None) -> None: ...

class Tracer(Protocol):
    def start_as_current_span(
        self,
        name: str,
        *,
        kind: str = 'INTERNAL',
        attributes: Mapping[str, object] | None = None,
        links: Sequence[object] = (),
    ) -> AbstractContextManager[Span]: ...
    def inject(self, carrier: dict[str, str]) -> None: ...
    def extract(self, carrier: Mapping[str, str]) -> object: ...
```

## Namespace `policy`

4 primitives.

| Primitive | Maturity | Agents | Sources | Invariants |
|---|---|---|---|---|
| **CorsPolicy** | `battle_tested` | #5 | 2 | 5 |
| **DataResidencyPolicy** | `emerging` | #6 | 2 | 5 |
| **EncryptionPolicy** | `battle_tested` | #6 | 3 | 5 |
| **KeyRotationSchedule** | `battle_tested` | #6 | 2 | 5 |

### Details

#### `CorsPolicy`

**Purpose.** Evaluate cross-origin preflight and simple-request allowance against a closed list of origins, methods, headers, and credential mode without reflecting arbitrary Origin values.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 5 SECURITY

**Sources (2):** OWASP ASVS 4.0.3; OWASP Top 10 2021

**api_signature:**
```python
from dataclasses import dataclass
from typing import Protocol

@dataclass(frozen=True)
class CorsDecision:
    allow_origin: str | None
    allow_methods: tuple[str, ...]
    allow_headers: tuple[str, ...]
    allow_credentials: bool
    max_age_seconds: int

class CorsPolicy(Protocol):
    def evaluate(self, origin: str, method: str, requested_headers: tuple[str, ...]) -> CorsDecision: ...
```

#### `DataResidencyPolicy`

**Purpose.** Binds a data class to a set of permitted storage and processing regions, refusing writes or cross-border transfers outside the allow-list.

**Maturity.** `emerging` — **Contributing agents.** Agent 6 COMPLIANCE

**Sources (2):** EU GDPR Regulation 2016/679 Articles 5, 6, 7, 15, 17, 30, 32; PCI-DSS v4.0

**api_signature:**
```python
from dataclasses import dataclass
from typing import Protocol

@dataclass(frozen=True)
class DataResidencyPolicy:
    data_class: str
    allowed_regions: tuple[str, ...]
    transfer_mechanism: str  # e.g. 'SCC_2021/914', 'adequacy_decision', 'intra_group_BCR'

class ResidencyEnforcer(Protocol):
    def bind(self, policy: DataResidencyPolicy) -> None: ...
    def check_write(self, data_class: str, region: str) -> None: ...
    def check_transfer(self, data_class: str, source: str, destination: str) -> None: ...
```

#### `EncryptionPolicy`

**Purpose.** Declares cipher, key provider, and rotation cadence for a data class at rest and in transit, and rejects storage without a bound policy.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 6 COMPLIANCE

**Sources (3):** HIPAA Security Rule 45 CFR §§ 164.308-164.312; NIST SP 800-53 revision 5; PCI-DSS v4.0

**api_signature:**
```python
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

@dataclass(frozen=True)
class EncryptionPolicy:
    data_class: str
    at_rest_cipher: str  # e.g. 'AES-256-GCM'
    in_transit_min_tls: str  # e.g. 'TLS1.2'
    key_provider: str  # kms uri
    rotation: timedelta

class EncryptionRegistry(Protocol):
    def bind(self, policy: EncryptionPolicy) -> None: ...
    def resolve(self, data_class: str) -> EncryptionPolicy: ...
    def require_tls(self, endpoint: str) -> None: ...
```

#### `KeyRotationSchedule`

**Purpose.** Drives rotation of data-encryption keys on a fixed cadence with overlap window, and blocks new writes with a key past its cutover.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 6 COMPLIANCE

**Sources (2):** NIST SP 800-53 revision 5; PCI-DSS v4.0

**api_signature:**
```python
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

@dataclass(frozen=True)
class KeyRotationSchedule:
    key_alias: str
    cadence: timedelta
    overlap: timedelta
    next_rotation_at: datetime

class KeyRotator(Protocol):
    def schedule(self, sched: KeyRotationSchedule) -> None: ...
    def rotate_now(self, key_alias: str) -> str: ...
    def active_key(self, key_alias: str, at: datetime) -> str: ...
```

## Namespace `resiliency`

10 primitives.

| Primitive | Maturity | Agents | Sources | Invariants |
|---|---|---|---|---|
| **BackpressureSignal** | `emerging` | #4 | 3 | 5 |
| **Bulkhead** | `battle_tested` | #4 | 2 | 5 |
| **ChaosInjector** | `emerging` | #4 | 3 | 5 |
| **CircuitBreaker** | `battle_tested` | #4 | 3 | 6 |
| **FallbackChain** | `battle_tested` | #4 | 3 | 5 |
| **LoadShedder** | `battle_tested` | #4 | 2 | 5 |
| **OutlierEjection** | `battle_tested` | #4 | 2 | 5 |
| **RateLimiter** [co-produced] | `battle_tested` | #4, #5 | 6 | 10 |
| **RetryPolicy** | `battle_tested` | #4 | 3 | 5 |
| **TimeoutBudget** | `battle_tested` | #4 | 3 | 5 |

### Details

#### `BackpressureSignal`

**Purpose.** Carry producer-visible pressure information from a consumer or queue so upstream components can slow down rather than fill unbounded buffers.

**Maturity.** `emerging` — **Contributing agents.** Agent 4 RESILIENCY

**Sources (3):** Google SRE Workbook (Beyer et al., O'Reilly, 2018); Nygard, Release It! 2nd edition (2018), Pragmatic Bookshelf; Reactive Streams Specification 1.0.4

**api_signature:**
```python
from __future__ import annotations
from typing import Protocol, Literal

Level = Literal['nominal', 'elevated', 'saturated']

class BackpressureSignal(Protocol):
    level: Level
    lag_ms: int
    queue_fill_ratio: float
    def acquire(self, bytes_or_items: int, timeout_ms: int) -> bool: ...
    def report(self, level: Level, lag_ms: int, queue_fill_ratio: float) -> None: ...
```

#### `Bulkhead`

**Purpose.** Partition concurrency so that saturation or stalls inside one dependency cannot exhaust the resources needed by unrelated dependencies.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 4 RESILIENCY

**Sources (2):** Nygard, Release It! 2nd edition (2018), Pragmatic Bookshelf; resilience4j 2.2.0 reference documentation

**api_signature:**
```python
from __future__ import annotations
from typing import Protocol, Awaitable, Callable, TypeVar, Literal

T = TypeVar('T')
Kind = Literal['semaphore', 'thread_pool']

class Bulkhead(Protocol):
    name: str
    kind: Kind
    max_concurrent_calls: int
    max_wait_duration_ms: int
    async def submit(self, fn: Callable[..., Awaitable[T]], /, *args, **kwargs) -> T: ...
    def available_permits(self) -> int: ...
```

#### `ChaosInjector`

**Purpose.** Deliberately introduce latency, errors or partial partitions in controlled scopes so resiliency primitives are exercised in production-like conditions.

**Maturity.** `emerging` — **Contributing agents.** Agent 4 RESILIENCY

**Sources (3):** Basiri et al., 'Chaos Engineering' IEEE Software (2016); Envoy proxy documentation, HTTP fault injection filter; Nygard, Release It! 2nd edition (2018), Pragmatic Bookshelf

**api_signature:**
```python
from __future__ import annotations
from typing import Protocol, Literal, Awaitable, Callable, TypeVar

T = TypeVar('T')
Fault = Literal['latency', 'error', 'abort', 'partition']

class ChaosInjector(Protocol):
    name: str
    enabled: bool
    blast_radius_percent: float
    async def apply(self, fault: Fault, fn: Callable[..., Awaitable[T]], /, *args, **kwargs) -> T: ...
    def arm(self, fault: Fault, rate: float, scope: str) -> None: ...
    def disarm(self, fault: Fault) -> None: ...
```

#### `CircuitBreaker`

**Purpose.** Short-circuit calls to a failing dependency by transitioning between closed, open, and half-open states driven by a rolling failure metric.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 4 RESILIENCY

**Sources (3):** Netflix Tech Blog, 'Making the Netflix API More Resilient' (Ben Christensen, 2011); Nygard, Release It! 2nd edition (2018), Pragmatic Bookshelf; resilience4j 2.2.0 reference documentation

**api_signature:**
```python
from __future__ import annotations
from typing import Protocol, Awaitable, Callable, TypeVar, Literal

T = TypeVar('T')
State = Literal['closed', 'open', 'half_open']

class CircuitBreaker(Protocol):
    name: str
    state: State
    async def call(self, fn: Callable[..., Awaitable[T]], /, *args, **kwargs) -> T: ...
    def on_success(self, elapsed_ms: float) -> None: ...
    def on_failure(self, exc: BaseException, elapsed_ms: float) -> None: ...
    def force_open(self, reason: str) -> None: ...
    def allow_probe(self) -> bool: ...
```

#### `FallbackChain`

**Purpose.** Deliver a typed degraded result when the primary path fails or is shed, via an ordered list of fallbacks that preserve the response contract.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 4 RESILIENCY

**Sources (3):** Netflix Hystrix wiki archive (github.com/Netflix/Hystrix, 2018 retirement notice); Nygard, Release It! 2nd edition (2018), Pragmatic Bookshelf; resilience4j 2.2.0 reference documentation

**api_signature:**
```python
from __future__ import annotations
from typing import Protocol, Awaitable, Callable, TypeVar, Sequence

T = TypeVar('T')

class FallbackChain(Protocol[T]):
    steps: Sequence[Callable[..., Awaitable[T]]]
    async def execute(self, *args, **kwargs) -> T: ...
    def on_degraded(self, step_name: str, exc: BaseException) -> None: ...
```

#### `LoadShedder`

**Purpose.** Drop or reject low-priority work when the server enters an overload regime so that high-priority traffic continues to meet its SLA.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 4 RESILIENCY

**Sources (2):** Google SRE Book (Beyer et al., O'Reilly, 2016); Google SRE Workbook (Beyer et al., O'Reilly, 2018)

**api_signature:**
```python
from __future__ import annotations
from typing import Protocol, Literal

Priority = Literal['critical', 'normal', 'sheddable_plus', 'sheddable']

class LoadShedder(Protocol):
    def admit(self, priority: Priority, queue_depth: int, cpu_load_ewma: float) -> bool: ...
    def current_cutoff(self) -> Priority: ...
    def shed_rate(self) -> float: ...
```

#### `OutlierEjection`

**Purpose.** Remove a backend instance from the load-balancing pool when its error rate or latency statistics exceed the cluster baseline and reinstate it after a cooldown.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 4 RESILIENCY

**Sources (2):** Envoy proxy documentation, outlier detection; Google SRE Book (Beyer et al., O'Reilly, 2016)

**api_signature:**
```python
from __future__ import annotations
from typing import Protocol

class OutlierEjection(Protocol):
    consecutive_5xx: int
    success_rate_stdev_factor: float
    base_ejection_time_ms: int
    max_ejection_percent: int
    def record(self, host_id: str, ok: bool, elapsed_ms: float) -> None: ...
    def is_ejected(self, host_id: str) -> bool: ...
    def healthy_hosts(self) -> list[str]: ...
```

#### `RateLimiter` *(co-produced)*

**Purpose.** Enforce a maximum rate of admitted operations over a rolling window, with optional waiting semantics, applied per caller, tenant or resource.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 4 RESILIENCY, Agent 5 SECURITY

**Sources (6):** Envoy proxy documentation, local and global rate limiting; Google SRE Workbook (Beyer et al., O'Reilly, 2018); NIST SP 800-63B; Nygard, Release It! 2nd edition (2018), Pragmatic Bookshelf; OWASP ASVS 4.0.3; OWASP Top 10 2021

**api_signatures** (multiple agents contributed — reconcile in audit):
*From Agent 4:*
```python
from __future__ import annotations
from typing import Protocol, Literal

Algorithm = Literal['token_bucket', 'leaky_bucket', 'sliding_window']

class RateLimiter(Protocol):
    algorithm: Algorithm
    rate_per_second: float
    burst: int
    async def acquire(self, key: str, cost: int = 1, wait_ms: int = 0) -> bool: ...
    def try_acquire(self, key: str, cost: int = 1) -> bool: ...
    def current_rate(self, key: str) -> float: ...
```
*From Agent 5:*
```python
from dataclasses import dataclass
from typing import Protocol

@dataclass(frozen=True)
class RateDecision:
    allowed: bool
    retry_after_seconds: int
    remaining: int

class RateLimiter(Protocol):
    def check(self, key: str, cost: int = 1) -> RateDecision: ...
    def reset(self, key: str) -> None: ...
```

#### `RetryPolicy`

**Purpose.** Describe under which conditions a failed call may be retried, bounded by max attempts, backoff with jitter, a retry budget and an idempotency requirement.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 4 RESILIENCY

**Sources (3):** AWS Architecture Blog, 'Exponential Backoff and Jitter' (Marc Brooker, 2015); Envoy proxy documentation, retry policy; Google SRE Workbook (Beyer et al., O'Reilly, 2018)

**api_signature:**
```python
from __future__ import annotations
from typing import Protocol, Callable, Awaitable, TypeVar

T = TypeVar('T')

class RetryPolicy(Protocol):
    max_attempts: int
    initial_interval_ms: int
    multiplier: float
    max_interval_ms: int
    jitter: float
    budget_ratio: float
    requires_idempotency: bool
    def should_retry(self, attempt: int, exc: BaseException) -> bool: ...
    def next_delay_ms(self, attempt: int) -> int: ...
    async def execute(self, fn: Callable[[], Awaitable[T]]) -> T: ...
```

#### `TimeoutBudget`

**Purpose.** Attach a monotonic deadline to an inbound request and propagate the remaining budget to every downstream call so no call outlives its originating request.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 4 RESILIENCY

**Sources (3):** Envoy proxy documentation, HTTP connection manager; Google SRE Workbook (Beyer et al., O'Reilly, 2018); Nygard, Release It! 2nd edition (2018), Pragmatic Bookshelf

**api_signature:**
```python
from __future__ import annotations
from typing import Protocol
from contextvars import ContextVar

class TimeoutBudget(Protocol):
    deadline_ns: int
    origin: str
    def remaining_ms(self) -> int: ...
    def for_call(self, max_ms: int) -> int: ...
    def expired(self) -> bool: ...

CURRENT_BUDGET: ContextVar[TimeoutBudget | None] = ContextVar('current_budget', default=None)
```

## Namespace `security`

8 primitives.

| Primitive | Maturity | Agents | Sources | Invariants |
|---|---|---|---|---|
| **ContentSecurityPolicy** | `battle_tested` | #5 | 2 | 6 |
| **CryptoEnvelope** | `battle_tested` | #5 | 2 | 6 |
| **CsrfGuard** | `battle_tested` | #5 | 2 | 5 |
| **InputValidator** | `battle_tested` | #5 | 2 | 5 |
| **OutputEncoder** | `battle_tested` | #5 | 2 | 5 |
| **PasswordHasher** | `battle_tested` | #5 | 3 | 6 |
| **SecretsVault** | `battle_tested` | #5 | 2 | 5 |
| **SignatureVerifier** | `battle_tested` | #5 | 2 | 5 |

### Details

#### `ContentSecurityPolicy`

**Purpose.** Compose, serialize, and enforce a Content Security Policy header that constrains script, style, frame, and connection origins with strict-dynamic and nonce-based script allowance.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 5 SECURITY

**Sources (2):** OWASP ASVS 4.0.3; OWASP Top 10 2021

**api_signature:**
```python
from dataclasses import dataclass
from typing import Protocol

@dataclass(frozen=True)
class Directive:
    name: str
    sources: tuple[str, ...]

class ContentSecurityPolicy(Protocol):
    def with_directive(self, directive: Directive) -> "ContentSecurityPolicy": ...
    def with_nonce(self, nonce: str) -> "ContentSecurityPolicy": ...
    def render_header(self) -> tuple[str, str]: ...
```

#### `CryptoEnvelope`

**Purpose.** Encrypt and decrypt payloads with authenticated encryption, key-id-tagged ciphertext, and deterministic header framing that enables key rotation without re-encryption on read.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 5 SECURITY

**Sources (2):** OWASP ASVS 4.0.3; OWASP Top 10 2021

**api_signature:**
```python
from dataclasses import dataclass
from typing import Protocol

@dataclass(frozen=True)
class Envelope:
    key_id: str
    nonce: bytes
    ciphertext: bytes
    aad: bytes

class CryptoEnvelope(Protocol):
    def seal(self, plaintext: bytes, aad: bytes) -> Envelope: ...
    def open(self, envelope: Envelope, aad: bytes) -> bytes: ...
```

#### `CsrfGuard`

**Purpose.** Bind state-changing HTTP requests to the authenticated session through per-session tokens validated against a matching header or form field.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 5 SECURITY

**Sources (2):** OWASP ASVS 4.0.3; OWASP Top 10 2021

**api_signature:**
```python
from typing import Protocol

class CsrfGuard(Protocol):
    def issue(self, session_id: str) -> str: ...
    def verify(self, session_id: str, submitted_token: str) -> None: ...
```

#### `InputValidator`

**Purpose.** Parse and constrain inbound payloads against a declared schema with typed coercion, length and range bounds, and rejection of unknown fields.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 5 SECURITY

**Sources (2):** OWASP ASVS 4.0.3; OWASP Top 10 2021

**api_signature:**
```python
from typing import Protocol, TypeVar

T = TypeVar("T")

class InputValidator(Protocol):
    def parse(self, raw: object, schema: type[T]) -> T: ...
```

#### `OutputEncoder`

**Purpose.** Encode untrusted values for a named sink (HTML text, HTML attribute, JavaScript string, URL path, URL query, CSS value) using sink-specific escaping rules.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 5 SECURITY

**Sources (2):** OWASP ASVS 4.0.3; OWASP Top 10 2021

**api_signature:**
```python
from enum import Enum
from typing import Protocol

class Sink(str, Enum):
    HTML_TEXT = "html_text"
    HTML_ATTRIBUTE = "html_attribute"
    JS_STRING = "js_string"
    URL_PATH = "url_path"
    URL_QUERY = "url_query"
    CSS_VALUE = "css_value"

class OutputEncoder(Protocol):
    def encode(self, value: str, sink: Sink) -> str: ...
```

#### `PasswordHasher`

**Purpose.** Derive a verifier from a user-supplied secret using a memory-hard KDF with per-credential salt, tunable cost, and constant-time comparison.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 5 SECURITY

**Sources (3):** NIST SP 800-63B; OWASP ASVS 4.0.3; OWASP Top 10 2021

**api_signature:**
```python
from typing import Protocol

class PasswordHasher(Protocol):
    def hash(self, plaintext: str) -> str: ...
    def verify(self, plaintext: str, stored: str) -> bool: ...
    def needs_rehash(self, stored: str) -> bool: ...
```

#### `SecretsVault`

**Purpose.** Fetch, cache, rotate, and audit application secrets through a named-secret interface backed by an external key management or secrets service.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 5 SECURITY

**Sources (2):** NIST SP 800-63B; OWASP ASVS 4.0.3

**api_signature:**
```python
from dataclasses import dataclass
from typing import Protocol

@dataclass(frozen=True)
class SecretVersion:
    name: str
    version: int
    material: bytes
    not_after: int | None

class SecretsVault(Protocol):
    def get(self, name: str) -> SecretVersion: ...
    def rotate(self, name: str) -> SecretVersion: ...
    def invalidate(self, name: str) -> None: ...
```

#### `SignatureVerifier`

**Purpose.** Produce and verify detached digital signatures with key-id selection, typed message framing, and refusal of weak or unannounced algorithms.

**Maturity.** `battle_tested` — **Contributing agents.** Agent 5 SECURITY

**Sources (2):** OWASP ASVS 4.0.3; OWASP Top 10 2021

**api_signature:**
```python
from typing import Protocol

class SignatureVerifier(Protocol):
    def sign(self, message: bytes, key_id: str) -> bytes: ...
    def verify(self, message: bytes, signature: bytes, key_id: str) -> None: ...
```

---

## Collisions handled

- **`HealthProbe`** — co-produced by Agent 1 (FRAMEWORKS), Agent 4 (RESILIENCY). 5 combined sources, 10 combined invariants.
- **`RateLimiter`** — co-produced by Agent 4 (RESILIENCY), Agent 5 (SECURITY). 6 combined sources, 10 combined invariants.

## Provenance matrix

| Agent | Codename | Primitives contributed | Unique sources |
|---|---|---|---|
| 1 | FRAMEWORKS | 14 | 37 |
| 2 | DISTRIBUTED | 16 | 16 |
| 3 | PATTERNS | 20 | 7 |
| 4 | RESILIENCY | 12 | 15 |
| 5 | SECURITY | 15 | 9 |
| 6 | COMPLIANCE | 12 | 5 |
| 7 | OBSERVABILITY | 12 | 23 |
| 8 | LLM_ERA | 14 | 9 |

