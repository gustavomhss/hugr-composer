"""`fastapi_observability` — the observability-domain tree dispatcher.

ONE MCP tool that routes to 3 slice tool(s) + 17 primitive(s) under the `observability` domain. The Claude agent chooses granularity by `action`.

See `mcp_tools/tree/auth.py` — the canonical POC template this file mirrors.
"""

from __future__ import annotations

import importlib
import shutil
import time
from pathlib import Path
from typing import Any

SKILL_ROOT = Path(__file__).resolve().parents[2]
VENOUS_DIR = SKILL_ROOT / "core" / "venous" / "obs"
ADAPTERS_FASTAPI = SKILL_ROOT / "core" / "venous" / "_adapters" / "fastapi"


# ---------------------------------------------------------------------------
# Tree declaration — single source of truth for the observability domain surface
# ---------------------------------------------------------------------------

SLICES: dict[str, dict[str, Any]] = {
    "add_opentelemetry": {
        "mod": "add_opentelemetry",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Add OpenTelemetry traces, metrics, and logs with lazy SDK imports, OTELMiddleware for reques...",
    },
    "add_prometheus_metrics": {
        "mod": "add_prometheus_metrics",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Add Prometheus RED metrics (request_total, request_duration_seconds, request_errors_total) w...",
    },
    "add_structured_logging": {
        "mod": "add_structured_logging",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Upgrade to structlog with JSON renderer, correlation ID binding, per-request context, and PI...",
    },
}

PRIMITIVES: dict[str, str] = {
    "AccessLog": "Record every successful READ of a classified record separately from the security audit log s...",
    "CardinalityGuard": "Bound the unique attribute-value combinations attached to a metric or log stream to prevent...",
    "CorrelationContext": "Propagate a stable request identifier and optional baggage across threads, async tasks, and...",
    "CorrelationId": "Opaque string that travels with a request across services and log lines so a reader can stit...",
    "ErrorSink": "Capture uncaught exceptions with fingerprint grouping, attach current trace and correlation...",
    "EventBus": "In-process publish/subscribe point for named framework and application events with structure...",
    "HealthProbe": "Expose a typed liveness / readiness signal that reflects the real state of the process and i...",
    "HistogramBuckets": "Define explicit latency and size bucket boundaries for histogram instruments so quantile est...",
    "LifecycleHook": "Named callback fired at a defined application phase (starting, ready, stopping) so tools can...",
    "LlmTrace": "Emit structured spans for each model call with attributes aligned to OpenTelemetry GenAI sem...",
    "MetricMeter": "Record numeric measurements through four instrument shapes — counter, up-down counter, histo...",
    "ResourceDescriptor": "Describe the entity producing telemetry — service, version, deployment environment, instance...",
    "SamplingPolicy": "Decide whether a given trace or span is retained, combining head-based and tail-based rules...",
    "SemanticAttributes": "Expose OpenTelemetry semantic-convention attribute keys as typed constants and enforce that...",
    "StructuredLogger": "Emit machine-parseable key/value log records with a fixed level taxonomy and attached trace/...",
    "TelemetryExporter": "Serialize batched spans, metrics, or log records into an OTLP-compatible envelope and delive...",
    "Tracer": "Create spans that represent a unit of work, attach attributes and events, link related spans...",
}

# Curated 'bundle' — 3 canonical observability slices.
# Rationale: The three pillars wired end-to-end: OpenTelemetry traces/metrics/logs, Prometheus RED metrics, structured JSON logging with PII redaction.
BUNDLE_SLICES: tuple[str, ...] = (
    "add_opentelemetry",
    "add_prometheus_metrics",
    "add_structured_logging",
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
    because observability tools span multiple adapt/ subtrees.
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


def _copy_primitive(name: str, output_dir: str) -> dict:
    """Copy core/venous/obs/<Name>/ into <output_dir>/app/core/venous/obs/<Name>/.

    Follows ADR 0002 (copy-in distribution). Skips _t0_report.json +
    _evidence/ (per .gitignore). Also copies the matching fastapi
    adapter under _adapters/fastapi/ if one exists.
    """
    if name not in PRIMITIVES:
        raise ValueError(
            f"unknown primitive {name!r} in domain observability. Available: {sorted(PRIMITIVES)}"
        )
    src = VENOUS_DIR / name
    if not src.is_dir():
        raise FileNotFoundError(f"primitive source missing: {src}")
    target = Path(output_dir) / "app" / "core" / "venous" / "obs" / name
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(
        src,
        target,
        ignore=shutil.ignore_patterns(
            "__pycache__",
            "_t0_report.json",
            "_evidence",
            "*.pyc",
        ),
    )
    files_created = sorted(str(p.relative_to(output_dir)) for p in target.rglob("*") if p.is_file())
    adapter_name = f"{name}Adapter.py"
    adapter_src = ADAPTERS_FASTAPI / adapter_name
    if adapter_src.exists():
        adapter_target = Path(output_dir) / "app" / "core" / "venous" / "_adapters" / "fastapi"
        adapter_target.mkdir(parents=True, exist_ok=True)
        shutil.copy(adapter_src, adapter_target / adapter_name)
        files_created.append(str((adapter_target / adapter_name).relative_to(output_dir)))
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
    "name": "fastapi_observability",
    "description": (
        "Observability domain dispatcher (HuGR tree pattern). ONE tool that routes to every observability-related capability the kit ships. Choose granularity via `action`:\n  • 'list' → returns the full observability tree + primitive catalog.\n  • 'bundle' → one-shot: installs 3 curated observability slices (add_opentelemetry, add_prometheus_metrics, add_structured_logging).\n  • '<slice>' → install ONE slice (add_opentelemetry, add_prometheus_metrics, add_structured_logging).\n  • 'primitive' → copy ONE Lego block (AccessLog, CardinalityGuard, CorrelationContext, CorrelationId, ErrorSink, EventBus, HealthProbe, HistogramBuckets, LifecycleHook, LlmTrace, MetricMeter, ResourceDescriptor, SamplingPolicy, SemanticAttributes, StructuredLogger, TelemetryExporter, Tracer).\nCall with action='list' if unsure. Every return carries `next_steps`."
    ),
    "tags": ["observability", "domain", "dispatcher"],
    "annotations": {"readOnlyHint": False, "destructiveHint": False},
    "entry": "fastapi_observability",
}


def fastapi_observability(action: str, params: dict | None = None) -> dict:
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
            what="observability domain tree (3 bundle + 3 slices + 17 primitives)",
            result={
                "domain": "observability",
                "bundle": {
                    "description": (
                        "Install the curated production observability stack: "
                        f"{len(BUNDLE_SLICES)} slices composed in order."
                    ),
                    "slices_installed": list(BUNDLE_SLICES),
                    "required_params": {"output_dir": "str"},
                },
                "slices": {
                    name: {"description": meta["desc"]} for name, meta in sorted(SLICES.items())
                },
                "primitives": {
                    name: {"purpose": purpose} for name, purpose in sorted(PRIMITIVES.items())
                },
                "usage_examples": [
                    "fastapi_observability(action='bundle', params={'output_dir':'/tmp/my-app'})",
                    "fastapi_observability(action='add_opentelemetry', params={'output_dir':'/tmp/my-app'})",
                    "fastapi_observability(action='primitive', params={'name':'AccessLog','output_dir':'/tmp/my-app'})",
                ],
            },
            next_steps=[
                "action='bundle' → install everything for a new project.",
                "action='<slice>' → install one slice for an existing project.",
                "action='primitive' + name=X → copy one Lego surgically.",
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
        name = params.get("name")
        output_dir = params.get("output_dir")
        if not name or not output_dir:
            return _envelope(
                ok=False,
                what="primitive action requires name + output_dir",
                result={},
                next_steps=[
                    "Example: fastapi_observability(action='primitive', params={'name':'X','output_dir':'/tmp/app'}).",
                    "Call fastapi_observability(action='list') to see available primitive names.",
                ],
                t0=t0,
            )
        try:
            res = _copy_primitive(name, output_dir)
        except (ValueError, FileNotFoundError) as exc:
            return _envelope(
                ok=False,
                what=str(exc),
                result={},
                next_steps=["Call fastapi_observability(action='list') for valid primitive names."],
                t0=t0,
            )
        return _envelope(
            ok=True,
            what=f"primitive {name} copied into {output_dir}",
            result=res,
            next_steps=[
                f"Import in your handler: from core.venous.obs.{name} import {name}",
                f"Call fastapi_meta_describe(name='{name}') for Protocol + invariants.",
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
                "Additional features? call fastapi_observability(action='list') for more slices.",
            ],
            t0=t0,
        )

    valid = ["list", "bundle", "primitive"] + sorted(SLICES)
    return _envelope(
        ok=False,
        what=f"unknown action {action!r}",
        result={"valid_actions": valid},
        next_steps=[
            "Call fastapi_observability(action='list') to see the full tree.",
            f"Did you mean one of: {', '.join(valid[:5])}, ...?",
        ],
        t0=t0,
    )
