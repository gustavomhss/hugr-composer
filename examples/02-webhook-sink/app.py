"""Webhook sink — HMAC verification + exactly-once processing.

Self-contained demo. The production version wires these two stubs into
`SignatureVerifier` and `IdempotentConsumer` under `core/venous/`.
"""
from __future__ import annotations

import hashlib
import hmac
import threading
import time
from dataclasses import dataclass


class SignatureError(Exception):
    """Raised when signature or timestamp fails verification."""


def verify_signature(
    *, secret: bytes, body: bytes, signature_header: str,
    timestamp: int, now: int, tolerance_s: int = 300,
) -> None:
    """Mirror of `SignatureVerifier` primitive invariants:

    1. Timestamp must be within ±``tolerance_s`` of server clock.
    2. HMAC-SHA256 of ``body`` with ``secret`` must equal ``signature_header``.
    3. Constant-time comparison — no early return on partial match.
    """
    if abs(now - timestamp) > tolerance_s:
        raise SignatureError("timestamp out of tolerance")
    mac = hmac.new(secret, body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mac, signature_header):
        raise SignatureError("bad signature")


@dataclass(frozen=True)
class AcceptedEvent:
    provider: str
    event_id: str
    received_at: float
    signature_verified: bool
    raw_body: bytes


class IdempotentInbox:
    """Mirror of `IdempotentConsumer` + `InboxDeduplicator`.

    Invariant: exactly one ``process()`` call per ``(provider, event_id)``
    returns an ``AcceptedEvent``; every subsequent (or concurrent) call
    returns ``None`` (short-circuit).
    """

    def __init__(self) -> None:
        self._seen: set[tuple[str, str]] = set()
        self._lock = threading.Lock()
        self._records: list[AcceptedEvent] = []

    def process(self, *, provider: str, event_id: str, body: bytes, verified: bool) -> AcceptedEvent | None:
        key = (provider, event_id)
        with self._lock:
            if key in self._seen:
                return None
            self._seen.add(key)
            evt = AcceptedEvent(
                provider=provider, event_id=event_id,
                received_at=time.time(), signature_verified=verified,
                raw_body=body,
            )
            self._records.append(evt)
            return evt

    def all_accepted(self) -> list[AcceptedEvent]:
        with self._lock:
            return list(self._records)
