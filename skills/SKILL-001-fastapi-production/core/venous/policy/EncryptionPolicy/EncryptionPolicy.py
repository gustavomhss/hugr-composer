"""EncryptionPolicy primitive — bound cipher/KMS/rotation per data_class.

Regulation anchors:

- PCI-DSS v4.0 **Req 3.5** protect stored cryptographic keys; **Req 4.2**
  strong cryptography in transit.
- HIPAA Security Rule **§ 164.312(a)(2)(iv)** encryption/decryption;
  **§ 164.312(e)(2)(ii)** transmission encryption.
- NIST SP 800-53 rev 5 **SC-13** Cryptographic Protection; **SC-8**
  Transmission Confidentiality.

Invariant IDs:

- EP_INV_01: Every data_class storing PII, PHI, or PCI MUST have a bound
  EncryptionPolicy; writes without `resolve()` succeeding SHALL fail.
- EP_INV_02: `at_rest_cipher` MUST be one of the approved set
  (AES-256-GCM, ChaCha20-Poly1305); unapproved ciphers SHALL raise on bind.
- EP_INV_03: `in_transit_min_tls` MUST be TLS1.2 or higher; TLS1.0/1.1
  FORBIDDEN.
- EP_INV_04: `key_provider` MUST reference an external KMS
  (`aws-kms://`, `gcp-kms://`, `azure-keyvault://`, `hashicorp-vault://`);
  raw key material NEVER permitted.
- EP_INV_05: For PCI data_classes, `rotation` MUST be <= 365 days.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import timedelta
from typing import Final, Protocol, runtime_checkable

APPROVED_CIPHERS: Final[frozenset[str]] = frozenset(
    {"AES-256-GCM", "ChaCha20-Poly1305"},
)

APPROVED_TLS_VERSIONS: Final[frozenset[str]] = frozenset(
    {"TLS1.2", "TLS1.3"},
)

APPROVED_KMS_SCHEMES: Final[tuple[str, ...]] = (
    "aws-kms://", "gcp-kms://", "azure-keyvault://", "hashicorp-vault://",
)

PCI_ROTATION_CAP: Final[timedelta] = timedelta(days=365)


class EncryptionPolicyError(ValueError):
    """Runtime invariant violation."""


@dataclass(frozen=True)
class EncryptionPolicy:
    data_class: str
    at_rest_cipher: str
    in_transit_min_tls: str
    key_provider: str
    rotation: timedelta

    def __post_init__(self) -> None:
        if not isinstance(self.data_class, str) or not self.data_class.strip():
            raise EncryptionPolicyError("EP_INV_01: data_class MUST be non-empty.")
        if self.at_rest_cipher not in APPROVED_CIPHERS:
            raise EncryptionPolicyError(
                f"EP_INV_02: at_rest_cipher MUST be one of {sorted(APPROVED_CIPHERS)}; "
                f"got {self.at_rest_cipher!r}."
            )
        if self.in_transit_min_tls not in APPROVED_TLS_VERSIONS:
            raise EncryptionPolicyError(
                f"EP_INV_03: in_transit_min_tls MUST be one of {sorted(APPROVED_TLS_VERSIONS)}; "
                f"got {self.in_transit_min_tls!r}."
            )
        if not any(self.key_provider.startswith(s) for s in APPROVED_KMS_SCHEMES):
            raise EncryptionPolicyError(
                f"EP_INV_04: key_provider MUST reference an external KMS "
                f"with scheme in {APPROVED_KMS_SCHEMES}; got {self.key_provider!r}."
            )
        if not isinstance(self.rotation, timedelta) or self.rotation <= timedelta(0):
            raise EncryptionPolicyError("EP_INV_05: rotation MUST be timedelta > 0.")
        # Defer PCI-specific rotation cap to registry bind — a policy can exist
        # with a 2-year rotation for non-PCI data_classes.


@runtime_checkable
class EncryptionRegistry(Protocol):
    """Catalog-defined Protocol."""

    def bind(self, policy: EncryptionPolicy) -> None: ...
    def resolve(self, data_class: str) -> EncryptionPolicy: ...
    def require_tls(self, endpoint: str) -> None: ...


class InMemoryEncryptionRegistry:
    def __init__(self) -> None:
        self._policies: dict[str, EncryptionPolicy] = {}
        self._tls_endpoints: set[str] = set()
        self._lock = threading.Lock()

    def bind(self, policy: EncryptionPolicy) -> None:
        if not isinstance(policy, EncryptionPolicy):
            raise EncryptionPolicyError("EP_INV_01: bind() requires an EncryptionPolicy.")
        # EP_INV_05: PCI-class rotation cap. Match by word-boundary so benign
        # substrings like "japan" / "spanish" / "banker" don't false-positive
        # as PCI (a previous implementation used `"pan" in ...` which flagged
        # any token containing the letters p-a-n).
        import re as _re
        data_class_lower = policy.data_class.lower()
        is_pci = (
            data_class_lower.startswith("pci")
            or _re.search(r"(?:^|[_\-./:])pan(?:$|[_\-./:])", data_class_lower) is not None
        )
        if is_pci:
            if policy.rotation > PCI_ROTATION_CAP:
                raise EncryptionPolicyError(
                    f"EP_INV_05: PCI data_class {policy.data_class!r} rotation "
                    f"MUST be <= 365 days; got {policy.rotation}."
                )
        with self._lock:
            self._policies[policy.data_class] = policy

    def resolve(self, data_class: str) -> EncryptionPolicy:
        with self._lock:
            p = self._policies.get(data_class)
        if p is None:
            raise EncryptionPolicyError(
                f"EP_INV_01: no EncryptionPolicy bound for data_class {data_class!r}; "
                f"write rejected."
            )
        return p

    def require_tls(self, endpoint: str) -> None:
        if not isinstance(endpoint, str) or not endpoint.strip():
            raise EncryptionPolicyError("EP_INV_03: endpoint MUST be non-empty.")
        with self._lock:
            self._tls_endpoints.add(endpoint)

    @property
    def tls_endpoints(self) -> frozenset[str]:
        with self._lock:
            return frozenset(self._tls_endpoints)

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._policies)


__all__ = [
    "APPROVED_CIPHERS",
    "APPROVED_KMS_SCHEMES",
    "APPROVED_TLS_VERSIONS",
    "PCI_ROTATION_CAP",
    "EncryptionPolicy",
    "EncryptionPolicyError",
    "EncryptionRegistry",
    "InMemoryEncryptionRegistry",
]
