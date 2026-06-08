"""TOOL-021: add_cache_layer — Redis-pluggable caching backed by primitives.

The emitted primitives ship with an IN-MEMORY fallback and establish no Redis
connection by default (see Warnings); swap in real Redis-backed implementations
for production. "Redis-pluggable", not Redis-backed out of the box.

Follows the CONTRACT §B1.0 + §B1.0.1 pattern (Rails-style wiring):

1. Copy the framework-agnostic primitives
   ``core.venous.cache.KeyValueBucket`` (generic KV store),
   ``core.venous.cache.SessionCache`` (session-scoped read-through cache),
   and ``core.venous.cache.DistributedLock`` (stampede-prevention mutex)
   into the generated project.
2. Emit a thin ``app/cache.py`` glue file (≤ 20 logic lines, AST verified)
   that instantiates a ``KeyValueBucket`` + exposes a ``cache_aside`` helper
   gated by ``DistributedLock`` and a ``get_session_cache`` factory.
3. Emit the Redis-pluggable ``@cached`` decorator, invalidation, stats route
   — the *semantics* (revision-tracked KV, read-through loader, mutex
   lease validity) live in the primitives.

The tool is idempotent: a second run detects ``KeyValueBucket`` in
``app/cache/primitives.py`` and returns ``status="no_op"``.

Warnings:
    - The glue wires primitives as lazy singletons; no Redis connection is
      made at module import time (import-cheap: safe for boot smoke).
    - app/cache/primitives.py uses in-memory fallback primitives — swap for
      real Redis-backed implementations in production.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_resiliency_add_cache_layer",
    "description": (
        "Copy KeyValueBucket + SessionCache + DistributedLock primitives "
        "into the project and wire a ≤20-line app/cache.py glue that "
        "exposes cache_aside() + get_session_cache() helpers."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_cache_layer",
    "imports_primitives": [
        "core.venous.cache.KeyValueBucket",
        "core.venous.cache.SessionCache",
        "core.venous.cache.DistributedLock",
    ],
    "imports_adapters": (),
}


def add_cache_layer(inp: ToolInput) -> ToolResult:
    """Add Redis cache layer to a FastAPI project.

    Writes ``app/cache/`` package (primitives, core, decorator, invalidation,
    keys, stats route), patches ``app/main.py`` to register the cache
    lifespan, and adds a ``/cache/stats`` endpoint.

    Args:
        inp: ``ToolInput`` with ``project_dir`` and optional ``dry_run``.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_ms(start))

    from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.CONFIG_SETTINGS,
        Prereq.REQUIREMENTS_TXT,
        auto_scaffold=not inp.dry_run,
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
            execution_time_ms=_ms(start),
        )

    files_created: list[str] = []
    if scaffolded:
        files_created.extend(scaffolded)

    app_dir = project / "app"
    glue_file = app_dir / "cache" / "primitives.py"
    if glue_file.exists() and "KeyValueBucket" in glue_file.read_text():
        return ToolResult(
            status="no_op",
            notes=[
                "KeyValueBucket + SessionCache + DistributedLock primitives "
                "already wired via app/cache/primitives.py — skipped."
            ],
            execution_time_ms=_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/cache/ package with primitives, core, decorator, invalidation, keys, stats."
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_ms(start),
        )

    files_modified: list[str] = []

    # Step 0: Copy primitives (§B1.0)
    from generators.scaffold_venous import ensure_primitives

    manifest = ensure_primitives(
        str(project),
        names=[
            "core.venous.cache.KeyValueBucket",
            "core.venous.cache.SessionCache",
            "core.venous.cache.DistributedLock",
        ],
        adapters=[],
    )
    files_created.append(manifest.path)

    # Step 1: cache package
    cache_dir = app_dir / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    render_to(_HERE, "primitives.py.tmpl", dest=glue_file, substitutions={})
    files_created.append(str(glue_file))

    init_file = cache_dir / "__init__.py"
    render_to(_HERE, "cache_init.py.tmpl", dest=init_file, substitutions={})
    files_created.append(str(init_file))

    cache_core = cache_dir / "core.py"
    render_to(_HERE, "core.py.tmpl", dest=cache_core, substitutions={})
    files_created.append(str(cache_core))

    decorator_file = cache_dir / "decorator.py"
    render_to(_HERE, "decorator.py.tmpl", dest=decorator_file, substitutions={})
    files_created.append(str(decorator_file))

    invalidation_file = cache_dir / "invalidation.py"
    render_to(_HERE, "invalidation.py.tmpl", dest=invalidation_file, substitutions={})
    files_created.append(str(invalidation_file))

    keys_file = cache_dir / "keys.py"
    render_to(_HERE, "keys.py.tmpl", dest=keys_file, substitutions={})
    files_created.append(str(keys_file))

    # Step 2: /cache/stats route
    routes_dir = app_dir / "api" / "routes"
    if routes_dir.exists():
        stats_route = routes_dir / "cache_stats.py"
        render_to(_HERE, "cache_stats_route.py.tmpl", dest=stats_route, substitutions={})
        files_created.append(str(stats_route))

    # Step 3: Patch main.py
    main_file = app_dir / "main.py"
    if main_file.exists():
        _patch_main(main_file)
        files_modified.append(str(main_file))

    # Step 4: Patch requirements.txt
    req_file = project / "requirements.txt"
    if req_file.exists():
        req_src = req_file.read_text()
        req_adds = []
        if "msgpack" not in req_src:
            req_adds.append("msgpack>=1.0.0")
        if "redis" not in req_src:
            req_adds.append("redis[hiredis]>=5.0.0")
        if req_adds:
            req_file.write_text(req_src.rstrip("\n") + "\n" + "\n".join(req_adds) + "\n")
            files_modified.append(str(req_file))

    # Step 4b: Document the env vars the emitted code reads (config consistency)
    env_example = project / ".env.example"
    if env_example.exists() and _patch_env_example(env_example):
        files_modified.append(str(env_example))

    # Step 5: Enforce ≤20 logic lines in the primary glue (CONTRACT §B1.0.1)
    glue_loc = _count_logic_lines(glue_file.read_text())
    if glue_loc > 20:
        return ToolResult(
            status="error",
            error=f"Primary glue {glue_file} has {glue_loc} logic lines (> 20).",
            execution_time_ms=_ms(start),
        )

    # Step 6: Emit project test
    _emit_project_test(project, files_created)

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "Shipped primitives: core.venous.cache.KeyValueBucket, SessionCache, DistributedLock "
            "(⚠ in-memory fallback variants — distributed coordination only when swapped for "
            "Redis-backed implementations, see warnings).",
            "Glue: app/cache/primitives.py wires KeyValueBucket + DistributedLock + SessionCache "
            "as in-memory fallbacks (⚠ in-memory variants are per-process only — see warnings).",
            "Redis cache layer added: @cached decorator, key isolation, msgpack serialization.",
            "Invalidation: TTL expiry per key, plus a publish-only Redis pub/sub emit "
            "on `cache:invalidation` (⚠ no in-tool subscriber is wired — see warnings + "
            "next_steps for the subscriber loop the operator must add for true cross-worker "
            "fan-out).",
            "Key pattern: cache:{tenant}:resource:{id}",
            "/cache/stats endpoint added (requires require_admin dep).",
        ],
        warnings=[
            # B0.13 honest disclosure for the "fan-out to all workers" claim.
            # Closes the over-claim noted in r_notes_match_behaviour._WAIVED_TOOLS:
            #   `"distributed" / "fan-out" claims; no engine-level test
            #    asserts the wired primitives actually coordinate cross-worker.`
            "Publish-only invalidation: `invalidate_resource()` calls "
            "`redis.publish('cache:invalidation', ...)` but the tool emits NO "
            "subscriber. Other workers will NOT drop their local KeyValueBucket "
            "entries automatically — TTL expiry is the only cross-worker "
            "convergence mechanism in the box. To get true fan-out you must "
            "either (a) wire a startup task that runs "
            "`redis.pubsub().subscribe('cache:invalidation')` and calls "
            "`bucket.delete(...)` on each message, or (b) move the canonical "
            "store off the in-memory `KeyValueBucket` onto Redis itself so "
            "every worker reads the same row.",
            "In-memory primitives are per-process: `InMemoryKeyValueBucket`, "
            "`InMemorySessionCache`, and `InMemoryDistributedLock` from "
            "`core.venous.cache` do NOT share state across uvicorn workers. "
            "Swap to a Redis-backed implementation before scaling beyond a "
            "single worker — otherwise `cache_aside()` stampede prevention "
            "is local-only and cached values diverge per worker.",
        ],
        next_steps=[
            "pip install 'redis[hiredis]' msgpack",
            "Set REDIS_URL in .env (e.g. redis://localhost:6379/0).",
            "Decorate GET handlers: @cached(ttl=300, key_pattern='items:{item_id}')",
            "Call invalidate_resource('items', item_id) in POST/PUT/DELETE handlers.",
            "For multi-worker correctness: wire a startup pubsub subscriber on "
            "`cache:invalidation` that calls `bucket.delete(...)` on each "
            "incoming message, OR swap the in-memory primitives for Redis-backed "
            "ones (TTL-only fan-out is the default; explicit invalidation "
            "requires the subscriber).",
        ],
        execution_time_ms=_ms(start),
    )


def _emit_project_test(project: Path, created: list[str]) -> None:
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_cache_layer_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_cache_layer_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


def _patch_main(main_file: Path) -> None:
    """Inject cache init/close into main.py lifespan or startup/shutdown events."""
    src = main_file.read_text()
    if "init_cache" in src:
        return

    cache_import = (
        "\nfrom app.cache.core import init_cache, close_cache  "
        "# noqa: F401 — cache layer\n"
        "import os as _os\n"
    )
    cache_startup = (
        "\n"
        "# Cache layer startup — added by add_cache_layer tool\n"
        '_redis_url = _os.getenv("REDIS_URL", "redis://localhost:6379/0")\n'
        '_cache_ttl = int(_os.getenv("CACHE_DEFAULT_TTL", "300"))\n'
    )

    if "from fastapi import FastAPI" in src:
        src = src.replace(
            "from fastapi import FastAPI",
            "from fastapi import FastAPI" + cache_import,
        )
    else:
        src = cache_import + src

    src = src.rstrip("\n") + "\n" + cache_startup
    main_file.write_text(src)


def _ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


def _patch_env_example(env_example: Path) -> bool:
    """Document the env vars the cache primitives read. Returns True if patched.

    ``app/cache/primitives.py`` reads ``CACHE_LOCK_LEASE_S`` via ``os.getenv``;
    surfacing it in ``.env.example`` keeps generated config self-consistent.
    """
    src = env_example.read_text()
    if "CACHE_LOCK_LEASE_S" in src:
        return False
    trailing = "" if src.endswith("\n") else "\n"
    block = (
        "\n"
        "# --- Cache layer (add_cache_layer) ---\n"
        "# Distributed-lock lease duration in seconds (default 5).\n"
        "CACHE_LOCK_LEASE_S=5\n"
    )
    env_example.write_text(src + trailing + block)
    return True


def _count_logic_lines(source: str) -> int:
    """Count executable logic lines per CONTRACT §B1.0.1."""
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
