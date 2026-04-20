# Compliance-critical log aggregator

## Requirements

- Accept structured JSON log events from multiple source services.
- Every event is classified by data sensitivity (PII, PCI, health, general); PII fields are masked at ingest.
- Events are written to a tamper-evident store; each entry chains to its predecessor.
- A retention policy removes general-sensitivity events after 90 days; PII/PCI/health events retain for the legally-required window.
- Auditors can query the store by time window and source; queries are themselves logged.

## Acceptance criteria

- An event containing a credit-card-number-shaped field is stored with the card number masked and the event marked PCI.
- Deleting an event from the store breaks hash-chain verification for downstream entries.
- The retention job dry-run on day 91 identifies general events for deletion and skips PCI events dated the same day.
- Two auditors running the same query 10 minutes apart see the same dataset (no silent mutation).

## Non-requirements

- No log-ingest UI; ingest is API + agent.
- No full-text search; time + source only.
- No real-time alerting.
- No multi-region replication.
