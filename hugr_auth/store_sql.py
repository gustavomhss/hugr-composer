"""SQLAlchemy-backed SubscriptionStore — production-grade shared revocation.

Why this exists: InMemorySubscriptionStore and FileSubscriptionStore are
process-local. A real deployment runs multiple auth service instances (load
balancing, rolling deploys). Revocations written to one instance must be
immediately visible to all others — the only safe place for that is a shared DB.

This module adds ``SqlSubscriptionStore``, which satisfies the
``SubscriptionStore`` Protocol from ``hugr_auth.store`` without touching any
existing code (purely additive).

Schema — two simple tables, one row per revoked entity:

    cancelled_seats(seat TEXT PRIMARY KEY)
    revoked_keys(jti TEXT PRIMARY KEY)

Both are keyed by a natural identifier (seat name / jti); uniqueness is
enforced at the DB level (idempotent inserts via INSERT OR IGNORE / ON CONFLICT
DO NOTHING). No timestamps or metadata to keep the schema minimal; that can be
added in a migration if audit-log requirements arrive.

Concurrency: each public method opens and closes its own connection (SQLAlchemy
engine with ``pool_pre_ping=True``). The DB serialises writes; reads are
consistent within the transaction. Safe for concurrent processes on Postgres
and for single-writer SQLite (WAL mode is set automatically for SQLite).

Usage::

    from hugr_auth.store_sql import SqlSubscriptionStore

    store = SqlSubscriptionStore("sqlite:///hugr_auth.db")
    # or: store = SqlSubscriptionStore("postgresql+psycopg2://user:pass@host/db")

    store.cancel_seat("acme")
    store.revoke_key("deadbeef00000000")
    store.seat_cancelled("acme")   # True
    store.key_revoked("deadbeef00000000")  # True
"""

from __future__ import annotations

from sqlalchemy import Column, String, create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session


class _Base(DeclarativeBase):
    pass


class _CancelledSeat(_Base):
    __tablename__ = "cancelled_seats"

    seat = Column(String, primary_key=True, nullable=False)


class _RevokedKey(_Base):
    __tablename__ = "revoked_keys"

    jti = Column(String, primary_key=True, nullable=False)


class SqlSubscriptionStore:
    """SubscriptionStore backed by a SQL database via SQLAlchemy 2.x.

    Parameters
    ----------
    url:
        SQLAlchemy database URL.  Defaults to an in-memory SQLite database
        (``sqlite:///:memory:``) which is useful for tests that do not need
        cross-instance persistence.  For production use a file-path SQLite URL
        (``sqlite:////abs/path/hugr_auth.db``) or a Postgres URL.
    """

    def __init__(self, url: str = "sqlite:///:memory:") -> None:
        connect_args: dict = {}
        if url.startswith("sqlite"):
            # WAL mode: allows concurrent readers while a writer holds the lock.
            connect_args = {"check_same_thread": False}

        self._engine = create_engine(
            url,
            connect_args=connect_args,
            pool_pre_ping=True,
        )

        # Enable WAL journal mode for SQLite file databases.
        if url.startswith("sqlite") and url != "sqlite:///:memory:":
            @event.listens_for(self._engine, "connect")
            def _set_wal(dbapi_conn, _conn_record):  # type: ignore[misc]
                dbapi_conn.execute("PRAGMA journal_mode=WAL")

        _Base.metadata.create_all(self._engine)

    # ------------------------------------------------------------------
    # SubscriptionStore Protocol — reads
    # ------------------------------------------------------------------

    def seat_cancelled(self, seat: str) -> bool:
        """Return True iff *seat* is in the cancelled-seats deny-list."""
        if not seat:
            return False
        with Session(self._engine) as session:
            return session.get(_CancelledSeat, seat) is not None

    def key_revoked(self, jti: str) -> bool:
        """Return True iff *jti* is in the revoked-keys deny-list."""
        if not jti:
            return False
        with Session(self._engine) as session:
            return session.get(_RevokedKey, jti) is not None

    # ------------------------------------------------------------------
    # Admin mutations — writes
    # ------------------------------------------------------------------

    def cancel_seat(self, seat: str) -> None:
        """Add *seat* to the deny-list.  Idempotent."""
        with Session(self._engine) as session:
            with session.begin():
                if session.get(_CancelledSeat, seat) is None:
                    session.add(_CancelledSeat(seat=seat))

    def reactivate_seat(self, seat: str) -> None:
        """Remove *seat* from the deny-list.  Idempotent."""
        with Session(self._engine) as session:
            with session.begin():
                row = session.get(_CancelledSeat, seat)
                if row is not None:
                    session.delete(row)

    def revoke_key(self, jti: str) -> None:
        """Add *jti* to the deny-list.  Idempotent.

        Note: revoked keys are never removed (even if the seat is reactivated).
        The caller must mint a new key for the seat.
        """
        with Session(self._engine) as session:
            with session.begin():
                if session.get(_RevokedKey, jti) is None:
                    session.add(_RevokedKey(jti=jti))
