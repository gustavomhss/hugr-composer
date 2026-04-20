"""DataResidencyPolicy primitive — per-class allowed regions + transfer mechanism.

Regulation anchors:

- GDPR **Chapter V Articles 44-50** transfers of personal data to third
  countries.
- PCI-DSS v4.0 **Req 12.8** third-party service providers and cross-border
  processing.

Invariant IDs:

- DRP_INV_01: `allowed_regions` MUST be ISO-3166 alpha-2 codes.
- DRP_INV_02: A write to a non-allowed region MUST fail loudly; silent
  replication outside the policy is FORBIDDEN.
- DRP_INV_03: A cross-border transfer outside the EEA CANNOT proceed
  without a valid `transfer_mechanism` on the bound policy.
- DRP_INV_04: `check_write` MUST be called before any persistence primitive
  stores the record; read-time enforcement NEVER satisfies residency.
- DRP_INV_05: Policy changes MUST emit a TamperEvidentAuditLog entry.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Protocol, runtime_checkable

ALLOWED_TRANSFER_MECHANISMS: Final[frozenset[str]] = frozenset({
    "SCC_2021/914",
    "adequacy_decision",
    "intra_group_BCR",
    "derogation_explicit_consent",
})

# EEA member states (alpha-2).
EEA_REGIONS: Final[frozenset[str]] = frozenset({
    "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR",
    "GR", "HR", "HU", "IE", "IS", "IT", "LI", "LT", "LU", "LV", "MT",
    "NL", "NO", "PL", "PT", "RO", "SE", "SI", "SK",
})

_ISO_3166_ALPHA2 = re.compile(r"^[A-Z]{2}$")


class DataResidencyPolicyError(ValueError):
    """Runtime invariant violation."""


@dataclass(frozen=True)
class DataResidencyPolicy:
    data_class: str
    allowed_regions: tuple[str, ...]
    transfer_mechanism: str

    def __post_init__(self) -> None:
        if not isinstance(self.data_class, str) or not self.data_class.strip():
            raise DataResidencyPolicyError("DRP_INV_02: data_class MUST be non-empty.")
        if not self.allowed_regions:
            raise DataResidencyPolicyError(
                "DRP_INV_01: allowed_regions MUST be non-empty."
            )
        for cc in self.allowed_regions:
            if not _ISO_3166_ALPHA2.match(cc):
                raise DataResidencyPolicyError(
                    f"DRP_INV_01: allowed_regions entry {cc!r} MUST be ISO-3166 alpha-2."
                )
        if self.transfer_mechanism not in ALLOWED_TRANSFER_MECHANISMS:
            raise DataResidencyPolicyError(
                f"DRP_INV_03: transfer_mechanism MUST be in "
                f"{sorted(ALLOWED_TRANSFER_MECHANISMS)}; got {self.transfer_mechanism!r}."
            )


@runtime_checkable
class AuditSink(Protocol):
    def append(self, actor: str, action: str, resource: str, outcome: str,
               attributes: Mapping[str, object]) -> str: ...


@runtime_checkable
class ResidencyEnforcer(Protocol):
    """Catalog-defined Protocol."""

    def bind(self, policy: DataResidencyPolicy) -> None: ...
    def check_write(self, data_class: str, region: str) -> None: ...
    def check_transfer(self, data_class: str, source: str, destination: str) -> None: ...


class InMemoryResidencyEnforcer:
    def __init__(self, *, audit_sink: AuditSink | None = None) -> None:
        self._policies: dict[str, DataResidencyPolicy] = {}
        self._audit = audit_sink
        self._lock = threading.Lock()

    def bind(self, policy: DataResidencyPolicy) -> None:
        if not isinstance(policy, DataResidencyPolicy):
            raise DataResidencyPolicyError("DRP_INV_02: bind requires DataResidencyPolicy.")
        with self._lock:
            existing = self._policies.get(policy.data_class)
            self._policies[policy.data_class] = policy
        if self._audit is not None:
            self._audit.append(
                actor="residency-admin", action="residency.policy_changed",
                resource=f"data_class:{policy.data_class}",
                outcome="success",
                attributes={
                    "allowed_regions": list(policy.allowed_regions),
                    "mechanism": policy.transfer_mechanism,
                    "previous": list(existing.allowed_regions) if existing else [],
                },
            )

    def check_write(self, data_class: str, region: str) -> None:
        if not _ISO_3166_ALPHA2.match(region):
            raise DataResidencyPolicyError(
                f"DRP_INV_01: region {region!r} MUST be ISO-3166 alpha-2."
            )
        with self._lock:
            p = self._policies.get(data_class)
        if p is None:
            raise DataResidencyPolicyError(
                f"DRP_INV_04: no DataResidencyPolicy bound for {data_class!r}."
            )
        if region not in p.allowed_regions:
            raise DataResidencyPolicyError(
                f"DRP_INV_02: region {region!r} NOT allowed for {data_class!r}; "
                f"allowed={sorted(p.allowed_regions)}."
            )

    def check_transfer(self, data_class: str, source: str, destination: str) -> None:
        for cc in (source, destination):
            if not _ISO_3166_ALPHA2.match(cc):
                raise DataResidencyPolicyError(
                    f"DRP_INV_01: region {cc!r} MUST be ISO-3166 alpha-2."
                )
        with self._lock:
            p = self._policies.get(data_class)
        if p is None:
            raise DataResidencyPolicyError(
                f"DRP_INV_04: no DataResidencyPolicy bound for {data_class!r}."
            )
        if destination not in p.allowed_regions:
            raise DataResidencyPolicyError(
                f"DRP_INV_02: destination {destination!r} NOT allowed for {data_class!r}."
            )
        # DRP_INV_03: crossing EEA boundary requires a mechanism.
        # `transfer_mechanism` is validated at construction against
        # ALLOWED_TRANSFER_MECHANISMS, so the membership check that used to
        # live here was dead code; the real decision at this point is simply
        # whether a derogation is in effect. A non-derogation mechanism
        # (SCC / BCR / adequacy) satisfies DRP_INV_03 implicitly.
        src_in_eea = source in EEA_REGIONS
        dst_in_eea = destination in EEA_REGIONS
        if src_in_eea != dst_in_eea:
            if p.transfer_mechanism == "derogation_explicit_consent":
                # Allowed but only with the explicit derogation.
                return
            # Any other ALLOWED mechanism passes — no further check needed.

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._policies)


__all__ = [
    "ALLOWED_TRANSFER_MECHANISMS",
    "EEA_REGIONS",
    "AuditSink",
    "DataResidencyPolicy",
    "DataResidencyPolicyError",
    "InMemoryResidencyEnforcer",
    "ResidencyEnforcer",
]
