"""
SKILL-001: FastAPI Production — MCP Server v4 (Convention over Configuration)

Exposes 30 generators + 51 adapt tools as MCP tools.  Each generator produces
SOTA code that the LLM customizes for business logic — the infra is decided by
the generator, not the LLM.  Adapt tools extend, verify, operate, evolve, and
diagnose existing FastAPI projects.

Run:
    fastmcp run mcp_server.py:mcp
    fastmcp dev mcp_server.py:mcp   # with hot-reload

Architecture:
    generate_project()  →  orchestrates all generators  →  47-file project
    generate_*()        →  individual generators (granular control)
    fastapi_analyze()   →  benchmark analyzer (35-check production audit)
    fastapi_add_*()     →  adapt/extend: add features to existing projects
    fastapi_detect_*/fastapi_security_scan/etc. → adapt/verify: audit tools
    fastapi_blast_radius/etc. → adapt/operate: operational analysis
    fastapi_refactor_*/etc.   → adapt/evolve: structural evolution tools
    fastapi_doctor()    →  adapt/proactive: holistic health-check engine
"""
from __future__ import annotations

import sys
from pathlib import Path

from fastmcp import FastMCP

SKILL_ROOT = Path(__file__).parent
sys.path.insert(0, str(SKILL_ROOT))

# ── Server ──

mcp = FastMCP(
    "hugr-skill-fastapi",
    instructions=(
        "FastAPI Production skill — generates SOTA production projects AND adapts existing ones.\n\n"
        "Convention over Configuration: generators deliver calibrated defaults "
        "(argon2id, async pools, security headers, multi-stage Docker), "
        "you customize business logic only.\n\n"
        "PRIMARY TOOL: fastapi_generate_project — one call, full project.\n"
        "GRANULAR: Use individual generate_* tools for specific components.\n"
        "VERIFY: Use fastapi_analyze to audit any FastAPI project (35 checks).\n\n"
        "ADAPT TOOLS (51 tools for existing projects):\n"
        "  EXTEND: fastapi_add_soft_delete, fastapi_add_cursor_pagination, "
        "fastapi_add_file_upload, fastapi_add_search, fastapi_add_audit_log, "
        "fastapi_add_data_export, fastapi_add_bulk_operations, "
        "fastapi_add_multi_tenancy, fastapi_add_feature_flags, "
        "fastapi_add_api_key_auth, fastapi_add_oauth2_provider, fastapi_add_rbac, "
        "fastapi_add_mfa, fastapi_add_sse, fastapi_add_webhook_sender, "
        "fastapi_add_webhook_receiver, fastapi_add_api_versioning, "
        "fastapi_add_graphql, fastapi_add_batch_endpoint, "
        "fastapi_add_long_running_task, fastapi_add_cache_layer, "
        "fastapi_add_circuit_breaker, fastapi_add_outbox_pattern, fastapi_add_saga, "
        "fastapi_add_factory, fastapi_add_contract_tests, fastapi_add_load_profile.\n"
        "  VERIFY: fastapi_detect_n_plus_one, fastapi_security_scan, "
        "fastapi_dependency_audit, fastapi_schema_coverage, "
        "fastapi_test_coverage_gaps, fastapi_api_spec_compliance, "
        "fastapi_performance_baseline.\n"
        "  OPERATE: fastapi_blast_radius, fastapi_migration_diff, "
        "fastapi_dead_code_finder, fastapi_api_changelog, "
        "fastapi_dependency_graph, fastapi_connection_pool_monitor, "
        "fastapi_error_rate_analyzer, fastapi_sla_reporter.\n"
        "  EVOLVE: fastapi_add_migration_data, fastapi_refactor_model, "
        "fastapi_extract_service, fastapi_add_event_driven, "
        "fastapi_generate_sdk, fastapi_generate_admin_panel, "
        "fastapi_generate_docs, fastapi_add_i18n.\n"
        "  PROACTIVE: fastapi_doctor — runs all 7 verify tools, classifies "
        "findings by severity, and generates an ordered fix plan."
    ),
)


# ═══════════════════════════════════════════════════════════════════════
#  TIER 1: Orchestrator (one tool, full project)
# ═══════════════════════════════════════════════════════════════════════

from generators.orchestrator import generate_project


@mcp.tool(
    name="fastapi_generate_project",
    tags={"generator", "orchestrator"},
    annotations={"readOnlyHint": False, "destructiveHint": False},
)
def fastapi_generate_project(
    output_dir: str,
    name: str = "app",
    prefix: str = "/api/v1",
    models: dict[str, dict[str, str]] | None = None,
    owner_models: dict[str, str] | None = None,
    with_auth: bool = True,
    with_redis: bool = False,
    cors_origins: list[str] | None = None,
    with_docker_compose: bool = True,
    with_k8s: bool = False,
    with_ci: bool = True,
) -> dict:
    """Generate a complete production-ready FastAPI project.

    One call produces 30-50 files: config, models, CRUD, auth (argon2id +
    PyJWT), middleware (CORS + security headers + correlation ID + logging),
    health checks (3-level), Dockerfile (multi-stage, non-root), Alembic
    migrations, docker-compose, and optionally K8s manifests + CI pipeline.

    The LLM should NOT modify generated infra. Customize only business logic.

    Args:
        output_dir: Where to create the project.
        name: Project/app name.
        prefix: API URL prefix (e.g. "/api/v1").
        models: Domain models. {"Product": {"name": "str", "price": "Decimal"}}
        owner_models: Which models have owner FK. {"Product": "user"}
        with_auth: Generate auth stack (password hasher, JWT, login routes).
        with_redis: Add Redis support (config, health checks, docker-compose).
        cors_origins: Allowed CORS origins. Never wildcard.
        with_docker_compose: Generate docker-compose.yml.
        with_k8s: Generate Kubernetes manifests (deployment, HPA, PDB).
        with_ci: Generate GitHub Actions CI pipeline.

    Returns:
        Dict with files_created, notes, phases, total_files.

    Example:
        fastapi_generate_project(
            output_dir="/tmp/ecommerce",
            name="ecommerce",
            models={"Product": {"name": "str", "price": "Decimal", "stock": "int"}},
            owner_models={"Product": "user"},
        )
    """
    return generate_project(
        output_dir=output_dir,
        name=name,
        prefix=prefix,
        models=models,
        owner_models=owner_models,
        with_auth=with_auth,
        with_redis=with_redis,
        cors_origins=cors_origins,
        with_docker_compose=with_docker_compose,
        with_k8s=with_k8s,
        with_ci=with_ci,
    )


# ═══════════════════════════════════════════════════════════════════════
#  TIER 2: Granular generators (for targeted generation)
# ═══════════════════════════════════════════════════════════════════════

# --- Infra ---
from generators.infra.app import generate_app
from generators.infra.config import generate_config
from generators.infra.dockerfile import generate_dockerfile


@mcp.tool(name="fastapi_generate_app", tags={"generator", "infra"})
def fastapi_generate_app(output_dir: str, name: str = "app", prefix: str = "/api/v1", with_sentry: bool = False) -> dict:
    """Generate main.py with asynccontextmanager lifespan, middleware registration, and router setup."""
    return generate_app(output_dir, name, prefix, with_sentry)


@mcp.tool(name="fastapi_generate_config", tags={"generator", "infra"})
def fastapi_generate_config(output_dir: str, with_db: bool = True, with_redis: bool = False) -> dict:
    """Generate config.py with pydantic-settings, env parsing, and fail-fast validation."""
    return generate_config(output_dir, with_db, with_redis)


@mcp.tool(name="fastapi_generate_dockerfile", tags={"generator", "infra"})
def fastapi_generate_dockerfile(output_dir: str, python_version: str = "3.12", port: int = 8000) -> dict:
    """Generate multi-stage Dockerfile with non-root user and HEALTHCHECK."""
    return generate_dockerfile(output_dir, python_version, port)


# --- Database ---
from generators.database.engine import generate_engine
from generators.database.session import generate_session
from generators.database.model import generate_model
from generators.database.crud import generate_crud
from generators.database.alembic import generate_alembic


@mcp.tool(name="fastapi_generate_model", tags={"generator", "database"})
def fastapi_generate_model(
    output_dir: str, name: str, fields: dict[str, str],
    with_timestamps: bool = True, with_soft_delete: bool = False, owner_field: str | None = None,
) -> dict:
    """Generate a SQLAlchemy ORM model with UUID PK, typed columns, and optional timestamps/soft-delete."""
    return generate_model(output_dir, name, fields, with_timestamps, with_soft_delete, owner_field)


@mcp.tool(name="fastapi_generate_crud", tags={"generator", "database"})
def fastapi_generate_crud(output_dir: str, model_name: str, with_owner_filter: bool = False) -> dict:
    """Generate CRUD layer (create/read/update/delete/list) with pagination and optional owner filtering."""
    return generate_crud(output_dir, model_name, with_owner_filter)


@mcp.tool(name="fastapi_generate_engine", tags={"generator", "database"})
def fastapi_generate_engine(output_dir: str, driver: str = "asyncpg", pool_size: int = 5) -> dict:
    """Generate async database engine with pool_pre_ping, pool_recycle, and sized connection pool."""
    return generate_engine(output_dir, driver, pool_size)


@mcp.tool(name="fastapi_generate_session", tags={"generator", "database"})
def fastapi_generate_session(output_dir: str) -> dict:
    """Generate async session factory with commit/rollback/close and SessionDep dependency."""
    return generate_session(output_dir)


@mcp.tool(name="fastapi_generate_alembic", tags={"generator", "database"})
def fastapi_generate_alembic(output_dir: str) -> dict:
    """Generate complete Alembic migration setup (alembic.ini + env.py + script template)."""
    return generate_alembic(output_dir)


# --- Auth ---
from generators.auth.hasher import generate_password_hasher
from generators.auth.jwt import generate_jwt
from generators.auth.deps import generate_auth_deps
from generators.auth.routes import generate_auth_routes
from generators.auth.schemas import generate_auth_schemas


@mcp.tool(name="fastapi_generate_auth", tags={"generator", "auth"})
def fastapi_generate_auth(output_dir: str, prefix: str = "/api/v1") -> dict:
    """Generate complete auth stack: argon2id hasher, PyJWT tokens, OAuth2 deps, login routes.

    Includes DUMMY_HASH for timing-attack prevention and password-recovery
    that never reveals email existence.
    """
    results: dict = {"files_created": [], "notes": []}
    for gen in [
        lambda: generate_password_hasher(output_dir),
        lambda: generate_jwt(output_dir),
        lambda: generate_auth_deps(output_dir, f"{prefix}/login/access-token"),
        lambda: generate_auth_routes(output_dir),
        lambda: generate_auth_schemas(output_dir),
    ]:
        r = gen()
        results["files_created"].extend(r["files_created"])
        results["notes"].extend(r.get("notes", []))
    return results


# --- Middleware ---
from generators.middleware.stack import generate_middleware_stack


@mcp.tool(name="fastapi_generate_middleware", tags={"generator", "middleware"})
def fastapi_generate_middleware(output_dir: str, cors_origins: list[str] | None = None, with_gzip: bool = False) -> dict:
    """Generate full middleware stack: CORS, security headers (7), correlation ID, request logging.

    Middleware is registered in the correct Starlette order (last added = first to execute).
    """
    return generate_middleware_stack(output_dir, cors_origins, with_gzip)


# --- Endpoints ---
from generators.endpoints.health import generate_health_checks
from generators.endpoints.errors import generate_error_handlers
from generators.endpoints.user_routes import generate_user_routes


@mcp.tool(name="fastapi_generate_user_routes", tags={"generator", "endpoints", "auth"})
def fastapi_generate_user_routes(output_dir: str, with_superuser_management: bool = True) -> dict:
    """Generate complete User management routes: signup, /me, /me/password, and superuser CRUD.

    Includes: public registration, self-management (profile, password, delete),
    and optional superuser endpoints (list, create, get, update, delete users).
    """
    return generate_user_routes(output_dir, with_superuser_management)
from generators.endpoints.crud_routes import generate_crud_routes


@mcp.tool(name="fastapi_generate_crud_routes", tags={"generator", "endpoints"})
def fastapi_generate_crud_routes(
    output_dir: str, model_name: str, fields: dict[str, str],
    auth: str = "required", owner_field: str | None = None,
) -> dict:
    """Generate complete CRUD routes for a model with auth and owner-based access control.

    Auth modes: "required" (all routes need auth), "superuser" (admin only),
    "public_read" (GET public, write needs auth), "none" (no auth).
    If owner_field is set, regular users only see/modify their own resources.
    """
    return generate_crud_routes(output_dir, model_name, fields, auth, owner_field)


@mcp.tool(name="fastapi_generate_health", tags={"generator", "endpoints"})
def fastapi_generate_health(output_dir: str, check_db: bool = True, check_redis: bool = False) -> dict:
    """Generate 3-level health checks: /healthz (liveness), /readyz (readiness), /startupz (startup)."""
    return generate_health_checks(output_dir, check_db, check_redis)


@mcp.tool(name="fastapi_generate_errors", tags={"generator", "endpoints"})
def fastapi_generate_errors(output_dir: str) -> dict:
    """Generate error handlers: HTTPException, RequestValidationError, unhandled Exception."""
    return generate_error_handlers(output_dir)


# --- Schemas ---
from generators.schemas.input_schema import generate_input_schema
from generators.schemas.output_schema import generate_output_schema
from generators.schemas.list_response import generate_list_response


@mcp.tool(name="fastapi_generate_schemas", tags={"generator", "schemas"})
def fastapi_generate_schemas(output_dir: str, name: str, fields: dict[str, str]) -> dict:
    """Generate input (Create/Update), output (Public), and list ({data, count}) schemas for a model.

    Input schemas use strict=True with max_length on all strings and min/max on numbers.
    Output schemas use from_attributes=True and never expose hashed_password.
    """
    results: dict = {"files_created": [], "notes": []}
    for gen in [
        lambda: generate_input_schema(output_dir, name, fields),
        lambda: generate_output_schema(output_dir, name, fields),
        lambda: generate_list_response(output_dir, name),
    ]:
        r = gen()
        results["files_created"].extend(r["files_created"])
        results["notes"].extend(r.get("notes", []))
    return results


# --- Deployment ---

@mcp.tool(name="fastapi_generate_docker_compose", tags={"generator", "deployment"})
def fastapi_generate_docker_compose(output_dir: str, redis: bool = False) -> dict:
    """Generate docker-compose.yml with app, postgres, and optional redis services."""
    from generators.deployment.docker_compose import generate_docker_compose
    return generate_docker_compose(output_dir, redis=redis)


@mcp.tool(name="fastapi_generate_k8s", tags={"generator", "deployment"})
def fastapi_generate_k8s(output_dir: str, app_name: str = "fastapi-app", replicas: int = 2) -> dict:
    """Generate K8s manifests: Deployment, Service, HPA, PDB, ConfigMap, Secret."""
    from generators.deployment.k8s import generate_k8s_manifests
    return generate_k8s_manifests(output_dir, app_name, replicas=replicas)


@mcp.tool(name="fastapi_generate_ci", tags={"generator", "deployment"})
def fastapi_generate_ci(output_dir: str, python_version: str = "3.12") -> dict:
    """Generate GitHub Actions CI: lint (ruff+mypy), test (pytest+postgres), build (Docker), scan (Trivy)."""
    from generators.deployment.github_actions import generate_github_actions
    return generate_github_actions(output_dir, python_version)


@mcp.tool(name="fastapi_generate_loadtest", tags={"generator", "deployment"})
def fastapi_generate_loadtest(output_dir: str, base_url: str = "http://localhost:8000") -> dict:
    """Generate k6 load test with ramp/spike/recovery stages and SLA thresholds."""
    from generators.deployment.k6_loadtest import generate_k6_loadtest
    return generate_k6_loadtest(output_dir, base_url)


# --- Observability ---

@mcp.tool(name="fastapi_generate_otel", tags={"generator", "observability"})
def fastapi_generate_otel(output_dir: str, service_name: str = "fastapi-app") -> dict:
    """Generate OpenTelemetry setup: TracerProvider, BatchSpanProcessor, auto-instrumentation."""
    from generators.observability.otel import generate_otel_setup
    return generate_otel_setup(output_dir, service_name)


@mcp.tool(name="fastapi_generate_prometheus", tags={"generator", "observability"})
def fastapi_generate_prometheus(output_dir: str, prefix: str = "fastapi") -> dict:
    """Generate Prometheus RED metrics (Rate/Errors/Duration) with middleware and /metrics endpoint."""
    from generators.observability.prometheus import generate_prometheus_metrics
    return generate_prometheus_metrics(output_dir, prefix)


@mcp.tool(name="fastapi_generate_alerting", tags={"generator", "observability"})
def fastapi_generate_alerting(output_dir: str, service_name: str = "fastapi-app") -> dict:
    """Generate PrometheusRule alerts (5 rules) and Grafana dashboard (4 panels)."""
    from generators.observability.alerting import generate_alerting_rules
    return generate_alerting_rules(output_dir, service_name)


# --- Project files ---

from generators.infra.env_example import generate_env_example
from generators.infra.initial_data import generate_initial_data
from generators.infra.prestart import generate_prestart
from generators.infra.readme import generate_readme
from generators.infra.precommit import generate_precommit
from generators.infra.email import generate_email_utils
from generators.infra.gitignore import generate_gitignore


@mcp.tool(name="fastapi_generate_env_example", tags={"generator", "infra"})
def fastapi_generate_env_example(output_dir: str, with_redis: bool = False) -> dict:
    """Generate .env.example with all required environment variables and safe placeholders."""
    return generate_env_example(output_dir, with_redis=with_redis)


@mcp.tool(name="fastapi_generate_initial_data", tags={"generator", "infra"})
def fastapi_generate_initial_data(output_dir: str) -> dict:
    """Generate initial_data.py — idempotent superuser seeding script for first boot."""
    return generate_initial_data(output_dir)


@mcp.tool(name="fastapi_generate_prestart", tags={"generator", "infra"})
def fastapi_generate_prestart(output_dir: str) -> dict:
    """Generate backend_pre_start.py — waits for database readiness with exponential backoff."""
    return generate_prestart(output_dir)


@mcp.tool(name="fastapi_generate_readme", tags={"generator", "infra"})
def fastapi_generate_readme(output_dir: str, name: str = "app") -> dict:
    """Generate README.md with quick start, env reference, project structure, and deployment guide."""
    return generate_readme(output_dir, name=name)


@mcp.tool(name="fastapi_generate_email", tags={"generator", "infra"})
def fastapi_generate_email(output_dir: str) -> dict:
    """Generate email utilities: SMTP sender, password reset email, welcome email with HTML templates."""
    return generate_email_utils(output_dir)


@mcp.tool(name="fastapi_generate_gitignore", tags={"generator", "infra"})
def fastapi_generate_gitignore(output_dir: str) -> dict:
    """Generate .gitignore with Python, virtualenv, IDE, .env, database, testing, Docker exclusions."""
    return generate_gitignore(output_dir)


@mcp.tool(name="fastapi_generate_precommit", tags={"generator", "infra"})
def fastapi_generate_precommit(output_dir: str) -> dict:
    """Generate .pre-commit-config.yaml with Ruff linting/formatting and pre-commit hooks."""
    return generate_precommit(output_dir)


# --- Testing ---

from generators.testing.conftest import generate_test_infrastructure
from generators.testing.test_suite import generate_test_suite


@mcp.tool(name="fastapi_generate_tests", tags={"generator", "testing"})
def fastapi_generate_tests(
    output_dir: str, models: dict[str, dict[str, str]] | None = None,
    owner_models: dict[str, str] | None = None, with_auth: bool = True,
) -> dict:
    """Generate complete test infrastructure + test suite.

    Produces: conftest.py (async SQLite, fixtures for superuser/regular tokens),
    test_login.py (5 tests), test_users.py (8 tests), and test_{model}.py (6 tests each).
    """
    results: dict = {"files_created": [], "notes": []}
    r1 = generate_test_infrastructure(output_dir, with_auth=with_auth)
    results["files_created"].extend(r1["files_created"])
    results["notes"].extend(r1.get("notes", []))
    if models or with_auth:
        r2 = generate_test_suite(output_dir, models=models, owner_models=owner_models, with_auth=with_auth)
        results["files_created"].extend(r2["files_created"])
        results["notes"].extend(r2.get("notes", []))
    return results


# ═══════════════════════════════════════════════════════════════════════
#  TIER 3: Verification (audit existing projects)
# ═══════════════════════════════════════════════════════════════════════

from benchmark.analyzer import analyze


@mcp.tool(
    name="fastapi_analyze",
    tags={"verify", "audit"},
    annotations={"readOnlyHint": True, "destructiveHint": False},
)
def fastapi_analyze(project_path: str) -> dict:
    """Audit a FastAPI project against 35 production-readiness checks.

    Categories: Security (10), Database (6), API Design (4),
    Infrastructure (5), Deployment (5), Code Quality (5).

    Returns score, per-category breakdown, and actionable failures.
    Use AFTER generating or writing code to verify quality.

    Example: fastapi_analyze("/path/to/my-project")
    """
    result = analyze(project_path)
    return {
        "score": f"{result.passed}/{result.total} ({result.score:.0f}%)",
        "categories": {
            cat: {"passed": p, "total": t, "status": "pass" if p == t else "fail"}
            for cat, (p, t) in result.by_category().items()
        },
        "failures": [
            {"check": c.name, "category": c.category, "detail": c.detail}
            for c in result.checks if not c.passed
        ],
        "total_checks": result.total,
        "passed_checks": result.passed,
    }


# ═══════════════════════════════════════════════════════════════════════
#  TIER 3b: Adapt + Refactor (work on existing projects)
# ═══════════════════════════════════════════════════════════════════════

try:
    from generators.tools.add_model import add_model

    @mcp.tool(
        name="fastapi_add_model",
        tags={"adapt", "operate"},
        annotations={"readOnlyHint": False},
    )
    def fastapi_add_model(
        project_dir: str, name: str, fields: dict[str, str], owner_field: str | None = None,
    ) -> dict:
        """Add a complete model to an EXISTING project.

        Generates model + CRUD + schemas + routes, then updates the router
        registry and models/__init__.py. One call, fully wired.

        Example: fastapi_add_model("/my-project", "Review", {"rating": "int", "comment": "text"}, owner_field="user")
        """
        return add_model(project_dir, name, fields, owner_field)
except ImportError:
    pass

try:
    from generators.tools.fix_findings import fix_findings

    @mcp.tool(
        name="fastapi_fix_findings",
        tags={"refactor", "operate"},
        annotations={"readOnlyHint": False},
    )
    def fastapi_fix_findings(project_dir: str) -> dict:
        """Auto-fix production readiness findings in an existing project.

        Runs the 35-check analyzer, then applies automatic fixes:
        migrates bcrypt→argon2id, python-jose→PyJWT, adds security headers,
        structured logging, health checks, multi-stage Docker, etc.

        Returns: fixed count, manual-fix-required list, score before/after.
        """
        return fix_findings(project_dir)
except ImportError:
    pass

try:
    from generators.tools.add_endpoint import add_endpoint

    @mcp.tool(name="fastapi_add_endpoint", tags={"adapt"}, annotations={"readOnlyHint": False})
    def fastapi_add_endpoint(
        project_dir: str, route_file: str, method: str, path: str, name: str,
        auth: str = "required", request_body: dict[str, str] | None = None,
        response_model: str | None = None, description: str = "",
    ) -> dict:
        """Add a custom endpoint to an existing route file.

        Scaffolds the function with proper imports, auth, error handling.
        Generates inline Pydantic model if request_body is provided.
        """
        return add_endpoint(project_dir, route_file, method, path, name, auth, request_body, response_model, description)
except ImportError:
    pass

try:
    from generators.tools.add_middleware import add_middleware

    @mcp.tool(name="fastapi_add_middleware", tags={"adapt"}, annotations={"readOnlyHint": False})
    def fastapi_add_middleware(project_dir: str, name: str, code: str, position: str = "before_logging") -> dict:
        """Add custom middleware to the stack at the correct position.

        Positions: "outermost", "after_cors", "before_logging" (default), "innermost".
        Writes the middleware file and updates register_middleware().
        """
        return add_middleware(project_dir, name, code, position)
except ImportError:
    pass

try:
    from generators.tools.migrate_db import generate_migration

    @mcp.tool(name="fastapi_migrate_db", tags={"adapt", "database"}, annotations={"readOnlyHint": False})
    def fastapi_migrate_db(project_dir: str, message: str | None = None) -> dict:
        """Generate Alembic migration script and helper commands.

        Creates scripts/create_migration.sh and returns the exact commands
        to run for autogenerate + review + upgrade.
        """
        return generate_migration(project_dir, message)
except ImportError:
    pass

try:
    from generators.tools.add_background_job import add_background_job

    @mcp.tool(name="fastapi_add_background_job", tags={"adapt"}, annotations={"readOnlyHint": False})
    def fastapi_add_background_job(
        project_dir: str, name: str, queue: str = "default", retry_max: int = 3, cron: str | None = None,
    ) -> dict:
        """Add a background job using ARQ (async Redis queue).

        Generates worker.py (if first job), core/arq.py, and jobs/{name}.py.
        Optionally adds cron scheduling. Includes retry + dead letter patterns.
        """
        return add_background_job(project_dir, name, queue, retry_max, cron)
except ImportError:
    pass

try:
    from generators.tools.add_websocket import add_websocket

    @mcp.tool(name="fastapi_add_websocket", tags={"adapt"}, annotations={"readOnlyHint": False})
    def fastapi_add_websocket(project_dir: str, name: str, path: str = "/ws", auth: bool = True) -> dict:
        """Add a WebSocket endpoint with connection manager, rooms, heartbeat, and optional JWT auth."""
        return add_websocket(project_dir, name, path, auth)
except ImportError:
    pass

try:
    from generators.tools.add_integration import add_integration

    @mcp.tool(name="fastapi_add_integration", tags={"adapt"}, annotations={"readOnlyHint": False})
    def fastapi_add_integration(project_dir: str, service: str, config: dict | None = None) -> dict:
        """Add external service integration (Stripe, S3, SendGrid, Redis cache).

        Generates client wrapper, config entries, and optional webhook routes.
        Services: "stripe", "s3", "sendgrid", "redis".
        """
        return add_integration(project_dir, service, config)
except ImportError:
    pass


# ═══════════════════════════════════════════════════════════════════════
#  TIER 4: Pentest + Operate (runtime tools)
# ═══════════════════════════════════════════════════════════════════════

try:
    from modules.security.tools.pentest_api import run_all_tests as _pentest_run_all
    import asyncio as _asyncio

    @mcp.tool(
        name="fastapi_pentest",
        tags={"security", "pentest", "runtime"},
        annotations={"readOnlyHint": True},
    )
    def fastapi_pentest(base_url: str) -> dict:
        """Run security penetration tests against a running FastAPI instance.

        Tests: SQL injection, security headers, CORS bypass, rate limiting,
        body size limits, error information disclosure. Returns findings
        with severity levels.
        """
        results = _asyncio.run(_pentest_run_all(base_url))
        return results.model_dump(mode="json") if hasattr(results, 'model_dump') else results
except ImportError:
    pass

try:
    from modules.database.tools.operate_db import (
        check_pool_health,
        find_slow_queries,
        analyze_query,
        check_table_bloat,
        suggest_indexes,
    )

    @mcp.tool(name="fastapi_db_health", tags={"operate", "database"}, annotations={"readOnlyHint": True})
    def fastapi_db_health(db_url: str) -> dict:
        """Check PostgreSQL connection pool health: active/idle/waiting connections, pool utilization."""
        return check_pool_health(db_url)

    @mcp.tool(name="fastapi_db_slow_queries", tags={"operate", "database"}, annotations={"readOnlyHint": True})
    def fastapi_db_slow_queries(db_url: str, min_duration_ms: float = 100) -> list[dict]:
        """Find slow queries from pg_stat_statements. Requires pg_stat_statements extension."""
        return find_slow_queries(db_url, min_duration_ms=min_duration_ms)

    @mcp.tool(name="fastapi_db_explain", tags={"operate", "database"}, annotations={"readOnlyHint": True})
    def fastapi_db_explain(db_url: str, sql: str) -> dict:
        """Run EXPLAIN ANALYZE on a query and interpret the execution plan."""
        return analyze_query(db_url, sql)

    @mcp.tool(name="fastapi_db_bloat", tags={"operate", "database"}, annotations={"readOnlyHint": True})
    def fastapi_db_bloat(db_url: str) -> list[dict]:
        """Check table bloat — identifies tables that need VACUUM."""
        return check_table_bloat(db_url)

    @mcp.tool(name="fastapi_db_suggest_indexes", tags={"operate", "database"}, annotations={"readOnlyHint": True})
    def fastapi_db_suggest_indexes(db_url: str) -> list[dict]:
        """Suggest missing indexes based on sequential scan patterns."""
        return suggest_indexes(db_url)
except ImportError:
    pass


# ═══════════════════════════════════════════════════════════════════════
#  TIER 5: Legacy v2 tools
# ═══════════════════════════════════════════════════════════════════════

try:
    from core.tools.analyze import analyze_project
    from core.models import ScaffoldInput

    @mcp.tool(
        name="fastapi_analyze_project_v2",
        tags={"verify", "legacy"},
        annotations={"readOnlyHint": True},
    )
    def fastapi_analyze_project_v2(project_path: str) -> dict:
        """[Legacy v2] AST-based analysis of 8 core patterns. Use fastapi_analyze for the 35-check v3 audit."""
        result = analyze_project(project_path)
        return result.model_dump(mode="json")
except ImportError:
    pass

try:
    from core.tools.runtime import check_health, check_security_headers
    import asyncio

    @mcp.tool(name="fastapi_check_health", tags={"verify", "runtime"}, annotations={"readOnlyHint": True})
    def fastapi_check_health(base_url: str) -> list[dict]:
        """Check 3-level health endpoints (/healthz, /readyz, /startupz) of a running instance."""
        results = asyncio.run(check_health(base_url))
        return [r.model_dump(mode="json") for r in results]

    @mcp.tool(name="fastapi_check_headers", tags={"verify", "runtime"}, annotations={"readOnlyHint": True})
    def fastapi_check_headers(base_url: str) -> dict:
        """Check security headers and CORS of a running instance."""
        result = asyncio.run(check_security_headers(base_url))
        return result.model_dump(mode="json")
except ImportError:
    pass


# ═══════════════════════════════════════════════════════════════════════
#  TIER 6: Adapt tools — 51 tools for extending existing projects
# ═══════════════════════════════════════════════════════════════════════

# ── EXTEND > CRUD & Data ────────────────────────────────────────────────

@mcp.tool(name="fastapi_add_soft_delete", tags={"adapt", "extend", "crud"})
def fastapi_add_soft_delete(project_dir: str, dry_run: bool = False) -> dict:
    """Add soft delete to all models in the project.

    Adds SoftDeleteMixin, SQLAlchemy event filter, CRUD helpers,
    restore/permanent-delete routes, and Alembic migration.
    """
    from adapt.extend.crud_data.add_soft_delete import add_soft_delete
    from adapt.contracts import ToolInput
    result = add_soft_delete(ToolInput(project_dir=project_dir, dry_run=dry_run))
    return result.model_dump()


@mcp.tool(name="fastapi_add_cursor_pagination", tags={"adapt", "extend", "crud"})
def fastapi_add_cursor_pagination(project_dir: str, dry_run: bool = False) -> dict:
    """Replace offset pagination with cursor-based pagination across all list endpoints.

    Generates CursorPage schema, updates CRUD list methods, and patches routes
    to use opaque cursor tokens — safe for large datasets.
    """
    from adapt.extend.crud_data.add_cursor_pagination import add_cursor_pagination
    from adapt.contracts import ToolInput
    result = add_cursor_pagination(ToolInput(project_dir=project_dir, dry_run=dry_run))
    return result.model_dump()


@mcp.tool(name="fastapi_add_file_upload", tags={"adapt", "extend", "crud"})
def fastapi_add_file_upload(project_dir: str, dry_run: bool = False) -> dict:
    """Add file upload support (multipart/form-data) with S3-compatible storage backend.

    Generates upload routes, storage client wrapper, MIME validation,
    size limits, and a File model for tracking uploads.
    """
    from adapt.extend.crud_data.add_file_upload import add_file_upload
    from adapt.contracts import ToolInput
    result = add_file_upload(ToolInput(project_dir=project_dir, dry_run=dry_run))
    return result.model_dump()


@mcp.tool(name="fastapi_add_search", tags={"adapt", "extend", "crud"})
def fastapi_add_search(project_dir: str, dry_run: bool = False) -> dict:
    """Add full-text search endpoints backed by PostgreSQL tsvector or Elasticsearch.

    Generates search route, query parser, result ranking, and highlight
    support. Includes Alembic migration for tsvector columns and GIN index.
    """
    from adapt.extend.crud_data.add_search import add_search
    from adapt.contracts import ToolInput
    result = add_search(ToolInput(project_dir=project_dir, dry_run=dry_run))
    return result.model_dump()


@mcp.tool(name="fastapi_add_audit_log", tags={"adapt", "extend", "crud"})
def fastapi_add_audit_log(project_dir: str, dry_run: bool = False) -> dict:
    """Add immutable audit log to record all create/update/delete operations.

    Generates AuditLog model, SQLAlchemy event listeners, and query routes
    for reviewing history per resource and per actor.
    """
    from adapt.extend.crud_data.add_audit_log import add_audit_log
    from adapt.contracts import ToolInput
    result = add_audit_log(ToolInput(project_dir=project_dir, dry_run=dry_run))
    return result.model_dump()


@mcp.tool(name="fastapi_add_data_export", tags={"adapt", "extend", "crud"})
def fastapi_add_data_export(project_dir: str, dry_run: bool = False) -> dict:
    """Add CSV/XLSX data export endpoints for all major resources.

    Generates async export routes with streaming response, column selection,
    filter passthrough, and optional background task for large exports.
    """
    from adapt.extend.crud_data.add_data_export import add_data_export
    from adapt.contracts import ToolInput
    result = add_data_export(ToolInput(project_dir=project_dir, dry_run=dry_run))
    return result.model_dump()


@mcp.tool(name="fastapi_add_bulk_operations", tags={"adapt", "extend", "crud"})
def fastapi_add_bulk_operations(project_dir: str, dry_run: bool = False) -> dict:
    """Add bulk create/update/delete endpoints for all models.

    Generates bulk route handlers with atomic transactions, partial success
    reporting, and validation error aggregation per item.
    """
    from adapt.extend.crud_data.add_bulk_operations import add_bulk_operations
    from adapt.contracts import ToolInput
    result = add_bulk_operations(ToolInput(project_dir=project_dir, dry_run=dry_run))
    return result.model_dump()


# ── EXTEND > Auth & Access ──────────────────────────────────────────────

@mcp.tool(name="fastapi_add_multi_tenancy", tags={"adapt", "extend", "auth"})
def fastapi_add_multi_tenancy(project_dir: str, dry_run: bool = False) -> dict:
    """Add multi-tenancy support with schema-per-tenant or row-level isolation.

    Generates Tenant model, tenant resolver middleware, scoped CRUD helpers,
    and tenant-aware Alembic migration scripts.
    """
    from adapt.extend.auth_access.add_multi_tenancy import add_multi_tenancy
    from adapt.contracts import ToolInput
    result = add_multi_tenancy(ToolInput(project_dir=project_dir, dry_run=dry_run))
    return result.model_dump()


@mcp.tool(name="fastapi_add_feature_flags", tags={"adapt", "extend", "auth"})
def fastapi_add_feature_flags(project_dir: str, dry_run: bool = False) -> dict:
    """Add feature flag system with per-user, per-tenant, and global toggles.

    Generates FeatureFlag model, flag evaluation dependency, management routes,
    and optional Redis caching for flag states.
    """
    from adapt.extend.auth_access.add_feature_flags import add_feature_flags
    from adapt.contracts import ToolInput
    result = add_feature_flags(ToolInput(project_dir=project_dir, dry_run=dry_run))
    return result.model_dump()


@mcp.tool(name="fastapi_add_api_key_auth", tags={"adapt", "extend", "auth"})
def fastapi_add_api_key_auth(project_dir: str, dry_run: bool = False) -> dict:
    """Add API key authentication alongside the existing JWT auth.

    Generates ApiKey model with hashed storage, key generation endpoint,
    dependency for key validation, and per-key rate limiting support.
    """
    from adapt.extend.auth_access.add_api_key_auth import add_api_key_auth
    from adapt.contracts import ToolInput
    result = add_api_key_auth(ToolInput(project_dir=project_dir, dry_run=dry_run))
    return result.model_dump()


@mcp.tool(name="fastapi_add_oauth2_provider", tags={"adapt", "extend", "auth"})
def fastapi_add_oauth2_provider(project_dir: str, dry_run: bool = False) -> dict:
    """Add OAuth2 provider (authorization server) capabilities to the project.

    Generates authorization code flow, client credentials flow, token
    introspection, and revocation endpoints per RFC 6749/7662.
    """
    from adapt.extend.auth_access.add_oauth2_provider import add_oauth2_provider
    from adapt.contracts import ToolInput
    result = add_oauth2_provider(ToolInput(project_dir=project_dir, dry_run=dry_run))
    return result.model_dump()


@mcp.tool(name="fastapi_add_rbac", tags={"adapt", "extend", "auth"})
def fastapi_add_rbac(project_dir: str, dry_run: bool = False) -> dict:
    """Add role-based access control (RBAC) with hierarchical roles and permissions.

    Generates Role and Permission models, assignment endpoints, Casbin or
    custom policy evaluator, and FastAPI dependencies for route-level guards.
    """
    from adapt.extend.auth_access.add_rbac import add_rbac
    from adapt.contracts import ToolInput
    result = add_rbac(ToolInput(project_dir=project_dir, dry_run=dry_run))
    return result.model_dump()


@mcp.tool(name="fastapi_add_mfa", tags={"adapt", "extend", "auth"})
def fastapi_add_mfa(project_dir: str, dry_run: bool = False) -> dict:
    """Add multi-factor authentication (TOTP + backup codes) to the auth stack.

    Generates TOTP setup/verify/disable routes, encrypted secret storage,
    backup code generation and redemption, and MFA enforcement middleware.
    """
    from adapt.extend.auth_access.add_mfa import add_mfa
    from adapt.contracts import ToolInput
    result = add_mfa(ToolInput(project_dir=project_dir, dry_run=dry_run))
    return result.model_dump()


# ── EXTEND > Real-time ──────────────────────────────────────────────────

@mcp.tool(name="fastapi_add_sse", tags={"adapt", "extend", "realtime"})
def fastapi_add_sse(project_dir: str, dry_run: bool = False) -> dict:
    """Add Server-Sent Events (SSE) endpoints for real-time push to browser clients.

    Generates SSE router, event bus (Redis Pub/Sub backed), connection manager,
    and typed event schemas with automatic reconnection support.
    """
    from adapt.extend.realtime.add_sse import add_sse
    from adapt.contracts import ToolInput
    result = add_sse(ToolInput(project_dir=project_dir, dry_run=dry_run))
    return result.model_dump()


@mcp.tool(name="fastapi_add_webhook_sender", tags={"adapt", "extend", "realtime"})
def fastapi_add_webhook_sender(project_dir: str, dry_run: bool = False) -> dict:
    """Add outbound webhook delivery system with retry, signature, and delivery log.

    Generates WebhookEndpoint model, async dispatcher, HMAC-SHA256 signing,
    exponential backoff retry, and delivery history endpoints.
    """
    from adapt.extend.realtime.add_webhook_sender import add_webhook_sender
    from adapt.contracts import ToolInput
    result = add_webhook_sender(ToolInput(project_dir=project_dir, dry_run=dry_run))
    return result.model_dump()


@mcp.tool(name="fastapi_add_webhook_receiver", tags={"adapt", "extend", "realtime"})
def fastapi_add_webhook_receiver(project_dir: str, dry_run: bool = False) -> dict:
    """Add inbound webhook receiver with signature verification and idempotency.

    Generates receiver routes, HMAC signature validator, idempotency key
    deduplication, and async event dispatch to internal handlers.
    """
    from adapt.extend.realtime.add_webhook_receiver import add_webhook_receiver
    from adapt.contracts import ToolInput
    result = add_webhook_receiver(ToolInput(project_dir=project_dir, dry_run=dry_run))
    return result.model_dump()


# ── EXTEND > API Design ─────────────────────────────────────────────────

@mcp.tool(name="fastapi_add_api_versioning", tags={"adapt", "extend", "api_design"})
def fastapi_add_api_versioning(project_dir: str, dry_run: bool = False) -> dict:
    """Add URL-based API versioning (/api/v1, /api/v2) with deprecation headers.

    Refactors routers into versioned modules, adds Sunset and Deprecation
    response headers, and generates version negotiation middleware.
    """
    from adapt.extend.api_design.add_api_versioning import add_api_versioning
    from adapt.contracts import ToolInput
    result = add_api_versioning(ToolInput(project_dir=project_dir, dry_run=dry_run))
    return result.model_dump()


@mcp.tool(name="fastapi_add_graphql", tags={"adapt", "extend", "api_design"})
def fastapi_add_graphql(project_dir: str, dry_run: bool = False) -> dict:
    """Add GraphQL endpoint (Strawberry) alongside the existing REST API.

    Generates schema types from SQLAlchemy models, resolvers with DataLoader
    for N+1 prevention, and mounts /graphql with GraphiQL in development.
    """
    from adapt.extend.api_design.add_graphql import add_graphql
    from adapt.contracts import ToolInput
    result = add_graphql(ToolInput(project_dir=project_dir, dry_run=dry_run))
    return result.model_dump()


@mcp.tool(name="fastapi_add_batch_endpoint", tags={"adapt", "extend", "api_design"})
def fastapi_add_batch_endpoint(project_dir: str, dry_run: bool = False) -> dict:
    """Add a generic batch request endpoint that fans out to multiple sub-requests.

    Generates POST /batch accepting an array of {method, path, body} items,
    with parallel execution, per-request error isolation, and shared auth context.
    """
    from adapt.extend.api_design.add_batch_endpoint import add_batch_endpoint
    from adapt.contracts import ToolInput
    result = add_batch_endpoint(ToolInput(project_dir=project_dir, dry_run=dry_run))
    return result.model_dump()


@mcp.tool(name="fastapi_add_long_running_task", tags={"adapt", "extend", "api_design"})
def fastapi_add_long_running_task(project_dir: str, dry_run: bool = False) -> dict:
    """Add async long-running task pattern with polling endpoint and status tracking.

    Generates task submission endpoint, ARQ/Celery worker integration,
    Task model with status/progress/result, and GET /tasks/{id} polling route.
    """
    from adapt.extend.api_design.add_long_running_task import add_long_running_task
    from adapt.contracts import ToolInput
    result = add_long_running_task(ToolInput(project_dir=project_dir, dry_run=dry_run))
    return result.model_dump()


# ── EXTEND > Infrastructure ─────────────────────────────────────────────

@mcp.tool(name="fastapi_add_cache_layer", tags={"adapt", "extend", "infrastructure"})
def fastapi_add_cache_layer(project_dir: str, dry_run: bool = False) -> dict:
    """Add Redis caching layer with decorator, invalidation strategy, and TTL management.

    Generates cache dependency, @cached decorator, cache key builder,
    pattern-based invalidation helpers, and cache hit/miss metrics.
    """
    from adapt.extend.infrastructure.add_cache_layer import add_cache_layer
    from adapt.contracts import ToolInput
    result = add_cache_layer(ToolInput(project_dir=project_dir, dry_run=dry_run))
    return result.model_dump()


@mcp.tool(name="fastapi_add_circuit_breaker", tags={"adapt", "extend", "infrastructure"})
def fastapi_add_circuit_breaker(project_dir: str, dry_run: bool = False) -> dict:
    """Add circuit breaker pattern to all external service calls.

    Generates CircuitBreaker wrapper (pybreaker or native), per-service state
    tracking, half-open probe logic, and /health integration for breaker status.
    """
    from adapt.extend.infrastructure.add_circuit_breaker import add_circuit_breaker
    from adapt.contracts import ToolInput
    result = add_circuit_breaker(ToolInput(project_dir=project_dir, dry_run=dry_run))
    return result.model_dump()


@mcp.tool(name="fastapi_add_outbox_pattern", tags={"adapt", "extend", "infrastructure"})
def fastapi_add_outbox_pattern(project_dir: str, dry_run: bool = False) -> dict:
    """Add transactional outbox pattern for reliable event publishing.

    Generates OutboxEvent model, within-transaction event writing, relay worker,
    and at-least-once delivery guarantee for domain events to message brokers.
    """
    from adapt.extend.infrastructure.add_outbox_pattern import add_outbox_pattern
    from adapt.contracts import ToolInput
    result = add_outbox_pattern(ToolInput(project_dir=project_dir, dry_run=dry_run))
    return result.model_dump()


@mcp.tool(name="fastapi_add_saga", tags={"adapt", "extend", "infrastructure"})
def fastapi_add_saga(project_dir: str, dry_run: bool = False) -> dict:
    """Add saga orchestration pattern for distributed transaction management.

    Generates Saga coordinator, step definitions with compensating transactions,
    SagaExecution model for state tracking, and rollback orchestration logic.
    """
    from adapt.extend.infrastructure.add_saga import add_saga
    from adapt.contracts import ToolInput
    result = add_saga(ToolInput(project_dir=project_dir, dry_run=dry_run))
    return result.model_dump()


# ── EXTEND > Testing ────────────────────────────────────────────────────

@mcp.tool(name="fastapi_add_factory", tags={"adapt", "extend", "testing"})
def fastapi_add_factory(project_dir: str, dry_run: bool = False) -> dict:
    """Add factory_boy fixtures for all models to accelerate test authoring.

    Generates ModelFactory classes with Faker-based field defaults, nested
    factory support, and pytest fixtures for each factory.
    """
    from adapt.extend.testing_tools.add_factory import add_factory
    from adapt.contracts import ToolInput
    result = add_factory(ToolInput(project_dir=project_dir, dry_run=dry_run))
    return result.model_dump()


@mcp.tool(name="fastapi_add_contract_tests", tags={"adapt", "extend", "testing"})
def fastapi_add_contract_tests(project_dir: str, dry_run: bool = False) -> dict:
    """Add consumer-driven contract tests using Pact or Schemathesis.

    Generates contract test suite against the OpenAPI spec, provider verification
    setup, and CI step for contract validation on every push.
    """
    from adapt.extend.testing_tools.add_contract_tests import add_contract_tests
    from adapt.contracts import ToolInput
    result = add_contract_tests(ToolInput(project_dir=project_dir, dry_run=dry_run))
    return result.model_dump()


@mcp.tool(name="fastapi_add_load_profile", tags={"adapt", "extend", "testing"})
def fastapi_add_load_profile(project_dir: str, dry_run: bool = False) -> dict:
    """Add k6 load test profiles (smoke, load, stress, soak) for the project's endpoints.

    Generates scenario scripts with realistic think times, SLA thresholds,
    and a GitHub Actions workflow for scheduled soak tests.
    """
    from adapt.extend.testing_tools.add_load_profile import add_load_profile
    from adapt.contracts import ToolInput
    result = add_load_profile(ToolInput(project_dir=project_dir, dry_run=dry_run))
    return result.model_dump()


# ── VERIFY ──────────────────────────────────────────────────────────────

@mcp.tool(
    name="fastapi_detect_n_plus_one",
    tags={"adapt", "verify"},
    annotations={"readOnlyHint": True},
)
def fastapi_detect_n_plus_one(project_dir: str, dry_run: bool = False) -> dict:
    """Detect N+1 query patterns in SQLAlchemy ORM code.

    Performs static analysis to find relationships accessed in loops without
    eager loading, and suggests joinedload/selectinload fixes per finding.
    """
    from adapt.verify.detect_n_plus_one import detect_n_plus_one
    from adapt.contracts import ToolInput
    result = detect_n_plus_one(ToolInput(project_dir=project_dir, dry_run=dry_run))
    return result.model_dump()


@mcp.tool(
    name="fastapi_security_scan",
    tags={"adapt", "verify", "security"},
    annotations={"readOnlyHint": True},
)
def fastapi_security_scan(project_dir: str, dry_run: bool = False) -> dict:
    """Run security-focused static analysis on the FastAPI project.

    Checks for hardcoded secrets, unsafe deserialization, SQL injection
    vectors, insecure defaults, and OWASP Top 10 patterns.
    """
    from adapt.verify.security_scan import security_scan
    from adapt.contracts import ToolInput
    result = security_scan(ToolInput(project_dir=project_dir, dry_run=dry_run))
    return result.model_dump()


@mcp.tool(
    name="fastapi_dependency_audit",
    tags={"adapt", "verify"},
    annotations={"readOnlyHint": True},
)
def fastapi_dependency_audit(project_dir: str, dry_run: bool = False) -> dict:
    """Audit Python dependencies for vulnerabilities and outdated packages.

    Runs pip-audit / safety against requirements files, reports CVEs with
    severity, and suggests pinned upgrade versions where available.
    """
    from adapt.verify.dependency_audit import dependency_audit
    from adapt.contracts import ToolInput
    result = dependency_audit(ToolInput(project_dir=project_dir, dry_run=dry_run))
    return result.model_dump()


@mcp.tool(
    name="fastapi_schema_coverage",
    tags={"adapt", "verify"},
    annotations={"readOnlyHint": True},
)
def fastapi_schema_coverage(project_dir: str, dry_run: bool = False) -> dict:
    """Measure how well the OpenAPI schema covers all routes and models.

    Checks for missing response schemas, undocumented error codes, missing
    examples, and incomplete request body descriptions.
    """
    from adapt.verify.schema_coverage import schema_coverage
    from adapt.contracts import ToolInput
    result = schema_coverage(ToolInput(project_dir=project_dir, dry_run=dry_run))
    return result.model_dump()


@mcp.tool(
    name="fastapi_test_coverage_gaps",
    tags={"adapt", "verify"},
    annotations={"readOnlyHint": True},
)
def fastapi_test_coverage_gaps(project_dir: str, dry_run: bool = False) -> dict:
    """Identify test coverage gaps with risk-weighted analysis.

    Parses coverage.xml (branch coverage), applies risk weights (auth/payment/
    admin = 2x), diffs against baseline, and produces a ranked gap list.
    """
    from adapt.verify.test_coverage_gaps import test_coverage_gaps
    from adapt.contracts import ToolInput
    result = test_coverage_gaps(ToolInput(project_dir=project_dir, dry_run=dry_run))
    return result.model_dump()


@mcp.tool(
    name="fastapi_api_spec_compliance",
    tags={"adapt", "verify"},
    annotations={"readOnlyHint": True},
)
def fastapi_api_spec_compliance(project_dir: str, dry_run: bool = False) -> dict:
    """Check that the running API conforms to its own OpenAPI specification.

    Validates response schemas, status codes, and content types against the
    spec using Schemathesis-style contract testing.
    """
    from adapt.verify.api_spec_compliance import api_spec_compliance
    from adapt.contracts import ToolInput
    result = api_spec_compliance(ToolInput(project_dir=project_dir, dry_run=dry_run))
    return result.model_dump()


@mcp.tool(
    name="fastapi_performance_baseline",
    tags={"adapt", "verify"},
    annotations={"readOnlyHint": True},
)
def fastapi_performance_baseline(project_dir: str, dry_run: bool = False) -> dict:
    """Establish a performance baseline by profiling key endpoints.

    Runs lightweight benchmarks against the project's routes, records p50/p95/
    p99 latencies, and writes a baseline JSON for future regression detection.
    """
    from adapt.verify.performance_baseline import performance_baseline
    from adapt.contracts import ToolInput
    result = performance_baseline(ToolInput(project_dir=project_dir, dry_run=dry_run))
    return result.model_dump()


# ── OPERATE ─────────────────────────────────────────────────────────────

@mcp.tool(
    name="fastapi_blast_radius",
    tags={"adapt", "operate"},
    annotations={"readOnlyHint": True},
)
def fastapi_blast_radius(project_dir: str, dry_run: bool = False) -> dict:
    """Estimate the blast radius of a change by mapping module dependencies.

    Given the current git diff, identifies all modules, routes, and tests
    that could be affected, ranked by dependency depth.
    """
    from adapt.operate.blast_radius import blast_radius
    from adapt.contracts import ToolInput
    result = blast_radius(ToolInput(project_dir=project_dir, dry_run=dry_run))
    return result.model_dump()


@mcp.tool(
    name="fastapi_migration_diff",
    tags={"adapt", "operate"},
    annotations={"readOnlyHint": True},
)
def fastapi_migration_diff(project_dir: str, dry_run: bool = False) -> dict:
    """Compare pending Alembic migrations against the current database schema.

    Detects unapplied migrations, missing downgrade paths, and destructive
    operations (column drops, type changes) requiring a maintenance window.
    """
    from adapt.operate.migration_diff import migration_diff
    from adapt.contracts import ToolInput
    result = migration_diff(ToolInput(project_dir=project_dir, dry_run=dry_run))
    return result.model_dump()


@mcp.tool(
    name="fastapi_dead_code_finder",
    tags={"adapt", "operate"},
    annotations={"readOnlyHint": True},
)
def fastapi_dead_code_finder(project_dir: str, dry_run: bool = False) -> dict:
    """Find unreachable routes, unused dependencies, and dead models.

    Performs static reachability analysis from the FastAPI router graph
    and reports code that can be safely deleted.
    """
    from adapt.operate.dead_code_finder import dead_code_finder
    from adapt.contracts import ToolInput
    result = dead_code_finder(ToolInput(project_dir=project_dir, dry_run=dry_run))
    return result.model_dump()


@mcp.tool(
    name="fastapi_api_changelog",
    tags={"adapt", "operate"},
    annotations={"readOnlyHint": True},
)
def fastapi_api_changelog(project_dir: str, dry_run: bool = False) -> dict:
    """Generate a human-readable API changelog by diffing OpenAPI specs across git history.

    Detects added/removed/modified endpoints, breaking changes, and produces
    a versioned CHANGELOG.md entry ready for publication.
    """
    from adapt.operate.api_changelog import api_changelog
    from adapt.contracts import ToolInput
    result = api_changelog(ToolInput(project_dir=project_dir, dry_run=dry_run))
    return result.model_dump()


@mcp.tool(
    name="fastapi_dependency_graph",
    tags={"adapt", "operate"},
    annotations={"readOnlyHint": True},
)
def fastapi_dependency_graph(project_dir: str, dry_run: bool = False) -> dict:
    """Render the FastAPI dependency injection graph as a Mermaid diagram.

    Traces all Depends() chains, highlights circular dependencies, and
    shows shared vs. request-scoped singletons.
    """
    from adapt.operate.dependency_graph import dependency_graph
    from adapt.contracts import ToolInput
    result = dependency_graph(ToolInput(project_dir=project_dir, dry_run=dry_run))
    return result.model_dump()


@mcp.tool(
    name="fastapi_connection_pool_monitor",
    tags={"adapt", "operate"},
    annotations={"readOnlyHint": True},
)
def fastapi_connection_pool_monitor(project_dir: str, dry_run: bool = False) -> dict:
    """Monitor SQLAlchemy connection pool utilization and detect pool exhaustion risk.

    Connects to pg_stat_activity, reports active/idle/waiting counts, pool
    headroom, and recommends pool_size adjustments.
    """
    from adapt.operate.connection_pool_monitor import connection_pool_monitor
    from adapt.contracts import ToolInput
    result = connection_pool_monitor(ToolInput(project_dir=project_dir, dry_run=dry_run))
    return result.model_dump()


@mcp.tool(
    name="fastapi_error_rate_analyzer",
    tags={"adapt", "operate"},
    annotations={"readOnlyHint": True},
)
def fastapi_error_rate_analyzer(project_dir: str, dry_run: bool = False) -> dict:
    """Analyze application error rates from structured logs or Prometheus metrics.

    Computes error rates per endpoint, identifies error spikes, and surfaces
    the top error types with stack trace sampling.
    """
    from adapt.operate.error_rate_analyzer import error_rate_analyzer
    from adapt.contracts import ToolInput
    result = error_rate_analyzer(ToolInput(project_dir=project_dir, dry_run=dry_run))
    return result.model_dump()


@mcp.tool(
    name="fastapi_sla_reporter",
    tags={"adapt", "operate"},
    annotations={"readOnlyHint": True},
)
def fastapi_sla_reporter(project_dir: str, dry_run: bool = False) -> dict:
    """Generate SLA compliance report from Prometheus or log data.

    Computes uptime percentage, p99 latency SLO compliance, error budget
    burn rate, and produces a markdown report suitable for stakeholder review.
    """
    from adapt.operate.sla_reporter import sla_reporter
    from adapt.contracts import ToolInput
    result = sla_reporter(ToolInput(project_dir=project_dir, dry_run=dry_run))
    return result.model_dump()


# ── EVOLVE ──────────────────────────────────────────────────────────────

@mcp.tool(name="fastapi_add_migration_data", tags={"adapt", "evolve"})
def fastapi_add_migration_data(project_dir: str, dry_run: bool = False) -> dict:
    """Add data migration support alongside schema migrations in Alembic.

    Generates a data migration scaffold with bulk_insert helpers, progress
    tracking, rollback-safe chunking, and idempotency guards.
    """
    from adapt.evolve.add_migration_data import add_migration_data
    from adapt.contracts import ToolInput
    result = add_migration_data(ToolInput(project_dir=project_dir, dry_run=dry_run))
    return result.model_dump()


@mcp.tool(name="fastapi_refactor_model", tags={"adapt", "evolve"})
def fastapi_refactor_model(project_dir: str, dry_run: bool = False) -> dict:
    """Refactor a SQLAlchemy model: rename fields, split tables, or add/remove columns.

    Generates rename migration, updates all CRUD references, patches schemas,
    and produces a deprecation shim for backward compatibility.
    """
    from adapt.evolve.refactor_model import refactor_model
    from adapt.contracts import ToolInput
    result = refactor_model(ToolInput(project_dir=project_dir, dry_run=dry_run))
    return result.model_dump()


@mcp.tool(name="fastapi_extract_service", tags={"adapt", "evolve"})
def fastapi_extract_service(project_dir: str, dry_run: bool = False) -> dict:
    """Extract business logic from route handlers into a dedicated service layer.

    Identifies fat routes, moves logic to app/services/, updates route imports,
    and adds service-level unit tests without HTTP layer.
    """
    from adapt.evolve.extract_service import extract_service
    from adapt.contracts import ToolInput
    result = extract_service(ToolInput(project_dir=project_dir, dry_run=dry_run))
    return result.model_dump()


@mcp.tool(name="fastapi_add_event_driven", tags={"adapt", "evolve"})
def fastapi_add_event_driven(project_dir: str, dry_run: bool = False) -> dict:
    """Add event-driven architecture with domain events and async handlers.

    Generates EventBus, DomainEvent base class, async handler registry,
    and integrates with Redis Streams or SQLite for at-least-once delivery.
    """
    from adapt.evolve.add_event_driven import add_event_driven
    from adapt.contracts import ToolInput
    result = add_event_driven(ToolInput(project_dir=project_dir, dry_run=dry_run))
    return result.model_dump()


@mcp.tool(name="fastapi_generate_sdk", tags={"adapt", "evolve"})
def fastapi_generate_sdk(project_dir: str, dry_run: bool = False) -> dict:
    """Generate a typed Python SDK client from the project's OpenAPI spec.

    Produces an installable SDK package with async httpx client, Pydantic
    response models, retry logic, and usage examples for every endpoint.
    """
    from adapt.evolve.generate_sdk import generate_sdk
    from adapt.contracts import ToolInput
    result = generate_sdk(ToolInput(project_dir=project_dir, dry_run=dry_run))
    return result.model_dump()


@mcp.tool(name="fastapi_generate_admin_panel", tags={"adapt", "evolve"})
def fastapi_generate_admin_panel(project_dir: str, dry_run: bool = False) -> dict:
    """Generate an admin panel (SQLAdmin or Starlette-admin) wired to all models.

    Generates model admin views, authentication guard, read/create/edit/delete
    actions, and search/filter for each registered SQLAlchemy model.
    """
    from adapt.evolve.generate_admin_panel import generate_admin_panel
    from adapt.contracts import ToolInput
    result = generate_admin_panel(ToolInput(project_dir=project_dir, dry_run=dry_run))
    return result.model_dump()


@mcp.tool(name="fastapi_generate_docs", tags={"adapt", "evolve"})
def fastapi_generate_docs(project_dir: str, dry_run: bool = False) -> dict:
    """Generate developer documentation from the project's code and OpenAPI spec.

    Produces MkDocs or Sphinx docs with auto-generated API reference, usage
    guides, architecture diagrams, and a GitHub Pages deploy workflow.
    """
    from adapt.evolve.generate_docs import generate_docs
    from adapt.contracts import ToolInput
    result = generate_docs(ToolInput(project_dir=project_dir, dry_run=dry_run))
    return result.model_dump()


@mcp.tool(name="fastapi_add_i18n", tags={"adapt", "evolve"})
def fastapi_add_i18n(project_dir: str, dry_run: bool = False) -> dict:
    """Add internationalization (i18n) support with locale detection and message catalogs.

    Generates Babel config, message extraction setup, locale middleware,
    and translatable string helpers for error messages and API responses.
    """
    from adapt.evolve.add_i18n import add_i18n
    from adapt.contracts import ToolInput
    result = add_i18n(ToolInput(project_dir=project_dir, dry_run=dry_run))
    return result.model_dump()


# ── PROACTIVE ───────────────────────────────────────────────────────────

@mcp.tool(
    name="fastapi_doctor",
    tags={"adapt", "proactive"},
    annotations={"readOnlyHint": True},
)
def fastapi_doctor_tool(project_dir: str, dry_run: bool = False) -> dict:
    """Holistic FastAPI health-check and audit engine.

    Orchestrates all 7 VERIFY tools, classifies findings by severity
    (CRITICAL/HIGH/MEDIUM/LOW), generates an ordered fix plan where each item
    references a specific SKILL-001 tool, and recommends EXTEND tools the project
    currently lacks.
    """
    from adapt.proactive.fastapi_doctor import fastapi_doctor
    from adapt.contracts import ToolInput
    result = fastapi_doctor(ToolInput(project_dir=project_dir, dry_run=dry_run))
    return result.model_dump()


# ── Entry point ──

if __name__ == "__main__":
    mcp.run()
