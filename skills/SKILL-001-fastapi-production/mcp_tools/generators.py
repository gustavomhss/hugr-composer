"""Register generator, analyzer, and legacy tools on a FastMCP app.

These tools have custom parameter signatures (not just project_dir + dry_run),
so they cannot use the auto-discovery MCP_TOOL convention.  This is the ONLY
file that needs a manual update when adding new generators.
"""
from __future__ import annotations


def register_generators(mcp_app) -> int:
    """Register all generator, analyzer, and legacy tools.

    Returns:
        Number of tools registered.
    """
    count = 0

    # ═══════════════════════════════════════════════════════════════════
    #  TIER 1: Orchestrator (one tool, full project)
    # ═══════════════════════════════════════════════════════════════════

    from generators.orchestrator import generate_project

    @mcp_app.tool(
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
        profile: str = "full",
        with_auth: bool = True,
        with_redis: bool = False,
        cors_origins: list[str] | None = None,
        with_docker_compose: bool = True,
        with_k8s: bool = False,
        with_ci: bool = True,
    ) -> dict:
        """Generate a complete production-ready FastAPI project.

        One call produces 15-80 files depending on the profile. Profiles:

        - "minimal" (~15 files): models + DB + health check. No auth, middleware,
          deployment, or tests. Great for prototyping.
        - "api" (~50 files): models + auth + middleware + health. No deployment
          or observability. Good for backend development.
        - "full" (~80 files, default): Everything including deployment, CI,
          observability, and tests. Production-ready.
        - "worker" (~20 files): models + DB + config. No API routes or auth.
          For background job services.

        Individual flags (with_auth, with_k8s, etc.) override the profile preset.

        The LLM should NOT modify generated infra. Customize only business logic.

        Args:
            output_dir: Where to create the project.
            name: Project/app name.
            prefix: API URL prefix (e.g. "/api/v1").
            models: Domain models. {"Product": {"name": "str", "price": "Decimal"}}
            owner_models: Which models have owner FK. {"Product": "user"}
            profile: Project profile preset: "minimal", "api", "full", "worker".
            with_auth: Generate auth stack (password hasher, JWT, login routes).
            with_redis: Add Redis support (config, health checks, docker-compose).
            cors_origins: Allowed CORS origins. Never wildcard.
            with_docker_compose: Generate docker-compose.yml.
            with_k8s: Generate Kubernetes manifests (deployment, HPA, PDB).
            with_ci: Generate GitHub Actions CI pipeline.

        Returns:
            Dict with files_created, notes, phases, total_files, profile, profile_description.

        Example:
            fastapi_generate_project(
                output_dir="/tmp/ecommerce",
                name="ecommerce",
                profile="api",
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
            profile=profile,
            with_auth=with_auth,
            with_redis=with_redis,
            cors_origins=cors_origins,
            with_docker_compose=with_docker_compose,
            with_k8s=with_k8s,
            with_ci=with_ci,
        )

    count += 1

    # ═══════════════════════════════════════════════════════════════════
    #  TIER 2: Granular generators (for targeted generation)
    # ═══════════════════════════════════════════════════════════════════

    # --- Infra ---
    from generators.infra.app import generate_app
    from generators.infra.config import generate_config
    from generators.infra.dockerfile import generate_dockerfile

    @mcp_app.tool(name="fastapi_generate_app", tags={"generator", "infra"})
    def fastapi_generate_app(output_dir: str, name: str = "app", prefix: str = "/api/v1", with_sentry: bool = False) -> dict:
        """Generate main.py with asynccontextmanager lifespan, middleware registration, and router setup."""
        return generate_app(output_dir, name, prefix, with_sentry)

    @mcp_app.tool(name="fastapi_generate_config", tags={"generator", "infra"})
    def fastapi_generate_config(output_dir: str, with_db: bool = True, with_redis: bool = False) -> dict:
        """Generate config.py with pydantic-settings, env parsing, and fail-fast validation."""
        return generate_config(output_dir, with_db, with_redis)

    @mcp_app.tool(name="fastapi_generate_dockerfile", tags={"generator", "infra"})
    def fastapi_generate_dockerfile(output_dir: str, python_version: str = "3.12", port: int = 8000) -> dict:
        """Generate multi-stage Dockerfile with non-root user and HEALTHCHECK."""
        return generate_dockerfile(output_dir, python_version, port)

    count += 3

    # --- Database ---
    from generators.database.engine import generate_engine
    from generators.database.session import generate_session
    from generators.database.model import generate_model
    from generators.database.crud import generate_crud
    from generators.database.alembic import generate_alembic

    @mcp_app.tool(name="fastapi_generate_model", tags={"generator", "database"})
    def fastapi_generate_model(
        output_dir: str, name: str, fields: dict[str, str],
        with_timestamps: bool = True, with_soft_delete: bool = False, owner_field: str | None = None,
    ) -> dict:
        """Generate a SQLAlchemy ORM model with UUID PK, typed columns, and optional timestamps/soft-delete."""
        return generate_model(output_dir, name, fields, with_timestamps, with_soft_delete, owner_field)

    @mcp_app.tool(name="fastapi_generate_crud", tags={"generator", "database"})
    def fastapi_generate_crud(output_dir: str, model_name: str, with_owner_filter: bool = False) -> dict:
        """Generate CRUD layer (create/read/update/delete/list) with pagination and optional owner filtering."""
        return generate_crud(output_dir, model_name, with_owner_filter)

    @mcp_app.tool(name="fastapi_generate_engine", tags={"generator", "database"})
    def fastapi_generate_engine(output_dir: str, driver: str = "asyncpg", pool_size: int = 5) -> dict:
        """Generate async database engine with pool_pre_ping, pool_recycle, and sized connection pool."""
        return generate_engine(output_dir, driver, pool_size)

    @mcp_app.tool(name="fastapi_generate_session", tags={"generator", "database"})
    def fastapi_generate_session(output_dir: str) -> dict:
        """Generate async session factory with commit/rollback/close and SessionDep dependency."""
        return generate_session(output_dir)

    @mcp_app.tool(name="fastapi_generate_alembic", tags={"generator", "database"})
    def fastapi_generate_alembic(output_dir: str) -> dict:
        """Generate complete Alembic migration setup (alembic.ini + env.py + script template)."""
        return generate_alembic(output_dir)

    count += 5

    # --- Auth ---
    from generators.auth.hasher import generate_password_hasher
    from generators.auth.jwt import generate_jwt
    from generators.auth.deps import generate_auth_deps
    from generators.auth.routes import generate_auth_routes
    from generators.auth.schemas import generate_auth_schemas

    @mcp_app.tool(name="fastapi_generate_auth", tags={"generator", "auth"})
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

    count += 1

    # --- Middleware ---
    from generators.middleware.stack import generate_middleware_stack

    @mcp_app.tool(name="fastapi_generate_middleware", tags={"generator", "middleware"})
    def fastapi_generate_middleware(output_dir: str, cors_origins: list[str] | None = None, with_gzip: bool = False) -> dict:
        """Generate full middleware stack: CORS, security headers (7), correlation ID, request logging.

        Middleware is registered in the correct Starlette order (last added = first to execute).
        """
        return generate_middleware_stack(output_dir, cors_origins, with_gzip)

    count += 1

    # --- Endpoints ---
    from generators.endpoints.health import generate_health_checks
    from generators.endpoints.errors import generate_error_handlers
    from generators.endpoints.user_routes import generate_user_routes
    from generators.endpoints.crud_routes import generate_crud_routes

    @mcp_app.tool(name="fastapi_generate_user_routes", tags={"generator", "endpoints", "auth"})
    def fastapi_generate_user_routes(output_dir: str, with_superuser_management: bool = True) -> dict:
        """Generate complete User management routes: signup, /me, /me/password, and superuser CRUD.

        Includes: public registration, self-management (profile, password, delete),
        and optional superuser endpoints (list, create, get, update, delete users).
        """
        return generate_user_routes(output_dir, with_superuser_management)

    @mcp_app.tool(name="fastapi_generate_crud_routes", tags={"generator", "endpoints"})
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

    @mcp_app.tool(name="fastapi_generate_health", tags={"generator", "endpoints"})
    def fastapi_generate_health(output_dir: str, check_db: bool = True, check_redis: bool = False) -> dict:
        """Generate 3-level health checks: /healthz (liveness), /readyz (readiness), /startupz (startup)."""
        return generate_health_checks(output_dir, check_db, check_redis)

    @mcp_app.tool(name="fastapi_generate_errors", tags={"generator", "endpoints"})
    def fastapi_generate_errors(output_dir: str) -> dict:
        """Generate error handlers: HTTPException, RequestValidationError, unhandled Exception."""
        return generate_error_handlers(output_dir)

    count += 4

    # --- Schemas ---
    from generators.schemas.input_schema import generate_input_schema
    from generators.schemas.output_schema import generate_output_schema
    from generators.schemas.list_response import generate_list_response

    @mcp_app.tool(name="fastapi_generate_schemas", tags={"generator", "schemas"})
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

    count += 1

    # --- Deployment ---

    @mcp_app.tool(name="fastapi_generate_docker_compose", tags={"generator", "deployment"})
    def fastapi_generate_docker_compose(output_dir: str, redis: bool = False) -> dict:
        """Generate docker-compose.yml with app, postgres, and optional redis services."""
        from generators.deployment.docker_compose import generate_docker_compose
        return generate_docker_compose(output_dir, redis=redis)

    @mcp_app.tool(name="fastapi_generate_k8s", tags={"generator", "deployment"})
    def fastapi_generate_k8s(output_dir: str, app_name: str = "fastapi-app", replicas: int = 2) -> dict:
        """Generate K8s manifests: Deployment, Service, HPA, PDB, ConfigMap, Secret."""
        from generators.deployment.k8s import generate_k8s_manifests
        return generate_k8s_manifests(output_dir, app_name, replicas=replicas)

    @mcp_app.tool(name="fastapi_generate_ci", tags={"generator", "deployment"})
    def fastapi_generate_ci(output_dir: str, python_version: str = "3.12") -> dict:
        """Generate GitHub Actions CI: lint (ruff+mypy), test (pytest+postgres), build (Docker), scan (Trivy)."""
        from generators.deployment.github_actions import generate_github_actions
        return generate_github_actions(output_dir, python_version)

    @mcp_app.tool(name="fastapi_generate_loadtest", tags={"generator", "deployment"})
    def fastapi_generate_loadtest(output_dir: str, base_url: str = "http://localhost:8000") -> dict:
        """Generate k6 load test with ramp/spike/recovery stages and SLA thresholds."""
        from generators.deployment.k6_loadtest import generate_k6_loadtest
        return generate_k6_loadtest(output_dir, base_url)

    count += 4

    # --- Observability ---

    @mcp_app.tool(name="fastapi_generate_otel", tags={"generator", "observability"})
    def fastapi_generate_otel(output_dir: str, service_name: str = "fastapi-app") -> dict:
        """Generate OpenTelemetry setup: TracerProvider, BatchSpanProcessor, auto-instrumentation."""
        from generators.observability.otel import generate_otel_setup
        return generate_otel_setup(output_dir, service_name)

    @mcp_app.tool(name="fastapi_generate_prometheus", tags={"generator", "observability"})
    def fastapi_generate_prometheus(output_dir: str, prefix: str = "fastapi") -> dict:
        """Generate Prometheus RED metrics (Rate/Errors/Duration) with middleware and /metrics endpoint."""
        from generators.observability.prometheus import generate_prometheus_metrics
        return generate_prometheus_metrics(output_dir, prefix)

    @mcp_app.tool(name="fastapi_generate_alerting", tags={"generator", "observability"})
    def fastapi_generate_alerting(output_dir: str, service_name: str = "fastapi-app") -> dict:
        """Generate PrometheusRule alerts (5 rules) and Grafana dashboard (4 panels)."""
        from generators.observability.alerting import generate_alerting_rules
        return generate_alerting_rules(output_dir, service_name)

    count += 3

    # --- Project files ---

    from generators.infra.env_example import generate_env_example
    from generators.infra.initial_data import generate_initial_data
    from generators.infra.prestart import generate_prestart
    from generators.infra.readme import generate_readme
    from generators.infra.precommit import generate_precommit
    from generators.infra.email import generate_email_utils
    from generators.infra.gitignore import generate_gitignore

    @mcp_app.tool(name="fastapi_generate_env_example", tags={"generator", "infra"})
    def fastapi_generate_env_example(output_dir: str, with_redis: bool = False) -> dict:
        """Generate .env.example with all required environment variables and safe placeholders."""
        return generate_env_example(output_dir, with_redis=with_redis)

    @mcp_app.tool(name="fastapi_generate_initial_data", tags={"generator", "infra"})
    def fastapi_generate_initial_data(output_dir: str) -> dict:
        """Generate initial_data.py -- idempotent superuser seeding script for first boot."""
        return generate_initial_data(output_dir)

    @mcp_app.tool(name="fastapi_generate_prestart", tags={"generator", "infra"})
    def fastapi_generate_prestart(output_dir: str) -> dict:
        """Generate backend_pre_start.py -- waits for database readiness with exponential backoff."""
        return generate_prestart(output_dir)

    @mcp_app.tool(name="fastapi_generate_readme", tags={"generator", "infra"})
    def fastapi_generate_readme(output_dir: str, name: str = "app") -> dict:
        """Generate README.md with quick start, env reference, project structure, and deployment guide."""
        return generate_readme(output_dir, name=name)

    @mcp_app.tool(name="fastapi_generate_email", tags={"generator", "infra"})
    def fastapi_generate_email(output_dir: str) -> dict:
        """Generate email utilities: SMTP sender, password reset email, welcome email with HTML templates."""
        return generate_email_utils(output_dir)

    @mcp_app.tool(name="fastapi_generate_gitignore", tags={"generator", "infra"})
    def fastapi_generate_gitignore(output_dir: str) -> dict:
        """Generate .gitignore with Python, virtualenv, IDE, .env, database, testing, Docker exclusions."""
        return generate_gitignore(output_dir)

    @mcp_app.tool(name="fastapi_generate_precommit", tags={"generator", "infra"})
    def fastapi_generate_precommit(output_dir: str) -> dict:
        """Generate .pre-commit-config.yaml with Ruff linting/formatting and pre-commit hooks."""
        return generate_precommit(output_dir)

    count += 7

    # --- Testing ---

    from generators.testing.conftest import generate_test_infrastructure
    from generators.testing.test_suite import generate_test_suite

    @mcp_app.tool(name="fastapi_generate_tests", tags={"generator", "testing"})
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

    count += 1

    # ═══════════════════════════════════════════════════════════════════
    #  TIER 3: Verification (audit existing projects)
    # ═══════════════════════════════════════════════════════════════════

    from benchmark.analyzer import analyze

    @mcp_app.tool(
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

    count += 1

    # ═══════════════════════════════════════════════════════════════════
    #  TIER 3b: Adapt + Refactor (generator-based tools with custom args)
    # ═══════════════════════════════════════════════════════════════════

    try:
        from generators.tools.add_model import add_model

        @mcp_app.tool(
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

        count += 1
    except ImportError:
        pass

    try:
        from generators.tools.fix_findings import fix_findings

        @mcp_app.tool(
            name="fastapi_fix_findings",
            tags={"refactor", "operate"},
            annotations={"readOnlyHint": False},
        )
        def fastapi_fix_findings(project_dir: str) -> dict:
            """Auto-fix production readiness findings in an existing project.

            Runs the 35-check analyzer, then applies automatic fixes:
            migrates bcrypt->argon2id, python-jose->PyJWT, adds security headers,
            structured logging, health checks, multi-stage Docker, etc.

            Returns: fixed count, manual-fix-required list, score before/after.
            """
            return fix_findings(project_dir)

        count += 1
    except ImportError:
        pass

    try:
        from generators.tools.add_endpoint import add_endpoint

        @mcp_app.tool(name="fastapi_add_endpoint", tags={"adapt"}, annotations={"readOnlyHint": False})
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

        count += 1
    except ImportError:
        pass

    try:
        from generators.tools.add_middleware import add_middleware

        @mcp_app.tool(name="fastapi_add_middleware", tags={"adapt"}, annotations={"readOnlyHint": False})
        def fastapi_add_middleware(project_dir: str, name: str, code: str, position: str = "before_logging") -> dict:
            """Add custom middleware to the stack at the correct position.

            Positions: "outermost", "after_cors", "before_logging" (default), "innermost".
            Writes the middleware file and updates register_middleware().
            """
            return add_middleware(project_dir, name, code, position)

        count += 1
    except ImportError:
        pass

    try:
        from generators.tools.migrate_db import generate_migration

        @mcp_app.tool(name="fastapi_migrate_db", tags={"adapt", "database"}, annotations={"readOnlyHint": False})
        def fastapi_migrate_db(project_dir: str, message: str | None = None) -> dict:
            """Generate Alembic migration script and helper commands.

            Creates scripts/create_migration.sh and returns the exact commands
            to run for autogenerate + review + upgrade.
            """
            return generate_migration(project_dir, message)

        count += 1
    except ImportError:
        pass

    try:
        from generators.tools.add_background_job import add_background_job

        @mcp_app.tool(name="fastapi_add_background_job", tags={"adapt"}, annotations={"readOnlyHint": False})
        def fastapi_add_background_job(
            project_dir: str, name: str, queue: str = "default", retry_max: int = 3, cron: str | None = None,
        ) -> dict:
            """Add a background job using ARQ (async Redis queue).

            Generates worker.py (if first job), core/arq.py, and jobs/{name}.py.
            Optionally adds cron scheduling. Includes retry + dead letter patterns.
            """
            return add_background_job(project_dir, name, queue, retry_max, cron)

        count += 1
    except ImportError:
        pass

    try:
        from generators.tools.add_websocket import add_websocket

        @mcp_app.tool(name="fastapi_add_websocket", tags={"adapt"}, annotations={"readOnlyHint": False})
        def fastapi_add_websocket(project_dir: str, name: str, path: str = "/ws", auth: bool = True) -> dict:
            """Add a WebSocket endpoint with connection manager, rooms, heartbeat, and optional JWT auth."""
            return add_websocket(project_dir, name, path, auth)

        count += 1
    except ImportError:
        pass

    try:
        from generators.tools.add_integration import add_integration

        @mcp_app.tool(name="fastapi_add_integration", tags={"adapt"}, annotations={"readOnlyHint": False})
        def fastapi_add_integration(project_dir: str, service: str, config: dict | None = None) -> dict:
            """Add external service integration (Stripe, S3, SendGrid, Redis cache).

            Generates client wrapper, config entries, and optional webhook routes.
            Services: "stripe", "s3", "sendgrid", "redis".
            """
            return add_integration(project_dir, service, config)

        count += 1
    except ImportError:
        pass

    # ═══════════════════════════════════════════════════════════════════
    #  TIER 4: Pentest + Operate (runtime tools)
    # ═══════════════════════════════════════════════════════════════════

    try:
        from modules.security.tools.pentest_api import run_all_tests as _pentest_run_all
        import asyncio as _asyncio

        @mcp_app.tool(
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

        count += 1
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

        @mcp_app.tool(name="fastapi_db_health", tags={"operate", "database"}, annotations={"readOnlyHint": True})
        def fastapi_db_health(db_url: str) -> dict:
            """Check PostgreSQL connection pool health: active/idle/waiting connections, pool utilization."""
            return check_pool_health(db_url)

        @mcp_app.tool(name="fastapi_db_slow_queries", tags={"operate", "database"}, annotations={"readOnlyHint": True})
        def fastapi_db_slow_queries(db_url: str, min_duration_ms: float = 100) -> list[dict]:
            """Find slow queries from pg_stat_statements. Requires pg_stat_statements extension."""
            return find_slow_queries(db_url, min_duration_ms=min_duration_ms)

        @mcp_app.tool(name="fastapi_db_explain", tags={"operate", "database"}, annotations={"readOnlyHint": True})
        def fastapi_db_explain(db_url: str, sql: str) -> dict:
            """Run EXPLAIN ANALYZE on a query and interpret the execution plan."""
            return analyze_query(db_url, sql)

        @mcp_app.tool(name="fastapi_db_bloat", tags={"operate", "database"}, annotations={"readOnlyHint": True})
        def fastapi_db_bloat(db_url: str) -> list[dict]:
            """Check table bloat -- identifies tables that need VACUUM."""
            return check_table_bloat(db_url)

        @mcp_app.tool(name="fastapi_db_suggest_indexes", tags={"operate", "database"}, annotations={"readOnlyHint": True})
        def fastapi_db_suggest_indexes(db_url: str) -> list[dict]:
            """Suggest missing indexes based on sequential scan patterns."""
            return suggest_indexes(db_url)

        count += 5
    except ImportError:
        pass

    # ═══════════════════════════════════════════════════════════════════
    #  TIER 5: Legacy v2 tools
    # ═══════════════════════════════════════════════════════════════════

    try:
        from core.tools.analyze import analyze_project

        @mcp_app.tool(
            name="fastapi_analyze_project_v2",
            tags={"verify", "legacy"},
            annotations={"readOnlyHint": True},
        )
        def fastapi_analyze_project_v2(project_path: str) -> dict:
            """[Legacy v2] AST-based analysis of 8 core patterns. Use fastapi_analyze for the 35-check v3 audit."""
            result = analyze_project(project_path)
            return result.model_dump(mode="json")

        count += 1
    except ImportError:
        pass

    try:
        from core.tools.runtime import check_health, check_security_headers
        import asyncio

        @mcp_app.tool(name="fastapi_check_health", tags={"verify", "runtime"}, annotations={"readOnlyHint": True})
        def fastapi_check_health(base_url: str) -> list[dict]:
            """Check 3-level health endpoints (/healthz, /readyz, /startupz) of a running instance."""
            results = asyncio.run(check_health(base_url))
            return [r.model_dump(mode="json") for r in results]

        @mcp_app.tool(name="fastapi_check_headers", tags={"verify", "runtime"}, annotations={"readOnlyHint": True})
        def fastapi_check_headers(base_url: str) -> dict:
            """Check security headers and CORS of a running instance."""
            result = asyncio.run(check_security_headers(base_url))
            return result.model_dump(mode="json")

        count += 2
    except ImportError:
        pass

    return count
