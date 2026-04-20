# BreachNotificationQueue

## What it does (plain language)

Tracks suspected and confirmed personal-data incidents with the GDPR
Article 33 72-hour clock. `open_incident` is frictionless (any service may
call it), `confirm` timestamps the clock start, `notify_authority` stops it,
and `close` requires either a notification reference or a documented
no-notification-required basis.

## Regulation anchors

| Standard | Control |
|---|---|
| GDPR | **Article 33** 72-hour supervisory authority notification. |
| HIPAA | **§ 164.308(a)(6)** security incident procedures. |

## API surface (catalog fidelity)

```python
class BreachNotificationQueue(Protocol):
    def open_incident(self, detected_at: datetime, severity: Severity, summary: str) -> str: ...
    def confirm(self, incident_id: str, confirmed_at: datetime, data_classes: tuple[str, ...]) -> None: ...
    def notify_authority(self, incident_id: str, authority: str, at: datetime, reference: str) -> None: ...
    def close(self, incident_id: str, outcome: str) -> None: ...
```

## Invariants

| ID | Rule |
|---|---|
| BNQ_INV_01 | 72h statutory clock; T-24h warning. |
| BNQ_INV_02 | `open_incident` non-gating. |
| BNQ_INV_03 | Every transition emits audit. |
| BNQ_INV_04 | `data_classes` non-empty + registered. |
| BNQ_INV_05 | Close requires notify OR legal_basis. |

## Provenance

- EU GDPR Regulation 2016/679 — Article 33
- HIPAA Security Rule 45 CFR § 164.308(a)(6)

## Compose with:

- **72-hour containment** → `AuditEvent` + `TamperEvidentAuditLog`
  Incident lifecycle events are sealed and timestamped; the supervisory clock cannot be retroactively edited once `confirm` is called.

- **Impacted-subject notification** → `DataSubjectRequest` + `PiiClassification`
  Impacted subjects are derived from the incident scope and the PII classification map; each subject's DSR can reference the breach for Art 34 disclosures.

- **Evidence-gated closure** → `TamperEvidentAuditLog` + `AuditEvent`
  `close` requires either a supervisory notification reference or a documented no-notification-required basis — you cannot silently archive an incident.
