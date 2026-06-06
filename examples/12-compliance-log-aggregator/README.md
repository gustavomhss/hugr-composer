# Example 12 — Compliance-critical log aggregator

**Tier:** mid · **Benchmark spec:** `mid/07_compliance_log_aggregator.md`

PII-classifying log ingest with tamper-evident chain and class-aware
retention. Demonstrates the **`PiiClassification` + `TamperEvidentAuditLog`
+ `RetentionPolicy`** recipe.

## What this example shows

- Credit-card-shaped fields masked at ingest; event tagged PCI.
- Deleting an event breaks hash-chain verification downstream.
- Day-91 retention dry-run flags general events and skips PCI.
- Two auditors running the same query see byte-identical datasets.

## How to run

```bash
cd examples/12-compliance-log-aggregator
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q
```

## Tools used

| Tool                                 | Role                                            |
| ------------------------------------ | ----------------------------------------------- |
| `fastapi_add_log_ingest`             | Structured JSON event endpoint.                 |
| `fastapi_add_pii_classifier`         | Shape-based PCI/PII/health tagging.             |
| `fastapi_add_chain_verifier`         | SHA-256 hash chain + verify endpoint.           |
| `fastapi_add_retention_job`          | Class-aware purge with dry-run.                 |

## Primitives imported

| Primitive                | Role                                               |
| ------------------------ | -------------------------------------------------- |
| `PiiClassification`      | Field-level sensitivity tag (PCI/PII/health).      |
| `TamperEvidentAuditLog`  | Hash-chained append-only store.                    |
| `RetentionPolicy`        | Per-class TTL + `post-TTL` action.                 |
| `AccessLog`              | Query-audit entries for auditor reads.             |
| `Redactor`               | Masking rule applied at ingest.                    |

Reference pages at `docs.hugr.dev/primitive/<Name>`.
