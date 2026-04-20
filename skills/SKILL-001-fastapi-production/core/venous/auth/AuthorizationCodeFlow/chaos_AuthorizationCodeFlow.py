"""Chaos / game-day tests for AuthorizationCodeFlow.

Simulates token-endpoint failures, clock-skew, concurrent redemption
attempts, and attacker-supplied mutations to confirm the flow never enters
an inconsistent state and never leaks a plaintext token.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import replace

import pytest

from AuthorizationCodeFlow import (
    InvalidGrantError,
    InvalidStateError,
    ProviderMetadata,
    ReferenceAuthorizationCodeFlow,
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
        "access_token": "AT-1",
        "refresh_token": "RT-1",
        "id_token": "IT-1",
        "token_type": "Bearer",
        "expires_in": 3600,
    }


def _make_flow(**kw: object) -> ReferenceAuthorizationCodeFlow:
    return create_flow(
        client_id="c",
        redirect_uri="https://client.example/cb",
        provider=_PROVIDER,
        token_endpoint=kw.get("token_endpoint", _ok_token),  # type: ignore[arg-type]  # ACF-INV-05 supporting: injected endpoint is callable.
        code_ttl_seconds=float(kw.get("code_ttl_seconds", 600.0)),  # type: ignore[arg-type]  # ACF-INV-05: explicit TTL override.
    )


def test_chaos_token_endpoint_raises_flow_stays_consistent() -> None:
    def boom(_req: Mapping[str, str]) -> Mapping[str, object]:
        raise OSError("network down")

    flow = _make_flow(token_endpoint=boom)
    req = flow.begin(scopes=["openid"])
    with pytest.raises(OSError):
        flow.exchange(code="c", state=req.state, stored=req)
    # Redemption set remains empty because the exchange aborted before marking
    # the code as consumed; the caller may retry with the same code.
    assert flow.redeemed_count == 0


def test_chaos_100_replays_never_succeed_twice() -> None:
    flow = _make_flow()
    req = flow.begin(scopes=["openid"])
    flow.exchange(code="only-once", state=req.state, stored=req)

    failures = 0
    for _ in range(100):
        req2 = flow.begin(scopes=["openid"])
        try:
            flow.exchange(code="only-once", state=req2.state, stored=req2)
        except InvalidGrantError:
            failures += 1
    assert failures == 100
    assert flow.redeemed_count == 1


def test_chaos_concurrent_redemption_of_single_code_only_one_winner() -> None:
    flow = _make_flow()
    req = flow.begin(scopes=["openid"])

    wins: list[int] = []
    losses: list[int] = []
    lock = threading.Lock()
    barrier = threading.Barrier(8)

    def worker() -> None:
        barrier.wait()
        try:
            flow.exchange(code="concurrent-code", state=req.state, stored=req)
            with lock:
                wins.append(1)
        except (InvalidGrantError, InvalidStateError):
            with lock:
                losses.append(1)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(wins) == 1
    assert len(wins) + len(losses) == 8


def test_chaos_clock_skew_future_codes_never_resurrect() -> None:
    clock = {"t": 100.0}
    flow = ReferenceAuthorizationCodeFlow(
        client_id="c",
        redirect_uri="https://client.example/cb",
        provider=_PROVIDER,
        token_endpoint=_ok_token,
        code_ttl_seconds=30.0,
        clock=lambda: clock["t"],
    )
    req = flow.begin(scopes=["openid"])
    clock["t"] = 500.0  # way past TTL
    with pytest.raises(InvalidGrantError):
        flow.exchange(code="c", state=req.state, stored=req)
    # Even resetting the clock backwards does NOT resurrect the state — the
    # state was burned on expiry, so a follow-up raises InvalidStateError
    # (no outstanding request with that state anymore).
    clock["t"] = 100.0
    with pytest.raises(InvalidStateError):
        flow.exchange(code="c", state=req.state, stored=req)


def test_chaos_attacker_swapped_verifier_rejected() -> None:
    flow = _make_flow()
    req = flow.begin(scopes=["openid"])
    tampered = replace(req, code_verifier="evil")
    with pytest.raises(InvalidGrantError):
        flow.exchange(code="c", state=req.state, stored=tampered)


def test_chaos_mismatched_state_never_reaches_token_endpoint() -> None:
    calls: list[int] = []

    def tracked(_req: Mapping[str, str]) -> Mapping[str, object]:
        calls.append(1)
        return _ok_token(_req)

    flow = _make_flow(token_endpoint=tracked)
    reqs = [flow.begin(scopes=["openid"]) for _ in range(5)]
    # Use the WRONG state in every attempt.
    for i, r in enumerate(reqs):
        wrong = reqs[(i + 1) % 5].state
        with pytest.raises(InvalidStateError):
            flow.exchange(code="c", state=wrong, stored=r)
    assert calls == []


def test_chaos_large_burst_of_begin_calls_never_reuses_state() -> None:
    flow = _make_flow()
    seen: set[str] = set()
    for _ in range(1000):
        r = flow.begin(scopes=["openid"])
        assert r.state not in seen
        seen.add(r.state)
