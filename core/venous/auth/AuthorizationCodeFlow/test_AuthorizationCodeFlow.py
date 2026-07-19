"""Unit tests for AuthorizationCodeFlow — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

import pytest
from AuthorizationCodeFlow import (
    InvalidGrantError,
    InvalidRedirectURIError,
    InvalidRequestError,
    InvalidStateError,
    ProviderMetadata,
    ReferenceAuthorizationCodeFlow,
    create_flow,
    redact_token_response,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
_PROVIDER = ProviderMetadata(
    authorization_endpoint="https://op.example/authorize",
    token_endpoint="https://op.example/token",
    jwks_uri="https://op.example/jwks",
    code_challenge_methods_supported=("S256",),
    issuer="https://op.example",
)


def _ok_token(_req: Mapping[str, str]) -> Mapping[str, object]:
    return {
        "access_token": "AT-XXXXXXXXXXXX",
        "refresh_token": "RT-XXXXXXXXXXXX",
        "id_token": "ID-XXXXXXXXXXXX",
        "token_type": "Bearer",
        "expires_in": 3600,
        "scope": "openid profile",
    }


def _make_flow(
    *,
    token_endpoint: Any = _ok_token,
    audit: Any = None,
    redirect_uri: str = "https://client.example/cb",
    code_ttl_seconds: float = 600.0,
) -> ReferenceAuthorizationCodeFlow:
    return create_flow(
        client_id="client-123",
        redirect_uri=redirect_uri,
        provider=_PROVIDER,
        token_endpoint=token_endpoint,
        audit_sink=audit,
        code_ttl_seconds=code_ttl_seconds,
    )


# ---------------------------------------------------------------------------
# ACF_INV_01 — CSPRNG entropy, no reuse
# ---------------------------------------------------------------------------
def test_inv_csprng_entropy_confirms() -> None:
    flow = _make_flow()
    req = flow.begin(scopes=["openid"])
    # 32 random bytes → base64url of ≥43 chars; easily ≥128-bit entropy.
    assert len(req.state) >= 43
    assert len(req.nonce) >= 43
    assert len(req.code_verifier) >= 43
    # state / nonce / verifier MUST be distinct under normal operation.
    assert len({req.state, req.nonce, req.code_verifier}) == 3


def test_inv_csprng_entropy_prevents() -> None:
    # An RNG that always returns a short buffer MUST be rejected; invariant
    # failure is enforced via the ByteLength check, even if the caller
    # supplies a deterministic RNG (which is itself a violation of the entropy
    # requirement).
    short_bytes = b"\x00" * 8  # only 64 bits — below the 128-bit floor.

    def short_rng(_n: int) -> bytes:
        return short_bytes

    flow = ReferenceAuthorizationCodeFlow(
        client_id="client-123",
        redirect_uri="https://client.example/cb",
        provider=_PROVIDER,
        token_endpoint=_ok_token,
        rng=short_rng,
    )
    with pytest.raises(InvalidRequestError):
        flow.begin(scopes=["openid"])


def test_inv_csprng_entropy_under_failure() -> None:
    # Even across 50 begin() calls, NO state/nonce/verifier is ever reused.
    flow = _make_flow()
    states: set[str] = set()
    nonces: set[str] = set()
    verifiers: set[str] = set()
    for _ in range(50):
        r = flow.begin(scopes=["openid"])
        assert r.state not in states
        assert r.nonce not in nonces
        assert r.code_verifier not in verifiers
        states.add(r.state)
        nonces.add(r.nonce)
        verifiers.add(r.code_verifier)


# ---------------------------------------------------------------------------
# ACF_INV_02 — state byte-equality, abort before token endpoint
# ---------------------------------------------------------------------------
def test_inv_state_equal_confirms() -> None:
    flow = _make_flow()
    req = flow.begin(scopes=["openid"])
    resp = flow.exchange(code="authcode-1", state=req.state, stored=req)
    assert resp["access_token"] == "AT-XXXXXXXXXXXX"


def test_inv_state_equal_prevents() -> None:
    # State that differs by even ONE byte is rejected before the endpoint runs.
    calls: list[int] = []

    def tracking_token(_req: Mapping[str, str]) -> Mapping[str, object]:
        calls.append(1)
        return _ok_token(_req)

    flow = _make_flow(token_endpoint=tracking_token)
    req = flow.begin(scopes=["openid"])
    wrong = req.state[:-1] + ("A" if req.state[-1] != "A" else "B")
    with pytest.raises(InvalidStateError):
        flow.exchange(code="authcode-1", state=wrong, stored=req)
    assert calls == []  # token endpoint MUST NOT have been called


def test_inv_state_equal_under_failure() -> None:
    # Repeated mismatches NEVER reach the token endpoint, across many attempts.
    calls: list[int] = []

    def counting(_req: Mapping[str, str]) -> Mapping[str, object]:
        calls.append(1)
        return _ok_token(_req)

    flow = _make_flow(token_endpoint=counting)
    req = flow.begin(scopes=["openid"])
    for i in range(25):
        with pytest.raises(InvalidStateError):
            flow.exchange(code=f"c-{i}", state="not-the-real-state", stored=req)
    assert calls == []


# ---------------------------------------------------------------------------
# ACF_INV_03 — code_verifier bound to request
# ---------------------------------------------------------------------------
def test_inv_pkce_bound_confirms() -> None:
    flow = _make_flow()
    req = flow.begin(scopes=["openid"])
    # exchange with the bound verifier succeeds.
    resp = flow.exchange(code="code-A", state=req.state, stored=req)
    assert "access_token" in resp


def test_inv_pkce_bound_prevents() -> None:
    flow = _make_flow()
    req = flow.begin(scopes=["openid"])
    # Replace the verifier in the stored request — must be rejected.
    tampered = replace(req, code_verifier="evil-attacker-verifier")
    with pytest.raises(InvalidGrantError):
        flow.exchange(code="code-A", state=req.state, stored=tampered)


def test_inv_pkce_bound_under_failure() -> None:
    # Provider that REFUSES to advertise S256 MUST be rejected at construction.
    bad_provider = ProviderMetadata(
        authorization_endpoint="https://op.example/authorize",
        token_endpoint="https://op.example/token",
        jwks_uri="https://op.example/jwks",
        code_challenge_methods_supported=("plain",),
    )
    with pytest.raises(InvalidRequestError):
        create_flow(
            client_id="c",
            redirect_uri="https://client.example/cb",
            provider=bad_provider,
            token_endpoint=_ok_token,
        )


# ---------------------------------------------------------------------------
# ACF_INV_04 — redirect URI exact match
# ---------------------------------------------------------------------------
def test_inv_redirect_exact_confirms() -> None:
    captured: list[Mapping[str, str]] = []

    def recording(req: Mapping[str, str]) -> Mapping[str, object]:
        captured.append(dict(req))
        return _ok_token(req)

    flow = _make_flow(token_endpoint=recording, redirect_uri="https://client.example/cb")
    req = flow.begin(scopes=["openid"])
    flow.exchange(code="c", state=req.state, stored=req)
    assert captured[0]["redirect_uri"] == "https://client.example/cb"


def test_inv_redirect_exact_prevents() -> None:
    # Wildcard redirect URIs are FORBIDDEN at construction.
    with pytest.raises(InvalidRedirectURIError):
        create_flow(
            client_id="c",
            redirect_uri="https://client.example/*",
            provider=_PROVIDER,
            token_endpoint=_ok_token,
        )


def test_inv_redirect_exact_under_failure() -> None:
    # The registered redirect_uri NEVER morphs between begin and exchange.
    seen: list[str] = []

    def recording(req: Mapping[str, str]) -> Mapping[str, object]:
        seen.append(req["redirect_uri"])
        return _ok_token(req)

    flow = _make_flow(token_endpoint=recording, redirect_uri="https://client.example/cb")
    for i in range(5):
        r = flow.begin(scopes=["openid"])
        flow.exchange(code=f"c-{i}", state=r.state, stored=r)
    assert all(s == "https://client.example/cb" for s in seen)


# ---------------------------------------------------------------------------
# ACF_INV_05 — single-use codes
# ---------------------------------------------------------------------------
def test_inv_code_single_use_confirms() -> None:
    flow = _make_flow()
    req = flow.begin(scopes=["openid"])
    resp = flow.exchange(code="once", state=req.state, stored=req)
    assert resp["token_type"] == "Bearer"
    assert flow.redeemed_count == 1


def test_inv_code_single_use_prevents() -> None:
    flow = _make_flow()
    req = flow.begin(scopes=["openid"])
    flow.exchange(code="replay-me", state=req.state, stored=req)
    # Second redemption attempt raises invalid_grant.
    with pytest.raises(InvalidGrantError):
        # Need a NEW authorization request or the state would be burned too.
        req2 = flow.begin(scopes=["openid"])
        flow.exchange(code="replay-me", state=req2.state, stored=req2)


def test_inv_code_single_use_under_failure() -> None:
    # Repeated replays across many begin/exchange cycles never succeed twice.
    flow = _make_flow()
    req = flow.begin(scopes=["openid"])
    flow.exchange(code="burn-1", state=req.state, stored=req)
    for _ in range(10):
        req2 = flow.begin(scopes=["openid"])
        with pytest.raises(InvalidGrantError):
            flow.exchange(code="burn-1", state=req2.state, stored=req2)


# ---------------------------------------------------------------------------
# ACF_INV_06 — token redaction in audit
# ---------------------------------------------------------------------------
def test_inv_token_redaction_confirms() -> None:
    audit_events: list[Mapping[str, object]] = []

    def capture(e: Mapping[str, object]) -> None:
        audit_events.append(e)

    flow = _make_flow(audit=capture)
    req = flow.begin(scopes=["openid"])
    flow.exchange(code="c", state=req.state, stored=req)
    success = [e for e in audit_events if e.get("event_name") == "acf.exchange.success"]
    assert success
    tr = success[0]["token_response"]
    assert isinstance(tr, Mapping)
    # Token fields redacted, hashes present.
    assert tr["access_token"] == "[REDACTED_TOKEN]"
    assert tr["refresh_token"] == "[REDACTED_TOKEN]"
    assert tr["id_token"] == "[REDACTED_TOKEN]"
    assert isinstance(tr["access_token_hash"], str)
    assert len(str(tr["access_token_hash"])) == 16


def test_inv_token_redaction_prevents() -> None:
    # Direct invocation of redactor NEVER lets a full token leak through.
    redacted = redact_token_response({
        "access_token": "SECRET-TOKEN-VALUE",
        "refresh_token": "SECRET-REFRESH",
        "id_token": "SECRET-ID",
        "scope": "openid profile",
    })
    assert "SECRET" not in str(redacted["access_token"])
    assert "SECRET" not in str(redacted["refresh_token"])
    assert "SECRET" not in str(redacted["id_token"])
    assert redacted["scope"] == "openid profile"  # non-sensitive passes through


def test_inv_token_redaction_under_failure() -> None:
    # Even a weird token endpoint that stuffs tokens into mixed-case keys is
    # redacted — the matcher is case-insensitive. Non-token keys pass through.
    raw = {
        "ACCESS_TOKEN": "leakme",
        "Refresh_Token": "leakme-too",
        "token_type": "Bearer",
    }
    red = redact_token_response(raw)
    assert red["ACCESS_TOKEN"] == "[REDACTED_TOKEN]"
    assert red["Refresh_Token"] == "[REDACTED_TOKEN]"
    assert red["token_type"] == "Bearer"
    # Make sure the stringified dict never contains plaintext.
    assert "leakme" not in str(red)
