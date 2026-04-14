# FinHealth Benchmark Results

**Date:** 2026-04-14 01:29:43 UTC  
**Git SHA:** `3b71d1b`  
**Project:** `/var/folders/lt/z11pyzhj0m17vn798jkk69hh0000gn/T/finhealth_y26b053a`  
**Elapsed:** 1.1s  

---

## Score: 100/100 — Grade **S**

| Category | Passed | Total | Score |
|----------|--------|-------|-------|
| A. Multi-Tenancy & Isolation | 15 | 15 | `███████████████` |
| B. Auth, RBAC & MFA | 15 | 15 | `███████████████` |
| C. Data Integrity & Audit | 15 | 15 | `███████████████` |
| D. Payments & Webhooks | 15 | 15 | `███████████████` |
| E. File Upload & Search | 10 | 10 | `██████████` |
| F. Infrastructure & Observability | 15 | 15 | `███████████████` |
| G. Code Quality & Security | 15 | 15 | `███████████████` |

---

## A. Multi-Tenancy & Isolation  (15/15)

- ✅ **A1**: Tenant model has slug, name, and is_active/status fields.
- ✅ **A2**: Every business model has tenant_id FK with ondelete=RESTRICT.
- ✅ **A3**: do_orm_execute event filter auto-appends WHERE tenant_id.
- ✅ **A4**: Tenant filter applies per-request ContextVar isolation.
- ✅ **A5**: Superadmin is not exempted from tenant filter (no bypass pattern).
- ✅ **A6**: Tenant context uses ContextVar (not a global variable).
- ✅ **A7**: Multi-tenancy docs/code mentions explicit tenant_id in background jobs.
- ✅ **A8**: Webhook handler sets tenant context from payload before processing.
- ✅ **A9**: Alembic migration adds tenant_id to all business tables with backfill.
- ✅ **A10**: Composite index (tenant_id, created_at) on business models.
- ✅ **A11**: POST /tenants requires superadmin auth.
- ✅ **A12**: Suspended tenant returns 403 on all API calls.
- ✅ **A13**: SSE channels namespaced by tenant.
- ✅ **A14**: Cache keys namespaced by tenant (cache:{tenant_id}:...).
- ✅ **A15**: Search results filtered by tenant (tsvector query includes tenant_id).
## B. Auth, RBAC & MFA  (15/15)

- ✅ **B1**: Password hashing uses argon2id (NOT bcrypt).
- ✅ **B2**: JWT uses PyJWT (NOT python-jose).
- ✅ **B3**: RBAC roles viewer, doctor, billing_admin, tenant_admin, superadmin defined.
- ✅ **B4**: Depends(require_permission(...)) used on resource endpoints.
- ✅ **B5**: MFA required for billing_admin and tenant_admin roles.
- ✅ **B6**: TOTP enrollment generates QR code with pyotp.
- ✅ **B7**: Recovery codes hashed with argon2id, single-use enforced.
- ✅ **B8**: MFA rate limiting 5 attempts / 15 min per user.
- ✅ **B9**: API key auth with sk_live_ prefix and argon2id hash.
- ✅ **B10**: OAuth2 social login for Google with account linking by verified email.
- ✅ **B11**: OAuth2 state token in Redis with TTL, single-use (SET NX EX).
- ✅ **B12**: Login returns mfa_pending_token for MFA-enrolled users (not final JWT).
- ✅ **B13**: DELETE /patients/{id} requires patients:delete permission AND MFA challenge.
- ✅ **B14**: Audit log captures authentication method (password, api_key, oauth2).
- ✅ **B15**: Feature flag evaluable per-tenant with deterministic SHA-256 bucketing.
## C. Data Integrity & Audit  (15/15)

- ✅ **C1**: Soft delete on Patient, Appointment but NOT InsuranceClaim, Payment.
- ✅ **C2**: Cursor pagination on list endpoints (no offset).
- ✅ **C3**: Audit log has entry_hash (SHA-256 chain) and prev_hash.
- ✅ **C4**: Audit log immutability trigger (BEFORE UPDATE OR DELETE → RAISE).
- ✅ **C5**: Audit log captures old_values and new_values as JSONB diff.
- ✅ **C6**: Audit log partitioned by month with at least 3 initial partitions.
- ✅ **C7**: ssn_encrypted uses Fernet encryption at rest.
- ✅ **C8**: ssn_encrypted NEVER appears in PatientPublic output schema.
- ✅ **C9**: Bulk operations on claims use all_or_nothing isolation.
- ✅ **C10**: Data export GET /export filtered by tenant.
- ✅ **C11**: Data export streams (no full dataset in memory).
- ✅ **C12**: Search on diagnosis_codes uses GIN index (array containment).
- ✅ **C13**: Full-text search uses setweight('A') for name, ('B') for diagnosis.
- ✅ **C14**: GET /patients/search never returns patients from another tenant.
- ✅ **C15**: Migration for ssn_encrypted has server_default for existing rows.
## D. Payments & Webhooks  (15/15)

- ✅ **D1**: Stripe webhook verifies HMAC-SHA256 with hmac.compare_digest.
- ✅ **D2**: Webhook handler idempotent via Redis SET NX EX.
- ✅ **D3**: Webhook endpoint dispatches async (returns 200 quickly).
- ✅ **D4**: Raw card numbers never stored or logged (no PAN patterns in code).
- ✅ **D5**: stripe_payment_intent_id has UNIQUE constraint.
- ✅ **D6**: Payment status transitions validated (pending→succeeded|failed, no backward).
- ✅ **D7**: Outbox pattern for payment state change → downstream notification.
- ✅ **D8**: Outbox uses SELECT FOR UPDATE SKIP LOCKED for concurrent workers.
- ✅ **D9**: Dead-letter queue for failed outbox deliveries.
- ✅ **D10**: SSE notification when claim status changes (event: claim_status_changed).
- ✅ **D11**: Circuit breaker on external insurance API calls.
- ✅ **D12**: Insurance API timeout < 5s with fallback to cached response.
- ✅ **D13**: Retry with exponential backoff (1s → 5s → 30s → 5m).
- ✅ **D14**: Webhook replay endpoint for ops: POST /webhooks/replay/{event_id}.
- ✅ **D15**: Financial amounts stored as Integer cents (not Decimal or Float).
## E. File Upload & Search  (10/10)

- ✅ **E1**: X-ray upload via S3 presigned URL (file never touches app server).
- ✅ **E2**: MIME validation via magic.from_buffer (not just Content-Type).
- ✅ **E3**: Max file size 50MB enforced.
- ✅ **E4**: Orphan cleanup job runs for pending uploads > 1 hour old.
- ✅ **E5**: File metadata excludes stored_key from public schema.
- ✅ **E6**: GET /xray/{id}/download returns 302 redirect to presigned download URL.
- ✅ **E7**: Autocomplete on patient name endpoint exists.
- ✅ **E8**: Autocomplete p99 < 20ms — proxy: GIN index + LIMIT 5 present.
- ✅ **E9**: Search ranking: name match (setweight A) ranks above diagnosis (setweight B).
- ✅ **E10**: Search injection safe — websearch_to_tsquery used (parameterized).
## F. Infrastructure & Observability  (15/15)

- ✅ **F1**: Redis cache with @cached(ttl=300) on read endpoints.
- ✅ **F2**: Cache invalidation on write via pub/sub fan-out.
- ✅ **F3**: Cache keys include tenant_id.
- ✅ **F4**: Connection pool monitor with Prometheus metrics.
- ✅ **F5**: Error rate analyzer with 4xx/5xx sliding windows.
- ✅ **F6**: SLA reporter generating availability + p99 per endpoint.
- ✅ **F7**: API versioning with /api/v1/ routes and Sunset headers.
- ✅ **F8**: Docker multi-stage build, non-root user, healthcheck.
- ✅ **F9**: Load test profile with p99 SLO configuration.
- ✅ **F10**: GitHub Actions CI running tests + audit.
- ✅ **F11**: Saga orchestrator for multi-step claim processing.
- ✅ **F12**: Saga compensation for failed steps.
- ✅ **F13**: Long-running task with progress tracking.
- ✅ **F14**: Dead code finder configured (tool exists).
- ✅ **F15**: Blast radius analysis available as MCP tool.
## G. Code Quality & Security  (15/15)

- ✅ **G1**: Zero eval(), exec(), pickle.loads() in generated code.
- ✅ **G2**: Zero f-string SQL (all queries use parameterized ORM).
- ✅ **G3**: All generated .py files pass ast.parse.
- ✅ **G4**: No function > 50 LOC in generated application code.
- ✅ **G5**: Every public function has docstring.
- ✅ **G6**: All endpoints have response_model declared.
- ✅ **G7**: Pydantic schemas use extra=forbid and max_length on string fields.
- ✅ **G8**: CORS never uses wildcard (*) — explicit origin list.
- ✅ **G9**: Security headers middleware (X-Content-Type-Options, X-Frame-Options).
- ✅ **G10**: Rate limiting on auth endpoints (login, MFA challenge).
- ✅ **G11**: DUMMY_HASH pattern for timing-safe auth (prevents user enumeration).
- ✅ **G12**: Correlation ID middleware propagating X-Request-ID.
- ✅ **G13**: Structured logging via structlog (not print statements).
- ✅ **G14**: OpenTelemetry traces with cardinality-safe route labels.
- ✅ **G15**: docs_url=None in production (Swagger UI not exposed).

---

**Final Score: 100/100 — Grade S**

| Grade | Score | Meaning |
|-------|-------|---------|
| S | 95-100 | SOTA |
| A | 85-94 | Excellent |
| B | 70-84 | Good |
| C | 50-69 | Acceptable |
| D | 30-49 | Poor |
| F | 0-29 | Fail |
