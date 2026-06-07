# HuGR Arsenal

**Executable knowledge a agent LLM invokes to scaffold AND customize
production backend apps.** Rails-style 3-layer architecture: macro
scaffold (skill) + slice generators (tools) + reusable building blocks
(primitives).

## Read these first

- **[PRODUCT.md](PRODUCT.md)** — what we are building, for whom, and
  how we know it's working.
- **[ROADMAP.md](ROADMAP.md)** — where we are today, honest; phased
  plan through v1.0.
- **[CONTRACT.md](CONTRACT.md)** — inviolable rules + per-step DoD /
  Invariants / Completeness / Quality gates. Binding.

## Current status

```
Phase:      v1.0.0 (release-prep — awaiting ratification + tag)
Skills:      1   (SKILL-001-fastapi-production)
Tools:     217   (201 catalog + 7 tier-1 + 9 tree dispatchers)
Primitives: 124  (production, 17-FastAPI + 1-Redis + 1-Stripe adapters, 10-tier gate)
Staged:    175   (core/venous/_staging/, +42 quarantined, pre-audited pool)
Benchmark: 100.00 plan · 100.00 code-level (20/20 specs × 100%)
Contract:  37/37 green
Examples:   20   (full spec coverage; /examples/01-20)
```

Numbers machine-verified via
`python -m engine.audit.contract_check` from the skill root.
See `INVENTORY.md` in the skill dir for the full machine-verified
manifest and `FREEZE.md` + `GOLIVE.md` for the v1.0 cut checklist.

## Quick orient

```
HuGR_Arsenal/
├── PRODUCT.md            # architecture contract
├── ROADMAP.md            # phased plan
├── CONTRACT.md           # execution rules
├── FREEZE.md             # v1.0 scope lock
├── GOLIVE.md             # v1.0 execution checklist
├── INTERFACES.md         # agent + Forge contracts
└── skills/
    └── SKILL-001-fastapi-production/
        ├── SKILL.md              # skill manifest (Anthropic Agent Skills format)
        ├── INVENTORY.md          # machine-verified on-disk counts
        ├── adapt/                # 134 tools (104 extend + 30 other)
        ├── generators/           # 60 macro scaffold helpers
        ├── core/venous/          # 124 primitives + 17 FastAPI adapters (+2 provider) + 175 staged
        ├── mcp_tools/            # MCP server + tier-1 meta + tree dispatchers
        └── engine/               # audit + index + bench + promotion + extraction
```

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/humangr-labs/HuGR-Arsenal/main/install.sh | bash
```

Validated nightly in a fresh `python:3.12-slim` container — see
[`.github/workflows/install-docker.yml`](.github/workflows/install-docker.yml).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the primitive / tool / recipe
workflows and the 10-tier gate. Every PR is also judged against
[CONTRACT.md §C](CONTRACT.md#c--enforcement) six-field discipline.

## Status is not marketing

Every claim in every doc maps to a code location or a ROADMAP step.
Claim-vs-reality drift is a bug to fix the same day it's discovered
([CONTRACT.md A8](CONTRACT.md)). No aspirational phrasing allowed.

---

Signed: Gustavo Schneiter — 2026-04-19.
