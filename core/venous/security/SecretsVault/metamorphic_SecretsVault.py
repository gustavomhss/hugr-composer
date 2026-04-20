"""Metamorphic + differential tests for SecretsVault.

Algebraic laws validated:

- get_is_idempotent_within_ttl: repeated get() within TTL returns the same
  (version, material) tuple.
- rotate_strictly_increases_version: N rotations → versions 1..N+1, pairwise <.
- invalidate_is_noop_when_absent: invalidate on unknown name is safe.
- cache_respects_minimum_of_bounds: expiry == min(now+max_age, not_after).
- differential_backends_agree: two independent backends seeded with the same
  material return identical SecretVersion shape through the vault.
- idempotent_invalidate: invalidate(name) ; invalidate(name) is safe.
"""

from __future__ import annotations

from SecretsVault import (
    CachingSecretsVault,
    InMemoryAuditSink,
    InMemoryBackend,
    caller_identity,
)


class _FakeClock:
    def __init__(self) -> None:
        self.t = 2_000_000_000.0

    def now_s(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def _env(max_age_s: float = 60.0) -> tuple[CachingSecretsVault, InMemoryBackend, _FakeClock]:
    be = InMemoryBackend()
    be.register("k", b"initial-material")
    clock = _FakeClock()
    return CachingSecretsVault(be, audit=InMemoryAuditSink(), clock=clock, max_age_s=max_age_s), be, clock


def test_metamorphic_get_is_idempotent_within_ttl() -> None:
    vault, _, _ = _env()
    with caller_identity("svc"):
        a = vault.get("k")
        for _ in range(16):
            b = vault.get("k")
            assert (b.version, b.material) == (a.version, a.material)


def test_metamorphic_rotate_strictly_increases_version() -> None:
    vault, _, _ = _env()
    versions: list[int] = []
    materials: set[bytes] = set()
    with caller_identity("ops"):
        for _ in range(10):
            sv = vault.rotate("k")
            versions.append(sv.version)
            materials.add(sv.material)
    # Strictly increasing
    assert versions == sorted(set(versions))
    assert len(versions) == len(set(versions))
    # Each rotation MUST produce distinct material (SV-INV-03).
    assert len(materials) == len(versions)


def test_metamorphic_invalidate_is_safe_when_name_absent() -> None:
    vault, _, _ = _env()
    with caller_identity("svc"):
        vault.invalidate("never-in-cache")
        # Subsequent get still works.
        sv = vault.get("k")
        assert sv.version == 1


def test_metamorphic_cache_expires_at_min_of_bounds() -> None:
    """Cache MUST expire at min(now + max_age, not_after)."""
    be = InMemoryBackend()
    # not_after = clock_start + 5; max_age = 60 → effective TTL is 5.
    be.register("x", b"m", not_after=2_000_000_005)
    clock = _FakeClock()
    sink = InMemoryAuditSink()
    vault = CachingSecretsVault(be, audit=sink, clock=clock, max_age_s=60.0)
    with caller_identity("svc"):
        vault.get("x")  # miss
        clock.advance(3.0)  # within both bounds
        vault.get("x")  # HIT
        clock.advance(3.0)  # past not_after at t+6
        vault.get("x")  # MISS
    hits = [e.cache_hit for e in sink.events() if e.operation == "get"]
    assert hits == [False, True, False]


def test_metamorphic_differential_two_vaults_agree() -> None:
    """Two independent vaults seeded identically produce identical secret shapes."""
    be1 = InMemoryBackend()
    be2 = InMemoryBackend()
    be1.register("k", b"same")
    be2.register("k", b"same")
    v1 = CachingSecretsVault(be1)
    v2 = CachingSecretsVault(be2)
    with caller_identity("svc"):
        a = v1.get("k")
        b = v2.get("k")
    assert (a.name, a.version, a.material, a.not_after) == (
        b.name, b.version, b.material, b.not_after,
    )


def test_metamorphic_invalidate_twice_is_idempotent() -> None:
    vault, _, _ = _env()
    with caller_identity("svc"):
        vault.get("k")
        vault.invalidate("k")
        vault.invalidate("k")  # second time: still safe
        vault.get("k")  # re-fetches from backend


def test_metamorphic_rotation_breaks_cache() -> None:
    """rotate() MUST refresh the cache; the next get() sees the NEW version."""
    vault, _, _ = _env()
    with caller_identity("svc"):
        a = vault.get("k")
        r = vault.rotate("k")
        b = vault.get("k")
    assert a.version == 1
    assert r.version == 2
    assert b.version == 2
    assert b.material == r.material


def test_metamorphic_audit_count_matches_ops() -> None:
    """|audit events| == |get| + |rotate| + |invalidate| calls."""
    vault, _, _ = _env()
    sink = InMemoryAuditSink()
    vault._audit = sink  # noqa: SLF001 — test swaps audit sink to count ops per SV-INV-04.
    with caller_identity("svc"):
        vault.get("k")
        vault.rotate("k")
        vault.invalidate("k")
        vault.get("k")
    assert len(sink.events()) == 4
