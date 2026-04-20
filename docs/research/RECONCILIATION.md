# PARTIAL Reconciliation

> The keyword audit classified 10 primitives as PARTIAL — referenced in SKILL-001
> but with thin coverage (1–2 file hits). This document inspects the evidence
> for each and lands a decision: **PROMOTE** (add a first-class primitive),
> **RENAME** (align the existing surface to the venous-system name), or
> **DEPRECATE** (current impl is out of scope or superseded).
>
> Every decision carries the evidence (which SKILL-001 files hit), the
> rationale, and the action to take during the SkillEngine build-out.

## Decision legend

- **PROMOTE** — concept is touched in tests / specs / examples but no first-class primitive exists; create one.
- **RENAME** — SKILL-001 has a working tool / generator but uses a different name; align names and publish the canonical Protocol.
- **DEPRECATE** — the SKILL-001 hit is irrelevant (different concept sharing the word); no action beyond noting.

## Summary

| Primitive | Namespace | Decision | SKILL-001 home after action |
|---|---|---|---|
| `AuditEvent` | `compliance` | **PROMOTE** | `core/audit.py` — typed record that `add_audit_log` emits |
| `RetentionPolicy` | `compliance` | **PROMOTE** | new primitive; `add_compliance_engine` consumes it |
| `EventStream` | `events` | **PROMOTE** | new primitive; `add_event_sourcing` builds on it |
| `SagaOrchestrator` | `events` | **RENAME** | `add_saga` exposes canonical `SagaOrchestrator` class |
| `ModelRouter` | `llm` | **PROMOTE** | new primitive (current "router" hit is unrelated API routing) |
| `ResponseCache` | `llm` | **PROMOTE** | distinct from HTTP `add_request_fingerprint`; LLM-specific cache |
| `EventBus` | `obs` | **PROMOTE** | new primitive; tools emit through it (obsoletes ad-hoc callbacks) |
| `ChaosInjector` | `resiliency` | **RENAME** | `add_chaos_testing` exposes canonical `ChaosInjector` class |
| `ContentSecurityPolicy` | `security` | **PROMOTE** | extract CSP from `security_headers.py` into typed primitive |
| `SignatureVerifier` | `security` | **RENAME** | `add_request_signing` exposes canonical `SignatureVerifier` class |

**Totals:** 7 PROMOTE · 3 RENAME · 0 DEPRECATE.

---

## Per-primitive decisions

### `AuditEvent` — `compliance` — **PROMOTE**

**Evidence.** Single hit in `docs/examples/saas_b2b.py` (illustrative use in a tutorial). No primitive class. SKILL-001's `add_audit_log` tool emits audit rows but not as a typed `AuditEvent`.

**Decision.** Add `AuditEvent` as a canonical record primitive in `core/audit.py`; rewire `add_audit_log` so its inserts go through `AuditEvent` validation (tamper-evident hash chain, actor/subject/action shape).

**Impact.** Every compliance-heavy tool gains a typed audit shape instead of raw dict inserts.

---

### `RetentionPolicy` — `compliance` — **PROMOTE**

**Evidence.** Only mentioned in `specs/TOOL-113-add_compliance_engine.md` (planning doc). No implementation.

**Decision.** Promote to first-class primitive: declarative class-to-lifetime binding with enforced scheduled purge. `add_compliance_engine` becomes the consumer (composes multiple `RetentionPolicy` instances).

**Impact.** GDPR Article 5(1)(e) + HIPAA §164.316(b)(2) retention becomes default-on configuration, not case-by-case code.

---

### `EventStream` — `events` — **PROMOTE**

**Evidence.** 2 snake hits: `adapt/extend/realtime/test_add_sse.py` (unrelated streaming) and `specs/TOOL-079-add_event_sourcing.md` (related, but as a concept, not a primitive).

**Decision.** Promote `EventStream` as an ordered, append-only, partitioned, replayable log primitive. `add_event_sourcing` becomes the consumer.

**Impact.** Event-sourced aggregates share one stream abstraction across tools instead of each rolling its own append logic.

---

### `SagaOrchestrator` — `events` — **RENAME**

**Evidence.** SKILL-001 already has `adapt/extend/infrastructure/add_saga.py` (implementation) plus benchmark use. The name in the current surface is ad-hoc (`Saga`, helpers scattered).

**Decision.** Rename the public surface of `add_saga` to expose a canonical `SagaOrchestrator` class matching the venous-system Protocol (driver + compensations + idempotency key). Keep backward-compat alias for 1 release.

**Impact.** Composition with `Outbox`, `IdempotentConsumer`, and `TransactionalBatch` becomes typed, not duck-typed.

---

### `ModelRouter` — `llm` — **PROMOTE**

**Evidence.** Single hit is `adapt/extend/api_design/test_add_api_versioning.py` — unrelated ("router" in HTTP-routing sense, not LLM).

**Decision.** Promote `ModelRouter` as a new LLM primitive (cheap-vs-expensive policy, fallback chain, budget cap). SKILL-001 currently has ML serving tools (`add_ml_model_server`) but no routing layer.

**Impact.** Apps calling multiple LLMs get a single policy layer; cost and fallback stop being per-caller concerns.

---

### `ResponseCache` — `llm` — **PROMOTE**

**Evidence.** 2 snake hits in `add_request_fingerprint` tool + spec — the concept is HTTP request fingerprint caching, not LLM response cache. Different layer.

**Decision.** Promote `ResponseCache` as an LLM-specific primitive with exact (prompt hash) + semantic (embedding distance) variants. Distinct from the HTTP cache.

**Impact.** LLM callers get retry-safe idempotency and cost savings without reimplementing semantic matching per tool.

---

### `EventBus` — `obs` — **PROMOTE**

**Evidence.** 2 snake hits in planning specs only (`TOOL-045-extract_service`, `TOOL-098-add_retry_budget`). No implementation.

**Decision.** Promote as an in-process publish/subscribe primitive for framework-level events (e.g. `db.query.executed`, `circuit_breaker.opened`). Tools emit through it; observability subscribers hook in without touching tool code.

**Impact.** Observability stops being wired per-tool; `CorrelationId` and `StructuredLogger` subscribe once.

---

### `ChaosInjector` — `resiliency` — **RENAME**

**Evidence.** SKILL-001 has `adapt/extend/infrastructure/add_chaos_testing.py` + spec. Concept is implemented but under a different public shape.

**Decision.** Rename the public class exported by `add_chaos_testing` to `ChaosInjector` matching the venous-system Protocol (typed scope, deterministic seed, prod guardrail). Keep alias for one release.

**Impact.** Contracts-based composition with `CircuitBreaker` and `RetryPolicy` for end-to-end fault-injection stories.

---

### `ContentSecurityPolicy` — `security` — **PROMOTE**

**Evidence.** Single hit in `generators/middleware/security_headers.py` — CSP shipped as a header string, not as a typed policy.

**Decision.** Promote to first-class `ContentSecurityPolicy` primitive: compose directives as typed fields, serialize to header, enforce reporting-only / enforce split. `security_headers` generator consumes it.

**Impact.** Per-app CSP tightening becomes structured config instead of fragile header concatenation.

---

### `SignatureVerifier` — `security` — **RENAME**

**Evidence.** Single hit in `adapt/extend/auth_access/add_request_signing.py` — implementation exists under a local name.

**Decision.** Rename the exported surface to `SignatureVerifier` matching the venous-system contract (detached sig, key-id resolution, replay protection via nonce window). Keep alias for one release.

**Impact.** Webhook verification, JWT key-id flows, and request signing share one primitive instead of three look-alikes.

---

## Follow-up actions (for the SkillEngine build-out)

1. **All 7 PROMOTE items** become new entries in the SkillKit runtime core, under the namespace directories implied (`core/audit.py`, `core/compliance.py`, `core/events.py`, `core/llm.py`, `core/security.py`).
2. **All 3 RENAME items** get a one-release deprecation shim (`OldName = NewName` + `warnings.warn`) so existing consumers keep working.
3. **Update `VENOUS_SYSTEM_CATALOG.md`** — move these 10 primitives from "PARTIAL in SKILL-001" to "CANONICAL, to be implemented" status.
4. **Tests** — each PROMOTE/RENAME ships with the `consumption_example` from its PrimitiveSpec as a sanity test.
