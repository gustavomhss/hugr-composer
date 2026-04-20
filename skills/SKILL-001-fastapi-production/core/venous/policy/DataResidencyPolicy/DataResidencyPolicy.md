# DataResidencyPolicy

## What it does (plain language)

Binds a `data_class` to a set of allowed storage regions plus a transfer
mechanism. Writes to non-allowed regions fail; cross-EEA transfers require
the bound mechanism (SCC, adequacy decision, BCR, or explicit derogation).

## Regulation anchors

| Standard | Control |
|---|---|
| GDPR | **Articles 44-50 (Chapter V)** transfers to third countries. |
| PCI-DSS v4.0 | **Req 12.8** third-party cross-border processing. |

## API surface (catalog fidelity)

```python
@dataclass(frozen=True)
class DataResidencyPolicy:
    data_class: str
    allowed_regions: tuple[str, ...]
    transfer_mechanism: str

class ResidencyEnforcer(Protocol):
    def bind(self, policy: DataResidencyPolicy) -> None: ...
    def check_write(self, data_class: str, region: str) -> None: ...
    def check_transfer(self, data_class: str, source: str, destination: str) -> None: ...
```

## Invariants

| ID | Rule |
|---|---|
| DRP_INV_01 | ISO-3166 alpha-2 codes only. |
| DRP_INV_02 | Writes to non-allowed regions fail loudly. |
| DRP_INV_03 | Cross-border transfer requires `transfer_mechanism`. |
| DRP_INV_04 | `check_write` at write time, never read time. |
| DRP_INV_05 | Policy changes emit audit. |

## Provenance

- EU GDPR Regulation 2016/679 — Articles 44-50 (Chapter V)
- PCI-DSS v4.0 — Req 12.8

## Compose with:

- **Classification-driven placement** → `PiiClassification` + `EncryptionPolicy`
  Sensitivity class determines region + cipher; moving a field across tiers is one declaration, not a schema migration.

- **Cross-border enforcement** → `ProcessingRecord` + `AuditEvent`
  Every cross-EEA write either matches a bound transfer mechanism or is denied and audited — GDPR Chapter V is executable, not procedural.

- **Retention per region** → `RetentionPolicy` + `LegalHold`
  Residency and retention declarations compose: a record stays in-region for its TTL and survives deletion only under a lawful hold.
