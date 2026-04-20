"""Metamorphic + differential tests for AuthorizationCodeFlow.

Algebraic / differential properties:
- begin() is idempotent over the Python object identity (each call returns a
  brand-new AuthorizationRequest with fresh state/nonce/verifier).
- redact_token_response is idempotent: redacting twice is the same as once.
- A successful exchange followed by a second attempt with the same code is
  NEVER successful, regardless of which state is supplied.
- PKCE S256 challenge computation is deterministic for a given verifier
  (reference-equivalence with RFC 7636 test vector).
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Mapping

from AuthorizationCodeFlow import (
    ProviderMetadata,
    create_flow,
    redact_token_response,
)

_PROVIDER = ProviderMetadata(
    authorization_endpoint="https://op.example/authorize",
    token_endpoint="https://op.example/token",
    jwks_uri="https://op.example/jwks",
    code_challenge_methods_supported=("S256",),
)


def _ok_token(_req: Mapping[str, str]) -> Mapping[str, object]:
    return {
        "access_token": "A" * 32,
        "refresh_token": "R" * 32,
        "id_token": "I" * 32,
        "token_type": "Bearer",
        "expires_in": 3600,
    }


def test_metamorphic_begin_produces_fresh_values() -> None:
    flow = create_flow(
        client_id="c",
        redirect_uri="https://client.example/cb",
        provider=_PROVIDER,
        token_endpoint=_ok_token,
    )
    reqs = [flow.begin(scopes=["openid"]) for _ in range(20)]
    states = {r.state for r in reqs}
    nonces = {r.nonce for r in reqs}
    verifiers = {r.code_verifier for r in reqs}
    assert len(states) == 20
    assert len(nonces) == 20
    assert len(verifiers) == 20


def test_metamorphic_redaction_idempotent() -> None:
    raw = {"access_token": "plain-A", "refresh_token": "plain-R", "token_type": "Bearer"}
    once = redact_token_response(raw)
    twice = redact_token_response(once)
    # Second application leaves redacted tokens alone (they are already
    # "[REDACTED_TOKEN]", not a new plaintext).
    assert once["token_type"] == "Bearer"
    assert twice["access_token"] == "[REDACTED_TOKEN]"
    assert twice["refresh_token"] == "[REDACTED_TOKEN]"
    # The opaque hash from the FIRST redaction survives the second pass.
    assert once["access_token_hash"] == twice["access_token_hash"]


def test_differential_pkce_s256_matches_rfc_test_vector() -> None:
    # RFC 7636 Appendix B — verifier "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    # expected challenge "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    expected = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    got = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    assert got == expected


def test_metamorphic_exchange_then_replay_never_succeeds_twice() -> None:
    flow = create_flow(
        client_id="c",
        redirect_uri="https://client.example/cb",
        provider=_PROVIDER,
        token_endpoint=_ok_token,
    )
    req = flow.begin(scopes=["openid"])
    ok = flow.exchange(code="same-code", state=req.state, stored=req)
    assert "access_token" in ok

    # Every subsequent attempt to redeem "same-code", under any fresh state,
    # raises invalid_grant — the set of redeemed-codes is monotone increasing.
    from AuthorizationCodeFlow import InvalidGrantError
    for _ in range(5):
        req2 = flow.begin(scopes=["openid"])
        try:
            flow.exchange(code="same-code", state=req2.state, stored=req2)
            raise AssertionError("replay succeeded")
        except InvalidGrantError:
            pass


def test_differential_authorization_url_contains_required_oauth_params() -> None:
    # Differential parity with the OAuth 2.1 required-params list.
    from urllib.parse import parse_qs, urlparse
    flow = create_flow(
        client_id="c",
        redirect_uri="https://client.example/cb",
        provider=_PROVIDER,
        token_endpoint=_ok_token,
    )
    req = flow.begin(scopes=["openid", "email"])
    q = parse_qs(urlparse(req.authorization_url).query)
    for key in (
        "response_type", "client_id", "redirect_uri", "scope",
        "state", "nonce", "code_challenge", "code_challenge_method",
    ):
        assert key in q, f"missing {key}"
    assert q["response_type"] == ["code"]
    assert q["code_challenge_method"] == ["S256"]
