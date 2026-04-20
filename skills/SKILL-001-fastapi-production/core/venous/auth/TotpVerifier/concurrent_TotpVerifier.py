"""Concurrency / linearizability harness for TotpVerifier.

Confirms that under concurrent verify() calls the per-step single-use
invariant (TOTP-INV-04) holds: at most one thread can claim a given
(secret, step) pair.
"""

from __future__ import annotations

import threading

from TotpVerifier import (
    DEFAULT_STEP_SECONDS,
    StandardTotpVerifier,
    TotpReplayError,
    _hotp,  # type: ignore[attr-defined]
    generate_secret,
)


def test_concurrent_single_winner_per_step() -> None:
    secret = generate_secret()
    now = 1_700_000_000.0
    step = int(now // DEFAULT_STEP_SECONDS)
    code = _hotp(secret, step, 6, "SHA1")
    v = StandardTotpVerifier(now_fn=lambda: now)

    winners: list[int] = []
    replays: list[BaseException] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            s = v.verify(secret=secret, code=code, last_used_step=None)
            with lock:
                winners.append(s)
        except TotpReplayError as exc:
            with lock:
                replays.append(exc)
        except BaseException as exc:  # pragma: no cover — defensive
            with lock:
                errors.append(exc)

    ts = [threading.Thread(target=worker) for _ in range(64)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    assert not errors
    assert len(winners) == 1
    assert len(replays) == 63
    assert winners[0] == step


def test_concurrent_different_secrets_are_independent() -> None:
    # 8 distinct secrets each get one winner concurrently; no cross-secret
    # interference.
    now = 1_700_000_000.0
    step = int(now // DEFAULT_STEP_SECONDS)
    secrets_list = [generate_secret() for _ in range(8)]
    v = StandardTotpVerifier(now_fn=lambda: now)

    winners: dict[int, list[int]] = {i: [] for i in range(8)}
    lock = threading.Lock()

    def worker(i: int) -> None:
        code = _hotp(secrets_list[i], step, 6, "SHA1")
        try:
            s = v.verify(secret=secrets_list[i], code=code, last_used_step=None)
            with lock:
                winners[i].append(s)
        except TotpReplayError:
            pass

    ts = []
    for i in range(8):
        for _ in range(8):
            ts.append(threading.Thread(target=worker, args=(i,)))
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    for i in range(8):
        assert len(winners[i]) == 1


def test_concurrent_step_sweep_under_race() -> None:
    # Multiple threads attempting codes for consecutive steps; every accepted
    # step is unique.
    secret = generate_secret()
    now = 1_700_000_000.0
    step = int(now // DEFAULT_STEP_SECONDS)
    v = StandardTotpVerifier(now_fn=lambda: now)

    accepted: list[int] = []
    lock = threading.Lock()

    def worker(offset: int) -> None:
        code = _hotp(secret, step + offset, 6, "SHA1")
        try:
            s = v.verify(secret=secret, code=code, last_used_step=None)
            with lock:
                accepted.append(s)
        except BaseException:  # pragma: no cover — defensive
            pass

    # Offsets -1, 0, 1 (3 valid) plus 10 out-of-range that MUST be rejected.
    ts = []
    for offset in (-1, 0, 1):
        ts.append(threading.Thread(target=worker, args=(offset,)))
    for offset in range(5, 15):
        ts.append(threading.Thread(target=worker, args=(offset,)))
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    assert len(accepted) == len(set(accepted))
    assert set(accepted).issubset({step - 1, step, step + 1})
