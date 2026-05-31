"""B0.13 honesty test for ``extend/infrastructure/add_stripe_refund_flow``.

Closes the B0.13 ``_WAIVED_TOOLS`` entry for this tool. The tool's
``ToolResult(notes=…)`` carries the claim-bearing line::

    "POST /refunds/webhook/stripe (signature-verified)."

The matched B0.13 claim token is ``"verified"``. The honest reading:
the emitted route MUST call ``stripe.Webhook.construct_event`` (the
SDK primitive that performs HMAC-SHA256 signature verification with
the 5-minute replay tolerance window) AND MUST reject failures with
HTTP 4xx — silently swallowing the verification error would invert
the security claim.

Mirrors the pattern shipped for ``add_stripe_subscription`` in PR
#103: AST-anchor the route handler against the SDK call, NOT the
BillingAdapter wrapper, because the route is the user-visible attack
surface — if it doesn't invoke the verifier, "signature-verified" is
a lie regardless of what the adapter exposes.

Pair test path: ``engine/tests/test_<tool>_notes_invariants.py`` —
matches ``_PAIR_TEST_PATTERNS[0]``.

What we actually assert
=======================

1. ``test_refund_webhook_signature_verified_calls_construct_event``
   — the emitted ``stripe_refund_webhook`` handler in
   ``refunds_routes.py.tmpl`` MUST call
   ``stripe.Webhook.construct_event(payload, sig_header, secret)``.
   This is the load-bearing SDK call that performs HMAC verification.

2. ``test_refund_webhook_signature_verified_raises_400_on_failure``
   — the call MUST be wrapped in ``try/except`` that re-raises as
   ``HTTPException(status_code=400, ...)``. A naked ``except: pass``
   or a ``return {"received": True}`` in the except branch would
   silently accept forged webhooks (CWE-345) and invert the claim —
   this is the B0.16-style silent-fail pattern the honesty test
   exists to block.

3. ``test_refund_webhook_signature_verified_reads_stripe_signature_header``
   — the handler MUST read the ``stripe-signature`` header before
   the verify call; without it, ``construct_event`` is called with
   an empty signature and trivially fails (a backdoor route would
   skip the header read and feed the verifier a forged value).

4. ``test_b0_13_waiver_removed`` — the waiver entry MUST be gone
   from ``_WAIVED_TOOLS``.

Bypass surface declared
=======================

* AST-only inspection of ``refunds_routes.py.tmpl`` — no FastAPI
  app boot, no Stripe SDK install. The shape of the route
  handler is load-bearing.
* The Stripe SDK itself is trusted to implement ``construct_event``
  correctly (HMAC-SHA256 with 5-minute replay tolerance); we assert
  the *call exists with the right argument shape*, not the SDK's
  internals.
* The ``except Exception`` pattern is broad on purpose — the Stripe
  SDK raises both ``stripe.error.SignatureVerificationError`` and
  ``ValueError`` (malformed payload). Either MUST collapse to
  HTTPException(400); the test enforces that, not the exception
  class.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent.parent
sys.path.insert(0, str(SKILL_ROOT))

TOOL_DIR = SKILL_ROOT / "adapt" / "extend" / "infrastructure" / "add_stripe_refund_flow"
ROUTES_TMPL = TOOL_DIR / "templates" / "refunds_routes.py.tmpl"


# ---------------------------------------------------------------------------
# Placeholder cleanup — parity with sibling pair-test modules.
# ---------------------------------------------------------------------------

_PLACEHOLDER_BRACED_RE = re.compile(r"\$\{[^}]+\}")
_PLACEHOLDER_BARE_RE = re.compile(r"(?<![A-Za-z0-9_])\$[A-Za-z_][A-Za-z0-9_]*")


def _clean(src: str) -> str:
    src = _PLACEHOLDER_BRACED_RE.sub("PLACEHOLDER", src)
    src = _PLACEHOLDER_BARE_RE.sub("PLACEHOLDER", src)
    return src


def _parse(path: Path) -> ast.Module:
    return ast.parse(_clean(path.read_text(encoding="utf-8")))


def _find_async_func(tree: ast.Module, name: str) -> ast.AsyncFunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            return node
    raise AssertionError(f"async def {name}(...) not found in template")


def _calls(node: ast.AST) -> list[ast.Call]:
    return [n for n in ast.walk(node) if isinstance(n, ast.Call)]


def _attr_chain(call: ast.Call) -> str:
    parts: list[str] = []
    cur: ast.AST | None = call.func
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    return ".".join(reversed(parts))


# ---------------------------------------------------------------------------
# B0.13 — paired evidence for ``verified``.
# ---------------------------------------------------------------------------


def test_refund_webhook_signature_verified_calls_construct_event() -> None:
    """Notes claim "signature-verified" — the route MUST call
    ``stripe.Webhook.construct_event(payload, sig_header, secret)``.
    Without this call the verifier never runs and the claim is
    structurally false.
    """
    tree = _parse(ROUTES_TMPL)
    handler = _find_async_func(tree, "stripe_refund_webhook")

    matching_calls = [
        c for c in _calls(handler) if _attr_chain(c).endswith("construct_event")
    ]
    assert matching_calls, (
        "stripe_refund_webhook MUST call `stripe.Webhook.construct_event"
        "(payload, sig_header, secret)` — the SDK path that performs "
        "HMAC-SHA256 signature verification. Notes claim "
        "`signature-verified`; without this call the claim is false."
    )

    # Sanity: the call passes (payload, sig_header, secret) — three args.
    call = matching_calls[0]
    assert len(call.args) >= 3, (
        "stripe.Webhook.construct_event MUST receive (payload, "
        "sig_header, secret) — the three positional arguments that "
        "drive HMAC-SHA256 verification."
    )


def test_refund_webhook_signature_verified_raises_400_on_failure() -> None:
    """Notes claim ``verified`` implies forged-signature rejection.

    The route MUST wrap ``construct_event`` in ``try/except`` that
    re-raises as ``HTTPException(status_code=400, ...)`` — silently
    swallowing the exception (or returning ``{received: True}`` on
    failure) would invert the security claim and is the B0.16-style
    silent-fail pattern this honesty test exists to block.
    """
    tree = _parse(ROUTES_TMPL)
    handler = _find_async_func(tree, "stripe_refund_webhook")

    found = False
    for node in ast.walk(handler):
        if not isinstance(node, ast.Try):
            continue
        body_calls = [
            _attr_chain(c) for c in _calls(ast.Module(body=node.body, type_ignores=[]))
        ]
        if not any(name.endswith("construct_event") for name in body_calls):
            continue
        for hdlr in node.handlers:
            for sub in ast.walk(hdlr):
                if not isinstance(sub, ast.Raise) or sub.exc is None:
                    continue
                exc = sub.exc
                # `raise HTTPException(status_code=400, ...)` (with or
                # without `from exc`).
                if not isinstance(exc, ast.Call):
                    continue
                if not _attr_chain(exc).endswith("HTTPException"):
                    continue
                for kw in exc.keywords:
                    if kw.arg != "status_code":
                        continue
                    v = kw.value
                    if isinstance(v, ast.Constant) and v.value == 400:
                        found = True
                    # Accept `status.HTTP_400_BAD_REQUEST` as well.
                    if (
                        isinstance(v, ast.Attribute)
                        and v.attr == "HTTP_400_BAD_REQUEST"
                    ):
                        found = True
    assert found, (
        "stripe_refund_webhook MUST wrap construct_event in try/except "
        "that re-raises `HTTPException(status_code=400, ...)`. A silent "
        "swallow (`except: pass` or `return {received: True}`) would "
        "accept forged webhooks and invert the `verified` claim."
    )


def test_refund_webhook_signature_verified_reads_stripe_signature_header() -> None:
    """The handler MUST read the ``stripe-signature`` header before
    calling ``construct_event``. Without it, the verifier is called
    with an empty signature (which trivially fails) — but a future
    edit that skipped the header read and fed the verifier a forged
    body-derived value would defeat the claim.
    """
    tree = _parse(ROUTES_TMPL)
    handler = _find_async_func(tree, "stripe_refund_webhook")

    found = False
    for node in ast.walk(handler):
        if not isinstance(node, ast.Call):
            continue
        # request.headers.get("stripe-signature", ...) — _attr_chain
        # returns the trailing "get"; check the chain ends with
        # `headers.get`.
        chain = _attr_chain(node)
        if not chain.endswith("headers.get"):
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                if arg.value.lower() == "stripe-signature":
                    found = True
    assert found, (
        "stripe_refund_webhook MUST read the `stripe-signature` header "
        "via `request.headers.get(\"stripe-signature\", ...)` and pass "
        "it to construct_event. Without this read the verifier has no "
        "signature to validate against and the `verified` claim is "
        "structurally hollow."
    )


def test_b0_13_waiver_removed() -> None:
    """The B0.13 waiver entry for ``add_stripe_refund_flow`` MUST be gone."""
    from engine.audit.contract_rules.r_notes_match_behaviour import (
        _WAIVED_TOOLS,
    )

    assert "extend/infrastructure/add_stripe_refund_flow" not in _WAIVED_TOOLS, (
        "B0.13 waiver entry for add_stripe_refund_flow was NOT removed; "
        "the pair test is inert while the rule still skips the tool."
    )
