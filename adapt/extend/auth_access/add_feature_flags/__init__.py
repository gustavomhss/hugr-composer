"""TOOL-009: add_feature_flags — production-grade feature-flag system backed by primitives.

Ships the FeatureToggle + FeatureFlagCache primitives, emits a thin ≤20-line
``app/feature_flags.py`` glue that re-exports ``get_registry`` / ``get_cache``
/ ``require_flag``, plus a full DB-backed flag model, cache, evaluator, CRUD,
admin routes, schemas, and Alembic migration.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt._base import load_template, render
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.migration_helper import find_migration_head

_HERE = Path(__file__).parent


MCP_TOOL = {
    "name": "fastapi_auth_add_feature_flags",
    "description": (
        "Copy FeatureToggle + FeatureFlagCache primitives into the project "
        "and wire a ≤20-line app/feature_flags.py glue that exposes a "
        "require_flag FastAPI dependency."
    ),
    "tags": ["extend", "auth_access"],
    "entry": "add_feature_flags",
    "imports_primitives": [
        "core.venous.flags.FeatureToggle",
        "core.venous.auth.FeatureFlagCache",
    ],
    "imports_adapters": (),
}


def _emit(template_name: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(load_template(_HERE, template_name).template)


def add_feature_flags(inp: ToolInput) -> ToolResult:
    """Add a production-grade feature-flag subsystem to a FastAPI project."""
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

    from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.BASE_MODEL,
        Prereq.MODELS_INIT,
        Prereq.CONFIG_SETTINGS,
        Prereq.ROUTES_INIT,
        Prereq.ALEMBIC_VERSIONS,
    )
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=[
                "These prerequisites cannot be auto-created.",
                "Generate a base project first:",
                "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    if scaffolded:
        files_created.extend(scaffolded)

    app_dir = project / "app"
    glue_file = app_dir / "feature_flags.py"
    if glue_file.exists() and "FeatureToggle" in glue_file.read_text():
        return ToolResult(
            status="no_op",
            notes=[
                "FeatureToggle + FeatureFlagCache primitives already wired via "
                "app/feature_flags.py — skipped."
            ],
            execution_time_ms=_elapsed_ms(start),
        )
    flag_model_file = app_dir / "models" / "feature_flag.py"

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create feature-flag model, cache, evaluator, CRUD, routes, schemas, migration.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # Step 0: copy primitives + emit glue
    from generators.scaffold_venous import ensure_primitives

    manifest = ensure_primitives(
        str(project),
        names=[
            "core.venous.flags.FeatureToggle",
            "core.venous.auth.FeatureFlagCache",
        ],
        adapters=[],
    )
    files_created.append(manifest.path)
    glue_file.write_text(load_template(_HERE, "glue.py.tmpl").template)
    files_created.append(str(glue_file))

    # Step 1: models
    _emit("model.py.tmpl", flag_model_file)
    files_created.append(str(flag_model_file))
    _patch_models_init(
        app_dir / "models" / "__init__.py",
        [
            ("feature_flag", "FeatureFlag"),
            ("feature_flag", "FeatureFlagAudit"),
        ],
    )

    # Step 2-7: cache, evaluator, deps, crud, schemas, routes
    cache_file = app_dir / "core" / "feature_flag_cache.py"
    _emit("cache.py.tmpl", cache_file)
    files_created.append(str(cache_file))

    evaluator_file = app_dir / "core" / "feature_flag_evaluator.py"
    _emit("evaluator.py.tmpl", evaluator_file)
    files_created.append(str(evaluator_file))

    deps_file = app_dir / "core" / "feature_flag_deps.py"
    _emit("deps.py.tmpl", deps_file)
    files_created.append(str(deps_file))

    crud_file = app_dir / "crud" / "feature_flag.py"
    _emit("crud.py.tmpl", crud_file)
    files_created.append(str(crud_file))

    schema_file = app_dir / "schemas" / "feature_flag.py"
    _emit("schemas.py.tmpl", schema_file)
    files_created.append(str(schema_file))

    routes_file = app_dir / "api" / "routes" / "feature_flags.py"
    _emit("routes.py.tmpl", routes_file)
    files_created.append(str(routes_file))

    # Step 8: migration
    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        migration_file = _write_migration(versions_dir)
        files_created.append(str(migration_file))

    # Step 9: main.py patch
    main_file = app_dir / "main.py"
    if main_file.exists():
        _patch_main(main_file)
        files_modified.append(str(main_file))

    for path_str in files_created:
        p = Path(path_str)
        if p.suffix == ".py" and p.is_file():
            try:
                ast.parse(p.read_text())
            except SyntaxError as exc:
                return ToolResult(
                    status="error",
                    error=f"Generated file has syntax error: {p}: {exc}",
                    execution_time_ms=_elapsed_ms(start),
                )

    glue_loc = _count_logic_lines(glue_file.read_text())
    if glue_loc > 20:
        return ToolResult(
            status="error",
            error=f"Primary glue {glue_file} has {glue_loc} logic lines (> 20).",
            execution_time_ms=_elapsed_ms(start),
        )

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "Shipped primitives: core.venous.flags.FeatureToggle, core.venous.auth.FeatureFlagCache.",
            "Glue: app/feature_flags.py wires FeatureToggleRegistry + FeatureFlagCache + require_flag.",
            "Feature-flag subsystem added: model, cache, evaluator, deps, CRUD, routes, schemas.",
            # Honest disclosure (B0.13 / R5-S2-F7+F8): the in-process cache is
            # per-worker single-node with a 60s TTL; the Redis pubsub
            # ``publish_invalidation`` helper and ``start_invalidation_listener``
            # ship but are NOT wired by this tool (main.py patch is commented
            # out; CRUD never calls publish). See warnings= below.
            "single-node in-process LRU cache, 60s TTL — see next_steps for invalidation wiring.",
            "SHA-256 deterministic bucketing for percentage rollouts.",
            "Kill switch overrides all other evaluation logic at the per-worker cache level.",
            "Every flag mutation writes an audit row in the same transaction.",
        ],
        warnings=[
            # R5-S2-F7: invalidation listener startup is shipped as a
            # commented stub in _patch_main; operators must uncomment +
            # provide app/core/redis.py for cross-worker fan-out to occur.
            "Cache invalidation listener is NOT auto-wired: app/main.py "
            "lifespan ships a commented-out start_invalidation_listener "
            "stub. Until uncommented, mutations propagate only after the "
            "60s TTL expires on each worker.",
            # R5-S2-F8: cache TTL race — even with the listener wired, a
            # second between publish and per-worker invalidate means stale
            # reads. Kill-switch flips are subject to the same lag.
            "Kill-switch flips can lag up to 60s on workers that have a "
            "cached entry — the per-worker TTL is the upper bound; "
            "operators needing immediate effect must also bounce workers "
            "or call cache.clear() out-of-band.",
            "CRUD does not auto-publish invalidation events; wiring "
            "publish_invalidation into create/update/delete is left to "
            "the integrator (see app/core/feature_flag_cache.py).",
        ],
        next_steps=[
            "alembic upgrade head",
            "Set FEATURE_FLAG_CACHE_TTL=60 and FEATURE_FLAG_EVAL_TIMEOUT_MS=5 in .env",
            "Wire require_flag: @router.get('/beta', dependencies=[Depends(require_flag('my_flag'))])",
            "OPTIONAL cross-worker invalidation: provision Redis + app/core/redis.py, "
            "uncomment the start_invalidation_listener block in app/main.py lifespan, "
            "and call publish_invalidation(redis, key) inside crud.update/delete.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _patch_models_init(models_init: Path, class_imports: list[tuple[str, str]]) -> None:
    if not models_init.exists():
        return
    content = models_init.read_text()
    new_lines: list[str] = []
    for module, cls in class_imports:
        marker = f"from app.models.{module} import {cls}"
        if marker in content:
            continue
        new_lines.append(f"{marker}  # noqa: F401")
    if not new_lines:
        return
    if not content.endswith("\n"):
        content += "\n"
    content += "\n".join(new_lines) + "\n"
    models_init.write_text(content)


def _write_migration(versions_dir: Path) -> Path:
    rev_id = "0009_add_feature_flags"
    down_rev = find_migration_head(versions_dir) or "0001_initial"
    content = render(
        _HERE,
        "migration.py.tmpl",
        {"rev_id": rev_id, "down_rev": down_rev},
    )
    migration_file = versions_dir / f"{rev_id}.py"
    migration_file.write_text(content)
    return migration_file


def _patch_main(main_file: Path) -> None:
    src = main_file.read_text()
    if "feature_flag" in src:
        return
    marker = "await init_db()"
    flag_note = (
        "\n    # Feature flags: start Redis invalidation listener on startup\n"
        "    # from app.core.feature_flag_cache import get_flag_cache\n"
        "    # from app.core.redis import get_redis\n"
        "    # await get_flag_cache().start_invalidation_listener(await get_redis())"
    )
    if marker in src:
        src = src.replace(marker, marker + flag_note)
    main_file.write_text(src)


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


def _count_logic_lines(source: str) -> int:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return 0
    loc = 0
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0].lineno
            last = node.end_lineno or first
            loc += last - first + 1
    return loc
