"""Core implementation for :mod:`generators.orchestrator` (file 1 of N).

Holds the public ``generate_project`` entry point, the ``PROFILES``
preset table, and the shared ``_Ctx`` state object.  The generation
phases live in ``orchestrator__impl4`` (early) and
``orchestrator__impl3`` (late); leaf helpers in ``orchestrator__impl2``.
This file was extracted verbatim from the original
``generators/orchestrator.py`` during the ≤500-LOC file split with NO
behaviour change.

DO NOT import this module directly — use ``generators.orchestrator``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from generators.orchestrator__impl3 import (
    _phase_deployment,
    _phase_observability,
    _phase_project_files,
    _phase_requirements,
    _phase_scaffold_venous,
    _phase_tests,
)
from generators.orchestrator__impl4 import (
    _phase_auth,
    _phase_config_logging,
    _phase_database,
    _phase_endpoints,
    _phase_middleware,
    _phase_schemas,
)
from generators.scaffold_manifest import emit_doc_gate

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
        "with_ci": True,
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
        "description": (
            "Production API: models + auth + middleware + health. "
            "~50 files. No deployment/observability."
        ),
        "with_auth": True,
        "with_redis": True,
        "with_docker_compose": False,
        "with_ci": True,
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
        "description": (
            "Everything: auth + middleware + deployment + observability + testing. ~80 files."
        ),
        "skip_middleware": False,
        "skip_deployment": False,
        "skip_testing": False,
        "skip_email_utils": False,
        "skip_precommit": False,
    },
    "worker": {
        "description": (
            "Background worker only: models + DB + config. No API routes, "
            "no auth, no middleware. ~20 files."
        ),
        "with_auth": False,
        "with_redis": True,
        "with_docker_compose": False,
        "with_ci": True,
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


@dataclass
class _Ctx:
    """Shared mutable state threaded through the generation phases.

    Carries resolved flags, paths, and the accumulating manifest so the
    phase helpers behave exactly like the original single-function body.
    """

    out: Path
    app_dir: Path
    name: str
    prefix: str
    profile: str
    p: dict
    models: dict[str, dict[str, str]] | None
    owner_models: dict[str, str] | None
    shared_models_set: frozenset[str]
    with_auth: bool
    with_sentry: bool
    with_redis: bool
    with_gzip: bool
    cors_origins: list[str] | None
    python_version: str
    with_docker_compose: bool
    with_k8s: bool
    with_ci: bool
    with_loadtest: bool
    with_otel: bool
    with_prometheus: bool
    with_alerting: bool
    all_files: list[str] = field(default_factory=list)
    all_notes: list[str] = field(default_factory=list)
    phases: dict[str, dict] = field(default_factory=dict)

    def run(self, phase: str, result: dict) -> None:
        self.all_files.extend(result["files_created"])
        self.all_notes.extend(result.get("notes", []))
        self.phases[phase] = {
            "files": len(result["files_created"]),
            "status": "done",
        }


def _pascal_case(name: str) -> str:
    """Normalise a caller-supplied model key to PascalCase.

    The generator convention is PascalCase keys (``"Order"``); callers
    sometimes pass lowercase or snake_case (``"order"`` / ``"order_item"``).
    Normalising here keeps the class name, module name, and the import
    emitted by ``orchestrator__impl2`` consistent — otherwise the import
    uses the raw key while the class is capitalised, producing
    ``ImportError: cannot import name 'order'``.

    Only the first letter of each segment is uppercased (never
    ``str.capitalize()``, which would mangle already-PascalCase keys
    like ``OrderItem`` into ``Orderitem``).
    """
    return "".join(part[:1].upper() + part[1:] for part in name.split("_"))


def generate_project(  # noqa: C901 — orchestrator: each branch is one subsystem phase (auth, db, models, deploy, obs).
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
    # Model-key normalisation.  The convention is PascalCase keys
    # (``{"Order": ...}``); accept lowercase / snake_case and normalise
    # up-front so the class name, module name, and cross-file imports
    # stay consistent (see ``_pascal_case``).
    # ------------------------------------------------------------------
    if models:
        models = {_pascal_case(k): v for k, v in models.items()}
    if owner_models:
        owner_models = {_pascal_case(k): v for k, v in owner_models.items()}
    if shared_models:
        shared_models = {_pascal_case(name) for name in shared_models}

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

    ctx = _Ctx(
        out=out,
        app_dir=app_dir,
        name=name,
        prefix=prefix,
        profile=profile,
        p=p,
        models=models,
        owner_models=owner_models,
        shared_models_set=shared_models_set,
        with_auth=with_auth,
        with_sentry=with_sentry,
        with_redis=with_redis,
        with_gzip=with_gzip,
        cors_origins=cors_origins,
        python_version=python_version,
        with_docker_compose=with_docker_compose,
        with_k8s=with_k8s,
        with_ci=with_ci,
        with_loadtest=with_loadtest,
        with_otel=with_otel,
        with_prometheus=with_prometheus,
        with_alerting=with_alerting,
    )

    # ------------------------------------------------------------------
    # Generation phases (order matters — see each helper's docstring).
    # ------------------------------------------------------------------
    _phase_config_logging(ctx)  # Phase 1
    _phase_database(ctx)  # Phase 2 (may inject OrderItem into ctx.models)
    _phase_schemas(ctx)  # Phase 2b
    _phase_auth(ctx)  # Phase 3
    _phase_middleware(ctx)  # Phase 4
    _phase_endpoints(ctx)  # Phase 5 / 5b / 6
    _phase_deployment(ctx)  # Phase 7
    _phase_observability(ctx)  # Phase 8
    _phase_project_files(ctx)  # Phase 9
    _phase_requirements(ctx)  # Phase 10
    _phase_tests(ctx)  # Phase 11
    _phase_scaffold_venous(ctx)  # Phase 12

    # Phase 13: emit hash-sidecar manifest + vendored doc-gate scripts.
    # MUST run last — the manifest hashes the files written by every prior phase.
    manifest_path = emit_doc_gate(
        ctx.out,
        skill="SKILL-001-fastapi-production",
        name=ctx.name,
        prefix=ctx.prefix,
        profile=ctx.profile,
    )
    ctx.all_files.append(str(manifest_path))

    return {
        "files_created": ctx.all_files,
        "notes": ctx.all_notes,
        "phases": ctx.phases,
        "total_files": len(ctx.all_files),
        "profile": profile,
        "profile_description": p["description"],
    }
