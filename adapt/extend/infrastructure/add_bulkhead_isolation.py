"""TOOL-097: add_bulkhead_isolation — per-endpoint-group concurrency partitioning.

Follows the CONTRACT §B1.0 + §B1.0.1 pattern:

1. Copy the framework-agnostic primitive
   ``core.venous.resiliency.Bulkhead`` into the generated project.
2. Emit a thin ``app/resilience/bulkhead.py`` glue file (≤ 20 logic lines)
   that instantiates a ``PartitionRegistry`` and exposes a factory used by
   the ASGI middleware.
3. Emit a ``BulkheadMiddleware`` (thin glue over the primitive) and a
   status route — both are pure wiring over the primitive's public API.

No shipped FastAPI adapter exists for ``Bulkhead`` in
``core/venous/_adapters/fastapi/``; the ASGI middleware is emitted by this
tool because it is framework-specific wiring, not primitive logic.

The tool is idempotent: a second run detects the primitive's
``InMemoryBulkhead`` import in ``app/resilience/bulkhead.py`` and returns
``status="no_op"``.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_bulkhead_isolation import add_bulkhead_isolation

    result = add_bulkhead_isolation(ToolInput(project_dir="/path/to/project"))
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_resiliency_add_bulkhead_isolation",
    "description": (
        "Copy Bulkhead primitive into the project and wire a thin "
        "app/resilience/bulkhead.py + ASGI middleware that partitions "
        "semaphore permits per endpoint group."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_bulkhead_isolation",
    "imports_primitives": [
        "core.venous.resiliency.Bulkhead",
    ],
    "imports_adapters": (
        "core.venous._adapters.fastapi.BulkheadAdapter",
    ),
}


# ---------------------------------------------------------------------------
# Glue templates (thin wiring over core.venous.resiliency.Bulkhead)
# ---------------------------------------------------------------------------

_BULKHEAD_GLUE = '''\
"""Thin glue that wires the Bulkhead FastAPI adapter into the app.

Re-exports ``Bulkhead`` (multi-partition facade) and ``BulkheadFullError``
from ``core.venous._adapters.fastapi.BulkheadAdapter`` — the adapter owns
the convenience API (acquire, status, middleware). The motor primitive at
``core.venous.resiliency.Bulkhead`` owns all permit accounting, invariant
enforcement (BH_INV_01..05) and rejection metering. No business logic
lives in this file.

``get_bulkhead()`` builds a process-global ``Bulkhead`` from env vars.
"""

from __future__ import annotations

import os

from core.venous._adapters.fastapi.BulkheadAdapter import (
    Bulkhead,
    BulkheadFullError,
)
from app.resilience.pool_config import BulkheadConfig, get_default_config

_bulkhead: Bulkhead | None = None


def get_bulkhead() -> Bulkhead:
    """Return the process-global Bulkhead (lazy init from env)."""
    global _bulkhead
    if _bulkhead is None:
        _bulkhead = Bulkhead(get_default_config())
    return _bulkhead


__all__ = ["Bulkhead", "BulkheadConfig", "BulkheadFullError", "get_bulkhead"]
'''


_POOL_CONFIG_GLUE = '''\
"""App-specific bulkhead configuration + route classifier.

``BulkheadConfig`` is re-exported from the shipped adapter so the app
uses the exact type ``Bulkhead`` validates against. ``classify_route``
is app-specific policy: it decides which URL paths go to which partition.

Groups:
    payments   — payment processing (default: 10)
    crud       — standard CRUD endpoints (default: 50)
    analytics  — analytics / reporting queries (default: 20)
"""

from __future__ import annotations

import os

from core.venous._adapters.fastapi.BulkheadAdapter import BulkheadConfig


def get_default_config() -> BulkheadConfig:
    """Return BulkheadConfig populated from environment variables."""
    return BulkheadConfig(
        limits={
            "payments": int(os.getenv("BULKHEAD_PAYMENTS_MAX", "10")),
            "crud": int(os.getenv("BULKHEAD_CRUD_MAX", "50")),
            "analytics": int(os.getenv("BULKHEAD_ANALYTICS_MAX", "20")),
        },
        wait_ms=int(os.getenv("BULKHEAD_WAIT_MS", "0")),
    )


def classify_route(path: str) -> str:
    """Map a URL path to a bulkhead group name."""
    if path.startswith(("/payments", "/billing", "/subscriptions", "/invoices")):
        return "payments"
    if path.startswith(("/analytics", "/reports", "/exports", "/metrics")):
        return "analytics"
    return "crud"


__all__ = ["BulkheadConfig", "classify_route", "get_default_config"]
'''


_MIDDLEWARE_GLUE = '''\
"""BulkheadMiddleware re-export + env-gated installer.

The middleware class itself lives in the shipped adapter
(``core.venous._adapters.fastapi.BulkheadAdapter``). This file adds the
``BULKHEAD_ENABLED`` env guard and the ``install_if_enabled`` helper so
``main.py`` can opt in with one line.
"""

from __future__ import annotations

import os

from fastapi import FastAPI

from core.venous._adapters.fastapi.BulkheadAdapter import BulkheadMiddleware
from app.resilience.bulkhead import get_bulkhead
from app.resilience.pool_config import classify_route


def install_if_enabled(app: FastAPI) -> bool:
    """Install BulkheadMiddleware on *app* iff BULKHEAD_ENABLED=true in env.

    Returns ``True`` if installed, ``False`` otherwise.
    """
    if os.getenv("BULKHEAD_ENABLED", "false").lower() != "true":
        return False
    app.add_middleware(
        BulkheadMiddleware,
        bulkhead=get_bulkhead(),
        classify_route=classify_route,
    )
    return True


__all__ = ["BulkheadMiddleware", "install_if_enabled"]
'''


_STATUS_ROUTE_GLUE = '''\
"""GET /resilience/bulkheads — pool utilization per bulkhead partition.

Delegates to ``Bulkhead.status()`` on the adapter facade — no local
computation. Counters live in the motor primitive.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.resilience.bulkhead import get_bulkhead

router = APIRouter(prefix="/resilience", tags=["resilience"])


@router.get("/bulkheads", response_model=dict)
async def bulkhead_status() -> dict:
    """Return current partition utilization for every registered group."""
    return get_bulkhead().status()
'''


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_bulkhead_isolation(inp: ToolInput) -> ToolResult:
    """Add bulkhead isolation by delegating to the shipped primitive."""
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err,
                          execution_time_ms=_elapsed_ms(start))

    from adapt.contracts.prerequisites import ensure_prerequisites, Prereq

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
            notes=["Generate a base project first via fastapi_generate_project(...)."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = list(scaffolded or [])
    app_dir = project / "app"
    resilience_dir = app_dir / "resilience"
    glue_file = resilience_dir / "bulkhead.py"

    # --- Idempotency guard (detect the adapter's Bulkhead facade import) ----
    if glue_file.exists() and "BulkheadAdapter" in glue_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["Bulkhead adapter already wired via app/resilience/bulkhead.py."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would copy Bulkhead primitive and write "
                "app/resilience/bulkhead.py + pool_config.py + "
                "middleware/bulkhead.py + bulkhead_status.py."
            ],
            next_steps=["Re-run without dry_run=True to apply."],
            execution_time_ms=_elapsed_ms(start),
        )

    # --- Copy primitive ------------------------------------------------------
    from generators.scaffold_venous import ensure_primitives

    manifest = ensure_primitives(
        str(project),
        names=["core.venous.resiliency.Bulkhead"],
        adapters=["core.venous._adapters.fastapi.BulkheadAdapter"],
    )
    files_created.append(manifest.path)

    files_modified: list[str] = []

    # --- Primary glue --------------------------------------------------------
    resilience_dir.mkdir(parents=True, exist_ok=True)
    resilience_init = resilience_dir / "__init__.py"
    if not resilience_init.exists():
        resilience_init.write_text('"""Resilience patterns package."""\n')
        files_created.append(str(resilience_init))

    glue_file.write_text(_BULKHEAD_GLUE)
    files_created.append(str(glue_file))

    pool_config_file = resilience_dir / "pool_config.py"
    pool_config_file.write_text(_POOL_CONFIG_GLUE)
    files_created.append(str(pool_config_file))

    # --- Middleware glue -----------------------------------------------------
    middleware_dir = app_dir / "middleware"
    middleware_dir.mkdir(parents=True, exist_ok=True)
    middleware_init = middleware_dir / "__init__.py"
    if not middleware_init.exists():
        middleware_init.write_text('"""Middleware package."""\n')
        files_created.append(str(middleware_init))

    mw_file = middleware_dir / "bulkhead.py"
    mw_file.write_text(_MIDDLEWARE_GLUE)
    files_created.append(str(mw_file))

    # --- Status route glue ---------------------------------------------------
    routes_dir = app_dir / "api" / "routes"
    if routes_dir.exists():
        status_route = routes_dir / "bulkhead_status.py"
        status_route.write_text(_STATUS_ROUTE_GLUE)
        files_created.append(str(status_route))

    # --- Config patch --------------------------------------------------------
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    main_file = app_dir / "main.py"
    if main_file.exists():
        _patch_main(main_file)
        files_modified.append(str(main_file))

    # --- AST validation ------------------------------------------------------
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

    # --- Enforce ≤20 logic lines in the primary glue -------------------------
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
            "Shipped primitive: core.venous.resiliency.Bulkhead.",
            "Shipped adapter: core.venous._adapters.fastapi.BulkheadAdapter "
            "(Bulkhead facade + BulkheadMiddleware).",
            "Glue: app/resilience/bulkhead.py re-exports adapter + get_bulkhead() factory.",
            "app/middleware/bulkhead.py: install_if_enabled(app) — one-line wire-in.",
            "Status endpoint: GET /resilience/bulkheads (delegates to Bulkhead.status()).",
            "Config: BULKHEAD_ENABLED, BULKHEAD_PAYMENTS_MAX, BULKHEAD_CRUD_MAX, "
            "BULKHEAD_ANALYTICS_MAX, BULKHEAD_WAIT_MS.",
        ],
        next_steps=[
            "Set BULKHEAD_ENABLED=true in .env to activate.",
            "Call `install_if_enabled(app)` from main.py (idempotent no-op when disabled).",
            "Include bulkhead_status router in app for /resilience/bulkheads.",
            "Tune BULKHEAD_*_MAX values to match your workload profiles.",
            "Monitor /resilience/bulkheads to identify bottleneck groups.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _patch_config(config_file: Path) -> None:
    """Add BULKHEAD_* fields to ``app/core/config.py`` Settings class."""
    from adapt.contracts.config_patcher import patch_settings_fields

    patch_settings_fields(
        config_file,
        fields=[
            ("BULKHEAD_ENABLED", "BULKHEAD_ENABLED: bool = False"),
            ("BULKHEAD_PAYMENTS_MAX", "BULKHEAD_PAYMENTS_MAX: int = 10"),
            ("BULKHEAD_CRUD_MAX", "BULKHEAD_CRUD_MAX: int = 50"),
            ("BULKHEAD_ANALYTICS_MAX", "BULKHEAD_ANALYTICS_MAX: int = 20"),
        ],
    )


def _patch_main(main_file: Path) -> None:
    """Leave a hint in main.py for installing the BulkheadMiddleware."""
    src = main_file.read_text()
    if "bulkhead" in src:
        return
    note = (
        "\n# Bulkhead isolation — added by add_bulkhead_isolation tool\n"
        "# from app.middleware.bulkhead import install_if_enabled\n"
        "# from app.api.routes.bulkhead_status import router as bulkhead_router\n"
        "# install_if_enabled(app)\n"
        "# app.include_router(bulkhead_router)\n"
    )
    main_file.write_text(src.rstrip("\n") + "\n" + note)


def _count_logic_lines(source: str) -> int:
    """Count executable logic lines — imports, class/func defs, and decorators
    do NOT count (per CONTRACT §B1.0.1).
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return 0
    loc = 0
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.body:
                start = node.body[0].lineno
                end = node.end_lineno or start
                loc += end - start + 1
    return loc


def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*."""
    return int((time.monotonic() - start) * 1000)


# Silence unused import warning in certain lint configs — textwrap is kept
# available for future template helpers.
_ = textwrap
