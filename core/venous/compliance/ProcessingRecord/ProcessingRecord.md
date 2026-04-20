# ProcessingRecord

## What it does (plain language)

GDPR Article 30 Records of Processing Activities, generated from code
rather than a separate document. Decorators at handler registration emit a
`ProcessingRecord`; the registry exports a byte-for-byte reproducible
ROPA document that auditors can hash and diff across releases.

## Regulation anchors

- GDPR **Article 30** Records of processing activities.

## API surface (catalog fidelity)

```python
@dataclass(frozen=True)
class ProcessingRecord:
    activity: str
    controller: str
    purposes: tuple[str, ...]
    data_classes: tuple[str, ...]
    recipients: tuple[str, ...]
    retention_ref: str
    legal_basis: str
    transfers_outside_eea: tuple[str, ...] = ()

class ProcessingRegistry(Protocol):
    def register(self, record: ProcessingRecord) -> None: ...
    def export_ropa(self) -> bytes: ...
```

## Invariants

| ID | Rule |
|---|---|
| PR_INV_01 | Every PII-touching activity MUST register. |
| PR_INV_02 | `retention_ref` must resolve. |
| PR_INV_03 | `legal_basis` ∈ Article 6(1)(a-f). |
| PR_INV_04 | Country codes ISO-3166 alpha-2. |
| PR_INV_05 | `export_ropa()` reproducible. |

## Provenance

- EU GDPR Regulation 2016/679 — Article 30

## Compose with:

- **Code-first ROPA** → `PiiClassification` + `RetentionPolicy`
  Every handler declares data classes, retention ref, and purposes; the registry composes them into an Article-30 document without a parallel spreadsheet.

- **Lawful-basis binding** → `ConsentLedger` + `DataResidencyPolicy`
  Each activity names its lawful basis and the regions its data may enter — residency and consent are one declaration, not two.

- **Diffable across releases** → `AuditEvent` + `TamperEvidentAuditLog`
  ROPA hashes are sealed on each release; auditors diff two hashes to see exactly what changed between engagements.
