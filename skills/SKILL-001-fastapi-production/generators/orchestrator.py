"""Orchestrator: generates a complete FastAPI production project.

Calls all generators in the correct dependency order, producing a
fully-wired project that runs out of the box.  This is the single
MCP tool exposed to the LLM — the LLM calls ``generate_project()``
with business-domain parameters, the orchestrator handles all infra.

Usage:
    from generators.orchestrator import generate_project

    result = generate_project(
        output_dir="/tmp/my-ecommerce",
        name="ecommerce",
        models={
            "Product": {"name": "str", "price": "Decimal", "stock": "int"},
            "Order": {"user_id": "uuid", "status": "str", "total": "Decimal"},
        },
        owner_models={"Order": "user"},
    )
"""

from __future__ import annotations

MCP_TOOL = {
    "name": "fastapi_resiliency_generate_project",
    "description": "Generate a complete production-ready FastAPI project.",
    "tags": ["generator", "orchestrator"],
    "entry": "generate_project",
    "annotations": {"readOnlyHint": False, "destructiveHint": False},
}

from pathlib import Path

# ---------------------------------------------------------------------------
# Sentinel for "parameter not passed by caller"
# ---------------------------------------------------------------------------
_UNSET = object()

# ---------------------------------------------------------------------------
# Project profiles — presets that control which phases are generated.
# Users pick a profile, then override individual flags as needed.
# ---------------------------------------------------------------------------
PROFILES: dict[str, dict] = {
    "minimal": {
        "description": "Bare minimum: 1+ models, health check, no auth, no middleware. ~15 files.",
        "with_auth": False,
        "with_redis": False,
        "with_docker_compose": False,
        "with_ci": False,
        "with_otel": False,
        "with_prometheus": False,
        "with_alerting": False,
        "with_k8s": False,
        "with_loadtest": False,
        "skip_middleware": True,
        "skip_deployment": True,
        "skip_testing": True,
        "skip_email_utils": True,
        "skip_precommit": True,
    },
    "api": {
        "description": "Production API: models + auth + middleware + health. ~50 files. No deployment/observability.",
        "with_auth": True,
        "with_redis": True,
        "with_docker_compose": False,
        "with_ci": False,
        "with_otel": False,
        "with_prometheus": False,
        "with_alerting": False,
        "with_k8s": False,
        "with_loadtest": False,
        "skip_middleware": False,
        "skip_deployment": True,
        "skip_testing": False,
        "skip_email_utils": True,
        "skip_precommit": True,
    },
    "full": {
        "description": "Everything: auth + middleware + deployment + observability + testing. ~80 files.",
        "skip_middleware": False,
        "skip_deployment": False,
        "skip_testing": False,
        "skip_email_utils": False,
        "skip_precommit": False,
    },
    "worker": {
        "description": "Background worker only: models + DB + config. No API routes, no auth, no middleware. ~20 files.",
        "with_auth": False,
        "with_redis": True,
        "with_docker_compose": False,
        "with_ci": False,
        "with_otel": False,
        "with_prometheus": False,
        "with_alerting": False,
        "with_k8s": False,
        "with_loadtest": False,
        "skip_middleware": True,
        "skip_deployment": True,
        "skip_testing": True,
        "skip_email_utils": True,
        "skip_precommit": True,
        "skip_routes": True,
        "skip_app_entry": True,
    },
}


# --- Infra ---
from generators.auth.deps import generate_auth_deps

# --- Auth ---
from generators.auth.hasher import generate_password_hasher
from generators.auth.jwt import generate_jwt
from generators.auth.rate_limit import generate_rate_limit
from generators.auth.routes import generate_auth_routes
from generators.auth.schemas import generate_auth_schemas
from generators.database.alembic import generate_alembic
from generators.database.alembic_migration import generate_baseline_migration
from generators.database.crud import generate_crud
from generators.database.crud_base import generate_crud_base

# --- Database ---
from generators.database.engine import generate_engine
from generators.database.model import generate_model
from generators.database.session import generate_session
from generators.endpoints.crud_routes import generate_crud_routes
from generators.endpoints.errors import generate_error_handlers

# --- Endpoints ---
from generators.endpoints.health import generate_health_checks
from generators.endpoints.user_routes import generate_user_routes
from generators.infra.app import generate_app
from generators.infra.config import generate_config
from generators.infra.dockerfile import generate_dockerfile
from generators.infra.email import generate_email_utils
from generators.infra.env_example import generate_env_example
from generators.infra.gitignore import generate_gitignore
from generators.infra.initial_data import generate_initial_data
from generators.infra.logging import generate_logging_setup
from generators.infra.precommit import generate_precommit
from generators.infra.prestart import generate_prestart
from generators.infra.readme import generate_readme
from generators.middleware.body_size import generate_body_size_middleware
from generators.middleware.correlation import generate_correlation_id

# --- Middleware ---
from generators.middleware.idempotency import generate_idempotency_middleware
from generators.middleware.request_logging import generate_request_logging
from generators.middleware.security_headers import generate_security_headers
from generators.middleware.stack import generate_middleware_stack

# --- Schemas ---
from generators.schemas.input_schema import generate_input_schema
from generators.schemas.list_response import generate_list_response
from generators.schemas.output_schema import generate_output_schema

# --- Testing ---
from generators.testing.conftest import generate_test_infrastructure
from generators.testing.test_suite import generate_test_suite


def generate_project(
    output_dir: str,
    name: str = "app",
    prefix: str = "/api/v1",
    models: dict[str, dict[str, str]] | None = None,
    owner_models: dict[str, str] | None = None,
    shared_models: set[str] | None = None,
    *,
    profile: str = "full",
    with_auth: bool | object = _UNSET,
    with_sentry: bool = False,
    with_redis: bool | object = _UNSET,
    with_gzip: bool = False,
    cors_origins: list[str] | None = None,
    python_version: str = "3.12",
    with_docker_compose: bool | object = _UNSET,
    with_k8s: bool | object = _UNSET,
    with_ci: bool | object = _UNSET,
    with_loadtest: bool | object = _UNSET,
    with_otel: bool | object = _UNSET,
    with_prometheus: bool | object = _UNSET,
    with_alerting: bool | object = _UNSET,
) -> dict:
    """Generate a complete, production-ready FastAPI project.

    This is the top-level orchestrator.  It calls individual generators
    in the correct dependency order and returns a manifest of every
    file created plus notes.

    Args:
        output_dir: Root directory for the generated project.
        name: Application / project name.
        prefix: URL prefix for all API routes (e.g. ``/api/v1``).
        models: Domain models to generate.
            ``{"Product": {"name": "str", "price": "Decimal"}, ...}``
        owner_models: Which models have an ``owner_id`` FK.
            ``{"Product": "user"}`` means ``Product.owner_id -> users.id``.
        shared_models: BOLA opt-out — models that have an ``owner_id``
            FK (i.e. listed in ``owner_models``) but where per-object
            ownership SHOULD NOT be enforced.  Use for catalogue / lookup
            tables that track who created a row but are not user-private
            (e.g. ``ProductCatalog``, ``Tag``).  Each shared model gets
            an entry in the auto-generated
            ``tests/test_bola_shared_models.py`` audit file so reviewers
            can explicitly confirm the open-access policy.  Default
            ``None`` (every owner-bearing model is guarded =
            secure-by-default).
        profile: Project profile preset. ``"minimal"`` (~15 files),
            ``"api"`` (~50 files), ``"full"`` (~80 files, default),
            or ``"worker"`` (~20 files).  Individual ``with_*`` flags
            override the profile when explicitly passed.
        with_auth: Generate full auth stack (hasher, JWT, deps, routes).
        with_sentry: Include Sentry SDK in main.py.
        with_redis: Add Redis to config + docker-compose + health checks.
        with_gzip: Add GZip middleware.
        cors_origins: Explicit CORS origins list.
        python_version: Python version for Dockerfile.
        with_docker_compose: Generate docker-compose.yml.
        with_k8s: Generate Kubernetes manifests.
        with_ci: Generate GitHub Actions CI.
        with_loadtest: Generate k6 load test.
        with_otel: Generate OpenTelemetry setup.
        with_prometheus: Generate Prometheus metrics.
        with_alerting: Generate alerting rules + Grafana dashboard.

    Returns:
        Dict with ``files_created``, ``notes``, ``phases``, ``total_files``,
        ``profile``, and ``profile_description``.

    Raises:
        ValueError: If *profile* is not one of the known profile names.
    """
    # ------------------------------------------------------------------
    # Profile resolution: apply preset defaults for any flag the caller
    # did not explicitly pass.  Explicit kwargs always win.
    # ------------------------------------------------------------------
    if profile not in PROFILES:
        raise ValueError(f"Unknown profile '{profile}'. Valid profiles: {list(PROFILES.keys())}")
    p = PROFILES[profile]

    # ------------------------------------------------------------------
    # BOLA opt-out normalisation.  ``shared_models`` accepts any iterable
    # of model names; we coerce to a frozenset for fast membership checks
    # and reject names that are not in ``owner_models`` (a model that is
    # not owner-bearing has nothing to opt-out OF — silent acceptance
    # would mask caller typos like ``shared_models={"Prodcut"}``).
    # ------------------------------------------------------------------
    shared_models_set: frozenset[str] = frozenset(shared_models or ())
    if shared_models_set:
        owner_keys = set((owner_models or {}).keys())
        invalid = shared_models_set - owner_keys
        if invalid:
            raise ValueError(
                "shared_models contains names that are not in owner_models "
                f"(no owner_id column to opt-out from): {sorted(invalid)}. "
                "Either add them to owner_models or remove from shared_models."
            )

    if with_auth is _UNSET:
        with_auth = p.get("with_auth", True)
    if with_redis is _UNSET:
        with_redis = p.get("with_redis", False)
    if with_docker_compose is _UNSET:
        with_docker_compose = p.get("with_docker_compose", True)
    if with_k8s is _UNSET:
        with_k8s = p.get("with_k8s", False)
    if with_ci is _UNSET:
        with_ci = p.get("with_ci", True)
    if with_loadtest is _UNSET:
        with_loadtest = p.get("with_loadtest", False)
    if with_otel is _UNSET:
        with_otel = p.get("with_otel", True)
    if with_prometheus is _UNSET:
        with_prometheus = p.get("with_prometheus", True)
    if with_alerting is _UNSET:
        with_alerting = p.get("with_alerting", False)

    # Cast to bool after sentinel resolution (keeps type checkers happy
    # and avoids passing _UNSET deeper into the call chain).
    with_auth = bool(with_auth)
    with_redis = bool(with_redis)
    with_docker_compose = bool(with_docker_compose)
    with_k8s = bool(with_k8s)
    with_ci = bool(with_ci)
    with_loadtest = bool(with_loadtest)
    with_otel = bool(with_otel)
    with_prometheus = bool(with_prometheus)
    with_alerting = bool(with_alerting)

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Rate limiting, idempotency middleware, and the Stripe webhook
    # helper all require Redis — force-enable it whenever any of those
    # features are generated so ``docker-compose.yml`` and
    # ``requirements.txt`` stay in sync with what the code imports.
    if with_auth:
        with_redis = True

    # Source code lives under {out}/app/. Infrastructure (Dockerfile, .env,
    # docker-compose, README, requirements.txt, .github, etc.) stays at root.
    # This matches `from app.xxx import yyy` imports throughout the code.
    app_dir = out / "app"
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "__init__.py").write_text('"""Application package."""\n')

    all_files: list[str] = []
    all_notes: list[str] = []
    phases: dict[str, dict] = {}

    def _run(phase: str, result: dict) -> None:
        all_files.extend(result["files_created"])
        all_notes.extend(result.get("notes", []))
        phases[phase] = {
            "files": len(result["files_created"]),
            "status": "done",
        }

    # ---------------------------------------------------------------
    # Phase 1: Config + logging (foundation for everything else)
    # ---------------------------------------------------------------
    _run(
        "config",
        generate_config(
            output_dir=str(app_dir),
            with_db=True,
            with_redis=with_redis,
            with_sentry=with_sentry,
            prefix=prefix,
        ),
    )
    _run("logging_setup", generate_logging_setup(output_dir=str(app_dir)))

    # ---------------------------------------------------------------
    # Phase 2: Database layer
    # ---------------------------------------------------------------
    _run("db_engine", generate_engine(output_dir=str(app_dir)))
    _run("db_session", generate_session(output_dir=str(app_dir)))
    _run("crud_base", generate_crud_base(output_dir=str(app_dir)))

    # Auto-inject OrderItem when both Order and Product are present.
    # OrderItem is the join entity required for any real e-commerce checkout:
    # it snapshots the price at purchase time and maps quantities.
    if models and "Order" in models and "Product" in models and "OrderItem" not in models:
        models = dict(models)  # shallow copy — don't mutate caller's dict
        models["OrderItem"] = {
            "order_id": "uuid",  # FK -> orders (CASCADE)
            "product_id": "uuid",  # FK -> products (RESTRICT in spirit)
            "quantity": "int",  # ge=1 enforced at schema layer
            "price_at_purchase": "Decimal",  # snapshot — never re-read from product
        }

    if models:
        for model_name, fields in models.items():
            owner = (owner_models or {}).get(model_name)
            _run(
                f"model_{model_name}",
                generate_model(
                    output_dir=str(app_dir),
                    name=model_name,
                    fields=fields,
                    owner_field=owner,
                    # Pass the full model registry so generate_model can distinguish
                    # real cross-model FKs from plain *_id scalar fields.
                    known_models=models,
                ),
            )

    # User model (always generated when auth is enabled)
    if with_auth and (not models or "User" not in models):
        _run(
            "model_User",
            generate_model(
                output_dir=str(app_dir),
                name="User",
                fields={
                    "email": "EmailStr",
                    "full_name": "str",
                    "hashed_password": "str",
                    "is_active": "bool",
                    "is_superuser": "bool",
                },
            ),
        )
        # Patch User model with correct defaults + UNIQUE constraint on email
        user_model = app_dir / "models" / "user.py"
        if user_model.exists():
            content = user_model.read_text()
            content = content.replace(
                "is_active: Mapped[bool] = mapped_column(Boolean)",
                "is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)",
            )
            content = content.replace(
                "is_superuser: Mapped[bool] = mapped_column(Boolean)",
                "is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)",
            )
            content = content.replace(
                "email: Mapped[EmailStr] = mapped_column(String(320))",
                "email: Mapped[EmailStr] = mapped_column(String(320), unique=True, index=True, nullable=False)",
            )
            content = content.replace(
                "full_name: Mapped[str] = mapped_column(String(255))",
                "full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)",
            )
            user_model.write_text(content)

    # CRUD base class (shared by all entity CRUDs — generated once)
    if models or with_auth:
        _run("crud_base", generate_crud_base(output_dir=str(app_dir)))

    # CRUD layers
    if models:
        for model_name in models:
            has_owner = model_name in (owner_models or {})
            _run(
                f"crud_{model_name}",
                generate_crud(
                    output_dir=str(app_dir),
                    model_name=model_name,
                    with_owner_filter=has_owner,
                ),
            )

    if with_auth:
        _run(
            "crud_User",
            generate_crud(
                output_dir=str(app_dir),
                model_name="User",
                unique_field="email",
            ),
        )

    # Only generate Alembic if there are models to migrate.
    # Alembic config + versions live at the PROJECT ROOT (not under app/)
    # so that `alembic upgrade head` can be run from the same directory
    # that contains alembic.ini.  env.py still imports `app.core.config`.
    if models or with_auth:
        _run("alembic", generate_alembic(output_dir=str(out)))
        _run(
            "baseline_migration",
            generate_baseline_migration(
                output_dir=str(out),
                models=models,
                owner_models=owner_models,
                with_auth=with_auth,
            ),
        )

    # --- Schemas for all models ---
    all_model_names = list((models or {}).keys())
    if with_auth and "User" not in all_model_names:
        all_model_names.append("User")

    for model_name in all_model_names:
        fields = (models or {}).get(model_name, {})
        # Auth-generated User model has known fields
        if model_name == "User" and not fields:
            fields = {
                "email": "EmailStr",
                "password": "password",
                "full_name": "str",
            }
        exclude = None
        if model_name == "User":
            exclude = ["hashed_password", "password"]
        _run(
            f"schema_input_{model_name}",
            generate_input_schema(
                output_dir=str(app_dir),
                name=model_name,
                fields=fields,
            ),
        )
        _run(
            f"schema_output_{model_name}",
            generate_output_schema(
                output_dir=str(app_dir),
                name=model_name,
                fields=fields,
                exclude_fields=exclude,
            ),
        )
        _run(
            f"schema_list_{model_name}",
            generate_list_response(
                output_dir=str(app_dir),
                name=model_name,
            ),
        )

    # User schema: full_name is nullable in the DB column (see model patch
    # above) but the consolidated schemas/user.py declares it as required
    # in UserPublic. Relax UserPublic.full_name to match the DB.
    if with_auth:
        user_schema_file = app_dir / "schemas" / "user.py"
        if user_schema_file.exists():
            content = user_schema_file.read_text()
            # Only the UserPublic class has the bare ``full_name: str``
            # without a default; UserCreate is fine as required.
            # Replace inside UserPublic only (after the class line).
            if "class UserPublic" in content:
                public_idx = content.index("class UserPublic")
                head = content[:public_idx]
                tail = content[public_idx:]
                tail = tail.replace(
                    "    full_name: str\n",
                    "    full_name: str | None = None\n",
                    1,
                )
                user_schema_file.write_text(head + tail)

    # ---------------------------------------------------------------
    # Phase 3: Auth
    # ---------------------------------------------------------------
    if with_auth:
        _run("rate_limit", generate_rate_limit(output_dir=str(app_dir)))
        _run("password_hasher", generate_password_hasher(output_dir=str(app_dir)))
        _run("jwt", generate_jwt(output_dir=str(app_dir)))
        _run(
            "auth_deps",
            generate_auth_deps(
                output_dir=str(app_dir),
                token_url=f"{prefix}/login/access-token",
            ),
        )
        _run("auth_routes", generate_auth_routes(output_dir=str(app_dir)))
        _run("auth_schemas", generate_auth_schemas(output_dir=str(app_dir)))
        _run("user_routes", generate_user_routes(output_dir=str(app_dir)))

    # schemas/message.py — always needed (used by CRUD routes for delete responses)
    if not with_auth:
        # auth_schemas generates this, but when auth is off we need it standalone
        msg_dir = app_dir / "schemas"
        msg_dir.mkdir(parents=True, exist_ok=True)
        msg_file = msg_dir / "message.py"
        if not msg_file.exists():
            msg_file.write_text(
                '"""Generic message response schema."""\n\n'
                "from pydantic import BaseModel\n\n\n"
                "class Message(BaseModel):\n"
                "    message: str\n"
            )
            all_files.append(str(msg_file))
            phases["message_schema"] = {"files": 1, "status": "done"}

    # ---------------------------------------------------------------
    # Phase 4: Middleware (skipped by minimal/worker profiles)
    # ---------------------------------------------------------------
    if not p.get("skip_middleware"):
        # NOTE: cors_config.py was deprecated. CORS is configured directly
        # in middleware/__init__.py using settings.BACKEND_CORS_ORIGINS.
        # The generate_cors() generator is no longer called here.
        _run("security_headers", generate_security_headers(output_dir=str(app_dir)))
        _run("correlation_id", generate_correlation_id(output_dir=str(app_dir)))
        _run("request_logging", generate_request_logging(output_dir=str(app_dir)))
        _run("body_size", generate_body_size_middleware(output_dir=str(app_dir)))
        _run("idempotency", generate_idempotency_middleware(output_dir=str(app_dir)))
        _run(
            "middleware_stack",
            generate_middleware_stack(
                output_dir=str(app_dir),
                cors_origins=cors_origins,
                with_gzip=with_gzip,
            ),
        )

    # ---------------------------------------------------------------
    # Phase 5: Endpoints (skipped by worker profile)
    # ---------------------------------------------------------------
    if not p.get("skip_routes"):
        _run(
            "health_checks",
            generate_health_checks(
                output_dir=str(app_dir),
                check_redis=with_redis,
            ),
        )
        _run("error_handlers", generate_error_handlers(output_dir=str(app_dir)))

        # CRUD routes for domain models
        if models:
            route_auth = "required" if with_auth else "none"
            for model_name, fields in models.items():
                owner = (owner_models or {}).get(model_name)
                _run(
                    f"routes_{model_name}",
                    generate_crud_routes(
                        output_dir=str(app_dir),
                        model_name=model_name,
                        fields=fields,
                        auth=route_auth,
                        owner_field=owner if with_auth else None,
                        # BOLA secure-by-default: per-object guard fires unless
                        # this model is in the caller's shared_models opt-out.
                        shared_model=model_name in shared_models_set,
                    ),
                )

    # ---------------------------------------------------------------
    # Phase 5b: Package init files + router assembly
    # ---------------------------------------------------------------
    if not p.get("skip_routes"):
        _generate_package_inits(app_dir, models or {}, with_auth)

    # ---------------------------------------------------------------
    # Phase 6: Application entry point (skipped by worker profile)
    # ---------------------------------------------------------------
    if not p.get("skip_app_entry"):
        _run(
            "app",
            generate_app(
                output_dir=str(app_dir),
                name=name,
                prefix=prefix,
                with_sentry=with_sentry,
                with_rate_limit=with_auth,
                with_prometheus=with_prometheus,
            ),
        )

    # ---------------------------------------------------------------
    # Phase 7: Deployment (skipped by minimal/api/worker profiles)
    # ---------------------------------------------------------------
    if not p.get("skip_deployment"):
        _run(
            "dockerfile",
            generate_dockerfile(
                output_dir=str(out),
                python_version=python_version,
            ),
        )

    if not p.get("skip_deployment") and with_docker_compose:
        try:
            from generators.deployment.docker_compose import generate_docker_compose

            _run(
                "docker_compose",
                generate_docker_compose(
                    output_dir=str(out),
                    redis=with_redis,
                ),
            )
        except ImportError:
            phases["docker_compose"] = {"files": 0, "status": "skipped (generator not built yet)"}

    if not p.get("skip_deployment") and with_k8s:
        try:
            from generators.deployment.k8s import generate_k8s_manifests

            _run(
                "k8s",
                generate_k8s_manifests(
                    output_dir=str(out),
                    app_name=name,
                    prefix=prefix,
                ),
            )
        except ImportError:
            phases["k8s"] = {"files": 0, "status": "skipped (generator not built yet)"}

    if not p.get("skip_deployment") and with_ci:
        try:
            from generators.deployment.github_actions import generate_github_actions

            _run(
                "ci",
                generate_github_actions(
                    output_dir=str(out),
                    python_version=python_version,
                ),
            )
        except ImportError:
            phases["ci"] = {"files": 0, "status": "skipped (generator not built yet)"}

    if not p.get("skip_deployment") and with_loadtest:
        try:
            from generators.deployment.k6_loadtest import generate_k6_loadtest

            _run(
                "loadtest",
                generate_k6_loadtest(
                    output_dir=str(out),
                    api_prefix=prefix,
                ),
            )
        except ImportError:
            phases["loadtest"] = {"files": 0, "status": "skipped (generator not built yet)"}

    # ---------------------------------------------------------------
    # Phase 8: Observability
    # ---------------------------------------------------------------
    if with_otel:
        try:
            from generators.observability.otel import generate_otel_setup

            _run(
                "otel",
                generate_otel_setup(
                    output_dir=str(app_dir),
                    service_name=name,
                ),
            )
        except ImportError:
            phases["otel"] = {"files": 0, "status": "skipped (generator not built yet)"}

    if with_prometheus:
        try:
            from generators.observability.prometheus import generate_prometheus_metrics

            _run(
                "prometheus",
                generate_prometheus_metrics(
                    output_dir=str(app_dir),
                    prefix=name.replace("-", "_"),
                ),
            )
        except ImportError:
            phases["prometheus"] = {"files": 0, "status": "skipped (generator not built yet)"}

    if with_alerting:
        try:
            from generators.observability.alerting import generate_alerting_rules

            _run(
                "alerting",
                generate_alerting_rules(
                    output_dir=str(out),
                    service_name=name,
                ),
            )
        except ImportError:
            phases["alerting"] = {"files": 0, "status": "skipped (generator not built yet)"}

    # ---------------------------------------------------------------
    # Phase 9: Project files (root) + Python utility scripts (app/)
    # ---------------------------------------------------------------
    # Root-level project files (not Python source)
    _run(
        "env_example",
        generate_env_example(
            output_dir=str(out),
            with_db=True,
            with_redis=with_redis,
            with_sentry=with_sentry,
            prefix=prefix,
        ),
    )
    _run(
        "readme",
        generate_readme(
            output_dir=str(out),
            name=name,
            prefix=prefix,
        ),
    )
    if not p.get("skip_precommit"):
        _run("precommit", generate_precommit(output_dir=str(out)))
    _run("gitignore", generate_gitignore(output_dir=str(out)))

    # Python source utilities (live under app/)
    if not p.get("skip_email_utils"):
        _run("email_utils", generate_email_utils(output_dir=str(app_dir)))

    if with_auth:
        _run("initial_data", generate_initial_data(output_dir=str(app_dir)))

    _run("prestart", generate_prestart(output_dir=str(app_dir)))

    # ---------------------------------------------------------------
    # Phase 10: requirements.txt (must come BEFORE test_infra which appends to it)
    # ---------------------------------------------------------------
    _generate_requirements(
        out,
        with_auth,
        with_redis,
        with_otel,
        with_prometheus,
        with_sentry,
    )
    all_files.append(str(out / "requirements.txt"))
    phases["requirements"] = {"files": 1, "status": "done"}

    # ---------------------------------------------------------------
    # Phase 11: Test infrastructure + test suite (skipped by minimal/worker)
    # ---------------------------------------------------------------
    if not p.get("skip_testing") and (models or with_auth):
        _run(
            "test_infra",
            generate_test_infrastructure(
                output_dir=str(out),
                with_auth=with_auth,
            ),
        )
        _run(
            "test_suite",
            generate_test_suite(
                output_dir=str(out),
                models=models,
                owner_models=owner_models,
                with_auth=with_auth,
                # F-005 + F-007: pass shared_models through so emitted
                # tests pick the right BOLA story (403 vs open access).
                shared_models=shared_models_set or None,
            ),
        )

        # BOLA opt-out audit file.  When the caller has flagged any owner-
        # bearing model as ``shared_models``, emit an explicit pytest module
        # that documents (and at import time, asserts) the open-access
        # policy.  A reviewer scanning the repo sees a single file listing
        # every model that intentionally bypasses the per-object guard —
        # the security trade-off is one Cmd-F away from "BOLA".
        if shared_models_set:
            audit_file = _write_bola_shared_models_audit(
                out,
                sorted(shared_models_set),
                prefix,
            )
            all_files.append(str(audit_file))
            phases["bola_shared_models_audit"] = {
                "files": 1,
                "status": "done",
            }
            all_notes.append(
                "BOLA opt-out: shared_models="
                f"{sorted(shared_models_set)} — per-object ownership guard "
                "suppressed; audit file emitted at tests/test_bola_shared_models.py."
            )

    # ---------------------------------------------------------------
    # Phase 12: scaffold_venous smoke — prove the copy-in pipe works
    # for the reference primitive (see ADR 0002 + CONTRACT §B1.0).
    # Tools refactored under §B1.3 call ensure_primitives themselves;
    # this single call here keeps the orchestrator honest by shipping
    # at least one primitive on every fresh project.
    # ---------------------------------------------------------------
    try:
        from generators.scaffold_venous import ensure_primitives

        manifest = ensure_primitives(
            str(out),
            names=["core.venous.resiliency.GracefulShutdown"],
        )
        if manifest.copied:
            phases["scaffold_venous"] = {"files": len(manifest.copied), "status": "done"}
        else:
            phases["scaffold_venous"] = {"files": 0, "status": "already_present"}
    except Exception as exc:  # noqa: BLE001 — smoke step must not break project gen
        phases["scaffold_venous"] = {"files": 0, "status": f"skipped ({exc})"}

    return {
        "files_created": all_files,
        "notes": all_notes,
        "phases": phases,
        "total_files": len(all_files),
        "profile": profile,
        "profile_description": p["description"],
    }


def _write_bola_shared_models_audit(
    out: Path,
    shared: list[str],
    prefix: str,
) -> Path:
    """Emit ``tests/test_bola_shared_models.py`` documenting BOLA opt-outs.

    The file lists every model that was passed in ``shared_models=`` and
    asserts (at import time) that the list is exactly what was declared.
    Reviewers grep for ``test_bola_shared_models`` to see which models
    intentionally bypass the per-object ownership guard.

    Args:
        out: Project root directory.
        shared: Sorted list of shared (BOLA-opt-out) model names.
        prefix: API route prefix (e.g. ``/api/v1``) — embedded in the
            docstring so reviewers know which routes are affected.

    Returns:
        Path to the emitted audit test file.
    """
    tests_dir = out / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    audit_path = tests_dir / "test_bola_shared_models.py"

    bullet_lines = "\n".join(
        f"  * ``{m}``  -> ``{prefix}/{m.lower()}s/`` (no per-object guard)" for m in shared
    )
    shared_repr = repr(shared)

    parts = [
        '"""BOLA opt-out audit — auto-generated by generate_project.',
        "",
        "This file documents every model passed in ``shared_models=`` to the",
        "project generator.  Each model listed here:",
        "",
        "  * Has an ``owner_id`` column populated server-side on create.",
        "  * Does NOT enforce per-object ownership on GET-by-id / PATCH / DELETE.",
        "  * Therefore: any authenticated user may read / update / delete any",
        "    row of these tables.",
        "",
        "Shared models in this project:",
        bullet_lines,
        "",
        "If you did NOT intend any of these models to be open-access, REMOVE",
        "them from ``shared_models=...`` in your ``generate_project(...)`` call",
        "and regenerate — they will get the secure-by-default BOLA guard back.",
        "",
        "This file exists so the open-access policy is auditable: a reviewer",
        "running ``grep -r test_bola_shared_models`` immediately sees every",
        "intentional opt-out.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "",
        "# Authoritative list of BOLA-opt-out models (audit anchor).",
        f"SHARED_MODELS: frozenset[str] = frozenset({shared_repr})",
        "",
        "",
        "def test_shared_models_list_matches_generator_input() -> None:",
        '    """Shared list matches what was passed to generate_project()."""',
        f"    assert SHARED_MODELS == frozenset({shared_repr}), (",
        '        "shared_models drift — regenerate the project."',
        "    )",
        "",
        "",
        "def test_shared_models_documented() -> None:",
        '    """Every shared model is named in this module\'s docstring."""',
        '    doc = __doc__ or ""',
        "    for model in SHARED_MODELS:",
        '        assert f"``{model}``" in doc, (',
        '            f"shared model {model!r} missing from audit docstring"',
        "        )",
        "",
    ]
    audit_path.write_text("\n".join(parts))
    return audit_path


def _generate_requirements(
    out: Path,
    with_auth: bool,
    with_redis: bool,
    with_otel: bool,
    with_prometheus: bool,
    with_sentry: bool = False,
) -> None:
    """Write requirements.txt with pinned, production-grade dependencies.

    When ``with_sentry`` is True, ``sentry-sdk`` MUST be present — the
    emitted ``main.py`` imports it unconditionally under that flag and
    the app would ``ModuleNotFoundError`` at boot without the pin.
    """
    deps = [
        "fastapi>=0.115.0",
        "uvicorn[standard]>=0.32.0",
        "pydantic>=2.10.0",
        "pydantic-settings>=2.6.0",
        "sqlalchemy[asyncio]>=2.0.36",
        "asyncpg>=0.30.0",
        "alembic>=1.14.0",
        "email-validator>=2.2.0",
        "structlog>=24.4.0",
        "httpx>=0.28.0",
    ]
    if with_auth:
        deps.extend(
            [
                "pwdlib[argon2]>=0.2.1",
                "PyJWT>=2.9.0",
                "python-multipart>=0.0.12",
                "slowapi>=0.1.9",
            ]
        )
    if with_redis:
        deps.append("redis[hiredis]>=5.2.0")
    if with_otel:
        deps.extend(
            [
                "opentelemetry-api>=1.28.0",
                "opentelemetry-sdk>=1.28.0",
                "opentelemetry-exporter-otlp>=1.28.0",
                "opentelemetry-instrumentation-fastapi>=0.49b0",
                "opentelemetry-instrumentation-sqlalchemy>=0.49b0",
                "opentelemetry-instrumentation-httpx>=0.49b0",
            ]
        )
    if with_prometheus:
        deps.extend(
            [
                "prometheus-client>=0.21.0",
            ]
        )
    if with_sentry:
        deps.append("sentry-sdk>=2.18.0")
    (out / "requirements.txt").write_text("\n".join(sorted(deps)) + "\n")


def _generate_package_inits(
    out: Path,
    models: dict[str, dict[str, str]],
    with_auth: bool,
) -> None:
    """Create __init__.py files for all packages and assemble the API router."""
    # Package init files (make directories importable)
    for pkg in ["core", "models", "crud", "schemas", "middleware", "api", "api/routes", "routes"]:
        pkg_dir = out / pkg
        if pkg_dir.exists():
            init_file = pkg_dir / "__init__.py"
            if not init_file.exists():
                init_file.write_text("")
        # Also handle observability and alerts if they exist
    for pkg in ["observability", "alerts"]:
        pkg_dir = out / pkg
        if pkg_dir.exists() and not (pkg_dir / "__init__.py").exists():
            (pkg_dir / "__init__.py").write_text("")

    # routes/__init__.py — exports:
    #   - health_router  → mounted at ROOT in main.py (K8s convention)
    #   - api_router     → mounted under prefix (/api/v1) in main.py
    routes_init = out / "routes" / "__init__.py"
    lines = [
        '"""Route registration."""',
        "",
        "from fastapi import APIRouter",
        "",
        "from app.routes.health import router as health_router",
        "",
        "# api_router collects all business routes; mounted under /api/v1 in main.py.",
        "# health_router is exported separately and mounted at ROOT.",
        "api_router = APIRouter()",
    ]

    # Include webhooks router if Stripe integration was added (registered separately
    # because webhooks have raw body parsing requirements)
    webhooks_path = out / "routes" / "webhooks.py"
    if webhooks_path.exists():
        lines.insert(4, "from app.routes.webhooks import router as webhooks_router")
        lines.append("api_router.include_router(webhooks_router)")

    # Include auth routes if generated
    if with_auth and (out / "api" / "routes" / "login.py").exists():
        lines.insert(4, "from app.api.routes.login import router as login_router")
        lines.append("api_router.include_router(login_router)")

    # Include user management routes if generated
    if with_auth and (out / "api" / "routes" / "users.py").exists():
        lines.insert(4, "from app.api.routes.users import router as users_router")
        lines.append("api_router.include_router(users_router)")

    # Include domain model routes
    for model_name in models:
        lower = model_name.lower()
        route_file = out / "api" / "routes" / f"{lower}.py"
        if route_file.exists():
            lines.insert(4, f"from app.api.routes.{lower} import router as {lower}_router")
            lines.append(f"api_router.include_router({lower}_router)")

    lines.append("")
    lines.append('__all__ = ["api_router", "health_router"]')
    lines.append("")
    routes_init.write_text("\n".join(lines))

    # models/__init__.py — import all models so Alembic can discover them
    models_dir = out / "models"
    if models_dir.exists():
        models_init = models_dir / "__init__.py"
        model_imports = ['"""Import all models for Alembic auto-discovery."""', ""]
        for model_name in models:
            lower = model_name.lower()
            if (models_dir / f"{lower}.py").exists():
                model_imports.append(f"from app.models.{lower} import {model_name}  # noqa: F401")
        if with_auth and (models_dir / "user.py").exists():
            model_imports.append("from app.models.user import User  # noqa: F401")
        model_imports.append("")
        models_init.write_text("\n".join(model_imports))
