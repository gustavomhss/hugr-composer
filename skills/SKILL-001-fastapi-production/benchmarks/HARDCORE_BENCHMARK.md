# HARDCORE BENCHMARK — "FinHealth" Multi-Tenant Health-Finance Platform

> **Difficulty**: Extreme. Designed to be impossible for naked LLMs to get right on the first try.
> **Time limit**: 30 minutes (skill) / 60 minutes (naked LLM)
> **Scoring**: 100 mechanical checks, each pass/fail. No partial credit.

---

## The Scenario

**FinHealth** is a B2B SaaS platform where healthcare providers manage patient billing, insurance claims, and payment processing. It must comply with HIPAA (health data), PCI-DSS (payment data), and SOC2 (audit trail).

### Why this is hard

1. **Multi-tenancy + HIPAA**: patient data MUST be tenant-isolated at DB level (not just app level). A query bug leaks one hospital's patient records to another.
2. **Payment + PCI**: Stripe webhook receiver must verify HMAC signatures, never log card data, and handle idempotent retries.
3. **Audit + SOC2**: every data mutation must be recorded with actor, timestamp, old/new values, and a tamper-evident hash chain. Audit logs must be immutable.
4. **Event-driven billing**: when an insurance claim status changes, downstream systems must be notified reliably (outbox pattern, not fire-and-forget).
5. **MFA on admin routes**: doctors can view patient data, but admins who can export/delete must have TOTP MFA.
6. **Feature flags**: new billing algorithm must be rolled out to 10% of tenants first.
7. **API versioning**: v1 consumers must not break when v2 ships with new claim fields.
8. **Search**: full-text search on patient names + diagnosis codes with tenant isolation.
9. **File upload**: X-ray images uploaded via presigned URLs with virus scanning.
10. **Performance**: p99 < 200ms on all CRUD endpoints under 500 concurrent users.

---

## Models

```
Patient:        name, date_of_birth, ssn_encrypted, diagnosis_codes[], insurance_id FK
InsuranceClaim: patient_id FK, amount_cents, status (pending/approved/denied/paid), submitted_at, adjudicated_at
Payment:        claim_id FK, stripe_payment_intent_id, amount_cents, status, paid_at
Appointment:    patient_id FK, doctor_id FK, scheduled_at, notes, duration_minutes
XRayImage:      patient_id FK, appointment_id FK, file_key, content_type, uploaded_by FK
```

Owner relationships: Patient→tenant, InsuranceClaim→patient→tenant, Payment→claim, Appointment→patient, XRayImage→patient.

---

## 100 Acceptance Checks

### A. Multi-Tenancy & Isolation (15 checks)

- [ ] A1: Tenant model exists with `slug`, `name`, `is_active`, `plan` fields
- [ ] A2: Every business model has `tenant_id` FK with `ondelete=RESTRICT`
- [ ] A3: `do_orm_execute` event filter auto-appends `WHERE tenant_id = :current`
- [ ] A4: `GET /patients` for Hospital A returns ZERO patients from Hospital B (verified by DB seed + query)
- [ ] A5: `GET /claims` filtered by tenant even when accessed by superadmin
- [ ] A6: Tenant context propagated via `ContextVar`, not a global variable
- [ ] A7: Background jobs (ARQ) receive tenant_id explicitly in job payload
- [ ] A8: Webhook handlers set tenant context from the webhook payload before processing
- [ ] A9: Alembic migration adds `tenant_id` to ALL business tables with backfill to default tenant
- [ ] A10: Composite index `(tenant_id, created_at)` on every business table
- [ ] A11: `POST /tenants` requires superadmin auth
- [ ] A12: Suspended tenant returns 403 on all API calls
- [ ] A13: SSE channels namespaced by tenant (`tenant:{id}:claims`)
- [ ] A14: Cache keys namespaced by tenant (`cache:{tenant_id}:patient:{id}`)
- [ ] A15: Search results filtered by tenant (tsvector query includes tenant_id WHERE)

### B. Auth, RBAC & MFA (15 checks)

- [ ] B1: Password hashing uses argon2id (NOT bcrypt)
- [ ] B2: JWT uses PyJWT (NOT python-jose — has CVE-2024-33663)
- [ ] B3: RBAC roles: `viewer` (read), `doctor` (read+write patient data), `billing_admin` (claims+payments), `tenant_admin` (everything), `superadmin`
- [ ] B4: `Depends(require_permission("patients:read"))` on patient endpoints
- [ ] B5: MFA required for `billing_admin` and `tenant_admin` roles (enforced via RBAC policy)
- [ ] B6: TOTP enrollment generates QR code with `pyotp`, NOT a URL string
- [ ] B7: Recovery codes hashed with argon2id, single-use enforced
- [ ] B8: MFA rate limiting: 5 attempts / 15 min per user
- [ ] B9: API key auth for service-to-service: `sk_live_` prefix, argon2id hash, scoped
- [ ] B10: OAuth2 social login for doctors (Google only), account linking by verified email
- [ ] B11: OAuth2 state token stored in Redis with 5-min TTL, single-use consumed
- [ ] B12: Login response for MFA-enrolled users returns `mfa_pending_token`, NOT final JWT
- [ ] B13: `DELETE /patients/{id}` requires `patients:delete` permission AND MFA challenge
- [ ] B14: Audit log captures who authenticated, with what method (password, api_key, oauth2)
- [ ] B15: Feature flag `new_billing_algo` evaluable per-tenant with deterministic bucketing

### C. Data Integrity & Audit (15 checks)

- [ ] C1: Soft delete on Patient, Appointment (NOT on InsuranceClaim, Payment — financial records are immutable)
- [ ] C2: Cursor pagination on all list endpoints (NO offset)
- [ ] C3: Audit log has `entry_hash` (SHA-256 chain) and `prev_hash`
- [ ] C4: Audit log table has immutability trigger (`BEFORE UPDATE OR DELETE → RAISE`)
- [ ] C5: Audit log captures `old_values` and `new_values` as JSONB diff (not full snapshot)
- [ ] C6: Audit log partitioned by month with at least 3 initial partitions
- [ ] C7: `ssn_encrypted` field uses Fernet encryption at rest (HIPAA requirement)
- [ ] C8: `ssn_encrypted` NEVER appears in API response schemas (excluded from `PatientPublic`)
- [ ] C9: Bulk operations on claims use `all_or_nothing` isolation (financial data)
- [ ] C10: Data export for GDPR: `GET /export?format=csv&resource=patients` filtered by tenant
- [ ] C11: Data export streams (no full dataset in memory), max 50MB RAM
- [ ] C12: Search on `diagnosis_codes` uses GIN index (array containment), not LIKE
- [ ] C13: Full-text search on `patient.name` with `setweight('A')` for name, `setweight('B')` for diagnosis
- [ ] C14: `GET /patients/search?q=smith` never returns patients from another tenant
- [ ] C15: Alembic migration for `ssn_encrypted` has `server_default` for existing rows

### D. Payments & Webhooks (15 checks)

- [ ] D1: Stripe webhook endpoint verifies HMAC-SHA256 signature with `hmac.compare_digest`
- [ ] D2: Webhook handler is idempotent (Redis `SET NX EX` by event_id)
- [ ] D3: Webhook endpoint returns 200 within 100ms (async ARQ dispatch)
- [ ] D4: Raw card numbers NEVER stored or logged (regex scan for PAN patterns)
- [ ] D5: `stripe_payment_intent_id` has UNIQUE constraint
- [ ] D6: Payment status transitions validated: `pending → succeeded | failed` (no backward)
- [ ] D7: Outbox pattern: payment state change → outbox event → downstream notification
- [ ] D8: Outbox uses `SELECT FOR UPDATE SKIP LOCKED` for concurrent workers
- [ ] D9: Dead-letter queue for failed outbox deliveries
- [ ] D10: SSE notification when claim status changes (`event: claim_status_changed`)
- [ ] D11: Circuit breaker on external insurance API calls
- [ ] D12: Insurance API timeout < 5s, with fallback to cached response
- [ ] D13: Retry with exponential backoff (1s → 5s → 30s → 5m)
- [ ] D14: Webhook replay endpoint for ops: `POST /webhooks/replay/{event_id}`
- [ ] D15: Financial amounts stored as `Integer` cents (NOT `Decimal` or `Float`)

### E. File Upload & Search (10 checks)

- [ ] E1: X-ray upload via S3 presigned URL (file never touches app server)
- [ ] E2: MIME validation via `magic.from_buffer` (not just Content-Type header)
- [ ] E3: Max file size 50MB enforced at presign time
- [ ] E4: Orphan cleanup job runs every 60 min for pending uploads > 1 hour old
- [ ] E5: File metadata excludes `stored_key` from public schema (prevent key enumeration)
- [ ] E6: `GET /xray/{id}/download` returns 302 redirect to presigned download URL
- [ ] E7: Autocomplete on patient name: `GET /patients/autocomplete?q=smi` returns top 5
- [ ] E8: Autocomplete p99 < 20ms
- [ ] E9: Search ranking: name match (`setweight A`) ranks above diagnosis match (`setweight B`)
- [ ] E10: Search injection safe: `q='; DROP TABLE patients; --` returns 0 results, not error

### F. Infrastructure & Observability (15 checks)

- [ ] F1: Redis cache with `@cached(ttl=300)` on read endpoints
- [ ] F2: Cache invalidation on write via pub/sub fan-out
- [ ] F3: Cache keys include tenant_id (no cross-tenant cache leakage)
- [ ] F4: Connection pool monitor with Prometheus metrics
- [ ] F5: Error rate analyzer with 4xx/5xx sliding windows
- [ ] F6: SLA reporter generating availability + p99 per endpoint
- [ ] F7: API versioning: `/api/v1/` routes with Sunset headers on deprecated endpoints
- [ ] F8: Docker multi-stage build, non-root user, healthcheck
- [ ] F9: k6 load test with smoke/load/stress profiles
- [ ] F10: GitHub Actions CI running tests + audit
- [ ] F11: Saga orchestrator for multi-step claim processing (submit → verify → adjudicate)
- [ ] F12: Saga compensation: if adjudication fails, mark claim as `review_needed` (not `denied`)
- [ ] F13: Long-running task for batch claim reprocessing with progress tracking
- [ ] F14: Dead code finder configured and run as part of CI
- [ ] F15: Blast radius analysis available as MCP tool

### G. Code Quality & Security (15 checks)

- [ ] G1: Zero `eval()`, `exec()`, `pickle.loads()` in generated code
- [ ] G2: Zero f-string SQL (all queries use parameterized ORM)
- [ ] G3: All generated `.py` files pass `ast.parse`
- [ ] G4: No function > 50 LOC in generated application code (not templates)
- [ ] G5: Every public function has docstring
- [ ] G6: All endpoints have `response_model` declared
- [ ] G7: Pydantic schemas use `strict=True` and `max_length` on all string fields
- [ ] G8: CORS never uses wildcard (`*`) — explicit origin list
- [ ] G9: Security headers middleware (X-Content-Type-Options, X-Frame-Options, etc.)
- [ ] G10: Rate limiting on auth endpoints (login, MFA challenge)
- [ ] G11: `DUMMY_HASH` pattern for timing-safe auth (prevents user enumeration)
- [ ] G12: Correlation ID middleware propagating `X-Request-ID` across services
- [ ] G13: Structured logging via structlog (not print statements)
- [ ] G14: OpenTelemetry traces with cardinality-safe route labels
- [ ] G15: `docs_url=None` in production (Swagger UI not exposed)

---

## Scoring

| Grade | Score | Meaning |
|-------|-------|---------|
| **S** | 95-100 | SOTA — no production-ready template achieves this |
| **A** | 85-94 | Excellent — minor gaps, shippable with review |
| **B** | 70-84 | Good — needs manual work on security/compliance |
| **C** | 50-69 | Acceptable — significant gaps in critical areas |
| **D** | 30-49 | Poor — major security/data-integrity holes |
| **F** | 0-29 | Fail — unusable for production |

**Expected scores:**
- Opus naked (no skill): 35-45 (D) — will use bcrypt, miss tenant isolation, skip audit hash chain
- Haiku naked: 25-35 (F/D) — will miss most security and compliance requirements
- **SKILL-001 + any model**: 85-95 (A/S) — generators handle the hard parts

---

## How to Run

```bash
# With skill:
PYTHONPATH=. python3 benchmarks/run_finhealth.py

# Output: benchmarks/results/FINHEALTH_YYYY-MM-DD.md
# Contains: 100 checks, pass/fail each, final score
```
