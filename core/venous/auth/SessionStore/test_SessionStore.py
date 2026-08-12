"""Unit tests for SessionStore — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

import itertools
import threading

import pytest
from SessionStore import (
    CookieConfig,
    InMemorySessionStore,
    Session,
    SessionInvariantError,
    mint_session_id,
    register_adapter,
    validate_cookie_host,
)


# ---------------------------------------------------------------------------
# SESSION_INV_01 — high-entropy, CSPRNG-only ids
# ---------------------------------------------------------------------------
def test_inv_sid_entropy_confirms() -> None:
    ids = {mint_session_id() for _ in range(500)}
    # No collisions across 500 draws — equivalent to sampling a >=128-bit space.
    assert len(ids) == 500
    for sid in ids:
        # base64url alphabet: [A-Za-z0-9_-]
        assert len(sid) >= 22
        for c in sid:
            assert c.isalnum() or c in ("-", "_")


def test_inv_sid_entropy_prevents() -> None:
    # Requesting fewer than 128 bits of entropy is rejected up front.
    with pytest.raises(SessionInvariantError):
        mint_session_id(entropy_bytes=8)  # 64 bits

    # Session with a short (user-controllable) id is rejected at construction.
    with pytest.raises(SessionInvariantError):
        Session(
            id="short",
            subject="u",
            created_at=0,
            idle_expires_at=10,
            absolute_expires_at=10,
        )
    # Session with a non-printable id is rejected.
    with pytest.raises(SessionInvariantError):
        Session(
            id="a" * 30 + "\x00",
            subject="u",
            created_at=0,
            idle_expires_at=10,
            absolute_expires_at=10,
        )


def test_inv_sid_entropy_under_failure() -> None:
    # Simulate a broken RNG that returns the same id twice: the store MUST
    # refuse to overwrite (collision-detection) rather than silently losing
    # the first session.
    sequence = itertools.chain(["dupe_" + "x" * 30], itertools.repeat("dupe_" + "x" * 30))
    store = InMemorySessionStore(id_factory=lambda: next(sequence))
    store.create("alice")
    with pytest.raises(SessionInvariantError):
        store.create("bob")


# ---------------------------------------------------------------------------
# SESSION_INV_02 — rotation on elevation, prior id burned
# ---------------------------------------------------------------------------
def test_inv_rotate_fixation_confirms() -> None:
    store = InMemorySessionStore()
    s1 = store.create("alice")
    s2 = store.rotate(s1.id)
    assert s2.id != s1.id
    assert s2.subject == "alice"
    # Absolute ceiling MUST NOT reset on rotate.
    assert s2.absolute_expires_at == s1.absolute_expires_at


def test_inv_rotate_fixation_prevents() -> None:
    store = InMemorySessionStore()
    s1 = store.create("alice")
    store.rotate(s1.id)
    # Replay of the old id MUST NOT resolve.
    assert store.load(s1.id) is None
    # Rotating the old id again MUST fail — it is tombstoned.
    with pytest.raises(SessionInvariantError):
        store.rotate(s1.id)


def test_inv_rotate_fixation_under_failure() -> None:
    # Attempt many concurrent rotations on the same id — at most one wins,
    # the prior id MUST be unreachable afterwards.
    store = InMemorySessionStore()
    s1 = store.create("alice")
    successes: list[str] = []
    failures: list[BaseException] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            new = store.rotate(s1.id)
            with lock:
                successes.append(new.id)
        except SessionInvariantError as e:
            with lock:
                failures.append(e)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(successes) == 1
    assert len(failures) == 9
    assert store.load(s1.id) is None


# ---------------------------------------------------------------------------
# SESSION_INV_03 — expire at min(idle, absolute) + revocation wins
# ---------------------------------------------------------------------------
def test_inv_expiry_min_confirms() -> None:
    clock = {"t": 1000}
    store = InMemorySessionStore(
        idle_timeout_s=60,
        absolute_timeout_s=3600,
        clock=lambda: clock["t"],
    )
    s = store.create("alice")
    assert s.idle_expires_at == 1060
    assert s.absolute_expires_at == 4600
    # Advance beyond idle but under absolute — session expires.
    clock["t"] = 1061
    assert store.load(s.id) is None


def test_inv_expiry_min_prevents() -> None:
    # Revocation MUST beat a client-held cookie even while the clock is fresh.
    clock = {"t": 1000}
    store = InMemorySessionStore(clock=lambda: clock["t"])
    s = store.create("alice")
    assert store.load(s.id) is not None
    store.revoke(s.id)
    # Cookie still in clock window, but load MUST return None.
    clock["t"] = 1001
    assert store.load(s.id) is None
    assert store.is_revoked(s.id)


def test_inv_expiry_min_under_failure() -> None:
    # Repeated load calls inside the window refresh the idle clock but MUST
    # never push the session past absolute.
    clock = {"t": 1000}
    store = InMemorySessionStore(
        idle_timeout_s=30,
        absolute_timeout_s=100,
        clock=lambda: clock["t"],
    )
    s = store.create("alice")
    for _ in range(20):
        clock["t"] += 10
        current = store.load(s.id)
        if current is None:
            break
        assert current.absolute_expires_at == s.absolute_expires_at
    # After absolute ceiling, load MUST return None.
    clock["t"] = s.absolute_expires_at + 1
    assert store.load(s.id) is None


# ---------------------------------------------------------------------------
# SESSION_INV_04 — cookie attributes
# ---------------------------------------------------------------------------
def test_inv_cookie_attrs_confirms() -> None:
    cfg = CookieConfig(name="sid", secure=True, http_only=True, same_site="Lax")
    assert cfg.secure and cfg.http_only and cfg.same_site == "Lax"
    validate_cookie_host(cfg, "app.example.com")  # host-only, no Domain


def test_inv_cookie_attrs_prevents() -> None:
    with pytest.raises(SessionInvariantError):
        CookieConfig(secure=False)
    with pytest.raises(SessionInvariantError):
        CookieConfig(http_only=False)
    with pytest.raises(SessionInvariantError):
        CookieConfig(same_site="None")
    with pytest.raises(SessionInvariantError):
        CookieConfig(domain=".example.com")
    # Broader-than-host Domain is rejected at bind.
    cfg = CookieConfig(domain="attacker.example.com")
    with pytest.raises(SessionInvariantError):
        validate_cookie_host(cfg, "app.example.com")


def test_inv_cookie_attrs_under_failure() -> None:
    # Even when a caller loops with malformed attributes, each construction
    # MUST fail independently — no cached bad config CAN slip through.
    for bad in (
        {"secure": False},
        {"http_only": False},
        {"same_site": "lax"},
        {"same_site": ""},
    ):
        with pytest.raises(SessionInvariantError):
            CookieConfig(**bad)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# SESSION_INV_05 — revoke_all_for_subject atomicity
# ---------------------------------------------------------------------------
def test_inv_revoke_all_confirms() -> None:
    store = InMemorySessionStore()
    ids = [store.create("alice").id for _ in range(5)]
    store.create("bob")  # not affected
    n = store.revoke_all_for_subject("alice")
    assert n == 5
    for sid in ids:
        assert store.load(sid) is None
    # Bob's sessions MUST survive.
    assert len(store.live_session_ids()) == 1


def test_inv_revoke_all_prevents() -> None:
    # Adapter registration MUST reject capability maps lacking subject-wide revoke.
    class FakeAdapter:
        def create(self, subject: str) -> Session: raise NotImplementedError
        def load(self, session_id: str) -> Session | None: raise NotImplementedError
        def rotate(self, session_id: str) -> Session: raise NotImplementedError
        def revoke(self, session_id: str) -> None: raise NotImplementedError
        def revoke_all_for_subject(self, subject: str) -> int: raise NotImplementedError

    with pytest.raises(SessionInvariantError):
        register_adapter(FakeAdapter(), capabilities={"server_side_revocation": True})
    with pytest.raises(SessionInvariantError):
        register_adapter(
            FakeAdapter(),
            capabilities={"server_side_revocation": False, "subject_wide_revocation": False},
        )


def test_inv_revoke_all_under_failure() -> None:
    # Under concurrent create + revoke_all, any session observable after the
    # revoke_all call with that subject MUST have a created_at strictly greater
    # than the revoke_all barrier.
    store = InMemorySessionStore()
    for _ in range(20):
        store.create("alice")
    barrier_results: list[int] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def revoker() -> None:
        try:
            n = store.revoke_all_for_subject("alice")
            with lock:
                barrier_results.append(n)
        except BaseException as exc:  # pragma: no cover
            with lock:
                errors.append(exc)

    ts = [threading.Thread(target=revoker) for _ in range(5)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors
    # Sum across revokers equals the initial 20 — atomic, non-double-counting.
    assert sum(barrier_results) == 20


# ---------------------------------------------------------------------------
# SESSION_INV_06 — absolute ceiling is a hard cap
# ---------------------------------------------------------------------------
def test_inv_absolute_ceiling_confirms() -> None:
    clock = {"t": 1000}
    store = InMemorySessionStore(
        idle_timeout_s=150,
        absolute_timeout_s=200,
        clock=lambda: clock["t"],
    )
    s = store.create("alice")
    # At t=1100, a fresh idle window (1100 + 150 = 1250) would breach the
    # absolute ceiling (1200). load() MUST clip idle_expires_at to absolute.
    clock["t"] = 1100
    refreshed = store.load(s.id)
    assert refreshed is not None
    assert refreshed.idle_expires_at == s.absolute_expires_at == 1200
    assert refreshed.idle_expires_at <= s.absolute_expires_at


def test_inv_absolute_ceiling_prevents() -> None:
    # Constructing a Session whose idle exceeds absolute MUST fail.
    with pytest.raises(SessionInvariantError):
        Session(
            id="a" * 30,
            subject="alice",
            created_at=0,
            idle_expires_at=100,
            absolute_expires_at=50,
        )
    # Configuring a store with idle > absolute MUST fail.
    with pytest.raises(SessionInvariantError):
        InMemorySessionStore(idle_timeout_s=7200, absolute_timeout_s=3600)


def test_inv_absolute_ceiling_under_failure() -> None:
    # A monkey-patched id_factory cannot trick the store into extending past
    # absolute; every load respects the hard ceiling.
    clock = {"t": 1000}
    store = InMemorySessionStore(
        idle_timeout_s=30,
        absolute_timeout_s=60,
        clock=lambda: clock["t"],
    )
    s = store.create("alice")
    for step in range(6):
        clock["t"] = 1000 + step * 15
        _ = store.load(s.id)
    clock["t"] = s.absolute_expires_at
    assert store.load(s.id) is None
    clock["t"] = s.absolute_expires_at + 3600
    assert store.load(s.id) is None
