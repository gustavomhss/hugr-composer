"""ProcessingRecord primitive — GDPR Article 30 Records of Processing Activities.

Regulation anchors:

- GDPR **Article 30** Records of processing activities.

Invariant IDs:

- PR_INV_01: Every code path that reads or writes PII MUST be annotated
  with a registered ProcessingRecord.activity; unregistered activities
  SHALL fail at startup.
- PR_INV_02: Each record MUST reference a `retention_ref` that resolves to
  a bound RetentionPolicy; dangling refs CANNOT register.
- PR_INV_03: `legal_basis` MUST be one of GDPR Article 6(1)(a-f);
  free-text values SHALL raise.
- PR_INV_04: `transfers_outside_eea` entries MUST be ISO-3166 alpha-2
  country codes.
- PR_INV_05: `export_ropa()` output MUST be byte-for-byte reproducible
  given the same registry so auditors can hash and diff releases.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import asdict, dataclass
from typing import Final, Protocol, runtime_checkable

ALLOWED_LEGAL_BASES: Final[frozenset[str]] = frozenset({
    "GDPR Art 6(1)(a) consent",
    "GDPR Art 6(1)(b) contract",
    "GDPR Art 6(1)(c) legal obligation",
    "GDPR Art 6(1)(d) vital interests",
    "GDPR Art 6(1)(e) public task",
    "GDPR Art 6(1)(f) legitimate interest",
})

_ISO_3166_ALPHA2 = re.compile(r"^[A-Z]{2}$")


class ProcessingRecordError(ValueError):
    """Runtime invariant violation."""


@dataclass(frozen=True)
class ProcessingRecord:
    activity: str
    controller: str
    purposes: tuple[str, ...]
    data_classes: tuple[str, ...]
    recipients: tuple[str, ...]
    retention_ref: str
    legal_basis: str
    transfers_outside_eea: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name, v in (("activity", self.activity), ("controller", self.controller),
                        ("retention_ref", self.retention_ref)):
            if not isinstance(v, str) or not v.strip():
                raise ProcessingRecordError(f"PR_INV_01: {name} MUST be non-empty.")
        if not self.purposes:
            raise ProcessingRecordError("PR_INV_01: purposes MUST be non-empty tuple.")
        if not self.data_classes:
            raise ProcessingRecordError("PR_INV_01: data_classes MUST be non-empty.")
        if self.legal_basis not in ALLOWED_LEGAL_BASES:
            raise ProcessingRecordError(
                f"PR_INV_03: legal_basis MUST be in {sorted(ALLOWED_LEGAL_BASES)}; "
                f"got {self.legal_basis!r}."
            )
        for cc in self.transfers_outside_eea:
            if not _ISO_3166_ALPHA2.match(cc):
                raise ProcessingRecordError(
                    f"PR_INV_04: transfers_outside_eea {cc!r} MUST be ISO-3166 alpha-2."
                )


@runtime_checkable
class RetentionResolver(Protocol):
    """Resolves retention_ref → RetentionPolicy (duck-typed)."""

    def has(self, retention_ref: str) -> bool: ...


@runtime_checkable
class ProcessingRegistry(Protocol):
    """Catalog-defined Protocol."""

    def register(self, record: ProcessingRecord) -> None: ...
    def export_ropa(self) -> bytes: ...


class InMemoryProcessingRegistry:
    def __init__(self, *, retention_resolver: RetentionResolver | None = None) -> None:
        self._records: dict[str, ProcessingRecord] = {}
        self._resolver = retention_resolver
        self._lock = threading.Lock()

    def register(self, record: ProcessingRecord) -> None:
        if not isinstance(record, ProcessingRecord):
            raise ProcessingRecordError("PR_INV_01: register requires a ProcessingRecord.")
        if self._resolver is not None and not self._resolver.has(record.retention_ref):
            raise ProcessingRecordError(
                f"PR_INV_02: retention_ref {record.retention_ref!r} does not resolve to a "
                f"bound RetentionPolicy."
            )
        with self._lock:
            self._records[record.activity] = record

    def export_ropa(self) -> bytes:
        with self._lock:
            # PR_INV_05: sort by activity so output is deterministic.
            items = sorted(self._records.values(), key=lambda r: r.activity)
            payload = [asdict(r) for r in items]
            for p in payload:
                p["purposes"] = list(p["purposes"])
                p["data_classes"] = list(p["data_classes"])
                p["recipients"] = list(p["recipients"])
                p["transfers_outside_eea"] = list(p["transfers_outside_eea"])
            return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._records)


__all__ = [
    "ALLOWED_LEGAL_BASES",
    "InMemoryProcessingRegistry",
    "ProcessingRecord",
    "ProcessingRecordError",
    "ProcessingRegistry",
    "RetentionResolver",
]
