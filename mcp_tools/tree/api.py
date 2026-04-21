"""`fastapi_api` — the api-domain tree dispatcher.

ONE MCP tool that routes to 7 slice tool(s) + 17 primitive(s) under the `api` domain. The Claude Maestro chooses granularity by `action`.

See `mcp_tools/tree/auth.py` — the canonical POC template this file mirrors.
"""
from __future__ import annotations

import importlib
import shutil
import time
from pathlib import Path
from typing import Any

SKILL_ROOT = Path(__file__).resolve().parents[2]
VENOUS_DIR = SKILL_ROOT / "core" / "venous" / "api"
ADAPTERS_FASTAPI = SKILL_ROOT / "core" / "venous" / "_adapters" / "fastapi"


# ---------------------------------------------------------------------------
# Tree declaration — single source of truth for the api domain surface
# ---------------------------------------------------------------------------

SLICES: dict[str, dict[str, Any]] = {
    "add_api_deprecation":       {"mod": "add_api_deprecation",       "pkg": "adapt.extend.api_design", "desc": "Add endpoint lifecycle management with RFC 8594 Sunset headers, usage tracking, and @depreca..."},
    "add_api_versioning":        {"mod": "add_api_versioning",        "pkg": "adapt.extend.api_design", "desc": "Add URL-based API versioning (/api/v1, /api/v2) with deprecation headers"},
    "add_batch_endpoint":        {"mod": "add_batch_endpoint",        "pkg": "adapt.extend.api_design", "desc": "Add a generic batch request endpoint that fans out to multiple sub-requests"},
    "add_cqrs":                  {"mod": "add_cqrs",                  "pkg": "adapt.extend.api_design", "desc": "Add a production-grade CQRS layer with CommandBus, QueryBus, read-replica session routing, a..."},
    "add_graphql":               {"mod": "add_graphql",               "pkg": "adapt.extend.api_design", "desc": "Add GraphQL endpoint (Strawberry) alongside the existing REST API"},
    "add_graphql_subscriptions": {"mod": "add_graphql_subscriptions", "pkg": "adapt.extend.api_design", "desc": "Add WebSocket GraphQL subscriptions (graphql-ws protocol) to a FastAPI project, extending th..."},
    "add_long_running_task":     {"mod": "add_long_running_task",     "pkg": "adapt.extend.api_design", "desc": "Copy WorkflowRun + DurableTimer primitives + FastAPI WorkflowAdapter into the project and wi..."},
}

PRIMITIVES: dict[str, str] = {
    "BatchCore": "Async batch executor with per-item timeout, bounded parallelism, and two isolation modes (al...",
    "CommandBus": "Dispatch Commands to their registered async handlers.",
    "CommandQuerySeparator": "Partitions the API into write commands that mutate state and read queries that observe it so...",
    "ContextMap": "Catalogs every BoundedContext and the integration relationship so upstream/downstream teams...",
    "DataLoader": "Batches and dedupes per-request loads from N-per-resolver patterns into one bulk fetch per k...",
    "DeprecationEntry": "Value object carrying the metadata required to emit RFC 8594 Sunset / Deprecation headers fo...",
    "DeprecationRegistry": "Index DeprecationEntry objects by their (METHOD, path) composite key so request middleware c...",
    "DeprecationReporter": "In-memory call-count tracker for deprecated endpoints: record a hit per request, emit a usag...",
    "IdempotencyStore": "Thread-safe in-memory key-to-result cache used to deduplicate retried requests: get/put/seen...",
    "InboundVerifier": "Abstract extension point for provider-specific inbound webhook verification (Stripe, GitHub,...",
    "MemoryPubSubBackend": "In-process fan-out pub/sub backend: publish() broadcasts a payload to every live subscriber...",
    "MiddlewarePipeline": "Ordered chain of components that each transform the RequestContext and decide whether to cal...",
    "PersistedQueryRegistry": "SHA-256 keyed allow-list of pre-registered queries; clients send 64-char ids and unregistere...",
    "QueryBus": "Dispatch Queries to their registered async handlers.",
    "RequestContext": "Per-request bag that carries identity, headers, correlation id, and free-form assigns throug...",
    "RouterPipeline": "Named bundle of middleware that a route joins with `pipe_through` so groups share edge polic...",
    "ValueTransform": "Strongly-typed parse/validate step that converts a raw inbound argument into the domain type...",
}

# Curated 'bundle' — 5 canonical api slices.
# Rationale: Production API surface: versioning, deprecation headers, batch endpoint, CQRS, and durable long-running task support.
BUNDLE_SLICES: tuple[str, ...] = (
    "add_api_versioning",
    "add_api_deprecation",
    "add_batch_endpoint",
    "add_cqrs",
    "add_long_running_task",
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
    because api tools span multiple adapt/ subtrees.
    """
    meta = SLICES[slice_name]
    mod_name = f"{meta['pkg']}.{meta['mod']}"
    mod = importlib.import_module(mod_name)
    entry = getattr(mod, meta["mod"], None)
    if entry is None or not callable(entry):
        raise RuntimeError(
            f"slice {slice_name!r}: entry function {meta['mod']!r} "
            f"not found in {mod_name}"
        )
    return entry(**kwargs)


# ---------------------------------------------------------------------------
# Primitive routing
# ---------------------------------------------------------------------------

def _copy_primitive(name: str, output_dir: str) -> dict:
    """Copy core/venous/api/<Name>/ into <output_dir>/app/core/venous/api/<Name>/.

    Follows ADR 0002 (copy-in distribution). Skips _t0_report.json +
    _evidence/ (per .gitignore). Also copies the matching fastapi
    adapter under _adapters/fastapi/ if one exists.
    """
    if name not in PRIMITIVES:
        raise ValueError(
            f"unknown primitive {name!r} in domain api. "
            f"Available: {sorted(PRIMITIVES)}"
        )
    src = VENOUS_DIR / name
    if not src.is_dir():
        raise FileNotFoundError(f"primitive source missing: {src}")
    target = Path(output_dir) / "app" / "core" / "venous" / "api" / name
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(
        src, target,
        ignore=shutil.ignore_patterns(
            "__pycache__", "_t0_report.json", "_evidence", "*.pyc",
        ),
    )
    files_created = sorted(
        str(p.relative_to(output_dir)) for p in target.rglob("*") if p.is_file()
    )
    adapter_name = f"{name}Adapter.py"
    adapter_src = ADAPTERS_FASTAPI / adapter_name
    if adapter_src.exists():
        adapter_target = (
            Path(output_dir) / "app" / "core" / "venous" / "_adapters" / "fastapi"
        )
        adapter_target.mkdir(parents=True, exist_ok=True)
        shutil.copy(adapter_src, adapter_target / adapter_name)
        files_created.append(
            str((adapter_target / adapter_name).relative_to(output_dir))
        )
        test_src = ADAPTERS_FASTAPI / f"test_{adapter_name}"
        if test_src.exists():
            shutil.copy(test_src, adapter_target / f"test_{adapter_name}")
            files_created.append(
                str((adapter_target / f"test_{adapter_name}").relative_to(output_dir))
            )
    return {"primitive": name, "files_created": files_created}


# ---------------------------------------------------------------------------
# Top-level dispatcher
# ---------------------------------------------------------------------------

MCP_TOOL = {
    "name": "fastapi_api",
    "description": (
        "Api domain dispatcher (HuGR tree pattern). ONE tool that routes to every api-related capability the kit ships. Choose granularity via `action`:\n  • 'list' → returns the full api tree + primitive catalog.\n  • 'bundle' → one-shot: installs 5 curated api slices (add_api_versioning, add_api_deprecation, add_batch_endpoint, add_cqrs, add_long_running_task).\n  • '<slice>' → install ONE slice (add_api_deprecation, add_api_versioning, add_batch_endpoint, add_cqrs, add_graphql, add_graphql_subscriptions, add_long_running_task).\n  • 'primitive' → copy ONE Lego block (BatchCore, CommandBus, CommandQuerySeparator, ContextMap, DataLoader, DeprecationEntry, DeprecationRegistry, DeprecationReporter, IdempotencyStore, InboundVerifier, MemoryPubSubBackend, MiddlewarePipeline, PersistedQueryRegistry, QueryBus, RequestContext, RouterPipeline, ValueTransform).\nCall with action='list' if unsure. Every return carries `next_steps`."
    ),
    "tags": ["api", "domain", "dispatcher"],
    "annotations": {"readOnlyHint": False, "destructiveHint": False},
    "entry": "fastapi_api",
}


def fastapi_api(action: str, params: dict | None = None) -> dict:
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
            what="api domain tree (5 bundle + 7 slices + 17 primitives)",
            result={
                "domain": "api",
                "bundle": {
                    "description": (
                        "Install the curated production api stack: "
                        f"{len(BUNDLE_SLICES)} slices composed in order."
                    ),
                    "slices_installed": list(BUNDLE_SLICES),
                    "required_params": {"output_dir": "str"},
                },
                "slices": {
                    name: {"description": meta["desc"]}
                    for name, meta in sorted(SLICES.items())
                },
                "primitives": {
                    name: {"purpose": purpose}
                    for name, purpose in sorted(PRIMITIVES.items())
                },
                "usage_examples": [
                    "fastapi_api(action='bundle', params={'output_dir':'/tmp/my-app'})",
                    "fastapi_api(action='add_api_versioning', params={'output_dir':'/tmp/my-app'})",
                    "fastapi_api(action='primitive', params={'name':'BatchCore','output_dir':'/tmp/my-app'})"
                ],
            },
            next_steps=[
                "action='bundle' → install everything for a new project.",
                "action='<slice>' → install one slice for an existing project.",
                "action='primitive' + name=X → copy one Lego surgically."
            ],
            t0=t0,
        )

    if action == "bundle":
        output_dir = params.get("output_dir")
        if not output_dir:
            return _envelope(
                ok=False, what="bundle requires output_dir",
                result={}, next_steps=["Pass params={'output_dir':'/path/to/project'}."],
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
                ] if ok else
                ["Fix errors above. Retry failing slices individually via action=<slice>."]
            ),
            t0=t0,
        )

    if action == "primitive":
        name = params.get("name")
        output_dir = params.get("output_dir")
        if not name or not output_dir:
            return _envelope(
                ok=False,
                what="primitive action requires name + output_dir",
                result={},
                next_steps=[
                    "Example: fastapi_api(action='primitive', params={'name':'X','output_dir':'/tmp/app'}).",
                    "Call fastapi_api(action='list') to see available primitive names.",
                ],
                t0=t0,
            )
        try:
            res = _copy_primitive(name, output_dir)
        except (ValueError, FileNotFoundError) as exc:
            return _envelope(
                ok=False, what=str(exc), result={},
                next_steps=["Call fastapi_api(action='list') for valid primitive names."],
                t0=t0,
            )
        return _envelope(
            ok=True,
            what=f"primitive {name} copied into {output_dir}",
            result=res,
            next_steps=[
                f"Import in your handler: from core.venous.api.{name} import {name}",
                f"Call fastapi_meta_describe(name='{name}') for Protocol + invariants.",
            ],
            t0=t0,
        )

    if action in SLICES:
        output_dir = params.get("output_dir")
        if not output_dir:
            return _envelope(
                ok=False, what=f"slice {action!r} requires output_dir in params",
                result={},
                next_steps=["Pass params={'output_dir':'/path/to/project', ...}."],
                t0=t0,
            )
        try:
            res = _call_slice(action, **params)
        except Exception as exc:  # noqa: BLE001
            return _envelope(
                ok=False, what=f"slice {action!r} failed: {exc}",
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
                "Additional features? call fastapi_api(action='list') for more slices.",
            ],
            t0=t0,
        )

    valid = ["list", "bundle", "primitive"] + sorted(SLICES)
    return _envelope(
        ok=False,
        what=f"unknown action {action!r}",
        result={"valid_actions": valid},
        next_steps=[
            "Call fastapi_api(action='list') to see the full tree.",
            f"Did you mean one of: {', '.join(valid[:5])}, ...?",
        ],
        t0=t0,
    )
