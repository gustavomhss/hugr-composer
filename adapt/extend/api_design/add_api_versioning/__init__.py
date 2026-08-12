"""TOOL-017: add_api_versioning — add path-based API versioning to a FastAPI project.

Adds versioned routers under ``/api/v1/`` and ``/api/v2/``, a ``VersionRegistry``
with deprecation and sunset metadata, a ``VersionResolverMiddleware`` that sets
``request.state.api_version`` and attaches ``Sunset``/``Deprecation``/``Link``
response headers, and versioned schema stubs under ``app/schemas/v1/`` and
``app/schemas/v2/``.

The tool is idempotent: a second run on an already-patched project detects the
``VersionRegistry`` fingerprint and returns ``status="no_op"`` without touching any
file.

Warnings:
    - This tool routes by URL path prefix (/api/v1/, /api/v2/).
      It does NOT support header-based version routing.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.api_design.add_api_versioning import add_api_versioning

    result = add_api_versioning(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # ["...app/core/version_registry.py", ...]
    print(result.next_steps)    # ["Restart application", ...]
"""

from __future__ import annotations

import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_api_add_api_versioning",
    "description": "Add URL-based API versioning (/api/v1, /api/v2) with deprecation headers.",
    "tags": ["extend", "api_design"],
    "entry": "add_api_versioning",
    "imports_primitives": [],
    "imports_adapters": [],

}

_PREREQ_NOTES = [
    "These prerequisites cannot be auto-created.",
    "Generate a base project first:",
    "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
]


def add_api_versioning(inp: ToolInput) -> ToolResult:
    """Add path-based API versioning to a FastAPI project.

    Creates version registry, deprecation middleware, versioned schema stubs,
    versioned router packages, and wires everything into ``app/main.py``.

    Args:
        inp: ``ToolInput`` with ``project_dir`` (absolute path) and optional
            ``dry_run`` flag.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.CONFIG_SETTINGS,
        Prereq.ROUTES_INIT,
        auto_scaffold=not inp.dry_run,
    )
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=_PREREQ_NOTES,
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = list(scaffolded or [])
    app_dir = project / "app"

    # Idempotency guard
    registry_file = app_dir / "core" / "version_registry.py"
    if registry_file.exists() and "VersionRegistry" in registry_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["VersionRegistry already present — API versioning is already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    model_names = _discover_models(app_dir)

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would add VersionRegistry, VersionResolverMiddleware, versioned routers.",
                f"[dry_run] Models found: {', '.join(model_names) or 'none'}",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # Step 1: version_registry.py
    render_to(_HERE, "version_registry.py.tmpl", dest=registry_file, substitutions={})
    files_created.append(str(registry_file))

    # Step 2: version_resolver middleware
    mw_file = app_dir / "middleware" / "version_resolver.py"
    render_to(_HERE, "version_resolver.py.tmpl", dest=mw_file, substitutions={})
    files_created.append(str(mw_file))

    # Step 3: versioned schema stubs
    for ver in ("v1", "v2"):
        schema_init = app_dir / "schemas" / ver / "__init__.py"
        model_lines = (
            "\n".join(
                f"# from app.schemas.{ver}.{m.lower()} import {m}Create, {m}Public  # noqa: F401"
                for m in model_names
            )
            or "# No models discovered — add imports here."
        )
        render_to(
            _HERE,
            "versioned_schema_init.py.tmpl",
            dest=schema_init,
            substitutions={"version": ver, "model_lines": model_lines},
        )
        files_created.append(str(schema_init))

    # Step 4: versioned router packages
    for ver in ("v1", "v2"):
        router_init = app_dir / "api" / ver / "__init__.py"
        include_lines = (
            "\n".join(
                f"router.include_router("
                f"{m.lower()}_router, prefix='/{m.lower()}s', tags=['{ver}-{m.lower()}s'])"
                for m in model_names
            )
            or "# No models discovered — include routers here."
        )
        import_lines = (
            "\n".join(
                f"from app.api.{ver}.{m.lower()} import router as {m.lower()}_router"
                for m in model_names
            )
            or "# No models discovered."
        )
        render_to(
            _HERE,
            "versioned_router_init.py.tmpl",
            dest=router_init,
            substitutions={
                "version": ver,
                "import_lines": import_lines,
                "include_lines": include_lines,
            },
        )
        files_created.append(str(router_init))

    # Step 5: per-model versioned routes stubs
    for ver in ("v1", "v2"):
        for model in model_names:
            route_file = app_dir / "api" / ver / f"{model.lower()}.py"
            render_to(
                _HERE,
                "versioned_route.py.tmpl",
                dest=route_file,
                substitutions={"version": ver, "model_name": model, "lower": model.lower()},
            )
            files_created.append(str(route_file))

    # Step 6: patch main.py
    main_file = app_dir / "main.py"
    if main_file.exists():
        _patch_main(main_file, model_names)
        files_modified.append(str(main_file))

    # Step 7: emit test
    _emit_project_test(project, files_created)

    import ast
    for fpath in files_created:
        if fpath.endswith(".py"):
            try:
                ast.parse(Path(fpath).read_text())
            except SyntaxError as e:
                return ToolResult(
                    status="error",
                    error=f"Syntax error in {fpath}: {e}",
                    files_created=[],
                    execution_time_ms=_elapsed_ms(start),
                )

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "Path-based versioning added: /api/v1/ and /api/v2/.",
            "VersionResolverMiddleware sets request.state.api_version.",
            "Sunset/Deprecation/Link headers emitted for deprecated versions.",
            "Versioned schema stubs placed under app/schemas/v1/ and app/schemas/v2/.",
            "WARNING: routing is by URL path prefix only — header-based routing not supported.",
        ],
        next_steps=[
            "Restart the application to activate VersionResolverMiddleware.",
            "Populate app/schemas/v1/ and app/schemas/v2/ with real schema classes.",
            "Move existing endpoint logic into app/api/v1/<model>.py.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _discover_models(app_dir: Path) -> list[str]:
    """Return PascalCase model names that have a matching route file.

    Only models with a corresponding ``app/api/routes/{stem}.py`` are included
    so that versioned stubs can safely delegate to the existing router.

    Args:
        app_dir: The ``app/`` package directory.

    Returns:
        Sorted list of discovered model names (e.g. ``["Item"]``).
    """
    models_dir = app_dir / "models"
    routes_dir = app_dir / "api" / "routes"
    skip = {"base", "user", "mixins", "__init__", "tenant"}
    names: list[str] = []
    if not models_dir.exists():
        return names
    available_routes: set[str] = set()
    if routes_dir.exists():
        for r in routes_dir.glob("*.py"):
            if r.stem != "__init__":
                available_routes.add(r.stem)
    for f in sorted(models_dir.glob("*.py")):
        if f.stem in skip:
            continue
        if f.stem in available_routes:
            names.append(f.stem.capitalize())
    return names


def _patch_main(main_file: Path, model_names: list[str]) -> None:
    """Wire VersionResolverMiddleware and versioned routers into main.py."""
    src = main_file.read_text()
    if "VersionResolverMiddleware" in src:
        return

    middleware_import = "\nfrom app.middleware.version_resolver import VersionResolverMiddleware"
    v1_import = "\nfrom app.api.v1 import router as _v1_router"
    v2_import = "\nfrom app.api.v2 import router as _v2_router"

    if "from fastapi import FastAPI" in src:
        src = src.replace(
            "from fastapi import FastAPI",
            "from fastapi import FastAPI" + middleware_import + v1_import + v2_import,
        )
    else:
        src = middleware_import + v1_import + v2_import + "\n" + src

    middleware_call = (
        "\napp.add_middleware(VersionResolverMiddleware)"
        "\napp.include_router(_v1_router, prefix='/api/v1')"
        "\napp.include_router(_v2_router, prefix='/api/v2')"
        "\n"
    )
    if "app.add_middleware" in src:
        idx = src.rfind("app.add_middleware")
        end = src.find("\n", idx)
        src = src[: end + 1] + middleware_call + src[end + 1 :]
    else:
        src = src.rstrip("\n") + "\n" + middleware_call

    main_file.write_text(src)


def _emit_project_test(project: Path, created: list[str]) -> None:
    """Emit tests/test_add_api_versioning_emitted.py into the generated project."""
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_api_versioning_emitted.py"
    if emitted.exists():
        return
    render_to(
        _HERE,
        "test_add_api_versioning_emitted.py.tmpl",
        dest=emitted,
        substitutions={},
    )
    created.append(str(emitted))


