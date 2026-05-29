"""Tests for SqlSubscriptionStore — real-time revocation backed by SQLite.

Mirrors the structure of hugr_auth/test_store.py.  Covers:

- cancel/revoke cut access in real time
- a revoked jti stays dead while a sibling key on the same seat lives
- state PERSISTS across a fresh store instance on the same SQLite file
  (the production requirement: multi-instance shared revocation)
- reactivate_seat restores access for non-individually-revoked keys

Run standalone or via pytest::

    PYTHONPATH=. python3 hugr_auth/test_store_sql.py
    PYTHONPATH=. pytest hugr_auth/test_store_sql.py -v
"""

from __future__ import annotations

import secrets as _secrets
import sys
import tempfile
from pathlib import Path

from sqlalchemy.orm import Session

from hugr_auth.license import introspect_license, mint_license
from hugr_auth.store import SubscriptionStore, authorize
from hugr_auth.store_sql import SqlSubscriptionStore

_SECRET = _secrets.token_bytes(32)


# ---------------------------------------------------------------------------
# Protocol satisfaction check
# ---------------------------------------------------------------------------


def _protocol_check() -> list[str]:
    """Verify isinstance(..., SubscriptionStore) is True (runtime_checkable)."""
    f: list[str] = []
    store = SqlSubscriptionStore()
    if not isinstance(store, SubscriptionStore):
        f.append(
            "SqlSubscriptionStore does not satisfy the SubscriptionStore Protocol "
            "(runtime_checkable isinstance check failed)"
        )
    return f


# ---------------------------------------------------------------------------
# authorize() integration check
# ---------------------------------------------------------------------------


def _authorize_checks() -> list[str]:
    """authorize() from store.py works with SqlSubscriptionStore (in-memory DB)."""
    f: list[str] = []
    store = SqlSubscriptionStore()  # in-memory SQLite

    k1 = mint_license(_SECRET, seat="acme")
    k2 = mint_license(_SECRET, seat="acme")  # 2nd key, same seat
    j1 = (introspect_license(_SECRET, k1) or {}).get("jti")
    assert j1, "minted token must have a jti"

    # clean store → authentic + entitled
    if authorize(_SECRET, k1, store) is None:
        f.append("clean store denied a valid key")

    # revoke a single key (jti) → that key dead, sibling survives
    store.revoke_key(j1)
    if authorize(_SECRET, k1, store) is not None:
        f.append("revoked key still authorized")
    if authorize(_SECRET, k2, store) is None:
        f.append("revoking one key killed a sibling key on the same seat")

    # cancel the seat → every key for that seat dies immediately
    store.cancel_seat("acme")
    if authorize(_SECRET, k2, store) is not None:
        f.append("cancelled seat still authorized")

    # reactivate → sibling k2 lives again; k1 stays revoked by jti
    store.reactivate_seat("acme")
    if authorize(_SECRET, k2, store) is None:
        f.append("reactivated seat not authorized")
    if authorize(_SECRET, k1, store) is not None:
        f.append("reactivating seat un-revoked an individually-revoked key")

    return f


# ---------------------------------------------------------------------------
# Persistence check — the key production requirement
# ---------------------------------------------------------------------------


def _persistence_checks() -> list[str]:
    """State persists across a fresh SqlSubscriptionStore on the same SQLite file."""
    f: list[str] = []
    with tempfile.TemporaryDirectory() as d:
        db_path = Path(d) / "test_hugr_auth.db"
        url = f"sqlite:///{db_path}"

        # Instance 1 — write revocations
        s1 = SqlSubscriptionStore(url)
        s1.cancel_seat("beta")
        s1.revoke_key("deadbeef00000000")

        # Instance 2 — fresh object, same file, simulating a second process
        s2 = SqlSubscriptionStore(url)
        if not s2.seat_cancelled("beta"):
            f.append("cancelled seat did not persist across a fresh store instance")
        if not s2.key_revoked("deadbeef00000000"):
            f.append("revoked key did not persist across a fresh store instance")
        if s2.seat_cancelled("other"):
            f.append("unrelated seat reported as cancelled")
        if s2.key_revoked("not-revoked"):
            f.append("unrelated jti reported as revoked")

        # Reactivate on instance 1 → visible on instance 2
        s1.reactivate_seat("beta")
        if s2.seat_cancelled("beta"):
            f.append("reactivated seat still shows cancelled on a second instance")

    return f


# ---------------------------------------------------------------------------
# Idempotency check
# ---------------------------------------------------------------------------


def _idempotency_checks() -> list[str]:
    """cancel/revoke/reactivate are idempotent (no DB errors on double-call)."""
    f: list[str] = []
    store = SqlSubscriptionStore()
    try:
        store.cancel_seat("gamma")
        store.cancel_seat("gamma")  # second call must not raise
        store.revoke_key("aabbccdd")
        store.revoke_key("aabbccdd")  # second call must not raise
        store.reactivate_seat("gamma")
        store.reactivate_seat("gamma")  # already absent; must not raise
    except Exception as exc:
        f.append(f"idempotency raised an unexpected exception: {exc}")
    if store.seat_cancelled("gamma"):
        f.append("seat still cancelled after reactivate")
    return f


# ---------------------------------------------------------------------------
# Full authorize() + cancel via SqlStore (covers the scope requirement)
# ---------------------------------------------------------------------------


def _authorize_with_sql_cancel() -> list[str]:
    """Mint a license, cancel the seat via SqlSubscriptionStore, assert authorize returns None."""
    f: list[str] = []
    store = SqlSubscriptionStore()
    key = mint_license(_SECRET, seat="demo-seat")

    # Before cancel → authorized
    if authorize(_SECRET, key, store) is None:
        f.append("pre-cancel: authorize() returned None for a valid key")

    # Cancel the seat
    store.cancel_seat("demo-seat")

    # After cancel → denied
    if authorize(_SECRET, key, store) is not None:
        f.append("post-cancel: authorize() did not return None after seat cancellation")

    return f


# ---------------------------------------------------------------------------
# pytest entry-points
# ---------------------------------------------------------------------------


def test_protocol_satisfied() -> None:
    assert not _protocol_check(), "\n".join(_protocol_check())


def test_authorize_revocation() -> None:
    assert not _authorize_checks(), "\n".join(_authorize_checks())


def test_revocation_persists_across_instances() -> None:
    assert not _persistence_checks(), "\n".join(_persistence_checks())


def test_idempotent_mutations() -> None:
    assert not _idempotency_checks(), "\n".join(_idempotency_checks())


def test_authorize_with_sql_cancel() -> None:
    assert not _authorize_with_sql_cancel(), "\n".join(_authorize_with_sql_cancel())


# ---------------------------------------------------------------------------
# Codex C3 F-011 regression — SQL revocation is a real DB-level upsert
# ---------------------------------------------------------------------------


def test_revoke_and_cancel_are_db_level_upserts() -> None:
    """Double-revoke / double-cancel must be a DB-level no-op + leave 1 row.

    Before the F-011 fix, the mutation methods did Python-side
    ``session.get(...) is None`` then ``session.add(...)``. That READ-then-ADD
    is racy: two concurrent admins both observe "not present", both insert,
    and the second one hits the unique-key constraint and raises
    IntegrityError — the docstring's "INSERT OR IGNORE / ON CONFLICT DO
    NOTHING" promise was a lie.

    This test asserts the contract the docstring claims: idempotent at the DB
    level, no IntegrityError, exactly one row after duplicate writes.
    """
    from sqlalchemy import func, select

    from hugr_auth.store_sql import _CancelledSeat, _RevokedKey

    failures: list[str] = []
    store = SqlSubscriptionStore()

    # Double-write the same identifiers; must not raise.
    try:
        store.cancel_seat("dup-seat")
        store.cancel_seat("dup-seat")
        store.cancel_seat("dup-seat")
        store.revoke_key("dup-jti")
        store.revoke_key("dup-jti")
        store.revoke_key("dup-jti")
    except Exception as exc:
        failures.append(f"duplicate write raised: {type(exc).__name__}: {exc}")

    # Final row count must be exactly 1 per deny-list table.
    with Session(store._engine) as session:
        seat_rows = session.scalar(select(func.count()).select_from(_CancelledSeat))
        jti_rows = session.scalar(select(func.count()).select_from(_RevokedKey))
        if seat_rows != 1:
            failures.append(f"expected 1 cancelled_seats row, got {seat_rows}")
        if jti_rows != 1:
            failures.append(f"expected 1 revoked_keys row, got {jti_rows}")

    # Idempotent semantics survive a reload (the deny-list still denies).
    if not store.seat_cancelled("dup-seat"):
        failures.append("seat_cancelled returned False after triple-cancel")
    if not store.key_revoked("dup-jti"):
        failures.append("key_revoked returned False after triple-revoke")

    assert not failures, "\n".join(failures)


def test_concurrent_revoke_does_not_raise_integrity_error() -> None:
    """Two threads revoking the same jti concurrently must both succeed.

    This is the racy path the old read-then-add lost on: two threads pass the
    ``session.get(...) is None`` check, both call ``session.add(...)``, the
    second commit raises IntegrityError. With ON CONFLICT DO NOTHING /
    INSERT OR IGNORE the DB resolves the collision and both threads exit
    cleanly. SQLite serialises writes, so the test runs on an in-memory DB
    with ``check_same_thread=False`` already wired in.
    """
    import threading

    from sqlalchemy import func, select

    from hugr_auth.store_sql import _RevokedKey

    failures: list[str] = []
    # File-backed SQLite + WAL — the in-memory engine uses a SingletonThreadPool
    # that can't serve multiple writer threads; the file backend exercises the
    # real concurrent-writer path the production Postgres deployment lives on.
    with tempfile.TemporaryDirectory() as d:
        db_path = Path(d) / "race.db"
        store = SqlSubscriptionStore(f"sqlite:///{db_path}")
        errors: list[BaseException] = []
        barrier = threading.Barrier(8)

        def _revoke_same() -> None:
            try:
                barrier.wait()
                store.revoke_key("race-jti")
            except BaseException as exc:  # pragma: no cover — only on regression
                errors.append(exc)

        threads = [threading.Thread(target=_revoke_same) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        if errors:
            failures.append(
                "concurrent revoke raised: "
                + "; ".join(f"{type(e).__name__}: {e}" for e in errors)
            )
        with Session(store._engine) as session:
            jti_rows = session.scalar(select(func.count()).select_from(_RevokedKey))
            if jti_rows != 1:
                failures.append(
                    f"expected 1 revoked_keys row after race, got {jti_rows}"
                )

    assert not failures, "\n".join(failures)


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------


def main() -> int:
    all_checks = [
        ("protocol satisfied", _protocol_check),
        ("authorize() revocation", _authorize_checks),
        ("persistence across instances", _persistence_checks),
        ("idempotent mutations", _idempotency_checks),
        ("authorize() + SQL cancel", _authorize_with_sql_cancel),
    ]
    failures: list[str] = []
    for label, fn in all_checks:
        result = fn()
        if result:
            for msg in result:
                failures.append(f"[{label}] {msg}")

    if failures:
        print(f"HuGR auth store_sql: {len(failures)} check(s) FAILED")
        for x in failures:
            print(f"  FAIL  {x}")
        return 1

    print(
        "HuGR auth store_sql: all checks green — SqlSubscriptionStore satisfies "
        "the Protocol, authorize() works, revocations persist across instances, "
        "mutations are idempotent."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
