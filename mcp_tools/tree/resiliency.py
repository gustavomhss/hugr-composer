"""`fastapi_resiliency` — the resiliency-domain tree dispatcher.

ONE MCP tool that routes to 47 slice tool(s) + 14 primitive(s) under the `resiliency` domain. The Claude agent chooses granularity by `action`.

See `mcp_tools/tree/auth.py` — the canonical POC template this file mirrors.
"""

from __future__ import annotations

import importlib
import shutil
import time
from pathlib import Path
from typing import Any

SKILL_ROOT = Path(__file__).resolve().parents[2]
VENOUS_DIR = SKILL_ROOT / "core" / "venous" / "resiliency"
ADAPTERS_FASTAPI = SKILL_ROOT / "core" / "venous" / "_adapters" / "fastapi"


# ---------------------------------------------------------------------------
# Tree declaration — single source of truth for the resiliency domain surface
# ---------------------------------------------------------------------------

SLICES: dict[str, dict[str, Any]] = {
    "add_adaptive_throttle": {
        "mod": "add_adaptive_throttle",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Add multi-dimensional adaptive rate limiting: cost-based quota, behavioral fingerprinting, a...",
    },
    "add_adaptive_timeouts": {
        "mod": "add_adaptive_timeouts",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Add self-adjusting timeouts that learn from observed downstream latency, auto-calibrating to...",
    },
    "add_anomaly_detector": {
        "mod": "add_anomaly_detector",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Add statistical anomaly detection: Z-score + EMA on sliding windows for request rate, error...",
    },
    "add_api_monetization": {
        "mod": "add_api_monetization",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Add usage-metered billing with Stripe Billing Meters v2: MeteringMiddleware, metering rules...",
    },
    "add_api_replay_debugger": {
        "mod": "add_api_replay_debugger",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Add time-travel API replay debugger: Redis ring buffer captures full req/resp, replayer re-e...",
    },
    "add_arq_worker": {
        "mod": "add_arq_worker",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Add an arq (Redis-backed async) job queue with worker, task registry, and HTTP status routes",
    },
    "add_bulkhead_isolation": {
        "mod": "add_bulkhead_isolation",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Add bulkhead isolation with separate semaphore pools per endpoint group, preventing one slow...",
    },
    "add_cache_layer": {
        "mod": "add_cache_layer",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Add Redis caching layer with decorator, invalidation strategy, and TTL management",
    },
    "add_canary_tokens": {
        "mod": "add_canary_tokens",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Add canary token infrastructure: honeypot endpoints, fake credentials, and decoy DB records...",
    },
    "add_celery_beat": {
        "mod": "add_celery_beat",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Add Celery Beat scheduled tasks to a FastAPI project: celery app factory, task registry, bea...",
    },
    "add_circuit_breaker": {
        "mod": "add_circuit_breaker",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Copy CircuitBreaker primitive + FastAPI adapter into the project and wire a ≤20-line app/cir...",
    },
    "add_compliance_engine": {
        "mod": "add_compliance_engine",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Add declarative data-governance at ORM level: PII detection, retention enforcer, right-to-er...",
    },
    "add_cors_config": {
        "mod": "add_cors_config",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Upgrade CORS middleware with env-var configurable origins, wildcard warnings, preflight cach...",
    },
    "add_cost_tracker": {
        "mod": "add_cost_tracker",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Copy CostTracker primitive + FastAPI adapter into the project and wire a ≤20-line app/cost_t...",
    },
    "add_csrf_protection": {
        "mod": "add_csrf_protection",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Add CSRF token protection with double-submit cookie pattern to FastAPI",
    },
    "add_dependency_health_map": {
        "mod": "add_dependency_health_map",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Add a visual dependency health map: HealthMapBuilder discovers all deps from config (DB, Red...",
    },
    "add_dlp_shield": {
        "mod": "add_dlp_shield",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Add DLP (Data Loss Prevention) response middleware with regex PII/PHI/PCI detection, decorat...",
    },
    "add_email_templates": {
        "mod": "add_email_templates",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Add a production-grade transactional email layer with Jinja2 templates, pluggable providers...",
    },
    "add_excel_export": {
        "mod": "add_excel_export",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Add a production-grade Excel export layer with OpenPyXL streaming for large datasets, cell f...",
    },
    "add_graceful_shutdown": {
        "mod": "add_graceful_shutdown",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Copy GracefulShutdown primitive + FastAPI adapter into the project and wire a ≤20-line app/s...",
    },
    "add_health_deep": {
        "mod": "add_health_deep",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Upgrade to production-grade deep health checks with HealthRegistry, dependency matrix, per-c...",
    },
    "add_i18n": {
        "mod": "add_i18n",
        "pkg": "adapt.evolve",
        "desc": "Add internationalization (i18n) support with locale detection and message catalogs",
    },
    "add_input_sanitization": {
        "mod": "add_input_sanitization",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Add HTML sanitization and XSS prevention middleware to FastAPI",
    },
    "add_kubernetes_manifests": {
        "mod": "add_kubernetes_manifests",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Generate production-ready Kubernetes manifests: Deployment, Service, HPA, PDB, ConfigMap, Se...",
    },
    "add_load_shedding": {
        "mod": "add_load_shedding",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Copy LoadShedder primitive + LoadShedderAdapter into the project and wire a ≤20-line app/loa...",
    },
    "add_migration_data": {
        "mod": "add_migration_data",
        "pkg": "adapt.evolve",
        "desc": "Add data migration support alongside schema migrations in Alembic",
    },
    "add_ml_gpu_inference": {
        "mod": "add_ml_gpu_inference",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Upgrade a FastAPI project with GPU-optimised inference: DeviceManager, GPUPredictor (mixed p...",
    },
    "add_ml_model_registry": {
        "mod": "add_ml_model_registry",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Add a production-grade ML model registry with versioned artefacts, promote/rollback lifecycl...",
    },
    "add_ml_model_server": {
        "mod": "add_ml_model_server",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Add a framework-agnostic ML inference layer with ModelRegistry, Predictor, batch prediction,...",
    },
    "add_notifications": {
        "mod": "add_notifications",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Add a production-grade in-app notification layer with channel dispatch (in_app, push FCM stu...",
    },
    "add_pdf_reports": {
        "mod": "add_pdf_reports",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Add a production-grade PDF report generation layer with WeasyPrint lazy import, Jinja2 templ...",
    },
    "add_push_notifications_native": {
        "mod": "add_push_notifications_native",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Add production APNs + FCM push notifications with PushService, DeviceToken model, CRUD helpe...",
    },
    "add_rate_limiting": {
        "mod": "add_rate_limiting",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Copy RateLimiter primitive + FastAPI adapter into the project and wire a ≤20-line app/rate_l...",
    },
    "add_request_fingerprint": {
        "mod": "add_request_fingerprint",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Add automatic request deduplication: SHA-256 fingerprint of user+method+path+body. Returns c...",
    },
    "add_response_armor": {
        "mod": "add_response_armor",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Add five-layer response hardening: error sanitization (generic to client, full to logs), con...",
    },
    "add_retry_budget": {
        "mod": "add_retry_budget",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Copy RetryPolicy primitive + FastAPI adapter into the project and wire a ≤20-line app/retry....",
    },
    "add_runtime_sentinel": {
        "mod": "add_runtime_sentinel",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Add RASP middleware with SQL/command/SSRF injection detection, attack pattern registry, and...",
    },
    "add_s3_storage": {
        "mod": "add_s3_storage",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Add production-grade S3/MinIO object storage with presigned URL upload/download, content-typ...",
    },
    "add_scheduled_tasks": {
        "mod": "add_scheduled_tasks",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Add APScheduler-based cron jobs with Redis job store, decorator registry, and FastAPI lifesp...",
    },
    "add_secret_rotation": {
        "mod": "add_secret_rotation",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Add a secret manager abstraction (Vault/AWS SM/env), auto-rotation with dual-key windows, lo...",
    },
    "add_sqladmin": {
        "mod": "add_sqladmin",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Add a production-grade admin panel (SQLAdmin) with superuser-only auth and auto-generated mo...",
    },
    "add_stripe_checkout": {
        "mod": "add_stripe_checkout",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Add a production-grade Stripe Checkout flow with Payment model, webhook receiver, and idempo...",
    },
    "add_stripe_refund_flow": {
        "mod": "add_stripe_refund_flow",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Add a production-grade Stripe refund flow with Refund model, PII-safe schemas, async CRUD, R...",
    },
    "add_stripe_subscription": {
        "mod": "add_stripe_subscription",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Add production-grade Stripe subscription billing with Subscription model, webhook receiver,...",
    },
    "add_temporal_workflow": {
        "mod": "add_temporal_workflow",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Add a Temporal.io durable workflow engine with order-processing example, compensation patter...",
    },
    "add_tenant_onboarding": {
        "mod": "add_tenant_onboarding",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Add wizard orchestrator for tenant onboarding: OnboardingOrchestrator with atomic+compensata...",
    },
    "add_transactional_email": {
        "mod": "add_transactional_email",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Add Resend/Postmark/SendGrid email adapters with delivery tracking (sent/delivered/bounced/c...",
    },
}

PRIMITIVES: dict[str, str] = {
    "Bulkhead": "Partition concurrency so saturation inside one dependency cannot exhaust resources shared wi...",
    "CircuitBreaker": "Short-circuit calls to a failing dependency by transitioning between closed, open, and half-...",
    "CostTracker": "Aggregates per-request cost estimates from a pluggable list of estimators (db/s3/api/...). S...",
    "ExcelExporter": "Creates openpyxl workbooks with chunked streaming write for large result sets. Enforces a ha...",
    "GracefulShutdown": "Coordinates process shutdown across three phases — drain (stop accepting new work), wait-for...",
    "HeterogeneousWorkerPool": "Route inference tasks across mixed CPU+GPU workers using observed queue-depth and rolling-la...",
    "LoadShedder": "Drop or reject low-priority work when the server enters an overload regime so high-priority...",
    "ModelRegistry": "Dict-based singleton registry for lazily-loaded model instances (ML, embeddings, rule-engine...",
    "RateLimiter": "Enforce a maximum rate of admitted operations over a rolling window with optional waiting an...",
    "Redactor": "Structlog processor that redacts PII-shaped substrings (emails, CC numbers, tokens, etc.) fr...",
    "RetryBudget": "Sliding-window retry budget: caps the ratio of retries to total requests over a rolling time...",
    "RetryPolicy": "Describe under which conditions a failed call may be retried, bounded by max attempts, backo...",
    "TimeoutBudget": "Attach a monotonic deadline to an inbound request and propagate the remaining budget to ever...",
    "TracingBuffer": "Thread-safe in-memory ring buffer of the last N request traces. Supports newest-first iterat...",
}

# Curated 'bundle' — 8 canonical resiliency slices.
# Rationale: Eight core resiliency controls: circuit-breaker, rate-limit, retry-budget, graceful shutdown, bulkhead, load-shed, deep health, response armor.
BUNDLE_SLICES: tuple[str, ...] = (
    "add_circuit_breaker",
    "add_rate_limiting",
    "add_retry_budget",
    "add_graceful_shutdown",
    "add_bulkhead_isolation",
    "add_load_shedding",
    "add_health_deep",
    "add_response_armor",
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
    because resiliency tools span multiple adapt/ subtrees.
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
    """Copy core/venous/resiliency/<Name>/ into <output_dir>/app/core/venous/resiliency/<Name>/.

    Follows ADR 0002 (copy-in distribution). Skips _t0_report.json +
    _evidence/ (per .gitignore). Also copies the matching fastapi
    adapter under _adapters/fastapi/ if one exists.
    """
    if name not in PRIMITIVES:
        raise ValueError(
            f"unknown primitive {name!r} in domain resiliency. Available: {sorted(PRIMITIVES)}"
        )
    src = VENOUS_DIR / name
    if not src.is_dir():
        raise FileNotFoundError(f"primitive source missing: {src}")
    target = Path(output_dir) / "app" / "core" / "venous" / "resiliency" / name
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
    "name": "fastapi_resiliency",
    "description": (
        "Resiliency domain dispatcher (HuGR tree pattern). ONE tool that routes to every resiliency-related capability the kit ships. Choose granularity via `action`:\n  • 'list' → returns the full resiliency tree + primitive catalog.\n  • 'bundle' → one-shot: installs 8 curated resiliency slices (add_circuit_breaker, add_rate_limiting, add_retry_budget, add_graceful_shutdown, add_bulkhead_isolation, add_load_shedding, ...).\n  • '<slice>' → install ONE slice (add_adaptive_throttle, add_adaptive_timeouts, add_anomaly_detector, add_api_monetization, add_api_replay_debugger, add_arq_worker, add_bulkhead_isolation, add_cache_layer, add_canary_tokens, add_celery_beat, add_circuit_breaker, add_compliance_engine, add_cors_config, add_cost_tracker, add_csrf_protection, add_dependency_health_map, add_dlp_shield, add_email_templates, add_excel_export, add_graceful_shutdown, add_health_deep, add_i18n, add_input_sanitization, add_kubernetes_manifests, add_load_shedding, add_migration_data, add_ml_gpu_inference, add_ml_model_registry, add_ml_model_server, add_notifications, add_pdf_reports, add_push_notifications_native, add_rate_limiting, add_request_fingerprint, add_response_armor, add_retry_budget, add_runtime_sentinel, add_s3_storage, add_scheduled_tasks, add_secret_rotation, add_sqladmin, add_stripe_checkout, add_stripe_refund_flow, add_stripe_subscription, add_temporal_workflow, add_tenant_onboarding, add_transactional_email).\n  • 'primitive' → copy ONE Lego block (Bulkhead, CircuitBreaker, CostTracker, ExcelExporter, GracefulShutdown, HeterogeneousWorkerPool, LoadShedder, ModelRegistry, RateLimiter, Redactor, RetryBudget, RetryPolicy, TimeoutBudget, TracingBuffer).\nCall with action='list' if unsure. Every return carries `next_steps`."
    ),
    "tags": ["resiliency", "domain", "dispatcher"],
    "annotations": {"readOnlyHint": False, "destructiveHint": False},
    "entry": "fastapi_resiliency",
}


def fastapi_resiliency(action: str, params: dict | None = None) -> dict:
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
            what="resiliency domain tree (8 bundle + 47 slices + 14 primitives)",
            result={
                "domain": "resiliency",
                "bundle": {
                    "description": (
                        "Install the curated production resiliency stack: "
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
                    "fastapi_resiliency(action='bundle', params={'output_dir':'/tmp/my-app'})",
                    "fastapi_resiliency(action='add_circuit_breaker', params={'output_dir':'/tmp/my-app'})",
                    "fastapi_resiliency(action='primitive', params={'name':'Bulkhead','output_dir':'/tmp/my-app'})",
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
                    "Example: fastapi_resiliency(action='primitive', params={'name':'X','output_dir':'/tmp/app'}).",
                    "Call fastapi_resiliency(action='list') to see available primitive names.",
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
                next_steps=["Call fastapi_resiliency(action='list') for valid primitive names."],
                t0=t0,
            )
        return _envelope(
            ok=True,
            what=f"primitive {name} copied into {output_dir}",
            result=res,
            next_steps=[
                f"Import in your handler: from core.venous.resiliency.{name} import {name}",
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
                "Additional features? call fastapi_resiliency(action='list') for more slices.",
            ],
            t0=t0,
        )

    valid = ["list", "bundle", "primitive"] + sorted(SLICES)
    return _envelope(
        ok=False,
        what=f"unknown action {action!r}",
        result={"valid_actions": valid},
        next_steps=[
            "Call fastapi_resiliency(action='list') to see the full tree.",
            f"Did you mean one of: {', '.join(valid[:5])}, ...?",
        ],
        t0=t0,
    )
