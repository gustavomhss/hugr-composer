"""TOOL-116: add_adaptive_throttle — multi-dimensional adaptive rate limiter.

Generates production-grade adaptive throttling with:
- Cost-based limiting (expensive endpoints consume more quota)
- Behavioral fingerprinting (header order + timing patterns)
- Adaptive thresholds (learns normal per-client, tightens on anomaly)
- Cascading penalty escalation (1min->5min->30min->24h)
- Redis-backed sliding window + token bucket hybrid

Idempotent: a second run detects ``app/core/adaptive_throttle.py`` and
returns ``status="no_op"`` without touching any file.

Generated files:
  - ``app/core/adaptive_throttle.py``        core throttle engine + config
  - ``app/middleware/adaptive_throttle.py``  middleware + penalty tracker
  - ``app/api/routes/throttle_status.py``    GET /throttle/status endpoint

Patched files:
  - ``app/core/config.py``       ADAPTIVE_THROTTLE_* fields inside Settings
  - ``app/main.py``              throttle middleware registration
"""

from __future__ import annotations

import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_resiliency_add_adaptive_throttle",
    "description": (
        "Add multi-dimensional adaptive rate limiting: cost-based quota, "
        "behavioral fingerprinting, adaptive thresholds, and cascading "
        "penalty escalation (1min→5min→30min→24h). Redis-backed sliding "
        "window + token bucket hybrid."
    ),
    "tags": ["extend", "infrastructure", "security"],
    "entry": "add_adaptive_throttle",
}


def add_adaptive_throttle(inp: ToolInput) -> ToolResult:
    """Add multi-dimensional adaptive throttling to a FastAPI project."""
    start = time.monotonic()

    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_ms(start))

    project = Path(inp.project_dir)

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
                "Generate a base project first with fastapi_generate_project(...).",
            ],
            execution_time_ms=_ms(start),
        )

    files_created: list[str] = list(scaffolded)
    app_dir = project / "app"
    throttle_core = app_dir / "core" / "adaptive_throttle.py"

    if throttle_core.exists() and "AdaptiveThrottleConfig" in throttle_core.read_text():
        return ToolResult(
            status="no_op",
            notes=["AdaptiveThrottleConfig already present — adaptive throttle already installed."],
            execution_time_ms=_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/core/adaptive_throttle.py, "
                "app/middleware/adaptive_throttle.py, and "
                "app/api/routes/throttle_status.py."
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_ms(start),
        )

    files_modified: list[str] = []

    (app_dir / "core").mkdir(parents=True, exist_ok=True)
    render_to(_HERE, "throttle_core.py.tmpl", dest=throttle_core, substitutions={})
    files_created.append(str(throttle_core))

    middleware_dir = app_dir / "middleware"
    middleware_dir.mkdir(parents=True, exist_ok=True)
    mw_init = middleware_dir / "__init__.py"
    if not mw_init.exists():
        mw_init.write_text('"""Middleware package."""\n')
        files_created.append(str(mw_init))

    mw_file = middleware_dir / "adaptive_throttle.py"
    render_to(_HERE, "throttle_middleware.py.tmpl", dest=mw_file, substitutions={})
    files_created.append(str(mw_file))

    routes_dir = app_dir / "api" / "routes"
    if routes_dir.exists():
        status_route = routes_dir / "throttle_status.py"
        render_to(_HERE, "throttle_status_route.py.tmpl", dest=status_route, substitutions={})
        files_created.append(str(status_route))

    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    main_file = app_dir / "main.py"
    if main_file.exists():
        _patch_main(main_file)
        files_modified.append(str(main_file))

    _emit_project_test(project, files_created)

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "Adaptive throttle installed: cost-based quota + behavioral fingerprinting.",
            "Penalty ladder: 1min -> 5min -> 30min -> 24h (configurable via env).",
            "Learning period profiles per-client baseline before tightening thresholds.",
            "Redis sliding window + token bucket hybrid stores all state.",
        ],
        next_steps=[
            "Set REDIS_URL in .env (required for multi-worker penalty state).",
            "Disabled by default — set ADAPTIVE_THROTTLE_ENABLED=true in .env to activate.",
            "Decorate expensive endpoints with @throttle_cost(weight=5) to consume more quota.",
            "Monitor penalty events via GET /throttle/status (returns client penalty tier).",
            "Set ADAPTIVE_THROTTLE_LEARNING_PERIOD_H to baseline window in hours (default 24).",
            "Single-server (default): leave ADAPTIVE_THROTTLE_BEHIND_PROXY=false — the "
            "peer IP IS the real client, so escalation/bans work normally on it.",
            "Behind a load balancer/CDN: set ADAPTIVE_THROTTLE_BEHIND_PROXY=true AND "
            "ADAPTIVE_THROTTLE_TRUSTED_PROXIES to your proxy egress IPs/CIDRs so the "
            "fingerprint resolves the real client from X-Forwarded-For. In proxy mode a "
            "bare/untrusted peer (shared egress IP) fails OPEN — penalty escalation/bans "
            "are SKIPPED so a shared proxy IP cannot mass-ban every downstream user.",
        ],
        execution_time_ms=_ms(start),
    )


def _patch_config(config_file: Path) -> None:
    """Inject ``ADAPTIVE_THROTTLE_*`` fields inside the ``Settings`` class body."""
    src = config_file.read_text()
    if "ADAPTIVE_THROTTLE_ENABLED" in src:
        return

    fields = (
        "    ADAPTIVE_THROTTLE_ENABLED: bool = False\n"
        "    ADAPTIVE_THROTTLE_SENSITIVITY: float = 0.8\n"
        "    ADAPTIVE_THROTTLE_LEARNING_PERIOD_H: int = 24\n"
        "    ADAPTIVE_THROTTLE_BASE_QUOTA: int = 200\n"
        "    ADAPTIVE_THROTTLE_PENALTY_ESCALATION: bool = True\n"
        # CSV of trusted proxy IPs/CIDRs (e.g. your LB/CDN egress ranges).
        # The throttle fingerprint trusts X-Forwarded-For ONLY when the peer
        # is in this list; empty (default) pins the fingerprint to the peer IP.
        '    ADAPTIVE_THROTTLE_TRUSTED_PROXIES: str = ""\n'
        # False (default, single-server): the peer IP IS the real client, so
        # the throttle escalates/bans on it normally. True: you ARE behind a
        # proxy — set TRUSTED_PROXIES so the real client is resolved from
        # X-Forwarded-For; a bare/untrusted peer fails OPEN (no mass-ban).
        "    ADAPTIVE_THROTTLE_BEHIND_PROXY: bool = False\n"
    )

    anchor = "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    if anchor in src:
        src = src.replace(anchor, anchor + "\n" + fields.rstrip())
    else:
        src = src.rstrip("\n") + "\n" + fields + "\n"
    config_file.write_text(src)


def _patch_main(main_file: Path) -> None:
    """Register adaptive throttle middleware in ``app/main.py``."""
    src = main_file.read_text()
    if "register_adaptive_throttle" in src:
        return

    import_line = (
        "\nfrom app.middleware.adaptive_throttle import register_adaptive_throttle"
        "  # noqa: F401 — adaptive throttle\n"
    )
    if "from fastapi import FastAPI" in src:
        src = src.replace(
            "from fastapi import FastAPI",
            "from fastapi import FastAPI" + import_line,
        )
    else:
        src = import_line + src

    marker = "app = FastAPI("
    if marker in src:
        idx = src.find(marker)
        depth = 0
        end = idx
        for i in range(idx + len(marker), len(src)):
            ch = src[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                if depth == 0:
                    end = i + 1
                    break
                depth -= 1
        src = src[:end] + "\nregister_adaptive_throttle(app)\n" + src[end:]
    else:
        src = src.rstrip("\n") + "\nregister_adaptive_throttle(app)\n"

    main_file.write_text(src)


def _emit_project_test(project: Path, created: list[str]) -> None:
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_adaptive_throttle_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_adaptive_throttle_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


def _ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
