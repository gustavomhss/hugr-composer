# SKILL-001 Expansion Roadmap — v5.0

> **Status**: Planned. This doc tracks 11 new contexts + ~35 new tools
> that will bring SKILL-001 from "production-grade REST CRUD" to
> "production-grade anything FastAPI can do."

## Current coverage (v4.x)

SKILL-001 v4.x covers **15 distinct FastAPI contexts** via 100 MCP tools
(49 generators + 51 adapt):

| Context | Tools | Status |
|---|---|---|
| REST CRUD APIs | `fastapi_generate_project` + model-driven scaffold | ✅ |
| JWT / password auth | `fastapi_generate_auth_*` (5 generators) | ✅ |
| API keys | `add_api_key_auth` | ✅ |
| OAuth2 provider | `add_oauth2_provider` | ✅ |
| MFA (TOTP) | `add_mfa` | ✅ |
| RBAC | `add_rbac` (permissions + roles + inheritance) | ✅ |
| Multi-tenancy | `add_multi_tenancy` | ✅ |
| Audit log (HIPAA/SOC2) | `add_audit_log` (hash chain + partitioning) | ✅ |
| Cache layer | `add_cache_layer` (Redis + XFetch) | ✅ |
| Bulk ops | `add_bulk_operations`, `add_batch_endpoint` | ✅ |
| Cursor pagination | `add_cursor_pagination` | ✅ |
| Full-text search | `add_search` (PG FTS + cross-DB fallback) | ✅ |
| Outbox / Saga | `add_outbox_pattern`, `add_saga` | ✅ |
| Webhooks (send/recv) | `add_webhook_sender`, `add_webhook_receiver` | ✅ |
| Circuit breaker | `add_circuit_breaker` | ✅ |
| SSE | `add_sse` | ✅ |
| File upload | `add_file_upload` (S3 + quarantine) | ✅ |
| Feature flags | `add_feature_flags` | ✅ |
| API versioning | `add_api_versioning` | ✅ |
| GraphQL | `add_graphql` (queries + mutations) | ✅ |
| Long-running tasks | `add_long_running_task` (202 + polling) | ✅ |
| Data export | `add_data_export` (CSV/JSON/Parquet) | ✅ |
| Observability | OTEL + Prometheus + structured logs | ✅ |
| Deployment | Dockerfile + docker-compose + k8s + CI | ✅ |
| Verify / Operate | 15 tools (N+1, security, SLA, etc.) | ✅ |

## Missing contexts — v5.0 expansion plan

### 1. WebSocket chat + presence (2 tools)

**Gap**: SSE is one-way. Real-time bi-directional needs WebSocket.

| New tool | Generates |
|---|---|
| `add_websocket_chat` | `/ws/chat/{room}` endpoint, Redis pub/sub, auth handshake, room membership |
| `add_websocket_presence` | `/ws/presence` with heartbeat, online/offline/idle tracking, TTL-based expiry |

**Use cases**: chat apps, collaborative editors, live dashboards, multiplayer games.

### 2. Background job queues (3 tools)

**Gap**: `add_outbox_pattern` gives transactional event dispatch, but there's no job runner.

| New tool | Generates |
|---|---|
| `add_arq_worker` | arq (Redis) worker + `TaskRegistry` + `@task` decorator + CLI `python -m app.worker` |
| `add_celery` | Celery + broker config + result backend + periodic tasks (beat) |
| `add_temporal_workflow` | Temporal SDK workflows + activities + workers + durable execution |

**Use cases**: email sending, report generation, data imports, scheduled reconciliation.

### 3. ML model serving (3 tools)

**Gap**: No ML inference endpoint scaffolding.

| New tool | Generates |
|---|---|
| `add_ml_model_server` | `/predict` endpoint, model loading at startup, input validation (Pydantic), batch prediction |
| `add_ml_gpu_inference` | CUDA device check, model.to(device), mixed precision, memory guards |
| `add_ml_model_registry` | MLflow-style model registry, versioning, A/B test via feature flags |

**Use cases**: serve PyTorch/TensorFlow/ONNX/sklearn models as HTTP endpoints.

### 4. Admin UI (2 tools)

**Gap**: `generate_admin_panel` exists but is minimal (no out-of-the-box dashboard).

| New tool | Generates |
|---|---|
| `add_sqladmin` | SQLAdmin (FastAPI-native) mounted at `/admin`, per-model CRUD UI, auth gate |
| `add_piccolo_admin` | Piccolo Admin alternative for teams that prefer it |

**Use cases**: back-office data management without building custom UI.

### 5. Stripe payments — full flow (3 tools)

**Gap**: `add_webhook_receiver` handles Stripe signature verification. Missing: full checkout flow.

| New tool | Generates |
|---|---|
| `add_stripe_checkout` | `POST /checkout` → creates Stripe Checkout Session, returns URL, success/cancel webhooks wired |
| `add_stripe_subscription` | Subscription lifecycle (create/upgrade/cancel), billing portal, proration handling |
| `add_stripe_refund_flow` | `POST /refunds`, idempotency, audit trail, reconciliation queue |

**Use cases**: SaaS billing, e-commerce checkout, marketplace payouts.

### 6. Email / transactional messaging (2 tools)

**Gap**: `utils/email.py` generated is minimal (SMTP only).

| New tool | Generates |
|---|---|
| `add_email_templates` | Jinja2 templates dir, MJML→HTML pipeline, template registry, localization hooks |
| `add_transactional_email` | Resend/Postmark/SendGrid adapter, delivery tracking, bounce handling |

**Use cases**: signup confirmation, password reset, receipts, notifications.

### 7. Push notifications (1 tool)

| New tool | Generates |
|---|---|
| `add_push_notifications` | APNs + FCM adapters, device token registration, topic-based fanout |

**Use cases**: mobile push for iOS/Android apps.

### 8. Notification fanout (1 tool)

| New tool | Generates |
|---|---|
| `add_notification_service` | Orchestrator: email + push + in-app, per-user preferences, digest mode |

**Use cases**: consolidated notification layer with user-controlled channels.

### 9. GraphQL subscriptions (extend existing)

**Gap**: `add_graphql` covers queries + mutations. Subscriptions need WebSocket transport.

Extension to `add_graphql`:
- `subscriptions: bool = False` kwarg → emit `GraphQL.subscription` resolvers
- Ties into `add_websocket_presence` for auth

### 10. Policy engines (2 tools)

**Gap**: RBAC is role-based. ABAC (attribute-based) + policy-as-code is common in enterprise.

| New tool | Generates |
|---|---|
| `add_cedar_policies` | AWS Cedar engine, policy files, runtime evaluator, dep injected in routes |
| `add_opa_integration` | OPA sidecar + Rego policies, OPA gRPC client, decision logs |

**Use cases**: complex access rules that outgrow RBAC.

### 11. i18n (expand existing)

**Gap**: `add_i18n` is minimal. Missing: gettext extraction, locale middleware, ICU message format.

Extension:
- `extract_messages` CLI wrapping Babel
- Accept-Language middleware
- Pluralization + gender + number formatting
- Translation memory / fuzzy matching

## Total: 11 new contexts, ~18 new tools

After v5.0, the skill will cover **26 FastAPI contexts via ~118 MCP tools**.

## Prioritization

1. **Tier 1 — ship in v5.0**: WebSocket chat, arq worker, stripe checkout,
   email templates, sqladmin (top 5 most-requested in FastAPI community)
2. **Tier 2 — v5.1**: background jobs (celery + temporal), ML inference,
   notification fanout, push notifications
3. **Tier 3 — v5.2**: policy engines, GraphQL subscriptions, i18n expansion

## Success criteria per tool

Every new tool must pass, before merging:
- Unit test file (`test_add_X.py`) with ≥15 checks
- Boot test — generated code parses + imports clean
- Boot chain test — composes with prior tools
- Behavior test — exercised in at least 1 domain scenario (see
  `tests/test_behavior_scenarios.py`)
- SOTA reviewer — 16-section spec passes mechanical review
- FinHealth benchmark impact ≤ 0 (no regression)
- Cross-DB compatibility (SQLite + PostgreSQL)

## Non-goals

- **Not building** a frontend framework (that's SKILL-002: Next.js).
- **Not building** a mobile SDK (that's SKILL-003: React Native / Flutter).
- **Not building** an alternative to FastAPI (this is a FastAPI skill).
