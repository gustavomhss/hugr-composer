# DataSubjectRequest

## What it does (plain language)

Coordinates the lifecycle of a GDPR access / portability / erasure /
rectification request from open to close, with a statutory 30-day clock
and a per-store artifact manifest. A request cannot close until every
registered store has attached its artifact; erasure additionally requires
a cascade artifact.

## Regulation anchors

| Standard | Article / control | Role |
|---|---|---|
| GDPR | **Art 12(3)** 30-day response window, **Art 15** access, **Art 17** erasure | `STATUTORY_WINDOW`, `kind` enum, cascade artifact. |
| HIPAA | **§ 164.308(a)(4)** access management | Individual access rights. |

## API surface (catalog fidelity)

```python
class DataSubjectRequest(Protocol):
    def open(self, subject_id: str, kind: DsrKind, received_at: datetime) -> str: ...
    def attach_artifact(self, request_id: str, store: str, manifest: bytes) -> None: ...
    def close(self, request_id: str, outcome: str) -> None: ...
    def due_at(self, request_id: str) -> datetime: ...
```

## Invariants

| ID | Rule |
|---|---|
| DSR_INV_01 | `due_at = received_at + 30d`; clock does not pause. |
| DSR_INV_02 | Every required store MUST attach an artifact before close. |
| DSR_INV_03 | Erasure close requires a `cascade` artifact. |
| DSR_INV_04 | Open / attach / close each emit an audit entry. |
| DSR_INV_05 | Exports via time-bound signed URL only (7-day window). |

## Error model

- `DataSubjectRequestError` on any invariant violation; bytes-type check on
  manifests, non-empty checks on subject_id / outcome, UTC check on
  `received_at`.

## Security considerations

- Exports are pull-based from signed URLs; the primitive never emails PDFs.
- Erasure cascade is mandatory; partial erasure would violate Art 17.
- Naive datetimes rejected — statutory deadlines demand UTC.

## Provenance

- EU GDPR Regulation 2016/679 — Articles 12, 15, 17
- HIPAA Security Rule 45 CFR § 164.308(a)(4)

## Extension contract

Each store implements a `StoreAdapter.collect(subject_id)` / `.erase(subject_id)`
and registers itself. Workflow plugins subscribe to the lifecycle hook.

## Usage

```python
from DataSubjectRequest import InMemoryDataSubjectRequest
from datetime import datetime, timezone

d = InMemoryDataSubjectRequest(required_stores={"users", "events", "cascade"})
rid = d.open("alice", "erasure", datetime.now(timezone.utc))
for s in ("users", "events", "cascade"):
    d.attach_artifact(rid, s, b"erased")
d.close(rid, outcome="completed")
```

## Compose with:

- **Erasure cascade** → `RetentionPolicy` + `LegalHold`
  Erasure walks every store declared in the classification map; LegalHold.covers() is consulted first so lawful holds survive the request.

- **Portability export** → `PiiClassification` + `ConsentLedger`
  Access/portability exports are scoped by classification; consent records travel with the export so the recipient inherits the original lawful basis.

- **Closure evidence** → `AuditEvent` + `TamperEvidentAuditLog`
  A DSR cannot close until every registered store attaches a per-store artifact, and each artifact is sealed into the audit chain.
