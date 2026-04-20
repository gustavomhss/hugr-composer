"""Chaos / fault-injection tests for PasswordHasher.

Game-day scenarios: malformed input, algorithm downgrade, concurrent hash,
resource exhaustion, unicode edge cases. The hasher MUST remain correct
under each.
"""

from __future__ import annotations

import threading

import pytest

from PasswordHasher import (
    FORBIDDEN_ALGOS,
    PasswordHasherError,
    ScryptCost,
    ScryptHasher,
    parse_stored,
)


def _scrypt() -> ScryptHasher:
    cost = ScryptCost(n=14, r=8, p=1, dklen=32)
    return ScryptHasher(cost=cost, cost_floor=cost)


def test_chaos_algorithm_downgrade_attempt_rejected() -> None:
    h = _scrypt()
    # Attacker replaces algorithm tag with a forbidden weak one; verify MUST fail.
    stored = h.hash("pw")
    for weak in FORBIDDEN_ALGOS:
        parts = stored.split("$")
        parts[1] = weak
        forged = "$".join(parts)
        with pytest.raises(PasswordHasherError):
            h.verify("pw", forged)


def test_chaos_empty_and_null_byte_password() -> None:
    h = _scrypt()
    assert h.verify("", h.hash("")) is True
    assert h.verify("\x00", h.hash("\x00")) is True
    # Null byte in middle MUST NOT be truncated (unlike some legacy systems).
    assert h.verify("abc\x00def", h.hash("abc\x00def")) is True
    assert h.verify("abc", h.hash("abc\x00def")) is False


def test_chaos_long_password_does_not_crash() -> None:
    h = _scrypt()
    pw = "x" * 10_000
    stored = h.hash(pw)
    assert h.verify(pw, stored) is True
    assert h.verify(pw + "y", stored) is False


def test_chaos_concurrent_hash_no_corruption() -> None:
    h = _scrypt()
    errors: list[BaseException] = []
    results: list[str] = []
    lock = threading.Lock()

    def worker(seed: str) -> None:
        try:
            for _ in range(5):
                s = h.hash(seed)
                assert h.verify(seed, s)
                with lock:
                    results.append(s)
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(f"pw{i}",)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    # All outputs unique (different salts even across threads & passwords).
    assert len(results) == len(set(results))


def test_chaos_corrupt_params_rejected() -> None:
    # Verifier with non-integer params MUST NOT accept.
    with pytest.raises(PasswordHasherError):
        parse_stored("$scrypt$n=abc,r=8,p=1,dklen=32$AAAAAAAAAAAAAAAAAAAAAAAA$BBBB")


def test_chaos_truncated_digest_rejected() -> None:
    h = _scrypt()
    stored = h.hash("pw")
    parts = stored.split("$")
    parts[4] = parts[4][:10]  # truncate digest
    truncated = "$".join(parts)
    # Either verify returns False (length-mismatched compare_digest) or raises.
    try:
        assert h.verify("pw", truncated) is False
    except PasswordHasherError:
        pass


def test_chaos_type_confusion_rejected() -> None:
    h = _scrypt()
    for bad in (None, 42, 3.14, b"bytes", [], {}):
        with pytest.raises(PasswordHasherError):
            h.hash(bad)  # type: ignore[arg-type]


def test_chaos_empty_stored_rejected() -> None:
    h = _scrypt()
    for bad in ("", "$", "$$", "$$$$"):
        with pytest.raises(PasswordHasherError):
            h.verify("pw", bad)
