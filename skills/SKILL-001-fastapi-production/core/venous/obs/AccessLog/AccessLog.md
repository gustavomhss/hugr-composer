# AccessLog

## What it does (plain language)

Records every successful READ of a classified record, separate from the
security audit log. HIPAA § 164.528 "accounting of disclosures" is
impossible if reads and security events share a stream because read
volume drowns security events.

## Regulation anchors

| Standard | Control | Role |
|---|---|---|
| HIPAA | **§ 164.312(b)** audit controls, **§ 164.528** accounting | Distinct read stream. |
| AICPA SOC 2 | **CC6.1** logical access | Actor + purpose on every read. |

## API surface (catalog fidelity)

```python
class AccessLog(Protocol):
    def record_read(self, actor: str, record_id: str, data_class: str,
                    purpose_of_use: str, at: datetime) -> None: ...
    def query(self, record_id: str | None = None,
              actor: str | None = None) -> list[dict]: ...
    def count_by_actor(self, actor: str, since: datetime) -> int: ...
```

## Invariants

| ID | Rule |
|---|---|
| AL_INV_01 | Every classified read emits one row. |
| AL_INV_02 | `purpose_of_use` MUST be in the registered set. |
| AL_INV_03 | Storage distinct from `TamperEvidentAuditLog`. |
| AL_INV_04 | Actor MUST be a concrete identity (`'system'` forbidden). |
| AL_INV_05 | Retention bound at registration — no unbounded growth. |

## Error model

- `AccessLogError` on unregistered purpose, empty / bare-`system` actor,
  naive timestamps, empty record_id.

## Security considerations

- Reads of PHI are logged BEFORE the response leaves the process — a log
  failure MUST fail the read; this is how `record_read` should be wired.
- `count_by_actor` is the anomaly-detection hook for excessive-read alerts.

## Provenance

- HIPAA Security Rule 45 CFR §§ 164.312(b), 164.528
- AICPA SOC 2 Trust Services Criteria — CC6.1

## Extension contract

Repositories wrap reads with an access-log interceptor that calls
`record_read`. Custom purpose codes register via `register_purpose`.

## Usage

```python
from AccessLog import InMemoryAccessLog
from datetime import datetime, timezone

log = InMemoryAccessLog()
log.record_read("dr-42", "phi:patient:1138", "phi", "treatment",
                datetime.now(timezone.utc))
```

## Compose with:

- **Dual-stream auditing** → `AuditEvent` + `TamperEvidentAuditLog`
  Reads and security events hash-chain into distinct sealed streams; query volume never drowns security signal.

- **Classification-driven reads** → `PiiClassification` + `CurrentPrincipal`
  Every read captures actor + data_class + purpose_of_use; HIPAA accounting-of-disclosures is one projection over the stream.

- **Tamper-evident forensics** → `TamperEvidentAuditLog` + `SignatureVerifier`
  Access records seal into the chain; auditors verify 'this read log was not edited' with one signature check.
