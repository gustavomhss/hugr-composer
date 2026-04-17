# LLM.md — How to use SKILL-001 as an LLM

> This file is for LLMs (Claude, GPT, Gemini, etc.) consuming this skill
> via MCP tools. It explains what each tool does, when to use it, and the
> constraints you must follow.

## Your role

You are a developer using a FastAPI production skill. The skill generates
SOTA production-grade code. Your job is to customize the BUSINESS LOGIC only.
Do not modify infrastructure code — it's already calibrated.

## Quick start

```python
# 1. Generate the base project
fastapi_generate_project(
    output_dir="/path/to/project",
    name="my-api",
    models={"Product": {"name": "str", "price": "Decimal", "stock": "int"}},
    owner_models={"Product": "user"},
    profile="api",  # minimal | api | full | worker
)

# 2. Add features you need (pick any, in any order)
fastapi_add_search(project_dir="/path/to/project")
fastapi_add_soft_delete(project_dir="/path/to/project")
fastapi_add_stripe_checkout(project_dir="/path/to/project")
```

## What you get

The generated project includes:
- FastAPI app with lifespan, middleware stack, error handlers
- JWT auth (argon2id, not bcrypt) with login/signup/refresh
- SQLAlchemy 2.0 async with proper pool config
- Alembic migrations
- Health checks (/healthz, /readyz, /startupz)
- Security headers (7 headers)
- Structured logging (structlog)
- Docker + docker-compose

## Tools by use case

### "I need basic CRUD"
Already included in the base project. Each model in `models={}` gets full
CRUD routes automatically.

### "I need auth beyond basic JWT"
| Need | Tool |
|------|------|
| Multi-tenant isolation | `fastapi_add_multi_tenancy` |
| Role-based access control | `fastapi_add_rbac` |
| Two-factor auth (TOTP) | `fastapi_add_mfa` |
| API key authentication | `fastapi_add_api_key_auth` |
| OAuth2 provider (Google/GitHub) | `fastapi_add_oauth2_provider` |
| Feature flags (env-var based) | `fastapi_add_feature_flags` |
| Feature toggles (DB + API) | `fastapi_add_feature_toggles_api` |
| AWS Cedar policies (ABAC) | `fastapi_add_cedar_policies` |
| OPA integration (Rego) | `fastapi_add_opa_integration` |

### "I need data operations"
| Need | Tool |
|------|------|
| Soft delete (is_deleted flag) | `fastapi_add_soft_delete` |
| Cursor pagination | `fastapi_add_cursor_pagination` |
| Full-text search | `fastapi_add_search` |
| Bulk create/update/delete | `fastapi_add_bulk_operations` |
| Audit log (HIPAA/SOC2) | `fastapi_add_audit_log` |
| Data export (CSV/JSON) | `fastapi_add_data_export` |
| File upload (S3/local) | `fastapi_add_file_upload` |

### "I need payments"
| Need | Tool |
|------|------|
| One-time checkout | `fastapi_add_stripe_checkout` |
| Subscriptions + billing portal | `fastapi_add_stripe_subscription` |
| Refunds with audit trail | `fastapi_add_stripe_refund_flow` |

### "I need background jobs"
| Need | Tool |
|------|------|
| Redis-based (lightweight) | `fastapi_add_arq_worker` |
| Celery + beat (enterprise) | `fastapi_add_celery_beat` |
| Cron scheduler (APScheduler) | `fastapi_add_scheduled_tasks` |
| Durable workflows (Temporal) | `fastapi_add_temporal_workflow` |

### "I need real-time"
| Need | Tool |
|------|------|
| Server-sent events | `fastapi_add_sse` |
| WebSocket chat rooms | `fastapi_add_websocket_chat` |
| Online presence tracking | `fastapi_add_websocket_presence` |
| GraphQL subscriptions | `fastapi_add_graphql_subscriptions` |
| Outbound webhooks | `fastapi_add_webhook_sender` |
| Inbound webhook receiver | `fastapi_add_webhook_receiver` |

### "I need infrastructure"
| Need | Tool |
|------|------|
| Redis cache layer | `fastapi_add_cache_layer` |
| Circuit breaker | `fastapi_add_circuit_breaker` |
| Rate limiting (SlowAPI) | `fastapi_add_rate_limiting` |
| S3/MinIO object storage | `fastapi_add_s3_storage` |
| Deep health checks | `fastapi_add_health_deep` |
| Transactional outbox | `fastapi_add_outbox_pattern` |
| Saga orchestration | `fastapi_add_saga` |
| Email templates (Jinja2) | `fastapi_add_email_templates` |
| Push notifications (FCM) | `fastapi_add_notifications` |
| Admin panel (SQLAdmin) | `fastapi_add_sqladmin` |

### "I need ML serving"
| Need | Tool |
|------|------|
| /predict endpoint | `fastapi_add_ml_model_server` |
| GPU inference (CUDA) | `fastapi_add_ml_gpu_inference` |
| Model registry + A/B | `fastapi_add_ml_model_registry` |

### "I need API design patterns"
| Need | Tool |
|------|------|
| URL versioning (/v1, /v2) | `fastapi_add_api_versioning` |
| Batch endpoint | `fastapi_add_batch_endpoint` |
| GraphQL (queries + mutations) | `fastapi_add_graphql` |
| Long-running tasks + polling | `fastapi_add_long_running_task` |

## Rules you MUST follow

### DO
- Use the tools as-is — they produce calibrated code
- Customize business logic in the generated route handlers
- Add new routes for your domain-specific endpoints
- Use the generated patterns (e.g., `CurrentUser` dependency)
- Run `alembic upgrade head` after tools that create migrations

### DO NOT
- Do not modify middleware order (it's correct as generated)
- Do not change pool config in `db.py` (it's tuned for production)
- Do not replace argon2id with bcrypt (argon2id is stronger)
- Do not add top-level imports for optional SDKs (use lazy imports)
- Do not hard-code secrets in source files (use settings / .env)
- Do not remove security headers from the middleware stack

### Idempotency
Every tool is idempotent. Running it twice on the same project returns
`status="no_op"` without touching any file. Safe to call repeatedly.

### Profiles
| Profile | Use when |
|---------|----------|
| `minimal` | You want just models + health check |
| `api` | You want a production REST API with auth |
| `full` | You want everything (deploy, observability, testing) |
| `worker` | You want a background worker (no HTTP routes) |

### Bring Your Own Project
Tools work on ANY FastAPI project, not just generated ones. If a
prerequisite is missing (e.g., `app/core/config.py`), the tool
auto-scaffolds it with minimal defaults.

## Composition

Tools compose freely. Apply in any order. Examples:

```python
# SaaS billing stack
fastapi_add_multi_tenancy(project_dir=p)
fastapi_add_rbac(project_dir=p)
fastapi_add_stripe_subscription(project_dir=p)
fastapi_add_email_templates(project_dir=p)
fastapi_add_notifications(project_dir=p)

# ML serving platform
fastapi_add_ml_model_server(project_dir=p)
fastapi_add_ml_gpu_inference(project_dir=p)
fastapi_add_ml_model_registry(project_dir=p)
fastapi_add_health_deep(project_dir=p)
fastapi_add_rate_limiting(project_dir=p)

# Real-time collaboration
fastapi_add_websocket_chat(project_dir=p)
fastapi_add_websocket_presence(project_dir=p)
fastapi_add_sse(project_dir=p)
fastapi_add_notifications(project_dir=p)
```

## Error handling

Every tool returns a `ToolResult` with:
- `status`: `"success"` | `"no_op"` | `"error"`
- `error`: Human-readable error message (only when status="error")
- `files_created`: List of absolute paths created
- `files_modified`: List of absolute paths modified
- `notes`: Informational messages about what was done
- `next_steps`: Actions the user should take after running the tool
- `execution_time_ms`: Wall-clock time in milliseconds
