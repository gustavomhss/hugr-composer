"""Internal phase helpers for :mod:`generators.orchestrator` (file 3 of 3).

Late-stage generation phases (deployment, observability, project files,
requirements, tests, scaffold smoke) extracted verbatim from the original
``generators/orchestrator.py`` during the ≤500-LOC file split.  They
operate on a shared mutable context object (``_Ctx``) so behaviour is
identical to the original single-function implementation.

DO NOT import this module directly — use ``generators.orchestrator``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from generators.infra.dockerfile import generate_dockerfile
from generators.infra.email import generate_email_utils
from generators.infra.env_example import generate_env_example
from generators.infra.gitignore import generate_gitignore
from generators.infra.initial_data import generate_initial_data
from generators.infra.precommit import generate_precommit
from generators.infra.prestart import generate_prestart
from generators.infra.readme import generate_readme
from generators.orchestrator__impl2 import (
    _generate_requirements,
    _write_bola_shared_models_audit,
)
from generators.testing.conftest import generate_test_infrastructure
from generators.testing.test_suite import generate_test_suite

if TYPE_CHECKING:  # pragma: no cover
    from generators.orchestrator__impl1 import _Ctx


def _phase_deployment(ctx: _Ctx) -> None:
    """Phase 7: Deployment (skipped by minimal/api/worker profiles)."""
    p = ctx.p
    if not p.get("skip_deployment"):
        ctx.run(
            "dockerfile",
            generate_dockerfile(
                output_dir=str(ctx.out),
                python_version=ctx.python_version,
            ),
        )

    if not p.get("skip_deployment") and ctx.with_docker_compose:
        try:
            from generators.deployment.docker_compose import generate_docker_compose

            ctx.run(
                "docker_compose",
                generate_docker_compose(
                    output_dir=str(ctx.out),
                    redis=ctx.with_redis,
                ),
            )
        except ImportError:
            ctx.phases["docker_compose"] = {
                "files": 0,
                "status": "skipped (generator not built yet)",
            }

    if not p.get("skip_deployment") and ctx.with_k8s:
        try:
            from generators.deployment.k8s import generate_k8s_manifests

            ctx.run(
                "k8s",
                generate_k8s_manifests(
                    output_dir=str(ctx.out),
                    app_name=ctx.name,
                    prefix=ctx.prefix,
                ),
            )
        except ImportError:
            ctx.phases["k8s"] = {"files": 0, "status": "skipped (generator not built yet)"}

    if not p.get("skip_deployment") and ctx.with_ci:
        try:
            from generators.deployment.github_actions import generate_github_actions

            ctx.run(
                "ci",
                generate_github_actions(
                    output_dir=str(ctx.out),
                    python_version=ctx.python_version,
                ),
            )
        except ImportError:
            ctx.phases["ci"] = {"files": 0, "status": "skipped (generator not built yet)"}

    if not p.get("skip_deployment") and ctx.with_loadtest:
        try:
            from generators.deployment.k6_loadtest import generate_k6_loadtest

            ctx.run(
                "loadtest",
                generate_k6_loadtest(
                    output_dir=str(ctx.out),
                    api_prefix=ctx.prefix,
                ),
            )
        except ImportError:
            ctx.phases["loadtest"] = {
                "files": 0,
                "status": "skipped (generator not built yet)",
            }


def _phase_observability(ctx: _Ctx) -> None:
    """Phase 8: Observability."""
    if ctx.with_otel:
        try:
            from generators.observability.otel import generate_otel_setup

            ctx.run(
                "otel",
                generate_otel_setup(
                    output_dir=str(ctx.app_dir),
                    service_name=ctx.name,
                ),
            )
        except ImportError:
            ctx.phases["otel"] = {"files": 0, "status": "skipped (generator not built yet)"}

    if ctx.with_prometheus:
        try:
            from generators.observability.prometheus import generate_prometheus_metrics

            ctx.run(
                "prometheus",
                generate_prometheus_metrics(
                    output_dir=str(ctx.app_dir),
                    prefix=ctx.name.replace("-", "_"),
                ),
            )
        except ImportError:
            ctx.phases["prometheus"] = {
                "files": 0,
                "status": "skipped (generator not built yet)",
            }

    if ctx.with_alerting:
        try:
            from generators.observability.alerting import generate_alerting_rules

            ctx.run(
                "alerting",
                generate_alerting_rules(
                    output_dir=str(ctx.out),
                    service_name=ctx.name,
                ),
            )
        except ImportError:
            ctx.phases["alerting"] = {
                "files": 0,
                "status": "skipped (generator not built yet)",
            }


def _phase_project_files(ctx: _Ctx) -> None:
    """Phase 9: Project files (root) + Python utility scripts (app/)."""
    p = ctx.p
    # Root-level project files (not Python source)
    ctx.run(
        "env_example",
        generate_env_example(
            output_dir=str(ctx.out),
            with_db=True,
            with_redis=ctx.with_redis,
            with_sentry=ctx.with_sentry,
            prefix=ctx.prefix,
        ),
    )
    ctx.run(
        "readme",
        generate_readme(
            output_dir=str(ctx.out),
            name=ctx.name,
            prefix=ctx.prefix,
        ),
    )
    if not p.get("skip_precommit"):
        ctx.run("precommit", generate_precommit(output_dir=str(ctx.out)))
    ctx.run("gitignore", generate_gitignore(output_dir=str(ctx.out)))

    # Python source utilities (live under app/)
    if not p.get("skip_email_utils"):
        ctx.run("email_utils", generate_email_utils(output_dir=str(ctx.app_dir)))

    if ctx.with_auth:
        ctx.run("initial_data", generate_initial_data(output_dir=str(ctx.app_dir)))

    ctx.run("prestart", generate_prestart(output_dir=str(ctx.app_dir)))


def _phase_requirements(ctx: _Ctx) -> None:
    """Phase 10: requirements.txt (BEFORE test_infra which appends to it)."""
    _generate_requirements(
        ctx.out,
        ctx.with_auth,
        ctx.with_redis,
        ctx.with_otel,
        ctx.with_prometheus,
        ctx.with_sentry,
    )
    ctx.all_files.append(str(ctx.out / "requirements.txt"))
    ctx.phases["requirements"] = {"files": 1, "status": "done"}


def _phase_tests(ctx: _Ctx) -> None:
    """Phase 11: Test infrastructure + test suite (skipped by minimal/worker)."""
    p = ctx.p
    if not p.get("skip_testing") and (ctx.models or ctx.with_auth):
        ctx.run(
            "test_infra",
            generate_test_infrastructure(
                output_dir=str(ctx.out),
                with_auth=ctx.with_auth,
            ),
        )
        ctx.run(
            "test_suite",
            generate_test_suite(
                output_dir=str(ctx.out),
                models=ctx.models,
                owner_models=ctx.owner_models,
                with_auth=ctx.with_auth,
                # F-005 + F-007: pass shared_models through so emitted
                # tests pick the right BOLA story (403 vs open access).
                shared_models=ctx.shared_models_set or None,
            ),
        )

        # BOLA opt-out audit file.  When the caller has flagged any owner-
        # bearing model as ``shared_models``, emit an explicit pytest module
        # that documents (and at import time, asserts) the open-access
        # policy.  A reviewer scanning the repo sees a single file listing
        # every model that intentionally bypasses the per-object guard —
        # the security trade-off is one Cmd-F away from "BOLA".
        if ctx.shared_models_set:
            audit_file = _write_bola_shared_models_audit(
                ctx.out,
                sorted(ctx.shared_models_set),
                ctx.prefix,
            )
            ctx.all_files.append(str(audit_file))
            ctx.phases["bola_shared_models_audit"] = {
                "files": 1,
                "status": "done",
            }
            ctx.all_notes.append(
                "BOLA opt-out: shared_models="
                f"{sorted(ctx.shared_models_set)} — per-object ownership guard "
                "suppressed; audit file emitted at tests/test_bola_shared_models.py."
            )


def _phase_scaffold_venous(ctx: _Ctx) -> None:
    """Phase 12: scaffold_venous smoke — prove the copy-in pipe works.

    See ADR 0002 + CONTRACT §B1.0.  Tools refactored under §B1.3 call
    ensure_primitives themselves; this single call here keeps the
    orchestrator honest by shipping at least one primitive on every
    fresh project.
    """
    try:
        from generators.scaffold_venous import ensure_primitives

        manifest = ensure_primitives(
            str(ctx.out),
            names=["core.venous.resiliency.GracefulShutdown"],
        )
        if manifest.copied:
            ctx.phases["scaffold_venous"] = {
                "files": len(manifest.copied),
                "status": "done",
            }
        else:
            ctx.phases["scaffold_venous"] = {"files": 0, "status": "already_present"}
    except Exception as exc:  # noqa: BLE001 — smoke step must not break project gen
        ctx.phases["scaffold_venous"] = {"files": 0, "status": f"skipped ({exc})"}
