# KeyRotationSchedule

## What it does (plain language)

Drives rotation of data-encryption keys on a fixed cadence with an overlap
window so the prior version still decrypts existing records. Missed
rotations become alert signals; keys past `cadence + overlap` are
decrypt-only (new writes rejected).

## Regulation anchors

| Standard | Control |
|---|---|
| PCI-DSS v4.0 | **Req 3.7.4** key changes at defined cryptoperiod. |
| NIST SP 800-53 rev 5 | **SC-12** Cryptographic Key Establishment and Management. |

## API surface (catalog fidelity)

```python
@dataclass(frozen=True)
class KeyRotationSchedule:
    key_alias: str
    cadence: timedelta
    overlap: timedelta
    next_rotation_at: datetime

class KeyRotator(Protocol):
    def schedule(self, sched: KeyRotationSchedule) -> None: ...
    def rotate_now(self, key_alias: str) -> str: ...
    def active_key(self, key_alias: str, at: datetime) -> str: ...
```

## Invariants

| ID | Rule |
|---|---|
| KRS_INV_01 | Rotation on/before `next_rotation_at`. |
| KRS_INV_02 | `overlap > 0`. |
| KRS_INV_03 | Exactly one active key per alias. |
| KRS_INV_04 | Past `cadence + overlap` → decrypt-only. |
| KRS_INV_05 | Every rotation emits audit. |

## Error model

- `KeyRotationScheduleError` on invalid inputs and unknown aliases.

## Provenance

- PCI-DSS v4.0 — Req 3.7.4
- NIST SP 800-53 rev 5 — SC-12

## Extension contract

KMS providers implement `RotationAdapter.create_version(alias)` and
`.set_primary(alias, version)`. Post-rotation hooks subscribe to the
rotation transaction.

## Compose with:

- **Cadenced rotation** → `EncryptionPolicy` + `SecretsVault`
  Policy declares cadence; the vault ships the next version before the overlap expires — writes use the new key while reads still honor the old.

- **Envelope versioning** → `CryptoEnvelope` + `SignatureVerifier`
  Ciphertext carries the key version; readers fetch the right version from the vault — a rotation is not a mass re-encryption event.

- **Miss-detection alert** → `MetricMeter` + `AuditEvent`
  Missed rotations flip a metric and write an audit event; compliance lapse is a page, not an audit-year surprise.
