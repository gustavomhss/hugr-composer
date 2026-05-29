"""Subscription state for real-time revocation.

A valid signature + unexpired token proves *authenticity*, not *entitlement*.
A seat can cancel mid-term, or a key can leak — both must cut access NOW, not
at the token's exp. This module is that authority's state: a deny-list of
cancelled seats and revoked key-ids (jti), checked on every introspection.

Deny-list model (not allow-list): a seat is entitled unless explicitly
cancelled, a key unless explicitly revoked. This delivers "cancel → immediate
cut" without first needing the issuance flow to pre-register every seat (that's
a later brick). The `SubscriptionStore` Protocol is the seam to swap the
in-memory/file impls for Postgres/Redis later without touching the gate or app.

`authorize()` is the single entry point the app calls: authentic + entitled.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Protocol, runtime_checkable

from hugr_auth.license import introspect_license


@runtime_checkable
class SubscriptionStore(Protocol):
    def seat_cancelled(self, seat: str) -> bool: ...
    def key_revoked(self, jti: str) -> bool: ...


class InMemorySubscriptionStore:
    """Process-local deny-list. Thread-safe; lost on restart (use File for prod)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cancelled_seats: set[str] = set()
        self._revoked_keys: set[str] = set()

    def seat_cancelled(self, seat: str) -> bool:
        return seat in self._cancelled_seats

    def key_revoked(self, jti: str) -> bool:
        return bool(jti) and jti in self._revoked_keys

    # --- admin mutations (called by the issuance/billing flow; here for tests) ---
    def cancel_seat(self, seat: str) -> None:
        with self._lock:
            self._cancelled_seats.add(seat)

    def reactivate_seat(self, seat: str) -> None:
        with self._lock:
            self._cancelled_seats.discard(seat)

    def revoke_key(self, jti: str) -> None:
        with self._lock:
            self._revoked_keys.add(jti)


class FileSubscriptionStore(InMemorySubscriptionStore):
    """Deny-list persisted to a JSON file so revocations survive a restart.

    Tiny by design (two string sets). A real deployment swaps this for a DB via
    the SubscriptionStore Protocol; the JSON file keeps the first hosted cut
    durable without a DB dependency.

    Concurrency contract: every mutation holds ``self._lock`` across both the
    in-memory set update AND the on-disk JSON write. Without that, two
    concurrent admin writes can mutate the sets correctly, then race while
    persisting snapshots — letting the later write serialize an older view and
    silently lose a revocation across restart (Codex C3 F-009).
    """

    def __init__(self, path: str | Path) -> None:
        super().__init__()
        self._path = Path(path)
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        self._cancelled_seats = set(data.get("cancelled_seats", []))
        self._revoked_keys = set(data.get("revoked_keys", []))

    def _persist_locked(self) -> None:
        """Write a snapshot of the in-memory state to disk.

        Caller MUST hold ``self._lock`` — the snapshot is read directly from
        the live sets, so an unlocked call would race a concurrent mutation
        and could serialize a torn view.
        """
        payload = {
            "cancelled_seats": sorted(self._cancelled_seats),
            "revoked_keys": sorted(self._revoked_keys),
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self._path)  # atomic

    def cancel_seat(self, seat: str) -> None:
        with self._lock:
            self._cancelled_seats.add(seat)
            self._persist_locked()

    def reactivate_seat(self, seat: str) -> None:
        with self._lock:
            self._cancelled_seats.discard(seat)
            self._persist_locked()

    def revoke_key(self, jti: str) -> None:
        with self._lock:
            self._revoked_keys.add(jti)
            self._persist_locked()


def authorize(secret: bytes, key: str, store: SubscriptionStore) -> dict | None:
    """Authentic AND entitled → claims, else None.

    Authentic: valid signature + unexpired (introspect_license).
    Entitled: the seat is not cancelled and this key (jti) is not revoked.
    """
    claims = introspect_license(secret, key)
    if claims is None:
        return None
    if store.seat_cancelled(claims.get("seat", "")):
        return None
    if store.key_revoked(claims.get("jti", "")):
        return None
    return claims
