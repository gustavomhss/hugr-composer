# `core/venous/` — the primitive library ("venous system")

Framework-free building blocks that generated apps import from, so the
output survives hand-editing. This tree is deliberately large and layered;
the layout below is the map. Canonical counts live in
[`INVENTORY.md`](../../INVENTORY.md) (regenerate with
`python -m engine.inventory`).

## Layout

```
core/venous/
├── <concern>/<Name>/          124 REGISTERED primitives (production)
│   ├── <Name>.py              framework-free reference impl (§A1: no fastapi/sqlalchemy)
│   ├── <Name>.protocol.py     typed Protocol — the public interface (generated)
│   ├── <Name>.contract.json   machine-readable contract + T0–T9 tier record
│   ├── <Name>.md              narrative spec: invariants + "Compose with:"
│   ├── test_<Name>.py         ≥1 test per declared invariant
│   └── <generated corpus>     chaos_/metamorphic_/behavioral_/state_machine_/
│                              observability_ — machine-emitted analysis files
├── _adapters/
│   ├── fastapi/               18 production-wired FastAPI adapters
│   └── {redis,stripe}/        2 provider adapters over events.PubSub / billing.Billing
└── _staging/                 175 staged primitives (PascalCase-shelled, pre-audit
    └── _quarantine/          pool) + 41 quarantined (rejected by the extraction gate)
```

16 concerns: `api, auth, cache, compliance, cost, data.modelling,
data.persistence, data.schema, events, extras, flags, jobs, llm,
observability, policy, resiliency, security`.

## Why the volume

Each registered primitive ships a full evidence bundle — impl, protocol,
contract, spec, invariant tests, plus a generated chaos/metamorphic/
behavioral/observability corpus. That corpus is **machine-emitted**, not
hand-maintained surface, so it is excluded from `ruff` lint (see
`[tool.ruff] extend-exclude` in `pyproject.toml`); the impl (`<Name>.py`)
and its test (`test_<Name>.py`) are still linted. Directory names are
PascalCase (`<Name>/<Name>.py`) to mirror the class they define — an
intentional convention, so `N999` is ignored tree-wide.

## Lifecycle

`_staging/` → (extraction gate + `engine.promotion` classify/promote with
atomic rollback) → registered `<concern>/<Name>/`. Nothing promotes without
passing `engine.audit.contract_check`. See `engine/promotion/HANDOFF.md`.
