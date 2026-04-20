# HuGR SkillKit

**Executable knowledge a Maestro LLM invokes to scaffold AND customize
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
Phase:       5 (code-level benchmark) — v0.2.0
Skills:      1   (SKILL-001-fastapi-production)
Tools:     183   (MCP-registered: 180 adapt + 2 discovery + 1 audit)
Primitives: 122  (production, catalog-derived with 10-tier gate)
Staged:    430+  (core/venous/_extracted/, pre-audited pool)
Benchmark: 100.00 plan · 100.00 code-level (20/20 specs × 100%)
Contract:  30/30 green
Examples:   20   (full spec coverage; /examples/01-20)
```

Numbers machine-verified via
`python -m engine.audit.contract_check` from the skill root.

## Quick orient

```
HuGR_Skills/
├── PRODUCT.md            # architecture contract
├── ROADMAP.md            # phased plan
├── CONTRACT.md           # execution rules
└── skills/
    └── SKILL-001-fastapi-production/
        ├── SKILL.md              # skill manifest
        ├── adapt/extend/         # 100 slice tools
        ├── generators/           # macro scaffold helpers
        ├── core/venous/          # 97 production primitives
        ├── mcp_tools/            # MCP server (FastMCP)
        └── engine/               # audit + extraction pipelines
```

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/humangr-labs/HuGR_Skills/main/install.sh | bash
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
