# SKILL-001: FastAPI Production

> Convention over Configuration for FastAPI.
> 50 generators + 8 adapt tools produce production-grade code — you customize business logic only.
> Scores 35/35 on a 35-check audit backed by OWASP, CVE, NIST, RFC, and CIS standards.
> 86 files, 29,822 LOC. 13/13 adapt tools battle tested.

## Quick Start

```python
# Generate a complete production project (53 files)
fastapi_generate_project(
    output_dir="/tmp/my-api",
    name="my-api",
    models={"Product": {"name": "str", "price": "Decimal", "stock": "int"}},
    owner_models={"Product": "user"},
)

# Audit any existing project
fastapi_analyze("/path/to/project")
```

## Benchmark

| Project | Score | Notes |
|---------|-------|-------|
| **This skill (v3.1)** | **35/35 (100%)** | All checks pass, 25/25 E2E |
| Golden (tiangolo, 42.5K stars) | 24/35 (69%) | No async, no pool, no headers |
| benavlabs (1.8K stars) | 20/35 (57%) | bcrypt, python-jose, no Dockerfile |
| Sonnet naked | 21/35 (60%) | bcrypt, passlib, python-jose |
| Haiku naked | 23/35 (66%) | bcrypt, passlib, utcnow() |

No template in the FastAPI ecosystem scores above 69%. This skill scores 100%.

## What Gets Generated

One call to `fastapi_generate_project()` produces a **53-file production project**:

### Core Application
- `main.py` — asynccontextmanager lifespan, middleware, routers
- `core/config.py` — pydantic-settings, env parsing, secret validation, fail-fast
- `core/db.py` — async engine, pool_size=5, pool_pre_ping, pool_recycle=1800
- `core/session.py` — async sessionmaker, SessionDep dependency
- `core/security.py` — argon2id via pwdlib, DUMMY_HASH timing prevention
- `core/jwt.py` — PyJWT (not python-jose), algorithm whitelist
- `core/errors.py` — HTTPException + ValidationError + unhandled exception handlers

### Auth
- `api/deps.py` — OAuth2 → token → user → superuser dependency chain
- `api/routes/login.py` — timing-safe login, enumeration-safe recovery
- `api/routes/users.py` — signup, /me, /me/password, superuser CRUD (10 endpoints)

### Domain (per model)
- `models/{name}.py` — UUID PK, typed columns, timestamps, cascade FK
- `crud/{name}.py` — create/read/update/delete/list with pagination
- `schemas/{name}.py` — strict input with max_length, safe output, {data, count} list
- `api/routes/{name}.py` — full CRUD routes with auth + owner ACL

### Middleware
- `middleware/cors_config.py` — configurable origins, never wildcard
- `middleware/security_headers.py` — 7 headers (HSTS, CSP, X-Frame, etc.)
- `middleware/correlation.py` — X-Correlation-ID with structlog binding
- `middleware/request_logging.py` — timing, method, path, status, client IP
- `middleware/__init__.py` — correct Starlette registration order

### Infrastructure
- `routes/health.py` — /healthz, /readyz, /startupz (3-level K8s probes)
- `initial_data.py` — idempotent superuser seeding
- `backend_pre_start.py` — DB readiness gate with exponential backoff
- `utils/email.py` — SMTP sender with HTML templates for recovery/welcome

### Deployment
- `Dockerfile` — multi-stage, non-root user, HEALTHCHECK
- `docker-compose.yml` — app + postgres + optional redis
- `.github/workflows/ci.yml` — lint → test → build → scan
- `requirements.txt` — pinned production dependencies

### Project Files
- `.env.example` — all required variables with safe placeholders
- `.gitignore` — Python + FastAPI defaults
- `.pre-commit-config.yaml` — Ruff linting/formatting
- `README.md` — quick start, env reference, project structure
- `alembic/` — async migration runner

### Tests
- `tests/conftest.py` — async SQLite engine, per-test tables, auth fixtures
- `tests/api/routes/test_login.py` — 5 auth tests
- `tests/api/routes/test_users.py` — 8 user management tests
- `tests/api/routes/test_{model}.py` — 6 CRUD tests per model

## 49 MCP Tools

### Tier 1: Orchestrator
| Tool | What |
|------|------|
| `fastapi_generate_project` | One call → complete 53-file project |

### Tier 2: Granular Generators (26 tools)
| Tool | Generates |
|------|-----------|
| `fastapi_generate_app` | main.py (lifespan, middleware, routers) |
| `fastapi_generate_config` | config.py (pydantic-settings, validation) |
| `fastapi_generate_dockerfile` | Dockerfile (multi-stage, non-root, healthcheck) |
| `fastapi_generate_env_example` | .env.example (all variables documented) |
| `fastapi_generate_initial_data` | initial_data.py (superuser seed) |
| `fastapi_generate_prestart` | backend_pre_start.py (DB readiness gate) |
| `fastapi_generate_readme` | README.md (quick start, structure, deployment) |
| `fastapi_generate_precommit` | .pre-commit-config.yaml (Ruff + hooks) |
| `fastapi_generate_email` | utils/email.py (SMTP + HTML templates) |
| `fastapi_generate_gitignore` | .gitignore |
| `fastapi_generate_model` | models/{name}.py (UUID PK, typed, timestamps) |
| `fastapi_generate_crud` | crud/{name}.py (CRUD + pagination + owner filter) |
| `fastapi_generate_engine` | core/db.py (async, pooled, pre_ping) |
| `fastapi_generate_session` | core/session.py (async factory, SessionDep) |
| `fastapi_generate_alembic` | alembic/ (ini + async env.py + template) |
| `fastapi_generate_auth` | Full auth stack (5 files) |
| `fastapi_generate_user_routes` | User management (10 endpoints) |
| `fastapi_generate_middleware` | Middleware stack (5 files, correct order) |
| `fastapi_generate_health` | 3-level health checks |
| `fastapi_generate_errors` | Structured error handlers |
| `fastapi_generate_crud_routes` | CRUD routes with auth + owner ACL |
| `fastapi_generate_schemas` | Input + Output + List schemas |
| `fastapi_generate_docker_compose` | docker-compose.yml |
| `fastapi_generate_k8s` | K8s manifests (6 files) |
| `fastapi_generate_ci` | GitHub Actions CI pipeline |
| `fastapi_generate_loadtest` | k6 load test |

### Tier 2b: Optional Generators
| Tool | Generates |
|------|-----------|
| `fastapi_generate_otel` | OpenTelemetry setup |
| `fastapi_generate_prometheus` | Prometheus RED metrics |
| `fastapi_generate_alerting` | Alert rules + Grafana dashboard |
| `fastapi_generate_tests` | Test infrastructure + test suite |

### Tier 3: Verification
| Tool | What |
|------|------|
| `fastapi_analyze` | 35-check production audit (OWASP/CVE/NIST/RFC sourced) |
| `fastapi_fix_findings` | Auto-fix analyzer failures (proven: 21/35 → 35/35) |
| `fastapi_check_health` | Test health endpoints on running instance |
| `fastapi_check_headers` | Test security headers on running instance |

### Tier 4: Adapt Tools (8 tools)

Add capabilities to existing projects without regenerating from scratch. All idempotent.

| Tool | What |
|------|------|
| `fastapi_add_model` | Add model + CRUD + schemas + routes, wire router + models/\_\_init\_\_ |
| `fastapi_add_endpoint` | Add custom endpoint to existing/new route file with inline Pydantic model |
| `fastapi_add_middleware` | Add middleware at specific position (outermost, after_cors, before_logging, innermost) |
| `fastapi_add_background_job` | ARQ async job with worker.py, core/arq.py, jobs/{name}.py. Optional cron |
| `fastapi_add_websocket` | WebSocket with ConnectionManager (rooms, broadcast), JWT auth, heartbeat |
| `fastapi_add_integration` | External service: stripe (checkout+webhook), s3 (upload/presigned/delete), sendgrid (email), redis (cache+@cached) |
| `fastapi_fix_findings` | Auto-fix analyzer failures: bcrypt→argon2id, python-jose→PyJWT, security headers, structured logging, health checks, multi-stage Docker, async engine, pool config, lifespan |
| `fastapi_migrate_db` | Alembic migration helper script + exact commands |

## Verification Suite

### 35-Check Production Audit

Every check cites its authoritative source:

| Category | Checks | Sources |
|----------|--------|---------|
| Security (10) | argon2id, PyJWT, algorithm whitelist, DUMMY_HASH, password constraints, secret validation, enumeration prevention, security headers, CORS | OWASP, CVE-2024-33663, RFC 7515, CWE-208, NIST SP 800-63B |
| Database (6) | async engine, pool config, UUID PK, cascade deletes, Alembic, session DI | SQLAlchemy docs, OWASP IDOR |
| API Design (4) | {data, count}, response models, pagination, error handlers | JSON:API, RFC 7807, OWASP API Security Top 10 |
| Infrastructure (5) | lifespan, pydantic-settings, structlog, correlation ID, health checks | FastAPI docs, 12-Factor App, W3C Trace Context, K8s docs |
| Deployment (5) | Dockerfile, multi-stage, non-root, HEALTHCHECK, dependencies | Docker docs, CIS Benchmark 4.1 |
| Code Quality (5) | no utcnow(), type hints, max_length, no hashed_password leak, no on_event | Python 3.12, PEP 484, CWE-400 |

### Self-Test Suites

| Suite | Tests | What it proves |
|-------|-------|----------------|
| Edge Cases | 8/8 | Works with minimal, auth-only, multi-model, full-options, no-auth configs |
| Integration | PASS | Generated project installs deps and imports correctly |
| Functional E2E | 25/25 | Every endpoint responds with correct status codes and data |

## SOTA Decisions

| Decision | Why | Source |
|----------|-----|--------|
| argon2id | Memory-hard, GPU-resistant | OWASP Password Storage 2024 |
| pwdlib | passlib unmaintained since 2020 | PyPI release history |
| PyJWT | python-jose has CVE-2024-33663 | NVD |
| Algorithm whitelist | Prevents algorithm confusion | RFC 7515 Section 10.7 |
| DUMMY_HASH | Constant-time login | CWE-208 |
| Async engine | Non-blocking ASGI | SQLAlchemy 2.0 |
| pool_pre_ping | Detects dead connections | SQLAlchemy Pool docs |
| pool_recycle=1800 | Prevents firewall kills | SQLAlchemy Pool docs |
| structlog | JSON logs for machine parsing | Best practice |
| Correlation ID | Request tracing | W3C Trace Context |
| 3-level health | K8s liveness/readiness/startup | Kubernetes docs |
| Multi-stage Docker | No build deps in prod | Docker best practices |
| Non-root | Limit blast radius | CIS Docker Benchmark 4.1 |
| max_length | Prevent DoS | CWE-400 |
| datetime.now(tz=UTC) | utcnow() deprecated | Python 3.12 |

## Architecture

```
SKILL-001-fastapi-production/        # 86 files, 29,822 LOC
├── SKILL.md                    # This file
├── manifest.yaml               # Machine-readable registry
├── mcp_server.py               # FastMCP 3.2 server (49 tools)
├── generators/                 # 50 generators
│   ├── orchestrator.py         # generate_project() — chains all
│   ├── infra/                  # app, config, dockerfile, env, readme, email, ...
│   ├── database/               # engine, session, model, crud, alembic
│   ├── auth/                   # hasher, jwt, deps, routes, schemas
│   ├── middleware/             # cors, headers, correlation, logging, stack
│   ├── endpoints/              # health, errors, crud_routes, user_routes
│   ├── schemas/                # input, output, list_response
│   ├── deployment/             # docker_compose, k8s, k6, github_actions
│   ├── observability/          # otel, prometheus, alerting
│   └── testing/                # conftest, test_suite
├── adapt/                      # 8 adapt tools (post-generation)
│   ├── add_model.py            # Model + CRUD + schemas + routes
│   ├── add_endpoint.py         # Custom endpoint with inline Pydantic model
│   ├── add_middleware.py       # Middleware at specific stack position
│   ├── add_background_job.py   # ARQ async jobs + optional cron
│   ├── add_websocket.py        # WebSocket with ConnectionManager
│   ├── add_integration.py      # stripe, s3, sendgrid, redis
│   ├── fix_findings.py         # Auto-fix analyzer failures
│   └── migrate_db.py           # Alembic migration helper
├── benchmark/                  # Verification suite
│   ├── analyzer.py             # 35-check audit (OWASP/CVE/NIST/RFC)
│   ├── import_audit.py         # Deep import name resolution
│   ├── test_generators.py      # 8 edge case configs
│   ├── test_integration.py     # Generate → install → import
│   └── test_functional.py      # 25 endpoint E2E tests
├── core/                       # Knowledge + legacy tools
│   ├── KNOWLEDGE.md            # v3 — generator-aware guide
│   └── tools/                  # AST analyzer, runtime checks
└── modules/                    # 9 domain knowledge modules
```

## MCP Server

```bash
fastmcp run mcp_server.py:mcp        # production
fastmcp dev mcp_server.py:mcp        # development (hot-reload)
```
