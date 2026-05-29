"""`fastapi_deployment` — the deployment-domain tree dispatcher.

ONE MCP tool that routes to 2 slice tool(s) under the `deployment` domain. The Claude agent chooses granularity by `action`.

See `mcp_tools/tree/auth.py` — the canonical POC template this file mirrors.
"""

from __future__ import annotations

import importlib
import time
from pathlib import Path
from typing import Any

SKILL_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Tree declaration — single source of truth for the deployment domain surface
# ---------------------------------------------------------------------------

SLICES: dict[str, dict[str, Any]] = {
    "add_docker_production": {
        "mod": "add_docker_production",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Add a multi-stage production Dockerfile, .dockerignore, docker-compose.prod.yml, and docker-...",
    },
    "add_request_tracing_ui": {
        "mod": "add_request_tracing_ui",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Add an embedded request tracing dashboard: TracingBuffer ring buffer (last 1000 requests), T...",
    },
}

PRIMITIVES: dict[str, str] = {}

# Curated 'bundle' — 2 canonical deployment slices.
# Rationale: Production deployment essentials: multi-stage Docker image + request tracing UI for live observability.
BUNDLE_SLICES: tuple[str, ...] = (
    "add_docker_production",
    "add_request_tracing_ui",
)


# ---------------------------------------------------------------------------
# Shared envelope (same shape as tier-1 meta tools)
# ---------------------------------------------------------------------------


def _envelope(*, ok: bool, what: str, result: Any, next_steps: list[str], t0: float) -> dict:
    return {
        "ok": ok,
        "what_happened": what,
        "result": result,
        "next_steps": next_steps[:5],
        "elapsed_ms": int((time.perf_counter() - t0) * 1000),
    }


# ---------------------------------------------------------------------------
# Slice routing
# ---------------------------------------------------------------------------


def _call_slice(slice_name: str, **kwargs) -> dict:
    """Route to the underlying `<pkg>.<mod>` tool.

    Multi-bucket aware: each SLICES entry carries its own `pkg`
    because deployment tools span multiple adapt/ subtrees.
    """
    meta = SLICES[slice_name]
    mod_name = f"{meta['pkg']}.{meta['mod']}"
    mod = importlib.import_module(mod_name)
    entry = getattr(mod, meta["mod"], None)
    if entry is None or not callable(entry):
        raise RuntimeError(
            f"slice {slice_name!r}: entry function {meta['mod']!r} not found in {mod_name}"
        )
    return entry(**kwargs)


# ---------------------------------------------------------------------------
# Primitive routing
# ---------------------------------------------------------------------------

# No PRIMITIVES for domain 'deployment': action="primitive" returns a
# descriptive error pointing the caller at the other dispatchers.


# ---------------------------------------------------------------------------
# Top-level dispatcher
# ---------------------------------------------------------------------------

MCP_TOOL = {
    "name": "fastapi_deployment",
    "description": (
        "Deployment domain dispatcher (HuGR tree pattern). ONE tool that routes to every deployment-related capability the kit ships. Choose granularity via `action`:\n  • 'list' → returns the full deployment tree.\n  • 'bundle' → one-shot: installs 2 curated deployment slices (add_docker_production, add_request_tracing_ui).\n  • '<slice>' → install ONE slice (add_docker_production, add_request_tracing_ui).\n  • 'primitive' → N/A (no core.venous primitives here).\nCall with action='list' if unsure. Every return carries `next_steps`."
    ),
    "tags": ["deployment", "domain", "dispatcher"],
    "annotations": {"readOnlyHint": False, "destructiveHint": False},
    "entry": "fastapi_deployment",
}


def fastapi_deployment(action: str, params: dict | None = None) -> dict:
    """See MCP_TOOL description.

    Signature note: `params` is a polymorphic dict whose expected keys
    depend on `action`. FastMCP doesn't support **kwargs in tool
    signatures, so a single `params` dict is the uniform contract.
    """
    t0 = time.perf_counter()
    params = params or {}

    if action == "list":
        return _envelope(
            ok=True,
            what="deployment domain tree (2 bundle + 2 slices)",
            result={
                "domain": "deployment",
                "bundle": {
                    "description": (
                        "Install the curated production deployment stack: "
                        f"{len(BUNDLE_SLICES)} slices composed in order."
                    ),
                    "slices_installed": list(BUNDLE_SLICES),
                    "required_params": {"output_dir": "str"},
                },
                "slices": {
                    name: {"description": meta["desc"]} for name, meta in sorted(SLICES.items())
                },
                "usage_examples": [
                    "fastapi_deployment(action='bundle', params={'output_dir':'/tmp/my-app'})",
                    "fastapi_deployment(action='add_docker_production', params={'output_dir':'/tmp/my-app'})",
                ],
            },
            next_steps=[
                "action='bundle' → install everything for a new project.",
                "action='<slice>' → install one slice for an existing project.",
            ],
            t0=t0,
        )

    if action == "bundle":
        output_dir = params.get("output_dir")
        if not output_dir:
            return _envelope(
                ok=False,
                what="bundle requires output_dir",
                result={},
                next_steps=["Pass params={'output_dir':'/path/to/project'}."],
                t0=t0,
            )
        installed: list[dict] = []
        errors: list[str] = []
        for slice_name in BUNDLE_SLICES:
            try:
                res = _call_slice(slice_name, **{**params, "output_dir": output_dir})
                installed.append({"slice": slice_name, "result": res})
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{slice_name}: {exc}")
        ok = not errors
        return _envelope(
            ok=ok,
            what=f"bundle: {len(installed)}/{len(BUNDLE_SLICES)} slices installed"
            + (f"; {len(errors)} failure(s)" if errors else ""),
            result={"installed": installed, "errors": errors},
            next_steps=(
                [
                    "Bundle complete. Boot the app and exercise the new endpoints.",
                    "For remaining slices, call action=<slice> individually.",
                    "Call fastapi_meta_audit() to verify the contract.",
                ]
                if ok
                else ["Fix errors above. Retry failing slices individually via action=<slice>."]
            ),
            t0=t0,
        )

    if action == "primitive":
        return _envelope(
            ok=False,
            what="domain 'deployment' exposes no core.venous primitives",
            result={},
            next_steps=[
                "Use action='<slice>' to install a slice tool instead.",
                "Call other dispatchers (fastapi_auth / fastapi_data / etc.) for primitives.",
            ],
            t0=t0,
        )

    if action in SLICES:
        output_dir = params.get("output_dir")
        if not output_dir:
            return _envelope(
                ok=False,
                what=f"slice {action!r} requires output_dir in params",
                result={},
                next_steps=["Pass params={'output_dir':'/path/to/project', ...}."],
                t0=t0,
            )
        try:
            res = _call_slice(action, **params)
        except Exception as exc:  # noqa: BLE001
            return _envelope(
                ok=False,
                what=f"slice {action!r} failed: {exc}",
                result={},
                next_steps=[
                    f"Check params for {action!r}. "
                    f"Call fastapi_meta_describe(name='fastapi_{SLICES[action]['mod']}') for the schema."
                ],
                t0=t0,
            )
        return _envelope(
            ok=True,
            what=f"slice {action} installed",
            result=res if isinstance(res, dict) else {"raw": repr(res)[:500]},
            next_steps=[
                "Boot the emitted app + hit the new endpoints to verify.",
                "Additional features? call fastapi_deployment(action='list') for more slices.",
            ],
            t0=t0,
        )

    valid = ["list", "bundle"] + sorted(SLICES)
    return _envelope(
        ok=False,
        what=f"unknown action {action!r}",
        result={"valid_actions": valid},
        next_steps=[
            "Call fastapi_deployment(action='list') to see the full tree.",
            f"Did you mean one of: {', '.join(valid[:5])}, ...?",
        ],
        t0=t0,
    )
