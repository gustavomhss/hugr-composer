"""B0.13 honesty test for ``extend/infrastructure/add_stripe_subscription``.

Closes the B0.13 ``_WAIVED_TOOLS`` entry for this tool. The tool's
``ToolResult(notes=…)`` carries a single claim-bearing line:

    "POST /subscriptions/webhook/stripe (signature-verified via
    stripe.Webhook.construct_event)."

The claim token matched by B0.13 is ``"verified"``. This module ships
a paired honesty test whose name references the claim so the rule
recognises it as covered (per the rule's fuzzy-match contract: any
``def test_*`` whose name OR docstring contains the claim token
counts).

Pair test path: ``engine/tests/test_<tool>_notes_invariants.py`` —
matches ``_PAIR_TEST_PATTERNS[0]`` in ``r_notes_match_behaviour``.

What we actually assert
=======================

Per the briefing's "option (a)" — AST checks against the EMITTED
template (the file written into user projects), plus a structural
check against the framework-side adapter wrapper that the route
delegates to:

1. ``test_webhook_signature_verified_calls_construct_webhook_event``
   — the emitted route module
   ``subscriptions_routes.py.tmpl`` contains an ``async def
   stripe_webhook(...)`` whose body calls
   ``billing.construct_webhook_event(...)``. The claim token
   ``"verified"`` appears in the test name so B0.13's fuzzy matcher
   recognises this as paired evidence.
2. ``test_webhook_signature_verified_raises_400_on_failure`` — the
   verification call is wrapped in ``try/except`` that re-raises as
   ``HTTPException(status_code=status.HTTP_400_BAD_REQUEST, ...)``.
   This is the runtime shape of the claim: a forged signature MUST
   land on the 400 branch, never on the event-dispatch branch.
3. ``test_webhook_signature_verified_adapter_wraps_stripe_construct_event``
   — the BillingAdapter the helper instantiates actually delegates
   to ``stripe.Webhook.construct_event(...)``. Without this anchor
   the route could call a ``construct_webhook_event`` that is itself
   a no-op; we follow the call one hop down so the notes claim is
   anchored to the SDK primitive it advertises.

We deliberately do NOT exec the route template (it imports
``app.api.deps`` which doesn't exist outside an emitted project).
AST inspection is sufficient — the rule documents AST-style honesty
tests as the supported shape.

Bypass surface declared (per WP-16 §13)
=======================================

* The test name carries ``"verified"`` so the B0.13 fuzzy matcher
  treats every assertion in the file as covering the "verified"
  claim. A future tool that adds a new claim token (e.g.
  ``"signed"``) to this tool's notes WILL fail the rule until a
  pair test referencing the new token lands — that's intentional
  (per-claim coverage is the contract).
* Template AST is parsed after stripping the (non-existent) jinja
  placeholders. The Stripe templates use no ``${name}`` holes so
  the cleanup is a no-op; we keep the helper for parity with the
  other pair-test modules in this directory.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent.parent
sys.path.insert(0, str(SKILL_ROOT))

TOOL_DIR = (
    SKILL_ROOT
    / "adapt"
    / "extend"
    / "infrastructure"
    / "add_stripe_subscription"
)
ROUTES_TMPL = TOOL_DIR / "templates" / "subscriptions_routes.py.tmpl"
ADAPTER_PY = (
    SKILL_ROOT
    / "core"
    / "venous"
    / "_adapters"
    / "stripe"
    / "BillingAdapter.py"
)


# ---------------------------------------------------------------------------
# Placeholder cleanup — symmetrical with the rule scanner; templates
# under this tool use no placeholders but the helper keeps the
# pattern consistent with sibling pair-test modules.
# ---------------------------------------------------------------------------

_PLACEHOLDER_BRACED_RE = re.compile(r"\$\{[^}]+\}")
_PLACEHOLDER_BARE_RE = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*")


def _clean(src: str) -> str:
    src = _PLACEHOLDER_BRACED_RE.sub("PLACEHOLDER", src)
    src = _PLACEHOLDER_BARE_RE.sub("PLACEHOLDER", src)
    return src


def _parse_template(path: Path) -> ast.Module:
    return ast.parse(_clean(path.read_text(encoding="utf-8")))


def _find_async_func(tree: ast.Module, name: str) -> ast.AsyncFunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            return node
    raise AssertionError(f"async def {name}(...) not found in template")


def _calls(node: ast.AST) -> list[ast.Call]:
    return [n for n in ast.walk(node) if isinstance(n, ast.Call)]


def _attr_chain(call: ast.Call) -> str:
    """Best-effort ``a.b.c`` rendering of ``call.func`` for matching."""
    parts: list[str] = []
    cur: ast.AST | None = call.func
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    return ".".join(reversed(parts))


# ---------------------------------------------------------------------------
# B0.13 — paired honesty evidence for the "verified" claim.
# ---------------------------------------------------------------------------


def test_webhook_signature_verified_calls_construct_webhook_event() -> None:
    """Notes claim *signature-verified via stripe.Webhook.construct_event*
    is matched by the route: the emitted ``stripe_webhook`` handler
    calls ``billing.construct_webhook_event(payload, sig_header)``.

    The route is the user-visible attack surface; if it doesn't call
    the verifier, "signature-verified" is a lie regardless of what
    the adapter does.
    """
    tree = _parse_template(ROUTES_TMPL)
    handler = _find_async_func(tree, "stripe_webhook")

    matching_calls = [
        c for c in _calls(handler)
        if _attr_chain(c).endswith("construct_webhook_event")
    ]
    assert matching_calls, (
        "stripe_webhook handler MUST call `*.construct_webhook_event(...)` "
        "— this is the path that verifies the Stripe-Signature header. "
        "Notes line claims `signature-verified`; without this call the "
        "claim is structurally false."
    )

    # Sanity: payload + sig_header are passed in (positional, in that
    # order, mirroring the BillingAdapter signature).
    call = matching_calls[0]
    assert len(call.args) >= 2, (
        "construct_webhook_event MUST receive (payload, sig_header) — the "
        "two positional arguments that drive HMAC-SHA256 verification."
    )


def test_webhook_signature_verified_raises_400_on_failure() -> None:
    """Notes claim "verified" implies forged-signature rejection.

    The route MUST wrap ``construct_webhook_event`` in ``try/except``
    that re-raises as ``HTTPException(status_code=400, ...)`` —
    silently swallowing the exception (or returning ``{received: True}``
    on failure) would invert the security claim and is the B0.16-style
    silent-fail pattern this honesty test exists to block.
    """
    tree = _parse_template(ROUTES_TMPL)
    handler = _find_async_func(tree, "stripe_webhook")

    # Find a Try block in the handler whose body calls
    # construct_webhook_event AND whose handler raises HTTPException.
    found = False
    for node in ast.walk(handler):
        if not isinstance(node, ast.Try):
            continue
        body_calls_verify = any(
            _attr_chain(c).endswith("construct_webhook_event")
            for c in _calls(ast.Module(body=node.body, type_ignores=[]))
        )
        if not body_calls_verify:
            continue
        for h in node.handlers:
            for stmt in ast.walk(h):
                if isinstance(stmt, ast.Raise) and isinstance(stmt.exc, ast.Call):
                    fn = _attr_chain(stmt.exc)
                    if fn.endswith("HTTPException"):
                        # Look for status_code=400 (constant or
                        # status.HTTP_400_BAD_REQUEST).
                        for kw in stmt.exc.keywords:
                            if kw.arg != "status_code":
                                continue
                            v = kw.value
                            if isinstance(v, ast.Constant) and v.value == 400:
                                found = True
                            if (
                                isinstance(v, ast.Attribute)
                                and v.attr == "HTTP_400_BAD_REQUEST"
                            ):
                                found = True
        if found:
            break

    assert found, (
        "stripe_webhook MUST wrap construct_webhook_event() in try/except "
        "that re-raises HTTPException(status_code=400). Without the 400 "
        "branch, a forged Stripe-Signature header reaches the event "
        "dispatcher and the `signature-verified` notes claim is false."
    )


def test_webhook_signature_verified_adapter_wraps_stripe_construct_event() -> None:
    """The notes line names ``stripe.Webhook.construct_event`` by name.

    Follow the call one hop down: the BillingAdapter the helper
    instantiates MUST itself call ``stripe.Webhook.construct_event``.
    This anchors the claim to the SDK primitive — without it the route
    could be calling an adapter method that itself no-ops on
    verification.
    """
    tree = ast.parse(ADAPTER_PY.read_text(encoding="utf-8"))

    method: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == "construct_webhook_event":
                method = node
                break
    assert method is not None, (
        "StripeBillingAdapter MUST define `construct_webhook_event` — this "
        "is the wrapper the route delegates to."
    )

    delegates = [
        c for c in _calls(method)
        if _attr_chain(c).endswith("Webhook.construct_event")
        or _attr_chain(c).endswith("stripe.Webhook.construct_event")
    ]
    assert delegates, (
        "StripeBillingAdapter.construct_webhook_event MUST call "
        "`stripe.Webhook.construct_event(...)` — without this hop the "
        "notes claim referencing `stripe.Webhook.construct_event` is "
        "false at the framework boundary."
    )


def test_b0_13_waiver_removed() -> None:
    """The B0.13 waiver entry MUST be removed from ``_WAIVED_TOOLS``."""
    from engine.audit.contract_rules.r_notes_match_behaviour import (
        _WAIVED_TOOLS,
    )

    assert "extend/infrastructure/add_stripe_subscription" not in _WAIVED_TOOLS, (
        "B0.13 waiver entry for add_stripe_subscription was NOT removed; "
        "the pair test is meaningless if the rule still skips the tool."
    )


# ---------------------------------------------------------------------------
# B0.14 — write schemas declare extra="forbid" (R6-O3-P10 closure).
# Co-located with the B0.13 pair test because both close the same
# Wave-2 fix-PR for the same tool; keeping the assertions in one
# regression module makes future "did anyone undo this?" auditing a
# single-file grep.
# ---------------------------------------------------------------------------


SCHEMAS_TMPL = TOOL_DIR / "templates" / "subscription_schemas.py.tmpl"


def _exec_schemas_template() -> dict:
    """Exec the schemas template into a fresh namespace.

    Templates use no placeholders here, but the cleanup helper is
    applied for parity with the rule-side scanner.
    """
    src = _clean(SCHEMAS_TMPL.read_text(encoding="utf-8"))
    ns: dict = {"__name__": "under_test_subscription_schemas"}
    exec(compile(src, str(SCHEMAS_TMPL), "exec"), ns)  # noqa: S102 — exec is the test
    return ns


def test_b0_14_subscription_create_rejects_unknown_keys() -> None:
    """B0.14 (Pattern P5 / R6-O3-P10): ``SubscriptionCreate`` MUST reject
    unknown keys — this is the mass-assignment / key-smuggling defence
    on the Stripe billing input boundary. Pre-fix the schema lacked
    ``extra="forbid"`` and silently accepted any extra key (the
    catalog-wide cluster P5 surface).
    """
    import pytest
    from pydantic import ValidationError

    ns = _exec_schemas_template()
    SubscriptionCreate = ns["SubscriptionCreate"]

    # Sanity: valid payload accepted.
    ok = SubscriptionCreate(price_id="price_abc")
    assert ok.price_id == "price_abc"

    # Core assertion: smuggled key MUST raise.
    with pytest.raises(ValidationError):
        SubscriptionCreate(
            price_id="price_abc",
            user_id="ATTACKER-OVERRIDES-OWNER",  # smuggled key
        )


def test_b0_14_change_plan_request_rejects_unknown_keys() -> None:
    """B0.14: ``ChangePlanRequest`` MUST reject unknown keys. The
    sibling input boundary for ``POST /subscriptions/{id}/change-plan``
    carries the same mass-assignment surface; pre-fix it lacked
    ``extra="forbid"`` so an attacker could smuggle proration toggles
    / subscription_id overrides through the request body.
    """
    import pytest
    from pydantic import ValidationError

    ns = _exec_schemas_template()
    ChangePlanRequest = ns["ChangePlanRequest"]

    ok = ChangePlanRequest(new_price_id="price_xyz")
    assert ok.new_price_id == "price_xyz"

    with pytest.raises(ValidationError):
        ChangePlanRequest(new_price_id="price_xyz", subscription_id="other")


def test_b0_14_waiver_removed() -> None:
    """The B0.14 waiver entry MUST be removed from ``_WAIVED_TOOLS``."""
    from engine.audit.contract_rules.r_write_schemas_strict import _WAIVED_TOOLS

    assert "add_stripe_subscription" not in _WAIVED_TOOLS, (
        "B0.14 waiver entry for add_stripe_subscription was NOT removed; "
        "the fix is meaningless if the rule still skips the template."
    )
