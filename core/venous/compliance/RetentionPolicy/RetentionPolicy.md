# RetentionPolicy

## What it does (plain language)

Binds every piece of data to a maximum lifetime and a deletion mode. Writes
of data with no bound policy are rejected; the sweeper purges aged records
and emits an audit entry per policy id. Legal holds win over the retention
TTL — held records survive until released.

## Purpose

Implement GDPR Art 5(1)(e) storage limitation and PCI-DSS Req 3.2 in code,
not in a runbook. Retention becomes a type-level invariant rather than a
quarterly cron review.

## Regulation anchors

| Standard | Article / control | Role |
|---|---|---|
| GDPR | **Art 5(1)(e)** storage limitation, **Art 30** ROPA retention_ref | `legal_basis` cites the article verbatim. |
| PCI-DSS v4.0 | **Req 3.2** do not store beyond retention need | `data_class='cardholder_pan'` with `max_age ≤ 365d`. |
| NIST SP 800-53 rev 5 | **SI-12** Information Management and Retention | Policy binding + sweep evidence. |

## API surface (catalog fidelity)

```python
@dataclass(frozen=True)
class RetentionPolicy:
    data_class: str
    max_age: timedelta
    legal_basis: str
    deletion_mode: str  # 'hard' | 'crypto_shred' | 'anonymize'

class RetentionEnforcer(Protocol):
    def bind(self, policy: RetentionPolicy) -> None: ...
    def enforce_on_write(self, data_class: str, record_id: str) -> None: ...
    def sweep(self) -> int: ...
```

## Invariants

| ID | Rule |
|---|---|
| RP_INV_01 | Every write MUST carry a registered `data_class`. |
| RP_INV_02 | `max_age > 0` and `legal_basis` non-empty. |
| RP_INV_03 | `deletion_mode` MUST be one of the three approved literals. |
| RP_INV_04 | `sweep` is idempotent and respects `LegalHold.covers`. |
| RP_INV_05 | Every purge emits a `TamperEvidentAuditLog` entry. |

## Thread safety

`enforce_on_write` and `sweep` use CPython's atomic list operations and a
stable iteration snapshot; concurrent writes do not corrupt the record set.
A single-writer sweeper is assumed (standard cron pattern).

## Error model

- `RetentionPolicyError` on any invariant violation — dataclass constructor
  for `RP_INV_02` / `RP_INV_03`, enforce path for `RP_INV_01`.

## Security considerations

- Unclassified data MUST be quarantined by the write gate, not tolerated.
- `deletion_mode='crypto_shred'` assumes an external `KeyRotationSchedule`
  retires the data key; the mode alone does not delete bytes.
- `LegalHold` wins — evidence-preservation statutes override retention.

## Provenance

- EU GDPR Regulation 2016/679 — Articles 5, 30
- PCI-DSS v4.0 — Requirement 3.2
- NIST SP 800-53 rev 5 — SI-12

## Alternatives considered and rejected

- Database TTL indexes — per-collection, ignore legal_basis and hold.
- Cron scripts per table — drift silently when the schema evolves.
- Ops runbooks — move the rule outside code review; fail SOC 2 evidence.

## Extension contract

Target applications bind one policy per `data_class` and plug a `DeletionAdapter`
for storage-specific purge. Custom `deletion_mode` values register through the
approved-set extension hook (governance-reviewed).

## Usage

```python
from datetime import timedelta
from RetentionPolicy import InMemoryRetentionEnforcer, RetentionPolicy

policy = RetentionPolicy(
    data_class="access_token",
    max_age=timedelta(days=90),
    legal_basis="GDPR Art 5(1)(e) storage limitation",
    deletion_mode="hard",
)
enf = InMemoryRetentionEnforcer()
enf.bind(policy)
enf.enforce_on_write("access_token", "tok-abc")
purged = enf.sweep()
```

## Compose with:

- **Automated sweep** → `LegalHold` + `AuditEvent`
  Retention sweeper consults LegalHold.covers() before every delete; every retained-past-TTL record is audited with the covering hold id.

- **DSR-aware erasure** → `DataSubjectRequest` + `PiiClassification`
  An erasure DSR is a retention override scoped to one subject; the same classification map drives both automated sweep and ad-hoc erasure.

- **Policy evidence** → `ProcessingRecord` + `TamperEvidentAuditLog`
  The retention_ref in the ROPA points to the executable policy; auditors verify runtime behavior matches the document — not a screenshot.
