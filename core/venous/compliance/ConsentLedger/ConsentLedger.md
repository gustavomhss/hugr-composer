# ConsentLedger

## What it does (plain language)

Records every consent grant and revocation per (subject, purpose) with the
version of the notice accepted and the timestamp. Answering "did Alice
consent to marketing on 2024-11-03 at 14:22?" becomes a reproducible
point-in-time query, not a reconstruction from a boolean flag.

## Purpose

GDPR Art 6(1)(a) makes consent a lawful basis ONLY when the controller can
demonstrate the grant. This primitive makes the demonstration byte-for-byte
reproducible and makes revocation immediate.

## Regulation anchors

| Standard | Article / control | Role |
|---|---|---|
| GDPR | **Art 6(1)(a)** lawful basis, **Art 7** conditions for consent | Per-(subject, purpose) history + notice version. |
| AICPA SOC 2 | Privacy **P3.1** consent collection & documentation | Append-only evidence. |

## API surface (catalog fidelity)

```python
class ConsentLedger(Protocol):
    def grant(self, subject_id: str, purpose: str,
              notice_version: str, at: datetime) -> str: ...
    def revoke(self, subject_id: str, purpose: str, at: datetime) -> None: ...
    def is_granted(self, subject_id: str, purpose: str,
                   at: datetime | None = None) -> bool: ...
    def history(self, subject_id: str) -> list[dict]: ...
```

## Invariants

| ID | Rule |
|---|---|
| CL_INV_01 | Keyed by (subject, purpose); no blanket grants. |
| CL_INV_02 | Every grant cites `notice_version`. |
| CL_INV_03 | Revocation is immediate. |
| CL_INV_04 | History is append-only; revocation supersedes in time. |
| CL_INV_05 | `is_granted(..., at)` returns the state AT `at`, not current. |

## Error model

- `ConsentLedgerError` on empty / whitespace inputs, naive timestamps, and
  blanket (comma-separated) purposes. GDPR Art 7(2) requires granularity.

## Security considerations

- Revocation NEVER deletes prior grants — a grant that was legitimate at
  the time remains on record (evidence preservation).
- Naive timestamps are rejected: wall-clock ambiguity across emitters would
  produce non-reproducible audit answers.
- Homoglyph subject ids produce distinct subjects by design; if a dedup
  policy is needed, normalise BEFORE calling the ledger.

## Provenance

- EU GDPR Regulation 2016/679 — Articles 6, 7
- AICPA SOC 2 Trust Services Criteria — Privacy P3.1

## Alternatives considered and rejected

- Boolean column — no history, no notice version, no temporal query.
- CRM as source of truth — outside transactional boundary, racy.
- Cookie banner only — covers web UI, misses API/backend processing.

## Extension contract

Target applications register purpose codes (e.g. `marketing_email`,
`analytics_profiling`) and plug a `NoticeVersionProvider` adapter. A policy
decorator blocks consent-gated code paths when `is_granted` is False.

## Usage

```python
from ConsentLedger import InMemoryConsentLedger
from datetime import datetime, timezone

led = InMemoryConsentLedger()
led.grant("alice@ex.com", "marketing_email", "notice-2024-11", datetime.now(timezone.utc))
if not led.is_granted("alice@ex.com", "marketing_email"):
    raise PermissionError("no marketing consent")
```

## Compose with:

- **Lawful-basis enforcement** → `ProcessingRecord` + `DataSubjectRequest`
  Every processing activity declares its lawful basis; when the basis is consent, the ledger is the single source of truth a DSR can query.

- **Withdraw-and-erase** → `DataSubjectRequest` + `AuditEvent`
  Revocation opens an erasure DSR automatically and emits an audit event — no silent revocation and no ignored revocation.

- **Proof-of-grant** → `TamperEvidentAuditLog` + `AuditEvent`
  Consent grants are sealed into the audit chain so 'show me the exact consent as granted on 2024-03-01' is cryptographically answerable.
