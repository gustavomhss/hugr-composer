"""TamperEvidentAuditLog primitive — hash-chained, signed, append-only audit ledger.

Catalog fidelity: implements the `TamperEvidentAuditLog` Protocol verbatim from
`docs/research/outputs/AGENT_6_COMPLIANCE.json`. Methods: `append`,
`verify_chain`, `get`, `export`.

Regulation anchors:

- AICPA SOC 2 Trust Services Criteria CC7.2 — detection of security events;
  requires non-repudiable evidence of anomaly detection.
- NIST SP 800-53 rev 5 AU-9 (Protection of Audit Information) and AU-10
  (Non-repudiation); the hash chain + external signer realise both controls.
- HIPAA Security Rule 45 CFR § 164.312(b) — audit controls for ePHI.

Invariant IDs (enforced at runtime):

- TEAL_INV_01: Entries MUST be append-only; `update` / `delete` SHALL be
  refused (no such method is exposed and sequence overwrites raise).
- TEAL_INV_02: Each entry MUST carry `prev_hash = SHA-256(prior entry's
  canonical bytes)`; a mismatched link SHALL be detected by `verify_chain`.
- TEAL_INV_03: Each entry MUST carry a signature produced by a `Signer`
  adapter; the writing service NEVER holds the private key itself.
- TEAL_INV_04: Sequence numbers MUST be monotonically increasing by 1 with
  no gaps; `verify_chain` SHALL fail on gap or regression.
- TEAL_INV_05: `actor`, `action`, `resource`, `outcome`, and `timestamp`
  MUST all be non-empty on every entry; absence SHALL raise at append time.
- TEAL_INV_06: `timestamp` MUST come from the server's monotonic wall clock
  (`datetime.now(timezone.utc)`); client-supplied timestamps SHALL be
  rejected by the append surface (the Protocol does not accept one).

Design decisions:

- A `Signer` Protocol isolates the key custodian. The in-memory reference
  signer is a deterministic HMAC-like stub suitable for tests; production
  wires a KMS/HSM adapter whose private half NEVER touches the log writer.
- The canonical bytes used for hashing and signing are a deterministic
  serialization (key-sorted, UTF-8); two honest implementations produce
  identical digests.
- `export(since_seq)` returns a self-describing newline-delimited JSON byte
  stream that downstream verifiers can re-hash off-box without trusting the
  log writer's state.

No I/O at import; all dependencies are stdlib.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Protocol, runtime_checkable

ALLOWED_OUTCOMES: Final[frozenset[str]] = frozenset({"success", "failure", "denied"})
GENESIS_PREV_HASH: Final[str] = "0" * 64


class TamperEvidentAuditLogError(ValueError):
    """Runtime invariant violation on the TamperEvidentAuditLog."""


@runtime_checkable
class Signer(Protocol):
    """Out-of-process signer Protocol. The writer NEVER holds the private key."""

    def sign(self, payload: bytes) -> str: ...
    def verify(self, payload: bytes, signature: str) -> bool: ...
    def key_id(self) -> str: ...


class HmacReferenceSigner:
    """Reference signer. Uses a pre-shared HMAC-SHA256 key for deterministic tests.

    In production, the private key MUST be custodied by a KMS/HSM; this class
    is for tests and local development only. TEAL_INV_03 requires the writing
    service to delegate signing to an external signer Protocol implementation.
    """

    def __init__(self, secret: bytes, key_id: str = "test-key-1") -> None:
        if not isinstance(secret, bytes) or len(secret) < 16:
            raise TamperEvidentAuditLogError(
                "TEAL_INV_03: signer secret MUST be bytes of length >= 16."
            )
        self._secret = secret
        self._kid = key_id

    def sign(self, payload: bytes) -> str:
        import hmac
        return hmac.new(self._secret, payload, hashlib.sha256).hexdigest()

    def verify(self, payload: bytes, signature: str) -> bool:
        import hmac
        return hmac.compare_digest(self.sign(payload), signature)

    def key_id(self) -> str:
        return self._kid


@dataclass(frozen=True)
class AuditEntry:
    """One immutable ledger row."""

    seq: int
    timestamp: datetime
    actor: str
    action: str
    resource: str
    outcome: str
    attributes: Mapping[str, Any]
    prev_hash: str
    entry_hash: str
    signature: str
    key_id: str


def _canonical_bytes(
    *,
    seq: int,
    timestamp: datetime,
    actor: str,
    action: str,
    resource: str,
    outcome: str,
    attributes: Mapping[str, Any],
    prev_hash: str,
) -> bytes:
    """Deterministic serialization for hash + signature inputs.

    Sorts attribute keys; encodes UTF-8; ISO-8601 timestamp with microsecond
    precision. Two independent implementations produce identical output.
    """
    attrs_sorted = {k: attributes[k] for k in sorted(attributes.keys())}
    payload = {
        "seq": seq,
        "ts": timestamp.isoformat(),
        "actor": actor,
        "action": action,
        "resource": resource,
        "outcome": outcome,
        "attributes": attrs_sorted,
        "prev_hash": prev_hash,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _compute_entry_hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


@runtime_checkable
class TamperEvidentAuditLog(Protocol):
    """Catalog-defined Protocol (verbatim)."""

    def append(
        self,
        actor: str,
        action: str,
        resource: str,
        outcome: str,
        attributes: Mapping[str, Any],
    ) -> str: ...

    def verify_chain(
        self,
        start_seq: int | None = None,
        end_seq: int | None = None,
    ) -> bool: ...

    def get(self, seq: int) -> Mapping[str, Any]: ...

    def export(self, since_seq: int) -> bytes: ...


class InMemoryTamperEvidentAuditLog:
    """Reference `TamperEvidentAuditLog` with hash chain + external signer.

    Production deployments wire a KMS-backed `Signer` and a WORM storage
    adapter (S3 Object Lock, ledger DB); this class keeps the chain and the
    signer contract live for tests and CI.
    """

    def __init__(self, signer: Signer) -> None:
        if not isinstance(signer, Signer):
            raise TamperEvidentAuditLogError(
                "TEAL_INV_03: log MUST be constructed with an external Signer."
            )
        self._signer = signer
        self._entries: list[AuditEntry] = []
        self._lock = threading.Lock()

    # ------------------------------------------------------------- Public API
    def append(
        self,
        actor: str,
        action: str,
        resource: str,
        outcome: str,
        attributes: Mapping[str, Any],
    ) -> str:
        """Append one entry. Returns the new entry's hex `entry_hash`."""
        if not isinstance(actor, str) or not actor.strip():
            raise TamperEvidentAuditLogError("TEAL_INV_05: actor MUST be a non-empty string.")
        if not isinstance(action, str) or not action.strip():
            raise TamperEvidentAuditLogError("TEAL_INV_05: action MUST be a non-empty string.")
        if not isinstance(resource, str) or not resource.strip():
            raise TamperEvidentAuditLogError(
                "TEAL_INV_05: resource MUST be a non-empty string."
            )
        if outcome not in ALLOWED_OUTCOMES:
            raise TamperEvidentAuditLogError(
                f"TEAL_INV_05: outcome MUST be one of {sorted(ALLOWED_OUTCOMES)}; got {outcome!r}."
            )
        if not isinstance(attributes, Mapping):
            raise TamperEvidentAuditLogError("TEAL_INV_05: attributes MUST be a Mapping.")

        # TEAL_INV_06: server-side monotonic clock; no caller-supplied timestamp.
        ts = datetime.now(UTC)
        with self._lock:
            seq = len(self._entries) + 1
            prev_hash = self._entries[-1].entry_hash if self._entries else GENESIS_PREV_HASH
            snapshot = dict(attributes)  # TEAL_INV_01: snapshot so caller mutation cannot race.
            payload = _canonical_bytes(
                seq=seq, timestamp=ts, actor=actor, action=action,
                resource=resource, outcome=outcome, attributes=snapshot,
                prev_hash=prev_hash,
            )
            entry_hash = _compute_entry_hash(payload)
            signature = self._signer.sign(payload)
            entry = AuditEntry(
                seq=seq, timestamp=ts, actor=actor, action=action, resource=resource,
                outcome=outcome, attributes=snapshot, prev_hash=prev_hash,
                entry_hash=entry_hash, signature=signature, key_id=self._signer.key_id(),
            )
            self._entries.append(entry)
            return entry_hash

    def _verify_entry(self, entry: AuditEntry, expected_prev: str) -> bool:
        if entry.prev_hash != expected_prev:
            return False
        payload = _canonical_bytes(
            seq=entry.seq, timestamp=entry.timestamp, actor=entry.actor,
            action=entry.action, resource=entry.resource, outcome=entry.outcome,
            attributes=entry.attributes, prev_hash=entry.prev_hash,
        )
        if _compute_entry_hash(payload) != entry.entry_hash:
            return False
        return self._signer.verify(payload, entry.signature)

    def verify_chain(
        self,
        start_seq: int | None = None,
        end_seq: int | None = None,
    ) -> bool:
        """Walk the slice [start_seq, end_seq] and verify hash, link, signature."""
        with self._lock:
            if not self._entries:
                return True
            lo = 1 if start_seq is None else start_seq
            hi = self._entries[-1].seq if end_seq is None else end_seq
            if lo < 1 or hi > self._entries[-1].seq or lo > hi:
                return False
            # TEAL_INV_04: monotonic seq, no gaps.
            for idx in range(lo - 1, hi):
                if self._entries[idx].seq != idx + 1:
                    return False
            prev_hash = (
                GENESIS_PREV_HASH if lo == 1
                else self._entries[lo - 2].entry_hash
            )
            for idx in range(lo - 1, hi):
                e = self._entries[idx]
                if not self._verify_entry(e, prev_hash):
                    return False
                prev_hash = e.entry_hash
            return True

    def get(self, seq: int) -> Mapping[str, Any]:
        """Return a read-only view of entry `seq` (1-indexed)."""
        with self._lock:
            if not isinstance(seq, int) or seq < 1 or seq > len(self._entries):
                raise TamperEvidentAuditLogError(
                    f"TEAL_INV_04: seq {seq!r} out of range [1, {len(self._entries)}]."
                )
            e = self._entries[seq - 1]
            return {
                "seq": e.seq,
                "timestamp": e.timestamp.isoformat(),
                "actor": e.actor,
                "action": e.action,
                "resource": e.resource,
                "outcome": e.outcome,
                "attributes": dict(e.attributes),
                "prev_hash": e.prev_hash,
                "entry_hash": e.entry_hash,
                "signature": e.signature,
                "key_id": e.key_id,
            }

    def export(self, since_seq: int) -> bytes:
        """Export entries with seq >= since_seq as NDJSON bytes for off-box replay."""
        with self._lock:
            if not isinstance(since_seq, int) or since_seq < 1:
                raise TamperEvidentAuditLogError(
                    "TEAL_INV_04: since_seq MUST be an int >= 1."
                )
            lines: list[str] = []
            for e in self._entries:
                if e.seq < since_seq:
                    continue
                lines.append(json.dumps({
                    "seq": e.seq,
                    "timestamp": e.timestamp.isoformat(),
                    "actor": e.actor,
                    "action": e.action,
                    "resource": e.resource,
                    "outcome": e.outcome,
                    "attributes": dict(e.attributes),
                    "prev_hash": e.prev_hash,
                    "entry_hash": e.entry_hash,
                    "signature": e.signature,
                    "key_id": e.key_id,
                }, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
            return ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")

    # ----------------------------------------------------------- Test helpers
    @property
    def size(self) -> int:
        with self._lock:
            return len(self._entries)


__all__ = [
    "ALLOWED_OUTCOMES",
    "GENESIS_PREV_HASH",
    "AuditEntry",
    "HmacReferenceSigner",
    "InMemoryTamperEvidentAuditLog",
    "Signer",
    "TamperEvidentAuditLog",
    "TamperEvidentAuditLogError",
]
