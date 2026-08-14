"""PiiClassification primitive — schema-level PII/PHI/PCI tagging + central mask.

Regulation anchors:

- HIPAA **45 CFR § 164.514(b)** de-identification safe-harbor field list.
- PCI-DSS v4.0 **Requirement 3.4** — render PAN unreadable (masking,
  truncation, hashing).
- NIST SP 800-53 rev 5 **MP-3** Media Marking, **MP-4** Media Storage.

Invariant IDs:

- PIC_INV_01: Every persisted field MUST carry a PiiClass annotation; fields
  without one SHALL fail registration.
- PIC_INV_02: Serializers MUST route through `mask()` before emission;
  writing a raw object to a sink is FORBIDDEN.
- PIC_INV_03: PHI and PCI fields MUST NEVER be emitted to unauthenticated
  audiences, even masked, unless the field is explicitly PUBLIC.
- PIC_INV_04: `mask()` output for a given audience MUST be deterministic so
  diff tests can assert non-leakage.
- PIC_INV_05: Reclassifying DOWN the sensitivity ladder (PHI → PII → PUBLIC)
  MUST require an audit log entry with approver id.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Protocol, runtime_checkable


class PiiClass(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    PII = "pii"
    PHI = "phi"
    PCI = "pci"


# Sensitivity ladder (index = sensitivity; higher = more sensitive).
_LADDER: Final[tuple[PiiClass, ...]] = (
    PiiClass.PUBLIC,
    PiiClass.INTERNAL,
    PiiClass.PII,
    PiiClass.PHI,
    PiiClass.PCI,
)


def _rank(pc: PiiClass) -> int:
    return _LADDER.index(pc)


_UNAUTHENTICATED_SAFE: Final[frozenset[PiiClass]] = frozenset(
    {PiiClass.PUBLIC, PiiClass.INTERNAL},
)


class PiiClassificationError(ValueError):
    """Runtime invariant violation."""


@dataclass(frozen=True)
class ReclassificationRecord:
    model: str
    field: str
    old_class: PiiClass
    new_class: PiiClass
    approver: str


@runtime_checkable
class AuditSink(Protocol):
    def append(
        self, actor: str, action: str, resource: str, outcome: str, attributes: Mapping[str, object]
    ) -> str: ...


@runtime_checkable
class PiiClassification(Protocol):
    """Catalog-defined Protocol (verbatim)."""

    def classify(self, model: type, field: str) -> PiiClass: ...
    def mask(self, obj: Any, audience: str) -> Mapping[str, Any]: ...
    def audit_leak(self, obj: Any, sink: str) -> None: ...


class InMemoryPiiClassification:
    """Reference implementation.

    Stateful by design: maintains a mutable registry of (model, field) →
    PiiClass annotations plus a per-audience allow-list. Reclassification
    down the ladder is gated by `approver` and emits an audit row.
    """

    def __init__(self, *, audit_sink: AuditSink | None = None) -> None:
        self._annotations: dict[tuple[str, str], PiiClass] = {}
        self._audience_max: dict[str, PiiClass] = {
            "public": PiiClass.PUBLIC,
            "internal": PiiClass.INTERNAL,
            "clinician": PiiClass.PHI,
            "finance": PiiClass.PCI,
        }
        self._audit = audit_sink
        self._leak_count = 0
        self._lock = threading.Lock()

    # ------------------------------------------------------------ Registration
    def register(self, model: type, field: str, pii_class: PiiClass) -> None:
        """PIC_INV_01: every field must be registered with a PiiClass."""
        if not isinstance(field, str) or not field.strip():
            raise PiiClassificationError("PIC_INV_01: field MUST be non-empty.")
        if not isinstance(pii_class, PiiClass):
            raise PiiClassificationError("PIC_INV_01: pii_class MUST be a PiiClass enum value.")
        key = (getattr(model, "__name__", str(model)), field)
        with self._lock:
            existing = self._annotations.get(key)
            if existing is not None and _rank(pii_class) < _rank(existing):
                raise PiiClassificationError(
                    "PIC_INV_05: downward reclassification requires "
                    "`reclassify(..., approver=...)`."
                )
            self._annotations[key] = pii_class

    def reclassify(
        self,
        model: type,
        field: str,
        new_class: PiiClass,
        *,
        approver: str,
    ) -> ReclassificationRecord:
        """PIC_INV_05: downward reclassification MUST carry approver + audit row."""
        if not isinstance(approver, str) or not approver.strip():
            raise PiiClassificationError("PIC_INV_05: approver MUST be non-empty.")
        name = getattr(model, "__name__", str(model))
        with self._lock:
            key = (name, field)
            existing = self._annotations.get(key)
            if existing is None:
                raise PiiClassificationError(f"PIC_INV_01: field {name}.{field} is not registered.")
            self._annotations[key] = new_class
        record = ReclassificationRecord(
            model=name,
            field=field,
            old_class=existing,
            new_class=new_class,
            approver=approver,
        )
        if self._audit is not None and _rank(new_class) < _rank(existing):
            self._audit.append(
                actor=approver,
                action="pii.reclassify",
                resource=f"{name}.{field}",
                outcome="success",
                attributes={"old": existing.value, "new": new_class.value},
            )
        return record

    # ------------------------------------------------------------- Catalog API
    def classify(self, model: type, field: str) -> PiiClass:
        """PIC_INV_01: unregistered fields raise."""
        name = getattr(model, "__name__", str(model))
        with self._lock:
            pc = self._annotations.get((name, field))
        if pc is None:
            raise PiiClassificationError(
                f"PIC_INV_01: field {name}.{field} has no PiiClass annotation."
            )
        return pc

    def mask(self, obj: Any, audience: str) -> Mapping[str, Any]:
        """PIC_INV_02 + 03 + 04: deterministic, audience-gated projection.

        Takes a SINGLE snapshot of audience cap + per-field classifications
        under one lock acquisition so a concurrent `reclassify()` cannot cause
        drift mid-iteration (some fields under old cap, others under new).
        """
        if not isinstance(audience, str) or not audience.strip():
            raise PiiClassificationError("PIC_INV_04: audience MUST be non-empty.")
        fields = self._obj_fields(obj)
        cls_name = type(obj).__name__
        with self._lock:
            cap = self._audience_max.get(audience)
            if cap is None:
                raise PiiClassificationError(
                    f"PIC_INV_03: unknown audience {audience!r}; register it first."
                )
            # Atomic snapshot: resolve every field's class NOW.
            snapshot: dict[str, PiiClass] = {}
            for fname in fields:
                pc = self._annotations.get((cls_name, fname))
                if pc is None:
                    raise PiiClassificationError(
                        f"PIC_INV_01: unregistered field {cls_name}.{fname} cannot be masked."
                    )
                snapshot[fname] = pc
        out: dict[str, Any] = {}
        for fname in sorted(fields):
            pc = snapshot[fname]
            if pc in _UNAUTHENTICATED_SAFE:
                out[fname] = fields[fname]
                continue
            # Within audience cap → pass through; above cap → redact.
            if _rank(pc) <= _rank(cap):
                out[fname] = fields[fname]
            else:
                out[fname] = "[REDACTED]"
        return out

    def audit_leak(self, obj: Any, sink: str) -> None:
        """PIC_INV_02: record a leak of a raw object to a named sink."""
        with self._lock:
            self._leak_count += 1
        if self._audit is not None:
            self._audit.append(
                actor="pii-classifier",
                action="pii.leak",
                resource=f"sink:{sink}",
                outcome="failure",
                attributes={"type": type(obj).__name__},
            )

    # ------------------------------------------------------------- Helpers
    @staticmethod
    def _obj_fields(obj: Any) -> dict[str, Any]:
        import dataclasses as _dc

        if _dc.is_dataclass(obj) and not isinstance(obj, type):
            return {f.name: getattr(obj, f.name) for f in _dc.fields(obj)}
        if hasattr(obj, "__dict__"):
            return dict(obj.__dict__)
        raise PiiClassificationError(
            "PIC_INV_02: obj MUST be a dataclass instance or have __dict__."
        )

    @property
    def leak_count(self) -> int:
        with self._lock:
            return self._leak_count

    @property
    def registered_count(self) -> int:
        with self._lock:
            return len(self._annotations)


__all__ = [
    "AuditSink",
    "InMemoryPiiClassification",
    "PiiClass",
    "PiiClassification",
    "PiiClassificationError",
    "ReclassificationRecord",
]
