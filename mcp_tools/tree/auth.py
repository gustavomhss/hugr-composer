"""`fastapi_auth` — the auth-domain tree dispatcher (POC, tree variant).

ONE MCP tool that routes to 15 legacy slice tools + 8 primitives under
the `auth` domain. The Claude Maestro chooses granularity by `action`:

    fastapi_auth(action="list")                          → tree
    fastapi_auth(action="bundle", output_dir=..., ...)   → full auth stack
    fastapi_auth(action="add_oauth2", ...)               → slice
    fastapi_auth(action="primitive", name="SessionStore", output_dir=...)
                                                         → single lego

See `/docs/research/DUAL_INDEX_DESIGN.md` §4 (revised tree variant).

POC scope rules
  - No change to the 15 legacy `fastapi_add_*` tools — they remain
    registered. This dispatcher INDIRECTS to them by importing the
    underlying module and calling its entry function.
  - Same envelope as tier-1 tools: {ok, what_happened, result,
    next_steps, elapsed_ms}.
  - Failure in an underlying slice is surfaced, not swallowed.
"""
from __future__ import annotations

import importlib
import shutil
import time
from pathlib import Path
from typing import Any

SKILL_ROOT = Path(__file__).resolve().parents[2]
VENOUS_AUTH = SKILL_ROOT / "core" / "venous" / "auth"
ADAPTERS_FASTAPI = SKILL_ROOT / "core" / "venous" / "_adapters" / "fastapi"
ADAPT_ROOT = SKILL_ROOT / "adapt" / "extend" / "auth_access"


# ---------------------------------------------------------------------------
# Tree declaration — single source of truth for the domain surface
# ---------------------------------------------------------------------------

SLICES: dict[str, dict[str, Any]] = {
    # slice_name → {module, entry, one-line description, required params}
    "add_api_key_auth":     {"mod": "add_api_key_auth",     "desc": "API key authentication alongside JWT"},
    "add_bola_guard":       {"mod": "add_bola_guard",       "desc": "BOLA / IDOR protection with ownership checks"},
    "add_cedar_policies":   {"mod": "add_cedar_policies",   "desc": "AWS Cedar policy-as-code ABAC authorization"},
    "add_dpop_tokens":      {"mod": "add_dpop_tokens",      "desc": "RFC 9449 DPoP (proof-of-possession) tokens"},
    "add_feature_flags":    {"mod": "add_feature_flags",    "desc": "Per-user / per-tenant feature flag system"},
    "add_feature_toggles_api": {"mod": "add_feature_toggles_api", "desc": "HTTP API wrapping the FeatureToggle primitive"},
    "add_mfa":              {"mod": "add_mfa",              "desc": "TOTP second-factor via TotpVerifier primitive"},
    "add_multi_tenancy":    {"mod": "add_multi_tenancy",    "desc": "Tenant scoping (schema-per-tenant or row-level)"},
    "add_oauth2":           {"mod": "add_oauth2_provider",  "desc": "OAuth2 with PKCE + TokenIntrospector + SessionStore"},
    "add_opa_integration":  {"mod": "add_opa_integration",  "desc": "Open Policy Agent with circuit breaker"},
    "add_passkey_auth":     {"mod": "add_passkey_auth",     "desc": "WebAuthn / FIDO2 passwordless passkey auth"},
    "add_rbac":             {"mod": "add_rbac",             "desc": "RBAC via RequestGuard + CurrentPrincipal"},
    "add_request_signing":  {"mod": "add_request_signing",  "desc": "HMAC request signing (Stripe / AWS Sig V4 pattern)"},
    "add_sms_otp":          {"mod": "add_sms_otp",          "desc": "SMS OTP via Twilio / Vonage with rate limits"},
    "add_social_login":     {"mod": "add_social_login",     "desc": "Google / GitHub / Apple OAuth2 social login"},
}

PRIMITIVES: dict[str, str] = {
    # name → one-line purpose (from registry)
    "AuthorizationCodeFlow": "OAuth 2.0 auth-code grant with PKCE, state, nonce enforcement",
    "CurrentPrincipal":      "Read-only authenticated identity for the active request",
    "FeatureFlagCache":      "Bounded async LRU cache with per-entry TTL for flag payloads",
    "RequestGuard":          "Declarative authorization decision point per route, audited",
    "SessionStore":          "Issue / rotate / revoke server-side session records",
    "TokenIntrospector":     "Validate access tokens by signature / issuer / audience / expiry",
    "TotpVerifier":          "TOTP per RFC 6238 with constant-time comparison",
    "WebAuthnAuthenticator": "WebAuthn / passkey register + assert with binding",
}

# Curated "bundle" — the eight most-composed slices for a new project.
# Chosen to deliver "production auth out of the box": core token handling,
# session management, MFA, RBAC, rate limiting, and audit surface.
BUNDLE_SLICES: tuple[str, ...] = (
    "add_oauth2",           # tokens + session store
    "add_rbac",             # RequestGuard + CurrentPrincipal
    "add_mfa",              # TotpVerifier second factor
    "add_api_key_auth",     # API key alongside JWT
    "add_bola_guard",       # object-level auth
    "add_request_signing",  # outgoing + incoming HMAC
    "add_feature_flags",    # per-user / per-tenant toggles
    "add_multi_tenancy",    # tenant scoping middleware
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
# Slice routing — import + call the legacy fastapi_add_<slice> tool
# ---------------------------------------------------------------------------

def _call_slice(slice_name: str, **kwargs) -> dict:
    """Route to the underlying `adapt/extend/auth_access/<module>` tool."""
    meta = SLICES[slice_name]
    mod_name = f"adapt.extend.auth_access.{meta['mod']}"
    mod = importlib.import_module(mod_name)
    # Entry function = module stem (convention; verified below).
    entry = getattr(mod, meta["mod"], None)
    if entry is None or not callable(entry):
        raise RuntimeError(f"slice {slice_name!r}: entry function {meta['mod']!r} not found in {mod_name}")
    return entry(**kwargs)


# ---------------------------------------------------------------------------
# Primitive routing — copy the primitive dir into the target project
# ---------------------------------------------------------------------------

def _copy_primitive(name: str, output_dir: str) -> dict:
    """Copy core/venous/auth/<Name>/ into <output_dir>/app/core/venous/auth/<Name>/.

    Follows ADR 0002 (copy-in distribution). Skips _t0_report.json + _evidence/
    (per .gitignore). Also copies the matching fastapi adapter under
    _adapters/fastapi/ if one exists.
    """
    if name not in PRIMITIVES:
        raise ValueError(
            f"unknown primitive {name!r} in domain auth. "
            f"Available: {sorted(PRIMITIVES)}"
        )
    src = VENOUS_AUTH / name
    if not src.is_dir():
        raise FileNotFoundError(f"primitive source missing: {src}")
    target = Path(output_dir) / "app" / "core" / "venous" / "auth" / name
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
    # Matching adapter (if any)
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
        # adapter test (if present)
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
    "name": "fastapi_auth",
    "description": (
        "Auth / identity domain dispatcher (HuGR tree pattern). ONE tool "
        "that routes to every auth-related capability the kit ships. "
        "Choose granularity via `action`:\n"
        "  • 'list'      → returns the full auth tree + primitive catalog.\n"
        "  • 'bundle'    → one-shot: installs 8 curated auth slices (OAuth2, "
        "RBAC, MFA, API-key, BOLA guard, request signing, flags, "
        "multi-tenancy). Use on a new project.\n"
        "  • '<slice>'   → install ONE slice (add_oauth2, add_mfa, add_rbac, "
        "add_sms_otp, add_passkey_auth, add_dpop_tokens, "
        "add_cedar_policies, add_opa_integration, add_social_login, "
        "add_request_signing, add_bola_guard, add_feature_flags, "
        "add_feature_toggles_api, add_multi_tenancy, add_api_key_auth). "
        "Use to bolt a capability into an existing project.\n"
        "  • 'primitive' → copy ONE Lego block (SessionStore, "
        "TokenIntrospector, CurrentPrincipal, RequestGuard, "
        "AuthorizationCodeFlow, TotpVerifier, WebAuthnAuthenticator, "
        "FeatureFlagCache). Use when you need surgical granularity — "
        "e.g. 'I already have auth, I need the SessionStore for session "
        "preservation on node kill'.\n"
        "Call with action='list' if unsure which level to use. Every "
        "return carries `next_steps` pointing at the next likely call."
    ),
    "tags": ["auth", "domain", "dispatcher"],
    "annotations": {"readOnlyHint": False, "destructiveHint": False},
    "entry": "fastapi_auth",
}


def fastapi_auth(action: str, params: dict | None = None) -> dict:
    """See MCP_TOOL description.

    Signature note: `params` is a polymorphic dict whose expected keys
    depend on `action`. FastMCP doesn't support **kwargs in tool
    signatures, so a single `params` dict is the uniform contract.
    Every action documents its required / optional keys in the `list`
    action's response (usage_examples).
    """
    t0 = time.perf_counter()
    params = params or {}

    if action == "list":
        return _envelope(
            ok=True,
            what="auth domain tree (1 bundle + 15 slices + 8 primitives)",
            result={
                "domain": "auth",
                "bundle": {
                    "description": (
                        "Install the curated production auth stack: "
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
                    "fastapi_auth(action='bundle', params={'output_dir':'/tmp/my-app'})",
                    "fastapi_auth(action='add_oauth2', params={'output_dir':'/tmp/my-app','providers':['google']})",
                    "fastapi_auth(action='primitive', params={'name':'SessionStore','output_dir':'/tmp/my-app'})",
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
                ok=False, what="bundle requires output_dir",
                result={}, next_steps=["Pass output_dir='/path/to/project'."],
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
                    "Bundle complete. Boot: `uvicorn app.main:app`, then POST /auth/login.",
                    "For advanced flows (social, passkey, DPoP), call the individual add_* slices.",
                    "Call fastapi_meta_check_audit() to verify the contract.",
                ] if ok else
                [f"Fix errors above. Retry failing slices individually via action=<slice>."]
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
                result={}, next_steps=[
                    "Example: fastapi_auth(action='primitive', name='SessionStore', output_dir='/tmp/app').",
                    "Call fastapi_auth(action='list') to see available primitive names.",
                ], t0=t0,
            )
        try:
            res = _copy_primitive(name, output_dir)
        except (ValueError, FileNotFoundError) as exc:
            return _envelope(
                ok=False, what=str(exc), result={},
                next_steps=["Call fastapi_auth(action='list') for valid primitive names."],
                t0=t0,
            )
        return _envelope(
            ok=True,
            what=f"primitive {name} copied into {output_dir}",
            result=res,
            next_steps=[
                f"Import in your handler: from core.venous.auth.{name} import {name}",
                f"Call fastapi_meta_search_describe(name='{name}') for Protocol + invariants.",
            ],
            t0=t0,
        )

    if action in SLICES:
        output_dir = params.get("output_dir")
        if not output_dir:
            return _envelope(
                ok=False, what=f"slice {action!r} requires output_dir in params",
                result={}, next_steps=["Pass params={'output_dir':'/path/to/project', ...}."],
                t0=t0,
            )
        try:
            res = _call_slice(action, **params)
        except Exception as exc:  # noqa: BLE001
            return _envelope(
                ok=False, what=f"slice {action!r} failed: {exc}",
                result={}, next_steps=[
                    f"Check params for {action!r}. "
                    f"Call fastapi_meta_search_describe(name='fastapi_{SLICES[action]['mod']}') for the schema."
                ], t0=t0,
            )
        return _envelope(
            ok=True,
            what=f"slice {action} installed",
            result=res if isinstance(res, dict) else {"raw": repr(res)[:500]},
            next_steps=[
                "Boot the emitted app + hit the new endpoints to verify.",
                "Additional auth features? call fastapi_auth(action='list') for more slices.",
                "Need a primitive surgically? fastapi_auth(action='primitive', name=...).",
            ],
            t0=t0,
        )

    valid = ["list", "bundle", "primitive"] + sorted(SLICES)
    return _envelope(
        ok=False,
        what=f"unknown action {action!r}",
        result={"valid_actions": valid},
        next_steps=[
            "Call fastapi_auth(action='list') to see the full tree.",
            f"Did you mean one of: {', '.join(valid[:5])}, ...?",
        ],
        t0=t0,
    )
