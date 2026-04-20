# EncryptionPolicy

## What it does (plain language)

Declares cipher, KMS key provider, and rotation cadence per `data_class`.
The registry rejects writes that try to persist sensitive data before a
policy is bound, and the policy constructor refuses weak ciphers, sub-TLS1.2
transports, and raw-bytes key material.

## Regulation anchors

| Standard | Control | Role |
|---|---|---|
| PCI-DSS v4.0 | **Req 3.5** key storage, **Req 4.2** transit | Approved cipher set, TLS floor, KMS scheme. |
| HIPAA | **§ 164.312(a)(2)(iv)** at-rest, **(e)(2)(ii)** transit | Same enforcement for PHI. |
| NIST SP 800-53 rev 5 | **SC-13** crypto, **SC-8** transit | Cipher + cadence. |

## API surface (catalog fidelity)

```python
@dataclass(frozen=True)
class EncryptionPolicy:
    data_class: str
    at_rest_cipher: str  # AES-256-GCM | ChaCha20-Poly1305
    in_transit_min_tls: str  # TLS1.2 | TLS1.3
    key_provider: str  # aws-kms:// | gcp-kms:// | azure-keyvault:// | hashicorp-vault://
    rotation: timedelta

class EncryptionRegistry(Protocol):
    def bind(self, policy: EncryptionPolicy) -> None: ...
    def resolve(self, data_class: str) -> EncryptionPolicy: ...
    def require_tls(self, endpoint: str) -> None: ...
```

## Invariants

| ID | Rule |
|---|---|
| EP_INV_01 | Resolve MUST succeed for every sensitive data_class. |
| EP_INV_02 | Cipher in approved set. |
| EP_INV_03 | TLS >= 1.2. |
| EP_INV_04 | `key_provider` scheme ∈ approved KMS prefixes. |
| EP_INV_05 | PCI rotation cap ≤ 365 days. |

## Error model

- `EncryptionPolicyError` on any invariant violation at construction or bind.

## Security considerations

- Raw key bytes in configuration are rejected by prefix check on
  `key_provider`; upgrade a deployment by switching to a KMS URI.
- Rotation cadence is encoded; `KeyRotationSchedule` is the runtime that
  fires on cadence and emits the audit entry.

## Provenance

- PCI-DSS v4.0 — Req 3.5, 4.2
- HIPAA Security Rule 45 CFR § 164.312(a)(2)(iv), (e)(2)(ii)
- NIST SP 800-53 rev 5 — SC-8, SC-13

## Extension contract

Storage adapters call `resolve(data_class)` on every write. TLS-terminating
entrypoints register via `require_tls(endpoint)` middleware. New ciphers
must pass through governance-reviewed registration.

## Usage

```python
from datetime import timedelta
from EncryptionPolicy import EncryptionPolicy, InMemoryEncryptionRegistry

r = InMemoryEncryptionRegistry()
r.bind(EncryptionPolicy(
    data_class="cardholder_pan",
    at_rest_cipher="AES-256-GCM",
    in_transit_min_tls="TLS1.2",
    key_provider="aws-kms://alias/pci-pan",
    rotation=timedelta(days=365),
))
```

## Compose with:

- **Cipher-per-class** → `PiiClassification` + `DataResidencyPolicy`
  Sensitivity class pins cipher and region; unencrypted writes are rejected at the port — 'we forgot to encrypt field X' is a boot-time failure.

- **Scheduled rotation** → `KeyRotationSchedule` + `SecretsVault`
  Keys rotate on cadence with overlap; the vault serves the current version and retires the previous without app restart.

- **Transit-and-rest symmetry** → `ContentSecurityPolicy` + `SignatureVerifier`
  Transport and payload use matched strengths; a weak cipher anywhere is a structural incident, not a runtime anomaly.
