# TamperEvidentAuditLog

## What it does (plain language)

A hash-chained, externally-signed, append-only ledger of every
security-relevant action. Entries cannot be quietly rewritten; any retroactive
mutation shows up as a verification failure. Regulators ask "prove nobody
altered this log", and the primitive answers with a cryptographic chain plus
a KMS signature per row.

## Glossary

- **Entry**: one row (`seq`, `timestamp`, `actor`, `action`, `resource`,
  `outcome`, `attributes`, `prev_hash`, `entry_hash`, `signature`, `key_id`).
- **Chain**: linked list of entries where each `prev_hash` equals the prior
  entry's `entry_hash`.
- **Signer**: out-of-process adapter (KMS / HSM) that owns the private key;
  the writing service NEVER holds the private half.
- **Canonical bytes**: deterministic JSON serialization used as the hashing
  and signing input — sorted keys, UTF-8, ISO-8601 timestamp.

## Purpose

Provide one signed, chain-verified evidence stream so SOC 2 CC7.2 non-repudiation
and HIPAA § 164.312(b) audit controls are satisfied centrally instead of
reconstructed per-service at audit time.

## Regulation anchors

| Standard | Control | Why this primitive satisfies it |
|---|---|---|
| AICPA SOC 2 TSC | **CC7.2** — security event detection | Chain + signer makes tamper detectable during audit. |
| NIST SP 800-53 rev 5 | **AU-9** Protection of Audit Info; **AU-10** Non-repudiation | External signer + append-only chain realise both. |
| HIPAA Security Rule | **45 CFR § 164.312(b)** Audit controls | Every PHI-touching action is chained, signed, and queryable. |

## API surface (catalog fidelity)

```python
class TamperEvidentAuditLog(Protocol):
    def append(self, actor: str, action: str, resource: str,
               outcome: str, attributes: Mapping[str, Any]) -> str: ...
    def verify_chain(self, start_seq: int | None = None,
                     end_seq: int | None = None) -> bool: ...
    def get(self, seq: int) -> Mapping[str, Any]: ...
    def export(self, since_seq: int) -> bytes: ...
```

Invariant IDs (TEAL_INV_01..06) match the catalog entries byte-for-byte.

## Invariants

| ID | Rule |
|---|---|
| TEAL_INV_01 | Append-only; `update` / `delete` MUST be refused. |
| TEAL_INV_02 | `prev_hash` = SHA-256 of prior entry's canonical bytes. |
| TEAL_INV_03 | Signature MUST come from an external `Signer`; writer NEVER holds the key. |
| TEAL_INV_04 | Sequence numbers monotonic, gap-free; violations fail `verify_chain`. |
| TEAL_INV_05 | `actor`, `action`, `resource`, `outcome`, `timestamp` MUST be present and non-empty. |
| TEAL_INV_06 | Timestamp comes from server clock; client-supplied timestamps are FORBIDDEN. |

## Hash chain + signature

Each entry's `entry_hash` is SHA-256 over the canonical bytes of every non-hash
field including `prev_hash`. Each entry's `signature` is produced by the
`Signer.sign(canonical_bytes)` call — the same bytes that are hashed. Two honest
implementations produce identical canonical bytes and therefore identical
`entry_hash`, so an off-box verifier can re-hash the `export(since_seq)` stream
without trusting the writer's in-memory state.

## Thread safety

All operations (`append`, `verify_chain`, `get`, `export`) are serialised by a
single `threading.Lock`. Concurrent `append` calls are linearised and receive
consecutive sequence numbers with no fork (TEAL_INV_04).

## Operational characteristics

- `append`: O(1); one SHA-256 + one signer call. ~50 µs per entry with the
  stub signer; KMS-backed signers add network latency.
- `verify_chain`: O(n). Nightly full verification is typical; incremental
  `verify_chain(start_seq=checkpoint, end_seq=None)` keeps cost bounded
  when checkpoint hashes are stored off-box.
- `export`: NDJSON; size ≈ 400 bytes per entry plus attribute size.
- Self-observability: `teal.entries.appended{action, outcome}`,
  `teal.verify.failures{reason}`, `teal.chain.size`.

## Error model

- Missing / empty mandatory fields raise `TamperEvidentAuditLogError` citing
  `TEAL_INV_05`.
- Construction without a `Signer` raises `TEAL_INV_03`.
- `get(seq)` with out-of-range seq raises `TEAL_INV_04`.
- `verify_chain` returns `False` (not raise) on tamper; callers treat False
  as an incident signal.

## Security considerations

- The chain is tamper-evidence; pairing it with WORM storage (S3 Object Lock,
  ledger DB) is what makes tampering infeasible rather than merely detectable.
- `attributes` MUST NOT contain secrets. The log is append-only so a leaked
  secret persists forever; producers redact before calling `append`.
- The signer's private half MUST stay in a KMS/HSM. The reference
  `HmacReferenceSigner` is for tests only.

## Provenance

- AICPA SOC 2 Trust Services Criteria (2022) — CC7.2
- NIST SP 800-53 rev 5 — AU-9, AU-10
- HIPAA Security Rule 45 CFR § 164.312(b)

## Alternatives considered and rejected

- Per-table shadow columns — trivially tamperable by a DBA; no signature; fails CC7.2.
- Database binlog replay — captures DML not business intent; unsigned.
- SIEM-only ingestion — no chain, no non-repudiation, no replay against storage.

## Extension contract

Downstream targets register a `Signer` adapter (KMS/HSM) and a storage backend
(S3 Object Lock, WORM volume, ledger DB) by implementing the
`TamperEvidentAuditLog` Protocol. Additional attribute fields compose via an
attribute-enrichment hook invoked before the canonical payload is built.

## Usage

```python
from TamperEvidentAuditLog import HmacReferenceSigner, InMemoryTamperEvidentAuditLog

signer = HmacReferenceSigner(b"32-byte-test-secret-never-in-prod!!", key_id="kid-1")
log = InMemoryTamperEvidentAuditLog(signer)

seq_hash = log.append(
    actor="admin-42",
    action="user.password_reset",
    resource="user:1138",
    outcome="success",
    attributes={"via": "admin_console"},
)
assert log.verify_chain() is True
```

## Compose with:

- **Hash-chained evidence** → `SignatureVerifier` + `SecretsVault`
  Each entry signs the previous head; the signing key is vault-issued — a forged entry invalidates the chain from its insertion point forward.

- **Dual-stream auditing** → `AuditEvent` + `AccessLog`
  Security events and data reads hash-chain into the same sealed log without sharing a topic, so query volume never drowns security signal.

- **Compliance export** → `ConsentLedger` + `DataSubjectRequest`
  DSR and consent artifacts are sealed into the chain so 'prove this record was not altered after we sent it to the auditor' is one verify() call.
