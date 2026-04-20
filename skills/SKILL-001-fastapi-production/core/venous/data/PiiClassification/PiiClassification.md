# PiiClassification

## What it does (plain language)

Every persisted field is tagged with a sensitivity class (public, internal,
pii, phi, pci). All serialization goes through one central `mask(obj,
audience)` call that redacts fields above the audience's cap. Forgetting to
tag a field is a type error at startup, not an audit finding at renewal.

## Regulation anchors

| Standard | Article / control | Role |
|---|---|---|
| HIPAA | **45 CFR § 164.514(b)** de-identification safe harbor | PHI fields are never emitted to public. |
| PCI-DSS v4.0 | **Req 3.4** render PAN unreadable | PCI fields redacted for all non-finance audiences. |
| NIST SP 800-53 rev 5 | **MP-3** Media Marking | Schema-level class is the marking. |

## API surface (catalog fidelity)

```python
class PiiClass(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    PII = "pii"
    PHI = "phi"
    PCI = "pci"

class PiiClassification(Protocol):
    def classify(self, model: type, field: str) -> PiiClass: ...
    def mask(self, obj: Any, audience: str) -> Mapping[str, Any]: ...
    def audit_leak(self, obj: Any, sink: str) -> None: ...
```

## Invariants

| ID | Rule |
|---|---|
| PIC_INV_01 | Every field MUST carry a PiiClass annotation. |
| PIC_INV_02 | Serializers MUST route through `mask()`. |
| PIC_INV_03 | PHI/PCI never to unauthenticated audiences. |
| PIC_INV_04 | `mask()` is deterministic per audience. |
| PIC_INV_05 | Downward reclassification requires approver + audit row. |

## Thread safety

Annotation registry is mutex-protected. `classify`, `mask`, `register`, and
`reclassify` acquire the lock for the duration of the operation; the leak
counter is guarded by the same lock.

## Error model

`PiiClassificationError` on unregistered fields, unknown audiences, empty
approver, non-dataclass objects, and downward reclassification without the
explicit `reclassify(..., approver=...)` call.

## Security considerations

- Mask output for a given audience is deterministic so diff tests assert
  non-leakage across releases (PIC_INV_04).
- The registry is mutable but DOWNWARD moves require an approver AND emit
  an audit row; monotonic UPWARD moves are free-form.
- PCI audience cap is `PCI`; finance is the only named audience that sees
  PAN fields, and even then only when the field is classified PCI.

## Provenance

- HIPAA Security Rule 45 CFR § 164.514(b)
- PCI-DSS v4.0 Requirement 3.4
- NIST SP 800-53 rev 5 MP-3, MP-4

## Extension contract

Frameworks register a schema walker that extracts the annotation and plug an
`AudienceResolver` adapter. Custom PiiClass values extend the enum via a
registration decorator that defines the mask policy for the new class.

## Usage

```python
from dataclasses import dataclass
from PiiClassification import InMemoryPiiClassification, PiiClass

@dataclass
class User:
    email: str; ssn: str; public_name: str

c = InMemoryPiiClassification()
c.register(User, "email", PiiClass.PII)
c.register(User, "ssn", PiiClass.PHI)
c.register(User, "public_name", PiiClass.PUBLIC)

u = User(email="a@ex.com", ssn="999-99-9999", public_name="Alice")
out = c.mask(u, audience="public")
```

## Compose with:

- **Mask-at-the-edge** → `OutputEncoder` + `AccessLog`
  Outbound responses pass through mask(audience); the read is then accounted in the access log with the audience — de-identification is mechanical, not a review item.

- **Classification-driven residency** → `DataResidencyPolicy` + `RetentionPolicy`
  Class declares TTL and allowed regions; a single tag drives storage limitation and cross-border transfer rules.

- **DSR scope** → `DataSubjectRequest` + `LegalHold`
  Erasure walks every store holding a given class; LegalHold overrides deletion where lawful — one map drives both.
