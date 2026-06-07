"""BEHAVIOR scenarios — gap-fill part 3 (scenarios 37-38).

Split from ``test_behavior_scenarios_gap_fill.py`` to respect the 500-LOC
cap. Shared framework lives in
``test_behavior_scenarios_gap_fill__shared.py``.

Covers:
  * SCENARIO 37 — Push Notifications (Native) + Transactional Email
  * SCENARIO 38 — Rate Limiting
"""

from __future__ import annotations

import ast as _ast

import pytest

from tests.test_behavior_scenarios_gap_fill__shared import (
    Scenario,
    ScenarioContext,
    _assert_scenario,
)


# ===========================================================================
# SCENARIO 37 — Push Notifications (Native) + Transactional Email
# ===========================================================================

async def flow_push_and_email(ctx: ScenarioContext) -> None:
    """Push + email: service classes, lazy SDK imports, model exists, delivery tracker."""
    project_dir = ctx.project_dir

    # --- 1. PushService with send_to_device ---
    push_init = project_dir / "app" / "push" / "__init__.py"
    if push_init.exists():
        src = push_init.read_text()
        ctx.record(
            "push_service_exported",
            "PushService" in src,
            "PushService exported from app/push/__init__.py",
        )
    else:
        ctx.record("push_service_exported", False, "app/push/__init__.py not found")

    push_service_file = project_dir / "app" / "push" / "service.py"
    if push_service_file.exists():
        src = push_service_file.read_text()
        ctx.record(
            "push_service_class_present",
            "class PushService" in src,
            "PushService class in app/push/service.py",
        )
        ctx.record(
            "send_to_device_method",
            "def send_to_device" in src or "async def send_to_device" in src,
            "send_to_device method in PushService",
        )
    else:
        ctx.record("push_service_class_present", False, "app/push/service.py not found")
        ctx.record("send_to_device_method", False, "file not found")

    # --- 2. FCM provider — lazy firebase_admin import ---
    fcm_file = project_dir / "app" / "push" / "providers" / "fcm.py"
    if fcm_file.exists():
        src = fcm_file.read_text()
        ctx.record(
            "fcm_provider_exists",
            True,
            "app/push/providers/fcm.py present",
        )
        ctx.record(
            "firebase_admin_lazy_in_fcm",
            not any(
                (isinstance(n, _ast.Import) and any(a.name.startswith("firebase_admin") for a in n.names))
                or (isinstance(n, _ast.ImportFrom) and (n.module or "").startswith("firebase_admin"))
                for n in _ast.parse(src).body
            ),
            "firebase_admin not at module top-level in fcm.py (lazy import)",
        )
    else:
        ctx.record("fcm_provider_exists", False, "app/push/providers/fcm.py not found")
        ctx.record("firebase_admin_lazy_in_fcm", False, "file not found")

    # --- 3. APNs provider — lazy apns2 import ---
    apns_file = project_dir / "app" / "push" / "providers" / "apns.py"
    if apns_file.exists():
        src = apns_file.read_text()
        ctx.record(
            "apns_provider_exists",
            True,
            "app/push/providers/apns.py present",
        )
        ctx.record(
            "apns2_lazy_in_apns",
            not any(
                (isinstance(n, _ast.Import) and any(a.name.startswith("apns2") for a in n.names))
                or (isinstance(n, _ast.ImportFrom) and (n.module or "").startswith("apns2"))
                for n in _ast.parse(src).body
            ),
            "apns2 not at module top-level in apns.py (lazy import)",
        )
    else:
        ctx.record("apns_provider_exists", False, "app/push/providers/apns.py not found")
        ctx.record("apns2_lazy_in_apns", False, "file not found")

    # --- 4. DeviceToken model ---
    device_token_file = project_dir / "app" / "models" / "device_token.py"
    ctx.record(
        "device_token_model_exists",
        device_token_file.exists() and "DeviceToken" in device_token_file.read_text(),
        "DeviceToken model in app/models/device_token.py",
    )

    # --- 5. DeliveryTracker class in transactional email ---
    tracker_file = project_dir / "app" / "email" / "delivery_tracker.py"
    ctx.record(
        "delivery_tracker_exists",
        tracker_file.exists() and "DeliveryTracker" in tracker_file.read_text(),
        "DeliveryTracker class in app/email/delivery_tracker.py",
    )

    # --- 6. All three email provider files exist with lazy imports ---
    provider_names = ["resend_provider.py", "postmark_provider.py", "sendgrid_provider.py"]
    providers_dir = project_dir / "app" / "email" / "providers"
    for pname in provider_names:
        pfile = providers_dir / pname
        provider_key = pname.replace("_provider.py", "")
        ctx.record(
            f"{provider_key}_provider_exists",
            pfile.exists(),
            str(pfile.relative_to(project_dir) if pfile.exists() else "NOT FOUND"),
        )
        if pfile.exists():
            src = pfile.read_text()
            # SDK import for resend/postmarker/sendgrid must be lazy (not at top level)
            sdk_names = {"resend": "resend", "postmark": "postmarker", "sendgrid": "sendgrid"}
            sdk = sdk_names.get(provider_key, provider_key)
            is_lazy = not any(
                (isinstance(n, _ast.Import) and any(a.name.startswith(sdk) for a in n.names))
                or (isinstance(n, _ast.ImportFrom) and (n.module or "").startswith(sdk))
                for n in _ast.parse(src).body
            )
            ctx.record(
                f"{provider_key}_sdk_lazy_import",
                is_lazy,
                f"{sdk} not at module top-level in {pname}",
            )


PUSH_AND_EMAIL = Scenario(
    name="push_notifications_transactional_email",
    archetype="APNs+FCM push notifications + multi-provider transactional email",
    models={"User": {"email": "str", "device_token": "str"}},
    tools=[
        ("add_push_notifications_native", "adapt.extend.infrastructure.add_push_notifications_native"),
        ("add_transactional_email",       "adapt.extend.infrastructure.add_transactional_email"),
    ],
    flow=flow_push_and_email,
    needs_boot=False,  # APNs/FCM require real credentials; file-content checks are definitive
)


# ===========================================================================
# SCENARIO 38 — Rate Limiting
# ===========================================================================

async def flow_rate_limiting(ctx: ScenarioContext) -> None:
    """Rate limiting: RateLimitConfig dataclass, key functions, limiter symbol, 429 handler."""
    project_dir = ctx.project_dir

    # --- 1. RateLimitConfig dataclass ---
    rl_core = project_dir / "app" / "core" / "rate_limit.py"
    if rl_core.exists():
        src = rl_core.read_text()
        ctx.record(
            "rate_limit_core_exists",
            True,
            "app/core/rate_limit.py present",
        )
        ctx.record(
            "rate_limit_config_dataclass",
            "RateLimitConfig" in src,
            "RateLimitConfig present in app/core/rate_limit.py",
        )
        ctx.record(
            "key_ip_function",
            "def key_ip" in src,
            "key_ip function present in app/core/rate_limit.py",
        )
        ctx.record(
            "key_user_function",
            "def key_user" in src,
            "key_user function present in app/core/rate_limit.py",
        )
        ctx.record(
            "key_user_endpoint_function",
            "def key_user_endpoint" in src,
            "key_user_endpoint function present in app/core/rate_limit.py",
        )
        ctx.record(
            "limiter_module_level_symbol",
            "limiter" in src and ("= Limiter" in src or "= _build_limiter" in src),
            "module-level `limiter` symbol in app/core/rate_limit.py",
        )
    else:
        for label in [
            "rate_limit_core_exists",
            "rate_limit_config_dataclass",
            "key_ip_function",
            "key_user_function",
            "key_user_endpoint_function",
            "limiter_module_level_symbol",
        ]:
            ctx.record(label, False, "app/core/rate_limit.py not found")

    # --- 2. 429 handler with Retry-After header ---
    middleware_file = project_dir / "app" / "middleware" / "rate_limit.py"
    if middleware_file.exists():
        src = middleware_file.read_text()
        ctx.record(
            "rate_limit_middleware_exists",
            True,
            "app/middleware/rate_limit.py present",
        )
        ctx.record(
            "retry_after_header_in_handler",
            "Retry-After" in src,
            "Retry-After header in 429 handler",
        )
    else:
        ctx.record("rate_limit_middleware_exists", False,
                   "app/middleware/rate_limit.py not found")
        ctx.record("retry_after_header_in_handler", False, "file not found")

    # --- 3. Config has RATE_LIMIT_ENABLED / DEFAULT / STRATEGY ---
    cfg_path = project_dir / "app" / "core" / "config.py"
    cfg_src = cfg_path.read_text() if cfg_path.exists() else ""
    ctx.record(
        "rate_limit_enabled_in_config",
        "RATE_LIMIT_ENABLED" in cfg_src,
        "RATE_LIMIT_ENABLED in app/core/config.py",
    )
    ctx.record(
        "rate_limit_default_in_config",
        "RATE_LIMIT_DEFAULT" in cfg_src,
        "RATE_LIMIT_DEFAULT in app/core/config.py",
    )
    ctx.record(
        "rate_limit_strategy_in_config",
        "RATE_LIMIT_STRATEGY" in cfg_src,
        "RATE_LIMIT_STRATEGY in app/core/config.py",
    )

    # --- 4. GET /rate-limit/status route FILE exists ---
    # add_rate_limiting writes app/api/routes/rate_limit.py but does NOT auto-register
    # the route in routes/__init__.py — that step is left to the developer.
    # We verify the route file itself is present and defines the /status endpoint.
    rl_route_file = project_dir / "app" / "api" / "routes" / "rate_limit.py"
    if rl_route_file.exists():
        rl_src = rl_route_file.read_text()
        ctx.record(
            "rate_limit_status_endpoint_exists",
            ("@router.get" in rl_src or "status" in rl_src) and "rate" in rl_src.lower(),
            "GET /rate-limit/status route defined in app/api/routes/rate_limit.py",
        )
    else:
        ctx.record(
            "rate_limit_status_endpoint_exists",
            False,
            "app/api/routes/rate_limit.py not found",
        )


RATE_LIMITING = Scenario(
    name="rate_limiting",
    archetype="SlowAPI rate limiting with IP/user/endpoint keys + 429 Retry-After",
    models={"Request": {"path": "str", "method": "str"}},
    tools=[
        ("add_rate_limiting", "adapt.extend.infrastructure.add_rate_limiting"),
    ],
    flow=flow_rate_limiting,
    needs_boot=False,  # status route file written but not auto-registered; file checks are definitive
)


# ===========================================================================
# pytest integration — one parametrized test per scenario
# ===========================================================================

SCENARIOS: list[Scenario] = [
    PUSH_AND_EMAIL,
    RATE_LIMITING,
]


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.name for s in SCENARIOS])
@pytest.mark.asyncio
async def test_scenario(scenario: Scenario) -> None:
    """Run a behavior scenario end-to-end and assert all checks pass."""
    await _assert_scenario(scenario)
