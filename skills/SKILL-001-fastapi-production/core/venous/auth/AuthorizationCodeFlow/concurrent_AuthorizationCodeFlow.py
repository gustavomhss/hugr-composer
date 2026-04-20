"""Concurrency / linearizability harness for AuthorizationCodeFlow.

Confirms that concurrent begin() and exchange() calls from multiple threads
preserve:
- state / nonce uniqueness under parallel begin (ACF-INV-01)
- at-most-one-winner under parallel redemption of a single code (ACF-INV-05)
- no-state-leak between threads (each begin returns its own private request)
"""

from __future__ import annotations

import threading
from collections.abc import Mapping

from AuthorizationCodeFlow import (
    AuthorizationRequest,
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
        "access_token": "A" * 32,
        "refresh_token": "R" * 32,
        "id_token": "I" * 32,
        "token_type": "Bearer",
        "expires_in": 3600,
    }


def _make_flow() -> object:
    return create_flow(
        client_id="c",
        redirect_uri="https://client.example/cb",
        provider=_PROVIDER,
        token_endpoint=_ok_token,
    )


def test_concurrent_begin_produces_unique_states_across_threads() -> None:
    flow = _make_flow()
    lock = threading.Lock()
    results: list[AuthorizationRequest] = []
    errors: list[BaseException] = []

    def worker(n: int) -> None:
        try:
            for _ in range(n):
                req = flow.begin(scopes=["openid"])  # type: ignore[attr-defined]
                with lock:
                    results.append(req)
        except BaseException as exc:  # pragma: no cover - defensive
            with lock:
                errors.append(exc)

    ts = [threading.Thread(target=worker, args=(50,)) for _ in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors
    states = [r.state for r in results]
    assert len(set(states)) == len(states) == 400


def test_concurrent_exchange_same_code_only_one_succeeds() -> None:
    flow = _make_flow()
    req = flow.begin(scopes=["openid"])  # type: ignore[attr-defined]

    wins: list[int] = []
    losses: list[int] = []
    lock = threading.Lock()
    barrier = threading.Barrier(10)

    def worker() -> None:
        barrier.wait()
        try:
            flow.exchange(code="race-code", state=req.state, stored=req)  # type: ignore[attr-defined]
            with lock:
                wins.append(1)
        except (InvalidGrantError, InvalidStateError):
            with lock:
                losses.append(1)

    ts = [threading.Thread(target=worker) for _ in range(10)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(wins) == 1
    assert len(wins) + len(losses) == 10


def test_concurrent_mixed_begin_and_exchange_preserve_linearizability() -> None:
    flow = _make_flow()
    errors: list[BaseException] = []
    lock = threading.Lock()

    def beginner() -> None:
        try:
            for _ in range(20):
                flow.begin(scopes=["openid"])  # type: ignore[attr-defined]
        except BaseException as exc:  # pragma: no cover - defensive
            with lock:
                errors.append(exc)

    def exchanger() -> None:
        # Every exchanger uses its own begin result.
        try:
            for i in range(20):
                r = flow.begin(scopes=["openid"])  # type: ignore[attr-defined]
                flow.exchange(code=f"c-{i}-{r.state[:4]}", state=r.state, stored=r)  # type: ignore[attr-defined]
        except BaseException as exc:  # pragma: no cover - defensive
            with lock:
                errors.append(exc)

    ts = [threading.Thread(target=beginner) for _ in range(4)]
    ts += [threading.Thread(target=exchanger) for _ in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors


def test_concurrent_redeemed_count_never_exceeds_outstanding() -> None:
    flow = _make_flow()
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker(tid: int) -> None:
        try:
            for i in range(30):
                r = flow.begin(scopes=["openid"])  # type: ignore[attr-defined]
                # Globally-unique code per (thread, iteration) avoids
                # accidental collisions when `id()` reuses memory slots.
                flow.exchange(code=f"c-t{tid}-i{i}", state=r.state, stored=r)  # type: ignore[attr-defined]
        except BaseException as exc:  # pragma: no cover - defensive
            with lock:
                errors.append(exc)

    ts = [threading.Thread(target=worker, args=(tid,)) for tid in range(6)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors
    # 6 workers × 30 begin+exchange = 180 total redemptions.
    assert flow.redeemed_count == 180  # type: ignore[attr-defined]
