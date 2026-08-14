"""DataSubjectRequest primitive — GDPR access/erasure lifecycle coordinator.

Regulation anchors:

- GDPR **Article 15** right of access; **Article 17** right to erasure.
- HIPAA 45 CFR **§ 164.308(a)(4)** access management — individual access rights.

Invariant IDs:

- DSR_INV_01: Every request MUST have a statutory `due_at` computed from
  `received_at`; the clock NEVER pauses for internal delays.
- DSR_INV_02: Every registered store holding subject data MUST attach an
  artifact before close; a request CANNOT close with missing stores.
- DSR_INV_03: Erasure requests MUST invoke the `ErasureCascade`; a close
  with `kind='erasure'` and no cascade artifact SHALL be rejected.
- DSR_INV_04: Open, artifact, close actions MUST each emit a
  `TamperEvidentAuditLog` entry for regulator replay.
- DSR_INV_05: Access / portability exports MUST be delivered via a
  time-bound, signed URL; exports NEVER live beyond the delivery window.
"""

from __future__ import annotations

import hmac
import threading
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Final, Literal, Protocol, runtime_checkable

# DSR_INV_02: minimum manifest size — rejects empty / trivial closes.
_MIN_MANIFEST_BYTES: Final[int] = 8

DsrKind = Literal["access", "portability", "erasure", "rectification"]

ALLOWED_KINDS: Final[frozenset[str]] = frozenset(
    {"access", "portability", "erasure", "rectification"},
)

# GDPR Article 12(3): 30-day statutory deadline for response.
STATUTORY_WINDOW: Final[timedelta] = timedelta(days=30)

# Access / portability export signed-URL delivery window.
EXPORT_DELIVERY_WINDOW: Final[timedelta] = timedelta(days=7)


class DataSubjectRequestError(ValueError):
    """Runtime invariant violation."""


@runtime_checkable
class AuditSink(Protocol):
    def append(
        self,
        actor: str,
        action: str,
        resource: str,
        outcome: str,
        attributes: Mapping[str, object],
    ) -> str: ...


@dataclass
class _Request:
    request_id: str
    subject_id: str
    kind: DsrKind
    received_at: datetime
    due_at: datetime
    expected_stores: set[str] = field(default_factory=set)
    artifacts: dict[str, bytes] = field(default_factory=dict)
    closed_outcome: str | None = None


@runtime_checkable
class DataSubjectRequest(Protocol):
    """Catalog-defined Protocol (verbatim)."""

    def open(self, subject_id: str, kind: DsrKind, received_at: datetime) -> str: ...
    def attach_artifact(self, request_id: str, store: str, manifest: bytes) -> None: ...
    def close(self, request_id: str, outcome: str) -> None: ...
    def due_at(self, request_id: str) -> datetime: ...


class InMemoryDataSubjectRequest:
    """Reference `DataSubjectRequest` implementation."""

    def __init__(
        self,
        *,
        audit_sink: AuditSink | None = None,
        required_stores: set[str] | None = None,
        export_signing_key: bytes | None = None,
    ) -> None:
        if export_signing_key is not None and len(export_signing_key) < 32:
            raise DataSubjectRequestError(
                "DSR_INV_05: export_signing_key MUST be ≥32 bytes for HMAC-SHA256."
            )
        self._reqs: dict[str, _Request] = {}
        self._audit = audit_sink
        self._required = set(required_stores or ())
        self._lock = threading.Lock()
        self._export_key = bytes(export_signing_key) if export_signing_key else None

    def open(self, subject_id: str, kind: DsrKind, received_at: datetime) -> str:
        if not isinstance(subject_id, str) or not subject_id.strip():
            raise DataSubjectRequestError("DSR_INV_01: subject_id MUST be non-empty.")
        if kind not in ALLOWED_KINDS:
            raise DataSubjectRequestError(
                f"DSR_INV_01: kind MUST be one of {sorted(ALLOWED_KINDS)}."
            )
        if not isinstance(received_at, datetime) or received_at.tzinfo is None:
            raise DataSubjectRequestError("DSR_INV_01: received_at MUST be tz-aware UTC.")
        off = received_at.utcoffset()
        if off is None or off.total_seconds() != 0:
            raise DataSubjectRequestError("DSR_INV_01: received_at MUST be UTC.")
        rid = f"dsr-{uuid.uuid4().hex[:16]}"
        with self._lock:
            self._reqs[rid] = _Request(
                request_id=rid,
                subject_id=subject_id,
                kind=kind,
                received_at=received_at,
                due_at=received_at + STATUTORY_WINDOW,
                expected_stores=set(self._required),
            )
        if self._audit is not None:
            self._audit.append(
                actor="dsr-coordinator",
                action="dsr.open",
                resource=f"dsr:{rid}",
                outcome="success",
                attributes={"subject_id": subject_id, "kind": kind},
            )
        return rid

    def attach_artifact(self, request_id: str, store: str, manifest: bytes) -> None:
        if not isinstance(store, str) or not store.strip():
            raise DataSubjectRequestError("DSR_INV_02: store MUST be non-empty.")
        if not isinstance(manifest, (bytes, bytearray)):
            raise DataSubjectRequestError("DSR_INV_02: manifest MUST be bytes.")
        # DSR_INV_02 / DSR_INV_03: trivially-empty manifests let an attacker
        # discharge a cascade/erasure with zero evidence. Require minimum size.
        if len(manifest) < _MIN_MANIFEST_BYTES:
            raise DataSubjectRequestError(
                f"DSR_INV_02: manifest MUST be ≥{_MIN_MANIFEST_BYTES} bytes "
                f"(got {len(manifest)}); empty proofs are refused."
            )
        with self._lock:
            req = self._reqs.get(request_id)
            if req is None:
                raise DataSubjectRequestError(f"DSR_INV_02: unknown request_id {request_id!r}.")
            if req.closed_outcome is not None:
                raise DataSubjectRequestError(
                    "DSR_INV_02: CANNOT attach artifact to a closed request."
                )
            req.artifacts[store] = bytes(manifest)
        if self._audit is not None:
            self._audit.append(
                actor="dsr-coordinator",
                action="dsr.attach_artifact",
                resource=f"dsr:{request_id}",
                outcome="success",
                attributes={"store": store, "bytes": len(manifest)},
            )

    def close(self, request_id: str, outcome: str) -> None:
        if not isinstance(outcome, str) or not outcome.strip():
            raise DataSubjectRequestError("DSR_INV_04: outcome MUST be non-empty.")
        with self._lock:
            req = self._reqs.get(request_id)
            if req is None:
                raise DataSubjectRequestError(f"DSR_INV_02: unknown request_id {request_id!r}.")
            if req.closed_outcome is not None:
                raise DataSubjectRequestError("DSR_INV_04: request already closed.")
            missing = req.expected_stores - set(req.artifacts)
            if missing:
                raise DataSubjectRequestError(
                    f"DSR_INV_02: cannot close with missing stores: {sorted(missing)}."
                )
            # DSR_INV_03: erasure requires a cascade artifact.
            if req.kind == "erasure" and "cascade" not in req.artifacts:
                raise DataSubjectRequestError(
                    "DSR_INV_03: erasure close requires a 'cascade' artifact."
                )
            req.closed_outcome = outcome
        if self._audit is not None:
            self._audit.append(
                actor="dsr-coordinator",
                action="dsr.close",
                resource=f"dsr:{request_id}",
                outcome="success",
                attributes={"closed_outcome": outcome, "kind": req.kind},
            )

    def due_at(self, request_id: str) -> datetime:
        with self._lock:
            req = self._reqs.get(request_id)
            if req is None:
                raise DataSubjectRequestError(f"DSR_INV_01: unknown request_id {request_id!r}.")
            return req.due_at

    # ---------------------------------------------------------- Extensions
    def signed_export_url(self, request_id: str, at: datetime) -> str:
        """DSR_INV_05: HMAC-SHA256-signed URL valid only for
        EXPORT_DELIVERY_WINDOW. Tampering with the `expires=` claim invalidates
        the `sig=` digest; the verifier MUST reject mismatches.
        """
        if self._export_key is None:
            raise DataSubjectRequestError(
                "DSR_INV_05: export_signing_key not configured; signed URLs unavailable."
            )
        with self._lock:
            req = self._reqs.get(request_id)
            if req is None or req.kind not in ("access", "portability"):
                raise DataSubjectRequestError(
                    "DSR_INV_05: export only valid for access / portability requests."
                )
            expires = int((at + EXPORT_DELIVERY_WINDOW).timestamp())
            payload = f"{request_id}|{expires}".encode()
            sig = hmac.new(self._export_key, payload, sha256).hexdigest()
            return f"https://export.local/dsr/{request_id}?expires={expires}&sig={sig}"

    def verify_export_url_signature(
        self,
        request_id: str,
        expires: int,
        signature: str,
    ) -> bool:
        """DSR_INV_05: constant-time signature verification for the receiver side."""
        if self._export_key is None:
            return False
        payload = f"{request_id}|{expires}".encode()
        expected = hmac.new(self._export_key, payload, sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._reqs)


__all__ = [
    "ALLOWED_KINDS",
    "EXPORT_DELIVERY_WINDOW",
    "STATUTORY_WINDOW",
    "AuditSink",
    "DataSubjectRequest",
    "DataSubjectRequestError",
    "DsrKind",
    "InMemoryDataSubjectRequest",
]
