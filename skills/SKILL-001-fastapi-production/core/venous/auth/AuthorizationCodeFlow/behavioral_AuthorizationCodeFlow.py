"""Behavioral end-to-end scenarios for AuthorizationCodeFlow.

Each scenario exercises a realistic interaction with an OAuth 2.1 /
OpenID Connect authorization server and PROVES one or more catalog
invariants at runtime.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from AuthorizationCodeFlow import (
    InvalidGrantError,
    InvalidStateError,
    ProviderMetadata,
    create_flow,
)

_PROVIDER = ProviderMetadata(
    authorization_endpoint="https://op.example/authorize",
    token_endpoint="https://op.example/token",
    jwks_uri="https://op.example/jwks",
    code_challenge_methods_supported=("S256",),
)


def _ok_token(_req: Mapping[str, str]) -> Mapping[str, object]:
    return {
        "access_token": "access-opaque-xyz",
        "refresh_token": "refresh-opaque-xyz",
        "id_token": "id.jwt.payload",
        "token_type": "Bearer",
        "expires_in": 3600,
        "scope": "openid profile",
    }


def _make_flow(**kwargs: Any) -> Any:
    return create_flow(
        client_id="c-ACME",
        redirect_uri="https://client.example/callback",
        provider=_PROVIDER,
        token_endpoint=kwargs.pop("token_endpoint", _ok_token),
        audit_sink=kwargs.pop("audit_sink", None),
        code_ttl_seconds=kwargs.pop("code_ttl_seconds", 600.0),
    )


def test_scenario_happy_path_login_with_pkce() -> None:
    flow = _make_flow()
    req = flow.begin(scopes=["openid", "profile"])

    parsed = urlparse(req.authorization_url)
    params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
    assert params["response_type"] == "code"
    assert params["client_id"] == "c-ACME"
    assert params["code_challenge_method"] == "S256"
    assert params["state"] == req.state
    assert params["nonce"] == req.nonce

    resp = flow.exchange(code="server-issued-code", state=req.state, stored=req)
    assert resp["access_token"] == "access-opaque-xyz"
    assert resp["token_type"] == "Bearer"


def test_scenario_state_tampering_aborts_before_token_endpoint() -> None:
    hits: list[int] = []

    def would_be_called(_req: Mapping[str, str]) -> Mapping[str, object]:
        hits.append(1)
        return _ok_token(_req)

    flow = _make_flow(token_endpoint=would_be_called)
    req = flow.begin(scopes=["openid"])
    with pytest.raises(InvalidStateError):
        # Attacker-crafted state matches nothing we ever issued.
        flow.exchange(code="c", state="evil-state", stored=req)
    assert hits == []


def test_scenario_replay_of_authorization_code_is_rejected() -> None:
    flow = _make_flow()
    req = flow.begin(scopes=["openid"])
    flow.exchange(code="single-shot", state=req.state, stored=req)

    req2 = flow.begin(scopes=["openid"])
    with pytest.raises(InvalidGrantError):
        flow.exchange(code="single-shot", state=req2.state, stored=req2)


def test_scenario_expired_code_rejected_with_invalid_grant() -> None:
    clock_val = {"t": 0.0}

    def frozen_clock() -> float:
        return clock_val["t"]

    from AuthorizationCodeFlow import ReferenceAuthorizationCodeFlow
    flow = ReferenceAuthorizationCodeFlow(
        client_id="c",
        redirect_uri="https://client.example/callback",
        provider=_PROVIDER,
        token_endpoint=_ok_token,
        code_ttl_seconds=60.0,
        clock=frozen_clock,
    )
    req = flow.begin(scopes=["openid"])
    clock_val["t"] = 61.0  # advance past TTL
    with pytest.raises(InvalidGrantError):
        flow.exchange(code="c", state=req.state, stored=req)


def test_scenario_provider_error_surfaces_as_invalid_grant() -> None:
    def angry_token(_req: Mapping[str, str]) -> Mapping[str, object]:
        return {"error": "invalid_grant", "error_description": "code rejected by AS"}

    flow = _make_flow(token_endpoint=angry_token)
    req = flow.begin(scopes=["openid"])
    with pytest.raises(InvalidGrantError):
        flow.exchange(code="c", state=req.state, stored=req)


def test_scenario_audit_trace_never_contains_plaintext_tokens() -> None:
    captured: list[Mapping[str, object]] = []

    def sink(e: Mapping[str, object]) -> None:
        captured.append(e)

    flow = _make_flow(audit_sink=sink)
    req = flow.begin(scopes=["openid"])
    flow.exchange(code="c", state=req.state, stored=req)

    # No event string representation ever contains the plaintext access token.
    for e in captured:
        s = str(e)
        assert "access-opaque-xyz" not in s
        assert "refresh-opaque-xyz" not in s
        assert "id.jwt.payload" not in s
