# LegalHold

## What it does (plain language)

Suspends retention-driven deletion and erasure cascades for records covered
by a litigation or regulatory hold. Retention sweeper and DSR erasure
coordinator call `covers(record_id)` before deleting; True means skip.

## Regulation anchors

| Standard | Control |
|---|---|
| AICPA SOC 2 | **CC2.3** evidence preservation. |
| NIST SP 800-53 rev 5 | **AU-11** Audit Record Retention — preservation for investigations. |

## API surface (catalog fidelity)

```python
@dataclass(frozen=True)
class LegalHold:
    hold_id: str
    scope_query: str
    opened_at: datetime
    opened_by: str

class LegalHoldRegistry(Protocol):
    def open(self, hold: LegalHold) -> None: ...
    def release(self, hold_id: str, released_by: str) -> None: ...
    def covers(self, record_id: str) -> bool: ...
```

## Invariants

| ID | Rule |
|---|---|
| LH_INV_01 | Delete paths MUST call `covers()`; held records NEVER deleted. |
| LH_INV_02 | Open + release emit audit rows. |
| LH_INV_03 | Release requires distinct actor (or explicit override). |
| LH_INV_04 | Held records remain readable — registry has no drop surface. |
| LH_INV_05 | scope_query field tokens validated at open. |

## Error model

`LegalHoldError` on invalid / duplicate holds, unknown fields in
`scope_query`, same-actor release without override.

## Provenance

- AICPA SOC 2 Trust Services Criteria — CC2.3
- NIST SP 800-53 rev 5 — AU-11

## Extension contract

Storage adapters implement a `HoldCheck` hook that intercepts delete
operations. Custom scope evaluators register through a matcher plugin.

## Compose with:

- **Hold-first delete** → `RetentionPolicy` + `AuditEvent`
  Every retention sweep calls `covers(record_id)` before deleting; a covered record stays and a deferred-delete audit is emitted with the hold id.

- **DSR survival** → `DataSubjectRequest` + `AuditEvent`
  An erasure DSR on a held subject produces a documented deferral instead of a deletion; the subject is notified the hold exists (where lawful).

- **Hold lifecycle** → `TamperEvidentAuditLog` + `AuditEvent`
  Open, extend, and release events are sealed into the audit chain so 'show me who released this hold and when' is one signed query.
