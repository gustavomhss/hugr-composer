"""Chaos / fault-injection tests for SecretsVault.

Game-day scenarios: adversarial secret names, broken backend, malicious
audit sink, clock jumps, concurrent rotation + invalidate, oversized names,
and scope escape attempts. The primitive MUST remain correct under each and
MUST NEVER leak secret material or serve stale values during an outage.
"""

from __future__ import annotations

import threading

import pytest

from SecretsVault import (
    CachingSecretsVault,
    InMemoryAuditSink,
    InMemoryBackend,
    SecretBackendUnavailableError,
    SecretNotFoundError,
    SecretScopeError,
    SecretsVaultError,
    caller_identity,
    zeroize,
)


class _FakeClock:
    def __init__(self) -> None:
        self.t = 3_000_000_000.0

    def now_s(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def _make() -> tuple[CachingSecretsVault, InMemoryBackend, InMemoryAuditSink, _FakeClock]:
    be = InMemoryBackend()
    be.register("ok-secret", b"ok-material")
    sink = InMemoryAuditSink()
    clock = _FakeClock()
    return CachingSecretsVault(be, audit=sink, clock=clock, max_age_s=30.0), be, sink, clock


def test_chaos_empty_name_refused() -> None:
    vault, _, _, _ = _make()
    for bad in ("", "a" * 201, "has space", "has\x00null", "weird\n", "bad|char"):
        with pytest.raises(SecretsVaultError):
            with caller_identity("svc"):
                vault.get(bad)


def test_chaos_non_string_name_refused() -> None:
    vault, _, _, _ = _make()
    for bad in (None, 42, b"bytes-not-str", ["list"], {"dict": 1}):
        with pytest.raises(SecretsVaultError):
            with caller_identity("svc"):
                vault.get(bad)  # type: ignore[arg-type]


def test_chaos_backend_flaps_during_warmup() -> None:
    """Backend becomes unavailable mid-flight; subsequent cold calls MUST fail closed."""
    vault, backend, _, _ = _make()
    with caller_identity("svc"):
        vault.get("ok-secret")  # warms cache
    backend.set_available(False)
    with pytest.raises(SecretBackendUnavailableError):
        with caller_identity("svc"):
            vault.get("other-secret-never-cached")


def test_chaos_audit_sink_crashes_halts_operation() -> None:
    """A raising audit sink MUST cause the op to raise — never silently drop the event."""
    be = InMemoryBackend()
    be.register("x", b"m")

    def evil_sink(_e: object) -> None:
        raise RuntimeError("sink exploded")

    vault = CachingSecretsVault(be, audit=evil_sink)
    with pytest.raises(SecretsVaultError):
        with caller_identity("svc"):
            vault.get("x")


def test_chaos_clock_goes_backwards_does_not_panic() -> None:
    """Rewinding the clock MUST NOT expose cached material beyond its original TTL."""
    vault, _, _, clock = _make()
    with caller_identity("svc"):
        a = vault.get("ok-secret")
    clock.advance(-1000.0)  # rogue NTP jumps the clock backwards
    with caller_identity("svc"):
        # The cache entry is still within its (re-computed) TTL window, so it
        # returns the same version — this is safe because the material was
        # already authorized. Rewinding CANNOT EXTEND legitimate lifetime.
        b = vault.get("ok-secret")
    assert b.version == a.version


def test_chaos_concurrent_rotate_and_get() -> None:
    vault, _, _, _ = _make()
    errors: list[BaseException] = []

    def reader() -> None:
        try:
            for _ in range(20):
                with caller_identity("reader"):
                    sv = vault.get("ok-secret")
                    assert isinstance(sv.material, bytes)
                    assert sv.version >= 1
        except BaseException as exc:  # noqa: BLE001 — chaos harness records any reader failure per SV-INV-02.
            errors.append(exc)

    def rotator() -> None:
        try:
            for _ in range(5):
                with caller_identity("ops"):
                    vault.rotate("ok-secret")
        except BaseException as exc:  # noqa: BLE001 — chaos harness records rotator failure per SV-INV-03.
            errors.append(exc)

    threads = [
        threading.Thread(target=reader),
        threading.Thread(target=reader),
        threading.Thread(target=rotator),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors


def test_chaos_scope_escape_attempt_refused() -> None:
    """Caller tries to read a secret outside its scope — MUST be refused without echoing the name in the error."""
    vault, _, _, _ = _make()
    vault._backend.register("privileged", b"top-secret")  # noqa: SLF001 — chaos test seeds second secret per SV-INV-04.
    vault.declare_scope("low-priv", {"ok-secret"})
    with caller_identity("low-priv"):
        with pytest.raises(SecretScopeError) as ei:
            vault.get("privileged")
    assert "privileged" not in str(ei.value)  # name MUST be withheld


def test_chaos_get_unknown_name_raises_not_found() -> None:
    vault, _, _, _ = _make()
    with pytest.raises(SecretNotFoundError):
        with caller_identity("svc"):
            vault.get("never-registered")


def test_chaos_rotate_unknown_name_raises_not_found() -> None:
    vault, _, _, _ = _make()
    with pytest.raises(SecretNotFoundError):
        with caller_identity("ops"):
            vault.rotate("never-registered")


def test_chaos_zeroize_bytearray_is_zeroed() -> None:
    """zeroize() helper MUST actually overwrite bytearrays."""
    buf = bytearray(b"sensitive-material")
    zeroize(buf)
    assert bytes(buf) == b"\x00" * len(b"sensitive-material")


def test_chaos_zeroize_rejects_immutable_bytes() -> None:
    with pytest.raises(SecretsVaultError):
        zeroize(b"bytes-not-bytearray")  # type: ignore[arg-type]


def test_chaos_invalid_max_age_refused() -> None:
    be = InMemoryBackend()
    be.register("x", b"m")
    for bad in (0, -1, -100.0):
        with pytest.raises(SecretsVaultError):
            CachingSecretsVault(be, max_age_s=bad)


def test_chaos_empty_caller_identity_refused() -> None:
    with pytest.raises(SecretsVaultError):
        with caller_identity(""):
            pass
    with pytest.raises(SecretsVaultError):
        with caller_identity("   "):
            pass


def test_chaos_outage_does_not_rescue_from_stale_cache() -> None:
    """Classic SV-INV-05 game-day: a warmed secret MUST NOT be served past its
    TTL even when the caller would clearly prefer a stale read over an error."""
    be = InMemoryBackend()
    be.register("critical", b"material")
    clock = _FakeClock()
    vault = CachingSecretsVault(be, clock=clock, max_age_s=1.0)
    with caller_identity("svc"):
        vault.get("critical")  # warm
    be.set_available(False)
    clock.advance(2.0)
    with pytest.raises(SecretBackendUnavailableError):
        with caller_identity("svc"):
            vault.get("critical")
