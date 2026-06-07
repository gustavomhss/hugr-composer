"""Early-stage generation phases for :mod:`generators.orchestrator`.

Phases 1-6 (config/logging, database, schemas, auth, middleware,
endpoints, app entry) extracted verbatim from the original
``generators/orchestrator.py`` during the ≤500-LOC file split.  They
operate on the shared ``_Ctx`` object so behaviour is identical to the
original single-function implementation.

DO NOT import this module directly — use ``generators.orchestrator``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from generators.auth.deps import generate_auth_deps
from generators.auth.hasher import generate_password_hasher
from generators.auth.jwt import generate_jwt
from generators.auth.rate_limit import generate_rate_limit
from generators.auth.routes import generate_auth_routes
from generators.auth.schemas import generate_auth_schemas
from generators.database.alembic import generate_alembic
from generators.database.alembic_migration import generate_baseline_migration
from generators.database.crud import generate_crud
from generators.database.crud_base import generate_crud_base
from generators.database.engine import generate_engine
from generators.database.model import generate_model
from generators.database.session import generate_session
from generators.endpoints.crud_routes import generate_crud_routes
from generators.endpoints.errors import generate_error_handlers
from generators.endpoints.health import generate_health_checks
from generators.endpoints.user_routes import generate_user_routes
from generators.infra.app import generate_app
from generators.infra.config import generate_config
from generators.infra.logging import generate_logging_setup
from generators.middleware.body_size import generate_body_size_middleware
from generators.middleware.correlation import generate_correlation_id
from generators.middleware.idempotency import generate_idempotency_middleware
from generators.middleware.request_logging import generate_request_logging
from generators.middleware.security_headers import generate_security_headers
from generators.middleware.stack import generate_middleware_stack
from generators.schemas.input_schema import generate_input_schema
from generators.schemas.list_response import generate_list_response
from generators.schemas.output_schema import generate_output_schema

from generators.orchestrator__impl2 import _generate_package_inits

if TYPE_CHECKING:  # pragma: no cover
    from generators.orchestrator__impl1 import _Ctx


def _phase_config_logging(ctx: _Ctx) -> None:
    """Phase 1: Config + logging (foundation for everything else)."""
    ctx.run(
        "config",
        generate_config(
            output_dir=str(ctx.app_dir),
            with_db=True,
            with_redis=ctx.with_redis,
            with_sentry=ctx.with_sentry,
            prefix=ctx.prefix,
        ),
    )
    ctx.run("logging_setup", generate_logging_setup(output_dir=str(ctx.app_dir)))


def _phase_database(ctx: _Ctx) -> None:
    """Phase 2: Database layer (engine, session, models, CRUD, alembic)."""
    app_dir = ctx.app_dir
    out = ctx.out
    _run = ctx.run
    with_auth = ctx.with_auth
    owner_models = ctx.owner_models

    _run("db_engine", generate_engine(output_dir=str(app_dir)))
    _run("db_session", generate_session(output_dir=str(app_dir)))
    _run("crud_base", generate_crud_base(output_dir=str(app_dir)))

    models = ctx.models
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
        ctx.models = models

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


def _phase_schemas(ctx: _Ctx) -> None:
    """Phase 2b: Schemas for all models + UserPublic relaxation."""
    app_dir = ctx.app_dir
    _run = ctx.run
    models = ctx.models
    with_auth = ctx.with_auth

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


def _phase_auth(ctx: _Ctx) -> None:
    """Phase 3: Auth stack + standalone Message schema fallback."""
    app_dir = ctx.app_dir
    _run = ctx.run
    with_auth = ctx.with_auth
    prefix = ctx.prefix

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
            ctx.all_files.append(str(msg_file))
            ctx.phases["message_schema"] = {"files": 1, "status": "done"}


def _phase_middleware(ctx: _Ctx) -> None:
    """Phase 4: Middleware (skipped by minimal/worker profiles)."""
    app_dir = ctx.app_dir
    _run = ctx.run
    if not ctx.p.get("skip_middleware"):
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
                cors_origins=ctx.cors_origins,
                with_gzip=ctx.with_gzip,
            ),
        )


def _phase_endpoints(ctx: _Ctx) -> None:
    """Phase 5 + 5b + 6: Endpoints, package inits/router, app entry."""
    app_dir = ctx.app_dir
    _run = ctx.run
    p = ctx.p
    models = ctx.models
    with_auth = ctx.with_auth
    owner_models = ctx.owner_models
    shared_models_set = ctx.shared_models_set

    # Phase 5: Endpoints (skipped by worker profile)
    if not p.get("skip_routes"):
        _run(
            "health_checks",
            generate_health_checks(
                output_dir=str(app_dir),
                check_redis=ctx.with_redis,
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

    # Phase 5b: Package init files + router assembly
    if not p.get("skip_routes"):
        _generate_package_inits(app_dir, models or {}, with_auth)

    # Phase 6: Application entry point (skipped by worker profile)
    if not p.get("skip_app_entry"):
        _run(
            "app",
            generate_app(
                output_dir=str(app_dir),
                name=ctx.name,
                prefix=ctx.prefix,
                with_sentry=ctx.with_sentry,
                with_rate_limit=with_auth,
                with_prometheus=ctx.with_prometheus,
            ),
        )
