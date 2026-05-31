"""B0.13 honesty test for ``extend/auth_access/add_social_login``.

Closes the B0.13 ``_WAIVED_TOOLS`` entry for this tool. The
``ToolResult(notes=…)`` carries a claim-bearing line referencing
verified Apple id_token signatures:

    "Apple id_token RS256 signature verified against
     appleid.apple.com/auth/keys JWKS (cached 1h); iss/aud/exp claims
     enforced."

The B0.13 claim token matched is ``"verified"``. PR #91 / R5-O4-C2
fixed the underlying implementation — the prior version base64-decoded
the payload with no signature check. This module ships a paired
honesty test that AST-anchors the verified-shape against
``social_auth.py.tmpl`` so the fix cannot silently regress.

What we actually assert
=======================

* ``test_apple_id_token_signature_is_verified_end_to_end`` — the
  call chain ``_verify_apple_id_token → _select_apple_jwk →
  _decode_apple_id_token`` exists and is structurally wired (the
  outer function calls the JWK selector AND the decoder).
* ``test_apple_id_token_decoded_with_pyjwt_rs256_verify`` —
  ``_decode_apple_id_token`` calls ``jwt.decode(id_token,
  public_key, algorithms=["RS256"], audience=..., issuer=...,
  options={"require": [...]})``. PyJWT verifies the signature
  unconditionally when called with a key + algorithms list; the
  presence of ``options={"require": [...]}`` anchors registered-
  claim enforcement.
* ``test_apple_jwk_loaded_via_pyjwt_rsa_algorithm_from_jwk`` —
  ``_select_apple_jwk`` calls ``RSAAlgorithm.from_jwk(...)`` to
  materialise the public key from the matching JWKS entry. This is
  the boundary where a real PyJWK-equivalent loader is wired.
* ``test_apple_audience_refuses_empty_client_id`` —
  ``_decode_apple_id_token`` raises ``ValueError`` when
  ``APPLE_CLIENT_ID`` is empty. Without this, ``jwt.decode`` would
  accept any audience and the "verified" claim would be a lie when
  the operator forgets to configure the env var.

We deliberately do NOT execute the template directly (it imports
``app.core.config`` which only exists inside an emitted project).
The companion adapter-side behavioural test lives at
``adapt/extend/auth_access/test_add_social_login_apple_jwt.py``;
this pair test is the engine-level structural anchor B0.13's rule
contract requires.

Bypass surface declared (per WP-16 §13)
=======================================

* The "verified" token is matched by every test name in this file —
  the rule's fuzzy matcher counts function-name OR docstring
  substring as coverage, so even partial regressions to the
  signature-verification shape keep B0.13 evidence in place. The
  REAL regression guard is the structural ``jwt.decode`` shape
  assertion; the name-based bypass is a contract-level affordance.
* AST inspection only — a vacuous helper that wraps ``jwt.decode``
  but discards its result would not be caught by name-matching the
  call; it WOULD be caught by the adapter-side behavioural tests
  that round-trip a real signed token. The two layers complement.
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
    / "auth_access"
    / "add_social_login"
)
SOCIAL_AUTH_TMPL = TOOL_DIR / "templates" / "social_auth.py.tmpl"


# ---------------------------------------------------------------------------
# Placeholder cleanup — symmetrical with the rule scanner.
# ---------------------------------------------------------------------------

_PLACEHOLDER_BRACED_RE = re.compile(r"\$\{[^}]+\}")
_PLACEHOLDER_BARE_RE = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*")


def _clean(src: str) -> str:
    src = _PLACEHOLDER_BRACED_RE.sub("PLACEHOLDER", src)
    src = _PLACEHOLDER_BARE_RE.sub("PLACEHOLDER", src)
    return src


def _parse_template(path: Path) -> ast.Module:
    return ast.parse(_clean(path.read_text(encoding="utf-8")))


def _find_func(
    tree: ast.Module, name: str
) -> ast.FunctionDef | ast.AsyncFunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"def {name}(...) not found in template")


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
# B0.13 — paired honesty evidence for the "verified" claim.
# ---------------------------------------------------------------------------


def test_apple_id_token_signature_is_verified_end_to_end() -> None:
    """The notes claim ``"Apple id_token RS256 signature verified"`` is
    structurally wired: ``_verify_apple_id_token`` chains JWKS fetch
    → JWK selection → decode (which verifies)."""
    tree = _parse_template(SOCIAL_AUTH_TMPL)
    verifier = _find_func(tree, "_verify_apple_id_token")

    chain_names = {_attr_chain(c).split(".")[-1] for c in _calls(verifier)}
    for expected in ("_fetch_apple_jwks", "_select_apple_jwk", "_decode_apple_id_token"):
        assert expected in chain_names, (
            f"`_verify_apple_id_token` MUST call `{expected}(...)` — without "
            "this hop the verification chain is short-circuited and the "
            "`verified` notes claim is structurally false."
        )


def test_apple_id_token_decoded_with_pyjwt_rs256_verify() -> None:
    """The notes claim names PyJWT verification + iss/aud/exp enforcement.
    ``_decode_apple_id_token`` MUST call ``jwt.decode(id_token,
    public_key, algorithms=["RS256"], audience=..., issuer=...,
    options={"require": [...]})``."""
    tree = _parse_template(SOCIAL_AUTH_TMPL)
    decoder = _find_func(tree, "_decode_apple_id_token")

    decode_calls = [
        c for c in _calls(decoder) if _attr_chain(c).endswith("jwt.decode")
    ]
    assert decode_calls, (
        "`_decode_apple_id_token` MUST call `jwt.decode(...)` — PyJWT is "
        "what performs the RS256 signature verification."
    )

    call = decode_calls[0]
    # Positional args: (id_token, public_key)
    assert len(call.args) >= 2, (
        "jwt.decode MUST receive (id_token, public_key) as the first two "
        "positional args — without a key, PyJWT silently skips signature "
        "verification and the claim becomes a lie."
    )

    kwargs = {kw.arg: kw.value for kw in call.keywords}

    # algorithms=["RS256"]
    algorithms = kwargs.get("algorithms")
    assert isinstance(algorithms, ast.List), (
        "jwt.decode MUST be called with `algorithms=[...]` — without it "
        "PyJWT either guesses (older) or refuses (newer) and the "
        "signature-verification surface changes from under us."
    )
    alg_values = {
        el.value for el in algorithms.elts
        if isinstance(el, ast.Constant) and isinstance(el.value, str)
    }
    assert "RS256" in alg_values, (
        "jwt.decode `algorithms` MUST include `RS256` — Apple signs "
        "id_tokens with RS256; any other algorithm is the alg-confusion "
        "attack surface PyJWT explicitly guards against."
    )
    assert "none" not in {a.lower() for a in alg_values}, (
        "jwt.decode `algorithms` MUST NOT include `none` — that is the "
        "PyJWT-CVE-2015-2951 alg-stripping attack the verified claim "
        "exists to prevent."
    )

    # audience kwarg present
    assert "audience" in kwargs, (
        "jwt.decode MUST be called with `audience=...` — without it the "
        "`aud` claim is not enforced and any other Apple-issued id_token "
        "(e.g. from a different client app) would pass."
    )
    # issuer kwarg present
    assert "issuer" in kwargs, (
        "jwt.decode MUST be called with `issuer=...` — without it the "
        "`iss` claim is not enforced and a forged-issuer token would pass."
    )
    # options={"require": [...]} present
    options = kwargs.get("options")
    assert isinstance(options, ast.Dict), (
        "jwt.decode MUST be called with `options={...}` enforcing required "
        "claims; the notes line advertises iss/aud/exp enforcement."
    )
    require_present = False
    for k, v in zip(options.keys, options.values, strict=False):
        if isinstance(k, ast.Constant) and k.value == "require" and isinstance(v, ast.List):
            required = {
                el.value for el in v.elts
                if isinstance(el, ast.Constant)
            }
            for must_have in ("exp", "iss", "aud", "sub"):
                assert must_have in required, (
                    f"jwt.decode `options['require']` MUST include `{must_have}` "
                    "— the notes line advertises that claim is enforced."
                )
            require_present = True
            break
    assert require_present, (
        "jwt.decode `options` MUST contain a `require` key listing the "
        "mandatory claims; without it PyJWT defaults to permissive."
    )


def test_apple_jwk_loaded_via_pyjwt_rsa_algorithm_from_jwk() -> None:
    """The verified claim names Apple's JWKS by URL — the JWK loader
    MUST call ``RSAAlgorithm.from_jwk(...)`` to materialise the
    public key for ``jwt.decode``."""
    tree = _parse_template(SOCIAL_AUTH_TMPL)
    selector = _find_func(tree, "_select_apple_jwk")

    from_jwk_calls = [
        c for c in _calls(selector)
        if _attr_chain(c).endswith("RSAAlgorithm.from_jwk")
        or _attr_chain(c).endswith("from_jwk")
    ]
    assert from_jwk_calls, (
        "`_select_apple_jwk` MUST call `RSAAlgorithm.from_jwk(...)` — "
        "this is the bridge from Apple's published JWK dict to a "
        "PyJWT-compatible key object."
    )


def test_apple_audience_refuses_empty_client_id() -> None:
    """The notes claim ``"Requires APPLE_CLIENT_ID to be set (callback
    refuses to verify without an audience)."`` — ``_decode_apple_id_token``
    raises ``ValueError`` when the configured audience is empty.

    Without this guard, PyJWT would happily verify any audience and the
    "verified" claim becomes vacuous in mis-configured deployments.
    """
    tree = _parse_template(SOCIAL_AUTH_TMPL)
    decoder = _find_func(tree, "_decode_apple_id_token")

    # Find a Raise(ValueError(...)) somewhere in the function whose
    # message mentions APPLE_CLIENT_ID or audience.
    found = False
    for node in ast.walk(decoder):
        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            if _attr_chain(node.exc).endswith("ValueError"):
                # Inspect the message string.
                if node.exc.args and isinstance(node.exc.args[0], ast.Constant):
                    msg = str(node.exc.args[0].value).lower()
                    if "apple_client_id" in msg or "audience" in msg:
                        found = True
                        break
    assert found, (
        "`_decode_apple_id_token` MUST raise `ValueError` mentioning "
        "APPLE_CLIENT_ID or audience when the configured audience is "
        "empty — without this guard the verified claim is false in "
        "mis-configured deployments."
    )


def test_b0_13_waiver_removed() -> None:
    """The B0.13 waiver entry MUST be removed from ``_WAIVED_TOOLS``."""
    from engine.audit.contract_rules.r_notes_match_behaviour import (
        _WAIVED_TOOLS,
    )

    assert "extend/auth_access/add_social_login" not in _WAIVED_TOOLS, (
        "B0.13 waiver entry for add_social_login was NOT removed; "
        "the pair test is meaningless if the rule still skips the tool."
    )
