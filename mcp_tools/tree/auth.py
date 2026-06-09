"""`fastapi_auth` — the auth-domain tree dispatcher (M3.2 pilot).

ONE MCP tool that routes to 15 legacy slice tools + 8 primitives under
the `auth` domain. The Claude agent chooses granularity by `action`:

    fastapi_auth(action="list")                          → tree
    fastapi_auth(action="bundle", output_dir=..., ...)   → full auth stack
    fastapi_auth(action="add_oauth2", ...)               → slice
    fastapi_auth(action="primitive", name="SessionStore", output_dir=...)
                                                         → single lego

See `/docs/research/DUAL_INDEX_DESIGN.md` §4 (revised tree variant).

M3.2 PILOT: this module is now pure DATA + one
``make_dispatcher(DomainTreeConfig(...))`` call. The branch logic, envelope,
slice routing (dispatch_via_toolinput, F-001 drop-extras), and the
non-destructive primitive copy (F-002/F-003) all live in
``hugr_core.dispatch`` — the generic engine shared by every domain. The data
tables (SLICES / PRIMITIVES / BUNDLE_SLICES / MCP_TOOL) are unchanged, so the
public contract is byte-identical to the pre-extraction dispatcher.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hugr_core.dispatch import DomainTreeConfig, make_dispatcher

SKILL_ROOT = Path(__file__).resolve().parents[2]
VENOUS_AUTH = SKILL_ROOT / "core" / "venous" / "auth"
ADAPTERS_FASTAPI = SKILL_ROOT / "core" / "venous" / "_adapters" / "fastapi"
ADAPT_ROOT = SKILL_ROOT / "adapt" / "extend" / "auth_access"

# Single adapt package every auth slice lives under (auth's single-pkg style:
# slices carry no per-slice `pkg`; the dispatcher falls back to default_pkg).
AUTH_PKG = "adapt.extend.auth_access"


# ---------------------------------------------------------------------------
# Tree declaration — single source of truth for the domain surface
# ---------------------------------------------------------------------------

SLICES: dict[str, dict[str, Any]] = {
    # slice_name → {module, entry, one-line description, required params}
    "add_api_key_auth": {"mod": "add_api_key_auth", "desc": "API key authentication alongside JWT"},
    "add_bola_guard": {
        "mod": "add_bola_guard",
        "desc": "BOLA / IDOR protection with ownership checks",
    },
    "add_cedar_policies": {
        "mod": "add_cedar_policies",
        "desc": "AWS Cedar policy-as-code ABAC authorization",
    },
    "add_dpop_tokens": {
        "mod": "add_dpop_tokens",
        "desc": "RFC 9449 DPoP (proof-of-possession) tokens",
    },
    "add_feature_flags": {
        "mod": "add_feature_flags",
        "desc": "Per-user / per-tenant feature flag system",
    },
    "add_feature_toggles_api": {
        "mod": "add_feature_toggles_api",
        "desc": "HTTP API wrapping the FeatureToggle primitive",
    },
    "add_mfa": {"mod": "add_mfa", "desc": "TOTP second-factor via TotpVerifier primitive"},
    "add_multi_tenancy": {
        "mod": "add_multi_tenancy",
        "desc": "Tenant scoping (schema-per-tenant or row-level)",
    },
    "add_oauth2": {
        "mod": "add_oauth2_provider",
        "desc": "OAuth2 with PKCE + TokenIntrospector + SessionStore",
    },
    "add_opa_integration": {
        "mod": "add_opa_integration",
        "desc": "Open Policy Agent with circuit breaker",
    },
    "add_passkey_auth": {
        "mod": "add_passkey_auth",
        "desc": "WebAuthn / FIDO2 passwordless passkey auth",
    },
    "add_rbac": {"mod": "add_rbac", "desc": "RBAC via RequestGuard + CurrentPrincipal"},
    "add_request_signing": {
        "mod": "add_request_signing",
        "desc": "HMAC request signing (Stripe / AWS Sig V4 pattern)",
    },
    "add_sms_otp": {"mod": "add_sms_otp", "desc": "SMS OTP via Twilio / Vonage with rate limits"},
    "add_social_login": {
        "mod": "add_social_login",
        "desc": "Google / GitHub / Apple OAuth2 social login",
    },
}

PRIMITIVES: dict[str, str] = {
    # name → one-line purpose (from registry)
    "AuthorizationCodeFlow": "OAuth 2.0 auth-code grant with PKCE, state, nonce enforcement",
    "CurrentPrincipal": "Read-only authenticated identity for the active request",
    "FeatureFlagCache": "Bounded async LRU cache with per-entry TTL for flag payloads",
    "RequestGuard": "Declarative authorization decision point per route, audited",
    "SessionStore": "Issue / rotate / revoke server-side session records",
    "TokenIntrospector": "Validate access tokens by signature / issuer / audience / expiry",
    "TotpVerifier": "TOTP per RFC 6238 with constant-time comparison",
    "WebAuthnAuthenticator": "WebAuthn / passkey register + assert with binding",
}

# Curated "bundle" — the eight most-composed slices for a new project.
# Chosen to deliver "production auth out of the box": core token handling,
# session management, MFA, RBAC, rate limiting, and audit surface.
BUNDLE_SLICES: tuple[str, ...] = (
    "add_oauth2",  # tokens + session store
    "add_rbac",  # RequestGuard + CurrentPrincipal
    "add_mfa",  # TotpVerifier second factor
    "add_api_key_auth",  # API key alongside JWT
    "add_bola_guard",  # object-level auth
    "add_request_signing",  # outgoing + incoming HMAC
    "add_feature_flags",  # per-user / per-tenant toggles
    "add_multi_tenancy",  # tenant scoping middleware
)


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
        "preservation on node kill'. Pass params={'force': True} to "
        "overwrite an existing target (default is non-destructive: "
        "returns status='skipped' when the target already has files).\n"
        "Call with action='list' if unsure which level to use. Every "
        "return carries `next_steps` pointing at the next likely call."
    ),
    "tags": ["auth", "domain", "dispatcher"],
    "annotations": {"readOnlyHint": False, "destructiveHint": False},
    "entry": "fastapi_auth",
}


def _toolinput_factory(**kwargs):
    """Lazily import adapt.contracts.ToolInput (keeps action='list' pydantic-free)."""
    from adapt.contracts import ToolInput

    return ToolInput(**kwargs)


_CONFIG = DomainTreeConfig(
    domain="auth",
    tool_name="fastapi_auth",
    tool_meta=MCP_TOOL,
    slices=SLICES,
    primitives=PRIMITIVES,
    bundle_slices=BUNDLE_SLICES,
    list_summary="auth domain tree (1 bundle + 15 slices + 8 primitives)",
    venous_dir=VENOUS_AUTH,
    adapters_dir=ADAPTERS_FASTAPI,
    default_pkg=AUTH_PKG,  # auth single-pkg: slices carry no per-slice `pkg`
    toolinput_factory=_toolinput_factory,
    bundle_success_next_steps=(
        "Bundle complete. Boot: `uvicorn app.main:app`, then POST /auth/login.",
        "For advanced flows (social, passkey, DPoP), call the individual add_* slices.",
        "Call fastapi_meta_audit() to verify the contract.",
    ),
    slice_success_next_steps=(
        "Boot the emitted app + hit the new endpoints to verify.",
        "Additional auth features? call fastapi_auth(action='list') for more slices.",
        "Need a primitive surgically? fastapi_auth(action='primitive', name=...).",
    ),
    primitive_missing_args_next_steps=(
        "Example: fastapi_auth(action='primitive', name='SessionStore', output_dir='/tmp/app').",
        "Call fastapi_auth(action='list') to see available primitive names.",
    ),
    list_usage_examples=(
        "fastapi_auth(action='bundle', params={'output_dir':'/tmp/my-app'})",
        "fastapi_auth(action='add_oauth2', params={'output_dir':'/tmp/my-app','providers':['google']})",
        "fastapi_auth(action='primitive', params={'name':'SessionStore','output_dir':'/tmp/my-app'})",
    ),
)

fastapi_auth = make_dispatcher(_CONFIG)
